# Search price and recovery checks — 9 October 2026

The browser now shows the current service price and asks before retrying a saved
unpaid search at a changed price. **Keep request saved** has initial focus.
Continue approves the displayed amount; a later change requires another review.
The review has an accessible name/description and closes on account changes.
The original query and request key survive review, cancellation and reload.

The service validates the operator price and refuses a stale maximum quote
before inference or debit. Paid-result replay happens before current-price
checks, so recovering an already paid search remains free even if the price
changes or new searches become unavailable. Existing ledger entries, saved paid
responses and the historical **100,000-unit** default are unchanged. Choosing an
initial launch price still needs genuine contribution effort and hosted cost
measurements; this change does not choose one.

The actual loopback browser walkthrough used only a synthetic account/result:

1. Quote 100 was refused after the fixture price rose to 200.
2. The review displayed 200; cancellation kept the request saved.
3. Reload preserved the original query/key and quote 100; its retry was refused.
4. Explicit approval sent quote 200. The fixture saved one paid result/debit,
   then returned a simulated lost-response error and raised the price to 300.
5. Reload/recovery sent the same query/key and quote 200. It returned the saved
   paid result without a second debit, cleared the pending request and restored
   **Run Search**.

The final receipt records four deliveries, quotes `[100, 100, 200, 200]`, one
200-unit synthetic debit and completion. Earlier incomplete browser attempts
remain retained. The fixture's finish endpoint saved its successful receipt and
closed; the browser then reported a blocked navigation to that closed endpoint.
That navigation is not evidence of production service availability.

| Check | Result |
| --- | --- |
| Focused price/journal/service/recovery tests | 39 passed, zero skips/failures |
| Complete local Windows service suite | 448 passed, three explicit file-symlink permission skips, zero failures; 451 total |
| Python HTTP/interface checks | 11 passed, zero skips/failures |
| Actual local workerd/D1 | Three durable restarts; stale quote refusal, six concurrent retries with one debit, invalid-price shutdown and old paid replay passed |
| Actual browser | Price review, cancellation, reload, original request identity and free paid replay passed |

The restricted complete service run's nine link-privilege skips are separate
context, not additional passes. These checks used synthetic publications/balance,
no production database, no imagery, no native inference and no provider writes.
Public contribution flags remain closed. See the
[aggregate receipt and retained-file hashes](evidence/search-pricing-recovery-20261009.json).
