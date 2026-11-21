import { AUDIT_BUDGET_SETUP } from "./audit-budget-check.js";

// Reuse exactly the fixed public audit fixture. Freeze once in native code,
// then replay its sealed RGB three times into new indexes/profile caches.
// Pixels, vectors, poses, queries and logs never leave the temporary directory.
export const REPEATABILITY_CHECK = AUDIT_BUDGET_SETUP + String.raw`    import math, struct
    from calibration.quality import decoded_difference
    from community import native_scene_search as native
    from community.vision_index import require_complete_index
    from community.search_snapshot import encoded, write_file

    def checked_json(path):
        return native.strict_json(native.bounded_read(native.plain_path(path), 1024 * 1024))

    def vector(path, pin):
        raw = native.pinned_read(native.plain_path(path), pin['sha256'], pin['bytes'])
        if len(raw) != pin['bytes'] or len(raw) != 768 * 4:
            raise ValueError('invalid_model_output')
        values = struct.unpack('<768f', raw)
        if any(not math.isfinite(v) for v in values):
            raise ValueError('invalid_model_output')
        return values

    def comparison(left, right):
        an = math.sqrt(sum(v*v for v in left))
        bn = math.sqrt(sum(v*v for v in right))
        if not an or not bn:
            raise ValueError('invalid_model_output')
        return (max(-1.0, min(1.0, sum(a*b for a,b in zip(left,right)) / (an*bn))),
                math.sqrt(sum((a-b)**2 for a,b in zip(left,right))) / an)

    phase, number = 'prepare_input', 0
    with tempfile.TemporaryDirectory(prefix='operator-repeatability-', dir='/state') as temporary:
        root = Path(temporary)
        source = root / 'locations.tsv'
        write_file(source, ''.join('\t'.join(str(v) for v in ('community-audit', r['locationId'],
            r['lat'], r['lng'], r['heading'], r['pitch'], r['zoom'], r['assetId'],
            r['country'], r['cameraGeneration'], 'false')) + '\n' for r in records).encode())
        queries = [{'name': name, 'query': query, 'mode': 'textOnly', 'minSimilarity': -1.0, 'examples': []}
            for name, query in [('road', 'a road'), ('shop', 'a shop'), ('landscape', 'a landscape')]]
        spec = {'version': 1, 'runId': 'private-host-frozen-eight', 'totalLocations': 8, 'queries': queries,
            'sceneFp32': True, 'topK': 8, 'chunkSize': 16, 'concurrency': 8, 'embeddingBatchSize': 16,
            'imageEncoderSessions': 1, 'checkpointEvery': 8, 'shardLocations': 50000,
            'resultPruneMeters': 0.0, 'dutyCyclePercent': 100, 'thermalStateLimit': None, 'seedResults': None}
        write_file(root / 'input.json', encoded(spec))
        write_file(root / 'search-input.json', encoded({'runId': spec['runId'], 'queries': queries,
            'topK': 8, 'resultPruneMeters': 0.0}))
        frozen = root / 'frozen-rgb'
        baseline = None
        repetitions = []
        for number in range(4):
            job = root / ('capture' if number == 0 else 'repeat-' + str(number))
            job.mkdir(mode=0o700)
            command = [str(runtime.binary), 'study-four-views', '--input', str(root / 'input.json'),
                '--model-dir', str(runtime.models), '--locations-tsv', str(source), '--index-dir', str(job / 'index'),
                '--checkpoint', str(job / 'checkpoint.json'), '--output', str(job / 'results.json'),
                '--evidence-dir', str(job / 'evidence'), '--evidence-budget-mib', '64', '--scene-fp32']
            if number == 0:
                command += ['--capture-rgb', str(frozen)]
            else:
                command += ['--sealed-rgb', str(frozen), '--sealed-sha256', frozen_sha]
            run_started = time.monotonic()
            phase = 'native_index'
            native.run_native(command, job, 50)
            phase = 'execution_attestation'
            # Study sessions attest the selected graph in their sealed evidence,
            # rather than the ordinary indexer's explicit-input log marker.
            # The ordinary audit path still requires both original log markers.
            if '[vision] ONNX Runtime global threads: 1, spinning disabled' not in (job / 'stderr.log').read_text().splitlines():
                raise ValueError('invalid_model_output')
            phase = 'index_validation'
            require_complete_index(job / 'checkpoint.json', job / 'index', 8)
            phase = 'frozen_inventory'
            manifest = checked_json(frozen / 'manifest.json')
            current_sha = native.file_digest(frozen / 'manifest.json')
            if number == 0:
                frozen_sha = current_sha
            if current_sha != frozen_sha or manifest.get('status') != 'COMPLETE_RGB_BOUNDARY_ONLY' or len(manifest.get('frames', [])) != 32:
                raise ValueError('invalid_model_output')
            phase = 'evidence_inventory'
            evidence = checked_json(job / 'evidence' / 'scene-evidence.json')
            if (evidence.get('status') != 'NATIVE_SCENE_STUDY_COMPLETED_UNQUALIFIED'
                    or evidence.get('productionQualified') is not False or evidence.get('selectedImageGraph') != 'vision_model_fp32.onnx'
                    or len(evidence.get('frames', [])) != 32 or len(evidence.get('tensors', [])) != 96):
                raise ValueError('invalid_model_output')
            tensors = {(t['ordinal'], t['view'], t['event']): t for t in evidence['tensors']}
            expected = {(i, v, event) for i in range(8) for v in range(4)
                for event in ('pixel-values', 'pooler-output', 'normalized')}
            if set(tensors) != expected or any(t['dtype'] != 'float32-little-endian' for t in tensors.values()):
                raise ValueError('invalid_model_output')
            inputs = {}
            normalized = {}
            phase = 'tensor_validation'
            for key, tensor in tensors.items():
                pin = tensor['file']
                path = native.relative_file(job / 'evidence', pin['name'])
                if path.stat().st_size != pin['bytes'] or native.file_digest(path) != pin['sha256']:
                    raise ValueError('invalid_model_output')
                if key[2] == 'pixel-values':
                    inputs[key[:2]] = pin['sha256']
                elif key[2] == 'normalized':
                    normalized[key[:2]] = vector(path, pin)
            phase = 'packed_index'
            blob = (job / 'index' / 'shard-000000.i8').read_bytes()
            if len(blob) != 24640 or (job / 'index' / 'shard-000000.mask').read_bytes() != bytes([15]) * 8:
                raise ValueError('invalid_model_output')
            search_work = job / 'search'
            search_work.mkdir(mode=0o700)
            phase = 'native_search'
            native.run_native([str(runtime.binary), 'search-four-view-index', '--input', str(root / 'search-input.json'),
                '--model-dir', str(runtime.models), '--locations-tsv', str(source), '--index-dir', str(job / 'index'),
                '--profile-cache-dir', str(job / 'profiles'), '--output', str(job / 'search-results.json')], search_work, 20)
            phase = 'query_validation'
            result = checked_json(job / 'search-results.json')
            if not result.get('completed') or len(result.get('queries', [])) != 3:
                raise ValueError('invalid_model_output')
            ranked = [[(h['locationIndex'], h['viewOffset'], h['similarity']) for h in q['hits']] for q in result['queries']]
            if any(len(hits) != 8 or len({h[0] for h in hits}) != 8
                    or any(not math.isfinite(h[2]) for h in hits) for hits in ranked):
                raise ValueError('invalid_model_output')
            phase = 'comparison'
            if baseline is None:
                baseline = inputs, normalized, blob, ranked
            else:
                if inputs != baseline[0]:
                    raise ValueError('invalid_model_output')
                differences = [comparison(baseline[1][key], normalized[key]) for key in normalized]
                packed = decoded_difference(blob, baseline[2])
                repetitions.append({'repetition': number, 'elapsedSeconds': round(time.monotonic() - run_started, 3),
                    'indexSha256': hashlib.sha256(blob).hexdigest(), 'preprocessedInputsIdentical': True,
                    'minimumNormalizedCosine': min(v[0] for v in differences), 'maximumNormalizedRelativeL2': max(v[1] for v in differences),
                    'packedByteIdentical': blob == baseline[2], 'minimumPackedCosine': packed['cosine_similarity']['min'],
                    'maximumPackedRelativeL2': packed['relative_l2_error']['max'], 'nativeQueriesIdentical': ranked == baseline[3]})
        phase = 'runtime_recheck'
        runtime.verify_runtime()
        receipt = {'status': 'native_repeatability_check_completed', 'runtimeSha256': runtime_sha,
            'locations': 8, 'views': 32, 'frozenManifestSha256': frozen_sha, 'repetitions': repetitions,
            'sceneGraph': 'fp32', 'executionProvider': 'cpu', 'threads': 1, 'nativeTimeoutSeconds': 50,
            'elapsedSeconds': round(time.monotonic() - started, 3),
            'peakChildRssKiB': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, 'productionQualified': False}
    print(json.dumps(receipt), flush=True)
except Exception:
    print(json.dumps({'error': 'native_repeatability_check_failed',
        'phase': locals().get('phase', 'runtime_identity'), 'repetition': locals().get('number', 0)}), flush=True)
    sys.exit(1)
`;

export function checkedRepeatabilityFailure(value) {
  const phases = new Set(["runtime_identity", "prepare_input", "native_index", "execution_attestation", "index_validation",
    "frozen_inventory", "evidence_inventory", "tensor_validation", "packed_index", "native_search",
    "query_validation", "comparison", "runtime_recheck"]);
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== "error,phase,repetition"
      || value.error !== "native_repeatability_check_failed" || !phases.has(value.phase)
      || !Number.isSafeInteger(value.repetition) || value.repetition < 0 || value.repetition > 3) {
    throw Error("native_repeatability_check_failed");
  }
  return { phase: value.phase, repetition: value.repetition };
}

export function checkedRepeatabilityReceipt(value, runtimeSha256) {
  const fields = ["status", "runtimeSha256", "locations", "views", "frozenManifestSha256", "repetitions",
    "sceneGraph", "executionProvider", "threads", "nativeTimeoutSeconds", "elapsedSeconds", "peakChildRssKiB", "productionQualified"];
  const perRun = ["repetition", "elapsedSeconds", "indexSha256", "preprocessedInputsIdentical", "minimumNormalizedCosine",
    "maximumNormalizedRelativeL2", "packedByteIdentical", "minimumPackedCosine", "maximumPackedRelativeL2", "nativeQueriesIdentical"];
  const hash = v => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
  const positive = (v, max) => Number.isFinite(v) && v > 0 && v <= max;
  const cosine = v => Number.isFinite(v) && v >= -1 && v <= 1;
  const error = v => Number.isFinite(v) && v >= 0;
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== fields.sort().join(",")
      || value.status !== "native_repeatability_check_completed" || value.runtimeSha256 !== runtimeSha256
      || value.locations !== 8 || value.views !== 32 || !hash(value.frozenManifestSha256)
      || value.sceneGraph !== "fp32" || value.executionProvider !== "cpu" || value.threads !== 1
      || value.nativeTimeoutSeconds !== 50 || value.productionQualified !== false
      || !positive(value.elapsedSeconds, 300) || !Number.isSafeInteger(value.peakChildRssKiB) || value.peakChildRssKiB <= 0
      || !Array.isArray(value.repetitions) || value.repetitions.length !== 3
      || value.repetitions.some((r, i) => !r || typeof r !== "object" || Array.isArray(r)
        || Object.keys(r).sort().join(",") !== perRun.sort().join(",")
        || r.repetition !== i + 1 || !positive(r.elapsedSeconds, 75) || !hash(r.indexSha256)
        || r.preprocessedInputsIdentical !== true || typeof r.packedByteIdentical !== "boolean" || typeof r.nativeQueriesIdentical !== "boolean"
        || !cosine(r.minimumNormalizedCosine) || !cosine(r.minimumPackedCosine)
        || !error(r.maximumNormalizedRelativeL2) || !error(r.maximumPackedRelativeL2))) {
    throw Error("native_repeatability_check_failed");
  }
  return value;
}
