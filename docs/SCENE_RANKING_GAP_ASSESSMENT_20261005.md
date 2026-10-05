# Assessing close-score Scene rankings

The full controlled Windows and completed one/two/four-thread Mac trials return
the same leading location sets as the reference, with some reordered scores
and selected views. A separate offline check examines every ordered location
pair in all twelve complete 1,024-location rankings for each distinct completed
platform/thread result. Existing independent receipts establish repeat identity;
this check does not run models or grant approval.

The largest reference score gap in a reordered pair is **0.000122801** on
Windows and **0.000179630** on the current Mac CPU runtime. Every inversion fits
within twice that query's observed maximum score difference. No larger-gap
ordering changes are hidden by a rank-displacement allowance. Top-ten/top-100
location sets remain identical in every assessed query.

An absolute score difference bound of **0.00025** is a proposal rounded upward
from the observed full-reference maximum, **0.00022419**. If each location's
score differs by at most this bound, two locations whose reference scores
differ by more than **0.00050** must retain their order. All assessed rankings
meet both checks. This gives a concrete way to describe numerical uncertainty
without changing the native ranking or tie rules.

The proposal is fitted to completed controlled evidence, not an independent
guarantee for other imagery, runtimes or devices. The final independently
verified one-thread Mac study also passes the same proposed checks; all three
Mac thread settings have identical native query results across their repeats.

The selected-view margins are now separately recalculated using retained
native reference query vectors and the unchanged sequential float32 compressed
cosine expression. Before reusing those vectors, all **12,288 winning scores**
in the full reference are checked; the maximum discrepancy from native output
is **0.00000000615**, below the predeclared 0.0000002 check tolerance. The Windows
snowy-landscape view change has a reference margin of **0.000043313**. The Mac
road view change has a margin of **0.000015803**. These are close reference
choices; this check does not establish every candidate losing-view score or a
universal per-view numerical bound. The earlier
[held-out comparison](HELD_OUT_SCENE_REFERENCE_20261004.md) remains preserved.
Trusted live input identity, full runtime qualification and distribution remain
separate release requirements. No acceptance policy, quantizer, service
admission or Maximum setting is changed by this assessment.

Private assessment receipt SHA-256:
`f2bea46569cbd829b774e39b208fef3517e2ec1531483b08502742187876caf8`.
Private full-reference view-margin receipt SHA-256:
`00b8eeb6abc4eaa9577f17a80a3d18df121003a6a38df1c5a3035cb440d5505b`.
See [full Windows evidence](FULL_WINDOWS_SCENE_COMPARISON_20261005.md),
[Mac evidence](MAC_CPU_NATIVE_CHECK_20261004.md) and the
[release checklist](PRODUCTION_ACCEPTANCE.md).
