# Waiting for native Object capacity

A temporarily full native job queue now returns the distinct private error
`object_job_queue_full`. The coordinator saves a 15-minute wait and resumes the
same pending upload when due. Waiting survives restart and does not consume the
eight-fault transport allowance, request another inference attempt or award
credit. Status reads before the saved deadline contact no native host.

An already-authorized native retry keeps its original nonce and expected attempt
while waiting. It does not manufacture another retry authorization. Cancellation
and account deletion still win over late replies.

Only an exact bounded HTTP 503 queue-full reply receives this treatment. Disk
limits, the native 64-job/history limit, unknown errors, malformed bodies and
connection failures retain their existing finite attention threshold. Those
limits are not assumed to resolve automatically. Native registry/retention work
remains a launch dependency.

The private native service and bridge must both support the new error; older
generic capacity replies keep the previous behavior. Repin the exact changed
Python source in any future auditor policy. No installed runtime, frozen pilot,
public admission gate or live deployment is changed here.

The [verification receipt](evidence/object-queue-wait-20261012.json) records actual
Windows results and scope. Tests cover more than eight consecutive busy replies,
same-nonce recovery and a persisted wait across fresh local Cloudflare processes.
All inference, test locations and credits are synthetic.
