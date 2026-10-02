# Private native scene host

Runs the pinned Linux VISION image inside the existing private staging Container. The public website cannot call native search, audit or qualification directly.

- Bind `NativeSceneSearch` for search and `NativeSceneVerification` for audit/qualification.
- Use `NativeSceneOperator` only through an account-private operator service binding. A one-time staging check can use `tools/private-native-host-check.js` while all public routes remain disabled. It refuses an existing sealed bundle, persists a redacted report and stops compute. Remove its trigger after the check.
- Set separate `VISION_HOST_SECRET` and `VISION_HOST_OPERATOR_SECRET` secrets. Operator HTTP access also requires `HOST_OPERATOR_INGRESS_SECRET` (existing staging `PROBE_SECRET` is supported).
- Keep `NATIVE_IMAGE` digest-pinned and `NATIVE_RUNTIME_SHA256` matched to its verified runtime.
- Store sealed operator bundles only under `vision-community-staging/native-host/bundles/<sha256>.zip`. POST `/operator/bundle` with `{ "version": 1, "key": "native-host/bundles/<sha256>.zip", "sha256": "<sha256>", "bytes": 123 }`.

The controller streams and checks each bundle before saving its pointer. After container loss or Durable Object eviction, it restores that exact bundle from R2 before serving requests. A failed activation destroys uncertain container state and preserves the durable pointer and a redacted failure marker. One shared slot bounds activation, auditing and search. A durable alarm requests shutdown after three idle minutes, independent of the startup monitor; an active operation defers it until the slot is free. The platform inactivity timer remains a fallback.

CI exercises real workerd SQLite alarm delivery, renewed deadlines and active-operation deferral with synthetic compute. This verifies the timer/storage integration; hosted model and sealed-bundle recovery checks remain separate.

The checker also has a real workerd scheduled-event test: five delivered events run one synthetic launch, preserve its private R2 report and reject public requests. `private-check.wrangler.jsonc` contains no trigger and has an expired execution window. For a one-time check, set `CHECK_NOT_BEFORE` and `CHECK_NOT_AFTER` to absolute UTC timestamps such as `2026-10-02T19:40:00.000Z`, at most 30 minutes apart. Allow at least 15 minutes for a new trigger to propagate, then remove it after the result. Early or expired deliveries cannot write a marker or start compute. A missing start marker means the check has not established execution, regardless of a saved cron configuration.

Each completed stage also has a private `<report-key>.step-<number>` receipt with matching body and list metadata. This keeps model hashes and resource measurements inspectable when the combined report exceeds the metadata budget. A failed or conflicting stage-receipt write preserves the failure and cannot produce a passed report.

Startup uses explicit Python settings and a separate 60-second deadline. A failed boot stops compute and records a fixed failure code and numeric exit code, without exception text or credentials.

Normal startup uses `/usr/local/bin/python -B /opt/vision/server.py`, matching the pinned image's own server command, with explicit Python and thread settings. It preserves the existing authentication, model and helper pins. The separately retained fixed Python diagnostic classifies import, manifest, state-directory, runtime-pin and credential failures; it never grants readiness and retains only allowed codes and numeric errno values.

The fixed operator-only POST `/operator/launch-check` starts a bounded sleeper and checks pinned Python/runtime identity offline. It also binds the pinned host to loopback with generated disposable credentials, verifies service/operator authentication and closes the listening socket. No stored secrets are passed to this diagnostic. It retains only fixed failure stages/classes, refuses an existing sealed bundle and always stops compute. A one-time checker may select `CHECK_MODE=launch`; remove its trigger afterward. This diagnostic cannot grant readiness or run models, and does not prove the normal entrypoint starts successfully.

POST `/operator/main-check` privately executes the immutable image's exact server program. Its two existing credential bindings stay in process environments; output contains only a checked receipt or fixed failure code. HTTP/authentication, process output and lifetime are bounded, and the process group is stopped before the container is destroyed. Select `CHECK_MODE=main` for one diagnostic within an absolute execution window, then remove the trigger. It refuses sealed work and proves no model inference or production readiness.

Authenticated GET `/health` checks identity; GET `/operator/status` reads saved metadata without starting compute. POST `/operator/restart` stops compute while retaining the bundle pointer. The fixed POST `/operator/model-check` diagnostic requires explicit `NATIVE_IMAGERY_EGRESS=live-imagery`, processes one public canary location and returns hashes/resource measurements only. It accepts no commands, URLs or location data. Its temporary index is removed, and it never approves a runtime, device or contribution. `CHECK_MODE=launch-model-restart` runs the offline launch check first, then normal startup, model processing and restart within the same one-time check. A failed model receipt or final shutdown cannot be reported as a pass.

Missing measured policy or a contributor-only snapshot leaves the corresponding service unavailable. Keep public admission gates closed until the production acceptance checklist passes. Never include calibration archives, reference corpora, accounts or credentials in an operator bundle.
