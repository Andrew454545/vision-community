# Private native scene host

Runs the pinned Linux VISION image inside the existing private staging Container. The public website cannot call native search, audit or qualification directly.

- Bind `NativeSceneSearch` for search and `NativeSceneVerification` for audit/qualification.
- Use `NativeSceneOperator` only through an account-private operator service binding. A one-time staging check can use `tools/private-native-host-check.js` while all public routes remain disabled. It refuses an existing sealed bundle, persists a redacted report and stops compute. Remove its trigger after the check.
- Set separate `VISION_HOST_SECRET` and `VISION_HOST_OPERATOR_SECRET` secrets. Operator HTTP access also requires `HOST_OPERATOR_INGRESS_SECRET` (existing staging `PROBE_SECRET` is supported).
- Keep `NATIVE_IMAGE` digest-pinned and `NATIVE_RUNTIME_SHA256` matched to its verified runtime.
- Store sealed operator bundles only under `vision-community-staging/native-host/bundles/<sha256>.zip`. POST `/operator/bundle` with `{ "version": 1, "key": "native-host/bundles/<sha256>.zip", "sha256": "<sha256>", "bytes": 123 }`.

The controller streams and checks each bundle before saving its pointer. After container loss or Durable Object eviction, it restores that exact bundle from R2 before serving requests. A failed activation destroys uncertain container state and preserves the durable pointer and a redacted failure marker. One shared slot bounds activation, auditing and search. A durable alarm requests shutdown after three idle minutes, independent of the startup monitor; an active operation defers it until the slot is free. The platform inactivity timer remains a fallback.

CI exercises real workerd SQLite alarm delivery, renewed deadlines and active-operation deferral with synthetic compute. This verifies the timer/storage integration; hosted model and sealed-bundle recovery checks remain separate.

Startup uses explicit Python settings and a separate 60-second deadline. A failed boot stops compute and records a fixed failure code and numeric exit code, without exception text or credentials.

The fixed Python entrypoint also classifies import, manifest, state-directory, runtime-pin and credential failures. Its authenticated diagnostic front door exists for at most 45 seconds and never grants readiness; only allowed codes and numeric errno values are retained. It starts the existing pinned host on success and does not change model or helper pins.

Authenticated GET `/health` checks identity; GET `/operator/status` reads saved metadata without starting compute. POST `/operator/restart` stops compute while retaining the bundle pointer. The fixed POST `/operator/model-check` diagnostic requires explicit `NATIVE_IMAGERY_EGRESS=live-imagery`, processes one public canary location and returns hashes/resource measurements only. It accepts no commands, URLs or location data. Its temporary index is removed, and it never approves a runtime, device or contribution.

Missing measured policy or a contributor-only snapshot leaves the corresponding service unavailable. Keep public admission gates closed until the production acceptance checklist passes. Never include calibration archives, reference corpora, accounts or credentials in an operator bundle.
