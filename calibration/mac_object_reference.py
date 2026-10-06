"""Finite maintainer comparison of the published Mac Object program.

This is not the guided computer check. Detector outputs cannot qualify a device,
attest node placement, establish historical coverage or approve contributions.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from community import bootstrap
from community import object_canary as check

MANIFEST_SHA256 = 'b086083e00e527164b0433579a34d7a8141b05ed492081a4c1aa2f14a9164e87'
BINARY_SHA256 = '29ad87e50d368ee57e33fc1a07b9ec53acae187a2f6dc0ed9aa058a28f7965c0'
SOURCE = ('operator-canary\t145586295\t41.79270699022923\t20.39504004993244\t70.54816'
          '\t0\t0\tJe141ivXzUUx4ro1j8_3vw\tAlbania\tgen4\tfalse\t0\n')
QUERIES = ('car', 'a car')


def save(path, value):
    temporary = path.with_name(path.name + '.' + str(time.time_ns()) + '.tmp')
    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def image_pins(images):
    check.require(len(images) == 6, 'incomplete_saved_views')
    result = []
    for image in images:
        check.regular(image)
        check.require(0 < image.stat().st_size <= 32 * 1024**2, 'image_size_limit')
        with image.open('rb') as stream:
            header = stream.read(24)
        check.require(header[:8] == b'\x89PNG\r\n\x1a\n' and header[12:16] == b'IHDR'
                      and header[16:24] == (640).to_bytes(4, 'big') * 2, 'invalid_saved_dimensions')
        result.append({'name': image.name, 'bytes': image.stat().st_size, 'sha256': check.file_sha256(image)})
    return result


def selected_assets(manifest):
    check.require(check.file_sha256(check.regular(manifest)) == MANIFEST_SHA256, 'manifest_pin_changed')
    document = check.read_json(manifest)
    entries = bootstrap.files_for_platform(document, 'darwin-arm64', lane='object')
    expected = {'object-runtime/vision-object', *('models/object-hybrid-v1/' + name for name in check.MODELS)}
    check.require(len(entries) == 12 and {entry['path'] for entry in entries} == expected, 'asset_set_changed')
    executable = [entry for entry in entries if entry.get('executable')]
    check.require(len(executable) == 1 and executable[0]['asset'] == 'vision-object'
                  and executable[0]['sha256'] == BINARY_SHA256
                  and executable[0]['bytes'] == 23527808, 'binary_pin_changed')
    return document, entries


def inventory(root, entries):
    result = {}
    for entry in entries:
        path = check.regular(root / entry['path'])
        check.require(path.stat().st_size == entry['bytes'] and check.file_sha256(path) == entry['sha256'],
                      'runtime_pin_changed')
        result[entry['path']] = {'bytes': entry['bytes'], 'sha256': entry['sha256']}
    return result


def collect(out, *, runner=None, installer=None):
    out = Path(out).absolute()
    check.regular(out.parent, directory=True)
    out.mkdir(exist_ok=False)
    export = out / 'export'
    export.mkdir()
    report = {'version': 1, 'status': 'INCOMPLETE', 'productionQualified': False,
              'referenceIsAndrewInstalledGold': False, 'coverageAdmissionVerified': False,
              'nativeSourceCorrespondence': 'NOT_ATTESTED', 'actualProviderPlacement': 'NOT_ATTESTED',
              'sharedCpuThreadBudgetVerified': False, 'requestedCpuThreads': 1,
              'acceptedContributions': 0, 'searchCreditsCreated': 0, 'rawImagesExported': False,
              'fullNativeIndexVerified': False, 'locations': 1, 'views': 6, 'queries': list(QUERIES),
              'commands': [], 'comparisons': [], 'repeatComparisons': []}
    receipt = export / 'mac-object-reference.json'
    started = time.monotonic()
    def checkpoint():
        save(receipt, report)
    def run(label, arguments):
        report['stage'] = label
        command = {'stage': label, 'timeoutSeconds': 900, 'exitCode': None}
        report['commands'].append(command)
        checkpoint()
        began = time.monotonic()
        try:
            with (out / (label + '.stdout.log')).open('xb') as stdout, \
                    (out / (label + '.stderr.log')).open('xb') as stderr:
                result = (runner or check.run_owned)([str(binary), *map(str, arguments)],
                    env=environment, cwd=out, stdout=stdout, stderr=stderr, timeout=900)
            command['exitCode'] = result.returncode
            check.require(result.returncode == 0, 'native_command_failed')
            log = out / (label + '.stderr.log')
            check.require(log.stat().st_size <= check.MAX_JSON, 'native_log_limit')
            command['sharedPoolMarkerPresent'] = check.THREAD_MARKER in log.read_text(encoding='utf-8', errors='replace').splitlines()
            # The published older binary does not prove the new pool contract.
            # Never turn requested environment variables into budget approval.
        finally:
            command['wallSeconds'] = round(time.monotonic() - began, 3)
            checkpoint()
    try:
        report['stage'] = 'prerequisites'
        checkpoint()
        check.require(sys.platform == 'darwin' and bootstrap.runtime_platform() == 'darwin-arm64', 'requires_apple_silicon_mac')
        manifest = bootstrap.manifest_path()
        document, entries = selected_assets(manifest)
        runtime = out / 'runtime'
        (installer or bootstrap.install_runtime)(document, runtime, platform_name='darwin-arm64', lane='object')
        pins = inventory(runtime, entries)
        binary = runtime / 'object-runtime/vision-object'
        models = runtime / 'models/object-hybrid-v1'
        report.update(runtimeAssets=pins, manifestSha256=MANIFEST_SHA256,
                      collectorSha256=check.file_sha256(Path(__file__)),
                      validatorSha256=check.file_sha256(Path(check.__file__)))
        environment = {key: value for key, value in os.environ.items() if key.upper() in ('SYSTEMROOT', 'WINDIR')}
        environment.update(PATH=str(binary.parent) + os.pathsep + '/usr/bin:/bin',
            HOME=str(out), TMPDIR=str(out), TMP=str(out), TEMP=str(out))
        environment.update({key: '1' for key in check.THREAD_ENVIRONMENT_KEYS})
        source = out / 'source.tsv'
        source.write_text(SOURCE, encoding='utf-8', newline='\n')
        views = out / 'views'
        run('fetch-views', ['fetch-views', '--source-tsv', source, '--output-dir', views])
        images = sorted(views.glob('*.png'))
        report['inputImages'] = image_pins(images)
        image_arguments = [value for image in images for value in ('--image', image)]
        values = {}
        for execution in ('cpu', 'coreml-requested'):
            cache = out / (execution + '-cache')
            cache.mkdir()
            for query in (None, *QUERIES):
                lane = 'common' if query is None else 'hybrid-' + str(QUERIES.index(query))
                repetitions = []
                for repetition in (1, 2):
                    label = execution + '-' + lane + '-' + str(repetition)
                    target = out / (label + '.json')
                    args = ['detect-images', '--model', models / 'rfdetr-medium-576-b4.onnx'] if query is None else \
                        ['detect-hybrid-images', '--runtime-manifest', models / 'hybrid-object-runtime.json', '--query', query]
                    run(label, [*args, *image_arguments, '--output', target,
                                *(['--cpu'] if execution == 'cpu' else []), '--model-cache', cache])
                    rows = check.canonical_rows(check.read_json(target), images=images, query=query)
                    destination = export / (label + '.json')
                    save(destination, rows)
                    report['commands'][-1].update(outputSha256=check.file_sha256(target), portable={
                        'path': destination.name, 'bytes': destination.stat().st_size, 'sha256': check.file_sha256(destination)})
                    repetitions.append(rows)
                    checkpoint()
                report['repeatComparisons'].append({'execution': execution, 'lane': lane,
                    **check.compare_rows(repetitions[1], repetitions[0], query=query)})
                values[(execution, lane)] = repetitions[0]
                if execution != 'cpu':
                    report['comparisons'].append({'candidate': execution, 'reference': 'cpu', 'lane': lane,
                        **check.compare_rows(repetitions[0], values[('cpu', lane)], query=query)})
                checkpoint()
        report['stage'] = 'recheck'
        checkpoint()
        check.require(inventory(runtime, entries) == pins and selected_assets(manifest) == (document, entries), 'runtime_changed_during_check')
        check.require(image_pins(images) == report['inputImages'], 'frozen_inputs_changed')
        report.update(status='COMPLETE_UNQUALIFIED', stage='complete',
                      withinProfileExact=all(row['exact'] for row in report['repeatComparisons']))
    except (Exception, KeyboardInterrupt) as error:
        report['failure'] = {'type': type(error).__name__,
                            'code': str(error) if isinstance(error, (check.CheckError, bootstrap.BootstrapError)) else 'reference_collection_failed'}
    finally:
        report['wallSeconds'] = round(time.monotonic() - started, 3)
        checkpoint()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--accept-downloads-and-live-imagery', action='store_true', required=True)
    args = parser.parse_args()
    out = args.out.absolute()
    if out.exists() or out.resolve().is_relative_to(Path(__file__).resolve().parents[1]) \
            or out.resolve().is_relative_to(bootstrap.vision_root().resolve()):
        parser.error('Use a new temporary folder outside the repository and installed application')
    report = collect(out)
    print(json.dumps(report, allow_nan=False))
    return 0 if report['status'] == 'COMPLETE_UNQUALIFIED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
