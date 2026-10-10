"""Offline sealing from operator-pinned native audit and settlement exports.

These exports are private control-plane authority, never volunteer inputs. This
removes handwritten per-output approval lists; it does not fetch, activate or
publish a snapshot, and cannot qualify a runtime or grant contribution credit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .four_view import BYTES_PER_LOCATION
from .search_snapshot import (HEX, MAX_ARTIFACT_BYTES, MAX_INVENTORY_BYTES, MAX_LOCATIONS,
                              SnapshotError, bounded_read, build_snapshot, cache_file, digest,
                              encoded, pinned_read, resource_for_environment, write_file)


class PublicationSnapshotError(ValueError):
    pass


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PublicationSnapshotError("duplicate_control_field")
            result[key] = value
        return result

    def nonfinite(_):
        raise PublicationSnapshotError("nonfinite_control_field")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def document(path, expected, resource):
    value = strict_json(pinned_read(path, expected, MAX_INVENTORY_BYTES))
    if not isinstance(value, dict) or value.get("version") != 1 or value.get("resource") != resource:
        raise PublicationSnapshotError("invalid_publication_control_resource")
    return value


def indexed(value, key):
    if not isinstance(value, list) or not 0 < len(value) <= MAX_LOCATIONS:
        raise PublicationSnapshotError("invalid_publication_control_rows")
    result = {}
    for row in value:
        if (not isinstance(row, dict) or not isinstance(row.get(key), str) or not row[key]
                or row[key] in result):
            raise PublicationSnapshotError("ambiguous_publication_control")
        result[row[key]] = row
    return result


def approval_from_control(inventory, control, authority, cache, environment):
    """Correlate exact audit bytes, pose, qualification, owner and credit claim."""
    resource = resource_for_environment(environment)
    if any(value.get("resource") != resource for value in (inventory, control, authority)):
        raise PublicationSnapshotError("invalid_publication_control_resource")
    if (not isinstance(authority.get("inputModel"), str) or not authority["inputModel"]
            or not isinstance(authority.get("snapshotPolicyId"), str) or not authority["snapshotPolicyId"]
            or authority.get("scope") != "native-audited-community-scene-publications"
            or environment == "production" and authority.get("productionApproved") is not True):
        raise PublicationSnapshotError("invalid_publication_authority")
    policies = indexed(authority.get("policies"), "policyId")
    for policy in policies.values():
        profiles = policy.get("profileIds")
        if (not isinstance(profiles, list) or not profiles or len(profiles) > 16
                or any(not isinstance(profile, str) or not HEX.fullmatch(profile) for profile in profiles)
                or len(set(profiles)) != len(profiles)
                or not isinstance(policy.get("runtimeSha256"), str) or not HEX.fullmatch(policy["runtimeSha256"])
                or environment == "production" and policy["policyId"].startswith("staging.")):
            raise PublicationSnapshotError("invalid_publication_authority")
    rows = inventory.get("rows")
    if (not isinstance(rows, list) or not 0 < len(rows) <= MAX_LOCATIONS
            or any(not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] < 1 for row in rows)
            or len({row["id"] for row in rows}) != len(rows)):
        raise PublicationSnapshotError("invalid_publication_inventory")
    qualifications = indexed(control.get("qualifications"), "id")
    accounts = indexed(control.get("accounts"), "id")
    credits = indexed(control.get("ledger"), "reference")
    candidates = indexed(control.get("candidates"), "lease_id")
    approved = {}
    selected = {row["id"]: row for row in rows}
    for candidate in candidates.values():
        lease, owner = candidate["lease_id"], candidate.get("account_id")
        policy = policies.get(candidate.get("policy_id"))
        qualification = qualifications.get(candidate.get("qualification_id"))
        account = accounts.get(owner)
        credit = credits.get("lease:" + lease)
        created = candidate.get("created_at")
        if (candidate.get("state") != "published" or not policy or not qualification or not account
                or account.get("deleted_at") is not None or "deleted_at" not in account
                or qualification.get("account_id") != owner
                or qualification.get("policy_id") != candidate.get("policy_id")
                or qualification.get("profile_id") not in policy["profileIds"]
                or type(created) is not int or created < 0
                or type(qualification.get("created_at")) is not int
                or type(qualification.get("expires_at")) is not int
                or not qualification["created_at"] <= created < qualification["expires_at"]
                or not credit or credit.get("reason") != "verified_work" or credit.get("account_id") != owner
                or not isinstance(candidate.get("records_json"), str)):
            raise PublicationSnapshotError("publication_audit_not_authoritative")
        records = strict_json(candidate["records_json"])
        if (not isinstance(records, list) or not records or len(records) * BYTES_PER_LOCATION > MAX_ARTIFACT_BYTES
                or any(not isinstance(record, dict) or type(record.get("locationId")) is not int
                       or record["locationId"] < 1 for record in records)
                or len({record["locationId"] for record in records}) != len(records)
                or type(credit.get("units")) is not int or credit["units"] != len(records)):
            raise PublicationSnapshotError("publication_credit_mismatch")
        key = "four-view-v4/" + lease + ".i8"
        blob = bounded_read(cache_file(cache, key), MAX_ARTIFACT_BYTES)
        if (len(blob) != len(records) * BYTES_PER_LOCATION
                or digest(candidate["records_json"].encode("utf-8") + b"\n" + blob) != candidate.get("submission_sha256")
                or candidate.get("artifact_key") != "scene-quarantine/" + lease + "/" + candidate["submission_sha256"] + ".i8"):
            raise PublicationSnapshotError("publication_audit_bytes_mismatch")
        used = False
        for ordinal, record in enumerate(records):
            row = selected.get(record["locationId"])
            if row is None:
                continue  # Inventory, not an old audit, controls current membership.
            used = True
            if row["id"] in approved:
                raise PublicationSnapshotError("ambiguous_publication_control")
            expected = {"locationId": row["id"], "assetId": row.get("asset_id"), "capture": row.get("capture"),
                        "inputModel": row.get("model"), "lat": row.get("lat"), "lng": row.get("lon"),
                        "heading": row.get("heading"), "pitch": row.get("pitch"), "zoom": row.get("zoom"),
                        "country": row.get("country") or None,
                        "cameraGeneration": row.get("camera_generation") or "unknown",
                        "outputSha256": row.get("output_sha256")}
            record_bytes = blob[ordinal * BYTES_PER_LOCATION:(ordinal + 1) * BYTES_PER_LOCATION]
            if (record != expected or row.get("contributor_id") != owner or row.get("four_view_key") != key
                    or row.get("model") != authority["inputModel"] or digest(record_bytes) != row.get("output_sha256")):
                raise PublicationSnapshotError("publication_audit_membership_mismatch")
            approved[row["id"]] = {"assetId": row["asset_id"], "capture": row["capture"],
                                   "lat": row["lat"], "lng": row["lon"], "heading": row["heading"],
                                   "pitch": row["pitch"], "zoom": row["zoom"],
                                   "approvedSha256": [row["output_sha256"]]}
        if not used:
            raise PublicationSnapshotError("unrelated_publication_audit")
    if set(approved) != set(selected):
        raise PublicationSnapshotError("publication_audit_missing")
    return {"version": 1, "policyId": authority["snapshotPolicyId"], "inputModel": authority["inputModel"],
            "outputModel": "vision-four-view-v4", "references": [approved[key] for key in sorted(approved)]}


def seal_publications(inventory, inventory_sha256, control, control_sha256, authority, authority_sha256,
                      cache, destination, *, environment, previous=None, previous_sha256=None):
    """Build a new immutable snapshot or preserve a redacted terminal failure."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        resource = resource_for_environment(environment)
        source = document(inventory, inventory_sha256, resource)
        audit = document(control, control_sha256, resource)
        permission = document(authority, authority_sha256, resource)
        approval = approval_from_control(source, audit, permission, cache, environment)
        approval["auditControlSha256"] = control_sha256
        approval["operatorAuthoritySha256"] = authority_sha256
        approval_path = destination / "derived-approval.private.json"
        raw = encoded(approval)
        write_file(approval_path, raw)
        result = build_snapshot(inventory, inventory_sha256, approval_path, digest(raw), cache,
                                destination / "snapshot", environment=environment,
                                previous=previous, previous_sha256=previous_sha256)
        receipt = {"version": 1, "status": "NATIVE_AUDITED_PUBLICATIONS_SEALED", "environment": environment,
                   "locations": result["locations"], "snapshotSha256": result["snapshotSha256"],
                   "inventorySha256": inventory_sha256, "auditControlSha256": control_sha256,
                   "operatorAuthoritySha256": authority_sha256, "activated": False,
                   "networkUsed": False, "newCreditGranted": 0}
        write_file(destination / "receipt.json", encoded(receipt))
        return receipt
    except Exception as failure:
        code = str(failure) if isinstance(failure, (PublicationSnapshotError, SnapshotError)) else "publication_snapshot_failed"
        write_file(destination / "failure-report.json", encoded({"sealed": False, "error": code}))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inventory", "control", "authority"):
        parser.add_argument("--" + name, type=Path, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--previous-sha256")
    args = parser.parse_args()
    try:
        result = seal_publications(args.inventory, args.inventory_sha256, args.control, args.control_sha256,
                                   args.authority, args.authority_sha256, args.cache, args.output,
                                   environment=args.environment, previous=args.previous,
                                   previous_sha256=args.previous_sha256)
    except Exception:
        print(json.dumps({"ok": False, "error": "publication_snapshot_failed"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
