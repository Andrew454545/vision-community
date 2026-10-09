# Private native scene host

Runs the pinned Linux VISION image inside the existing private staging Container. The public website cannot call native search, audit or qualification directly.

- Bind `NativeSceneSearch` for search and `NativeSceneVerification` for audit/qualification.
- Use `NativeSceneOperator` only through an account-private operator service binding. A one-time staging check can use `tools/private-native-host-check.js` while all public routes remain disabled. It refuses an existing sealed bundle, persists a redacted report and stops compute. Remove its trigger after the check.
- Set separate `VISION_HOST_SECRET` and `VISION_HOST_OPERATOR_SECRET` secrets. Operator HTTP access also requires `HOST_OPERATOR_INGRESS_SECRET` (existing staging `PROBE_SECRET` is supported).
- Keep `NATIVE_IMAGE` digest-pinned and `NATIVE_RUNTIME_SHA256` matched to its verified runtime.
- Set `NATIVE_DAILY_COMPUTE_REQUESTS` and `NATIVE_DAILY_CONTAINER_STARTS` explicitly. The private staging defaults are 48 operations and 12 starts per UTC day. Missing or invalid values block compute.
- Deploy the complete `wrangler.jsonc` with `--keep-vars`. Preserve both the named `exports.NativeHostProbe.container` attachment and `containers[].images`; a code-only upload can remove the runtime image map while leaving environment bindings intact.
- Store sealed operator bundles only under `vision-community-staging/native-host/bundles/<sha256>.zip`. POST `/operator/bundle` with `{ "version": 1, "key": "native-host/bundles/<sha256>.zip", "sha256": "<sha256>", "bytes": 123 }`.

The controller streams and checks each bundle before saving its pointer. After container loss or Durable Object eviction, it restores that exact bundle from R2 before serving requests. A failed activation destroys uncertain container state and preserves the durable pointer and a redacted failure marker. One shared slot bounds activation, auditing and search. A durable alarm requests shutdown after three idle minutes, independent of the startup monitor; an active operation defers it until the slot is free. The platform inactivity timer remains a fallback.

The daily allowance is reserved in the existing Durable Object's SQLite storage before native side effects. Failed or interrupted work is not refunded. Restarts and redeploys retain usage; increases take effect on the next UTC day, while a decrease is sealed on the next reservation. Exhaustion stops compute and returns a fixed unavailable response with a retry delay. Saved status and stop remain available without allowance, and status reads cannot extend the idle deadline. The record contains only counters, limits and a UTC day. These operation/start ceilings are not a dollar cap on the Cloudflare account; billing and realistic capacity validation remain release requirements. See [verified allowance evidence](../../../docs/HOSTED_COMPUTE_ALLOWANCE_20261009.md).

Preserve the current imagery setting when deploying. The checked-in default disables imagery retrieval; the existing private staging host explicitly enables it. `--keep-vars` does not override conflicting values supplied in the configuration.

CI exercises real workerd SQLite alarm delivery, renewed deadlines and active-operation deferral with synthetic compute. This verifies the timer/storage integration; hosted model and sealed-bundle recovery checks remain separate.

The checker also has a real workerd scheduled-event test: five delivered events run one synthetic launch, preserve its private R2 report and reject public requests. `private-check.wrangler.jsonc` contains no trigger and has an expired execution window. For a one-time check, set `CHECK_NOT_BEFORE` and `CHECK_NOT_AFTER` to absolute UTC timestamps such as `2026-10-02T19:40:00.000Z`, at most 30 minutes apart. Allow at least 15 minutes for a new trigger to propagate, then remove it after the result. Early or expired deliveries cannot write a marker or start compute. A missing start marker means the check has not established execution, regardless of a saved cron configuration.

Each completed stage also has a private `<report-key>.step-<number>` receipt with matching body and list metadata. This keeps model hashes and resource measurements inspectable when the combined report exceeds the metadata budget. A failed or conflicting stage-receipt write preserves the failure and cannot produce a passed report.

Startup uses explicit Python settings and a separate 60-second deadline. A failed boot stops compute and records a fixed failure code and numeric exit code, without exception text or credentials.

Normal startup uses `/usr/local/bin/python -B /opt/vision/server.py`, matching the pinned image's own server command, with explicit Python and thread settings. It preserves the existing authentication, model and helper pins. The separately retained fixed Python diagnostic classifies import, manifest, state-directory, runtime-pin and credential failures; it never grants readiness and retains only allowed codes and numeric errno values.

The fixed operator-only POST `/operator/launch-check` starts a bounded sleeper and checks pinned Python/runtime identity offline. It also binds the pinned host to loopback with generated disposable credentials, verifies service/operator authentication and closes the listening socket. No stored secrets are passed to this diagnostic. It retains only fixed failure stages/classes, refuses an existing sealed bundle and always stops compute. A one-time checker may select `CHECK_MODE=launch`; remove its trigger afterward. This diagnostic cannot grant readiness or run models, and does not prove the normal entrypoint starts successfully.

POST `/operator/main-check` privately executes the immutable image's exact server program. Its two existing credential bindings stay in process environments; output contains only a checked receipt or fixed failure code. HTTP/authentication, process output and lifetime are bounded, and the process group is stopped before the container is destroyed. Select `CHECK_MODE=main` for one diagnostic within an absolute execution window, then remove the trigger. It refuses sealed work and proves no model inference or production readiness.

Failures retain only an allowlisted code, bounded numeric child exit/output sizes and the numeric frame in the fixed server source. Raw tracebacks, credentials and other paths are discarded. The current private image binds HTTP without reverse DNS, avoiding Container hostname encoding failures. Actual hosted startup, scene processing and restart passed on 2026-10-03; [remaining release checks](../../../docs/PRODUCTION_ACCEPTANCE.md) still apply.

Authenticated GET `/health` checks identity; GET `/operator/status` reads saved metadata without starting compute. POST `/operator/restart` stops compute while retaining the bundle pointer. The fixed POST `/operator/model-check` diagnostic requires explicit `NATIVE_IMAGERY_EGRESS=live-imagery`, processes one public canary location and returns hashes/resource measurements only. It accepts no commands, URLs or location data. Its temporary index is removed, and it never approves a runtime, device or contribution. `CHECK_MODE=launch-model-restart` runs the offline launch check first, then normal startup, model processing and restart within the same one-time check. A failed model receipt or final shutdown cannot be reported as a pass.

Private POST `/operator/audit-budget-check` measures the first eight public canary locations through the actual 50-second audit path. POST `/operator/repeatability-check` captures that fixed fixture once, then runs three native sealed-input replays and saved-index searches. Both return bounded measurements only. All model diagnostics refuse an active sealed bundle and stop compute afterward. The [saved measurements](../../../docs/HOSTED_SCENE_BUDGET_20261003.md) support retaining the initial eight-location limit; they do not grant admission.

Missing measured policy or a contributor-only snapshot leaves the corresponding service unavailable. Keep public admission gates closed until the production acceptance checklist passes. Never include calibration archives, reference corpora, accounts or credentials in an operator bundle.

Private search failures may retain one `lastSearchFailure` entry containing only
an allowlisted adapter code and timestamp. Unknown, oversized or extra-field
error bodies stay redacted. The controller stops uncertain compute, preserves
the seal and does not replay inference in that request. The public gateway still
returns its generic unavailable response and spends no credit on that failure.
