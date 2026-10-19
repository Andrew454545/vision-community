"""Offline Scene qualification. No account, cloud call, or self-reported pass flag.

An owner reviews the exact report/index against a trusted fixed-input policy.
The resulting receipt permits cooperative local work, not publication or credit.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
from pathlib import Path

from calibration.quality import decoded_difference
from .four_view import BYTES_PER_LOCATION
from .local_scene_packets import canonical, digest
from .mac_starter import regular
from .pc_canary import CanaryPolicy, runtime_profile, run_canary

BOUNDS = {'minimumViewCosine': .9999, 'maximumViewRelativeL2': .02}
CONTRACT = 'vision-local-scene-approval-v1'


def read_document(path, maximum=2 * 1024 * 1024):
    path = regular(path)
    if path.stat().st_size > maximum:
        raise ValueError('qualification_document_too_large')
    return json.loads(path.read_text(encoding='utf-8'))


def fixed_policy(path, expected_sha256):
    path = regular(path)
    if path.stat().st_size > 256 * 1024:
        raise ValueError('qualification_policy_too_large')
    policy = CanaryPolicy.load(path, expected_sha256=expected_sha256)
    if policy.document['version'] != 3 or policy.document['thresholds'] != BOUNDS:
        raise ValueError('fixed_scene_qualification_policy_required')
    policy.pinned_inputs()  # Includes trusted generator, reference and fixture pins.
    return policy


def approve(report_path, policy_path, policy_sha256, gold_path, installation_id):
    """Owner-side comparison of all 448 actual packed output vectors.

    gold_path is a private owner-reviewed correspondence record, never a
    contributor pass flag. Its reference pin must match this exact policy.
    """
    report = read_document(report_path)
    policy = fixed_policy(policy_path, policy_sha256)
    gold = read_document(gold_path)
    if (gold.get('contract') != 'vision-local-gold-correspondence-v1'
            or gold.get('verified') is not True
            or gold.get('verificationScope') not in ('REFERENCE_REGENERATED', 'INSTALLED_INDEX_CONSUMER')
            or type(gold.get('referenceRegeneratedByInstalledBinary')) is not bool
            or (gold['verificationScope'] == 'REFERENCE_REGENERATED'
                and gold['referenceRegeneratedByInstalledBinary'] is not True)
            or (gold['verificationScope'] == 'INSTALLED_INDEX_CONSUMER'
                and (gold.get('locations') != 112 or type(gold.get('queries')) is not int or gold['queries'] < 1))
            or gold.get('referenceSha256') != policy.document['referenceSha256']
            or not all(isinstance(gold.get(k), str) and len(gold[k]) == 64
                       and all(c in '0123456789abcdef' for c in gold[k])
                       for k in ('localVisionBinarySha256', 'evidenceSha256'))):
        raise ValueError('local_vision_gold_correspondence_required')
    if (not isinstance(installation_id, str) or len(installation_id) != 64
            or any(c not in '0123456789abcdef' for c in installation_id)):
        raise ValueError('invalid_installation_identity')
    if (report.get('status') != 'COMPLETE' or report.get('complete') is not True
            or report.get('locations') != 112 or report.get('views') != 448
            or report.get('inputIdentity') != 'SEALED_SYNTHETIC_RGB_BYTES'):
        raise ValueError('complete_fixed_112_check_required')
    canary = report.get('submission', {}).get('canary', {})
    profile = canary.get('runtimeProfile', {})
    if (profile != report.get('runtimeProfile') or set(profile) != {'profile', 'sha256'}
            or digest(profile['profile']) != profile['sha256']
            or profile['sha256'] != policy.document['runtimeProfileSha256']):
        raise ValueError('qualification_profile_mismatch')
    threads = profile['profile'].get('threads', {})
    values = set(threads.values())
    if not threads or values not in ({'1'}, {'2'}, {'4'}):
        raise ValueError('unsupported_qualification_threads')
    records = canary.get('records', [])
    if not isinstance(records, list) or len(records) != 112:
        raise ValueError('qualification_records_required')
    try:
        decoded = [base64.b64decode(r, validate=True) for r in records]
    except (ValueError, TypeError):
        raise ValueError('invalid_qualification_records') from None
    if any(len(r) != BYTES_PER_LOCATION for r in decoded):
        raise ValueError('invalid_qualification_records')
    body = b''.join(decoded)
    if (hashlib.sha256(body).hexdigest() != report.get('payloadSha256')
            or canary.get('outputSha256') != report['payloadSha256']):
        raise ValueError('qualification_output_changed')
    inputs = policy.pinned_inputs()
    metrics = decoded_difference(body, inputs['referenceBytes'])
    identity = report.get('identity', {})
    if any(canary.get(k) != identity.get(k) for k in
           ('fixtureSha256', 'referenceSha256', 'parentReferenceSha256')):
        raise ValueError('qualification_input_mismatch')
    passed, _ = policy.evaluate(profile['sha256'], identity, metrics)
    if not passed:
        raise ValueError('scene_numerical_qualification_failed')
    receipt = {'contract': CONTRACT, 'installationId': installation_id,
               'runtimeProfile': profile, 'inferenceThreads': int(next(iter(values))),
               'policySha256': policy_sha256, 'referenceSha256': identity['referenceSha256'],
               'goldCorrespondenceSha256': digest(gold), 'bounds': BOUNDS,
               'goldVerificationScope': gold['verificationScope'],
               'locations': 112, 'views': 448, 'outputSha256': report['payloadSha256'],
               'reportSha256': digest(report), 'metrics': metrics,
               'scope': 'LOCAL_PROCESSING_ONLY', 'productionQualified': False}
    receipt['sha256'] = digest(receipt)
    return receipt


def validate_approval(receipt, installation_id, profile):
    if not isinstance(receipt, dict):
        raise ValueError('local_scene_approval_required')
    unsigned = {k: v for k, v in receipt.items() if k != 'sha256'}
    if (receipt.get('contract') != CONTRACT or receipt.get('sha256') != digest(unsigned)
            or receipt.get('installationId') != installation_id
            or receipt.get('runtimeProfile') != profile or receipt.get('bounds') != BOUNDS
            or receipt.get('scope') != 'LOCAL_PROCESSING_ONLY'
            or receipt.get('locations') != 112 or receipt.get('views') != 448
            or receipt.get('inferenceThreads') not in (1, 2, 4)):
        raise ValueError('local_scene_approval_mismatch')
    metrics = receipt.get('metrics', {})
    try:
        cosine, error = metrics['cosine_similarity']['min'], metrics['relative_l2_error']['max']
        if (not math.isfinite(cosine) or not math.isfinite(error)
                or not BOUNDS['minimumViewCosine'] <= cosine <= 1
                or not 0 <= error <= BOUNDS['maximumViewRelativeL2']):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError('scene_numerical_qualification_failed') from None
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'approve'))
    parser.add_argument('--policy', required=True, type=Path)
    parser.add_argument('--policy-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--models', type=Path)
    parser.add_argument('--threads', type=int, choices=(1, 2, 4), default=1)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--gold', type=Path)
    parser.add_argument('--installation-id')
    args = parser.parse_args()
    if args.command == 'check':
        if not args.binary or not args.models:
            parser.error('--binary and --models required')
        policy = fixed_policy(args.policy, args.policy_sha256)
        if runtime_profile(args.binary, args.models, inference_threads=args.threads)['sha256'] != policy.document['runtimeProfileSha256']:
            raise ValueError('qualification_profile_mismatch')
        report = run_canary(args.output, binary=args.binary, model_dir=args.models,
                            policy=policy, inference_threads=args.threads)
        print(json.dumps({'status': report['status'], 'qualified': report['qualified']}))
        if not report['qualified']:
            raise SystemExit(1)
    else:
        if not args.report or not args.gold or not args.installation_id:
            parser.error('--report, --gold and --installation-id required')
        result = approve(args.report, args.policy, args.policy_sha256, args.gold, args.installation_id)
        from .local_scene_pilot import immutable
        immutable(args.output, canonical(result) + b'\n')
        print(json.dumps({'approvalSha256': result['sha256'], 'scope': result['scope']}))


if __name__ == '__main__':
    main()
