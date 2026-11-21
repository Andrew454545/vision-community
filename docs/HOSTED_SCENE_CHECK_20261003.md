# Private hosted scene check — 2026-10-03 UTC

The private staging server now starts, processes a real location and repeats
processing after a Container restart. These are staging checks, not production
admission or a complete contribution/search test.

## Repairs

- The completed Cloudflare sign-in grants the scoped Workers/Containers access
  needed for account-private service bindings. Credentials stay in Windows
  secure storage and process memory.
- Worker version metadata showed that a code-only upload omitted `containers`
  while retaining its environment variables. A complete Wrangler deployment
  restored the image map and explicitly attached the existing named Container.
  Its Durable Object namespace and secrets were preserved.
- Python's HTTP listener attempted reverse DNS during startup. A bounded
  hosted preflight identified a hostname encoding failure, and the preceding
  exact-main check identified line 268 of the immutable server source.
  The server now binds its socket directly and uses a constant private server
  name. A real authenticated listener passes with a hostname resolver that
  deliberately raises `UnicodeError`.

Private VISION source commit: `b4507b7843bfcc04d0b717d9aa2df0ccca81e373`.
Its committed server SHA-256 is
`576ce1728f8a82d0243c611d1b6f6eb81345ddc65619d1fcbcdede4420d899e0`.
The verified image overlay changes only that server file. All ten base layers,
models, native executable, environment and non-root user remain unchanged.

Image digest:
`sha256:d951eff7987b0284d333f193489de339cc5bd63252284bfc8297d1a322bf91d6`.
Runtime SHA-256:
`bbc60e94e6590c657f256d89f6d63db47f7f3d53d1ba37ffeafba07b6211d64e`.

## Actual hosted results

At 04:54 UTC, the immutable image's exact main program passed HTTP,
service/operator authentication and runtime/model-file checks using its
existing credentials, Python 3.12.15 and uid 10001.

At 04:56 UTC, normal startup and two live model runs passed:

| Check | First run | After restart |
| --- | ---: | ---: |
| Locations / views | 1 / 4 | 1 / 4 |
| Fetch / inference errors | 0 / 0 | 0 / 0 |
| Scene graph / provider / threads | FP32 / CPU / 1 | FP32 / CPU / 1 |
| Model-check elapsed seconds | 5.402 | 6.085 |
| Peak native child RSS, KiB | 614,068 | 614,292 |
| Output bytes | 3,080 | 3,080 |

Both output hashes were
`73a7cbb469ea67b6cbed96f22fe2950830d6070e9b479cabb8d2cbd52dcf4b46`.
This is repeatability for one retrieved location; it does not establish
cross-platform quality tolerance or broad performance/cost bounds.

The host uses one shared slot with a configured 1 vCPU, 3,072 MiB memory and
8,000 MB disk. No sealed bundle was active. The final shutdown succeeded.
Private readback confirmed disabled public/preview URLs, SSH and container
logs, the same namespace, the staging bucket and no diagnostic cron.

Local validation passed 19 diagnostic/launch tests, 176 Worker unit tests,
27 actual workerd private-host checks and 14 private server/preparation tests.
Historical failures remain preserved privately; their saved status markers are
historical, not a failure of the later passing runs.

## Still required

Seal measured admission policy and a contributor-only snapshot; verify a real
accepted Windows batch, credits, search, sealed restart/eviction recovery and
the remaining [production acceptance checks](PRODUCTION_ACCEPTANCE.md).
No account, contribution, credit, search charge or production gate changed.
Raw calibration records and imagery were not uploaded. The excluded R2 bucket
was not accessed.
