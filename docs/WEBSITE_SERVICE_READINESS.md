# Website availability guidance

The browser checks the anonymous/account status and `/api/capabilities` before
showing an indexing command. Scene setup requires the current version-1
`vision-four-view-v4` audited-new-locations contract, an enabled 112-location
device check and a named policy. Missing, legacy, malformed or unavailable
capabilities do not enable scene commands. Queue size alone does not mean the
service can accept contributions.

Object and Both commands remain unavailable until portable object admission is
qualified and its capability contract is implemented. The page explains this
and offers Scene. This restriction covers command copying and click handlers;
it does not claim object inference has passed comparison with the reference.

A visible status and **Check again** button let users retry deliberately. There
is no new polling interval. Service GET requests have a 15-second timeout;
other browser API requests have a 75-second timeout. Failed status checks
disable new work/search actions while retaining the existing displayed balance,
account recovery code and saved browser journals. A later check re-enables only
the available actions. A search outage does not disable available scene setup,
and a connected service may recover an existing saved search request without
preparing a new debit. The server still decides whether it can serve that request.

Account creation/recovery require a connected operational service. Accounts
may be restored even while scene verification or online search is unavailable.
The Pause button is disabled when no browser processing is active; copying a
desktop command does not give the website control of that desktop process.

These are availability hints, not health attestation or permission to bypass
device qualification, trusted auditing, coverage checks or server credit rules.
A configured service may still fail its actual device/inference check.

Validation includes five new browser-state checks for outage/recovery, legacy
and malformed contracts, unqualified Objects/Both, independent search outage
and bounded capability requests. All 87 JavaScript checks pass locally. A
disposable read-only local browser fixture also exercises actual page controls
with synthetic balances and capability/outage changes. No live account,
contribution, debit or Cloudflare deployment is part of that fixture.
