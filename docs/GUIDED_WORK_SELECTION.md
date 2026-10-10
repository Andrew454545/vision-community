# Guided work selection

Step 1 of the local application offers **Scenes**, **Objects** and **Both**.
Scenes describes places; Objects finds things in places. Both takes turns,
running one native batch at a time. The Windows and Mac background controls
offer the same choice alongside the day/night schedule.

The guided page names the controls of the download that opened it. A sealed
native app directs people to **Automatic processing** in the **VISION Community**
window; an extracted download names its **Background VISION** file. Reconnection
also names the matching way to reopen the app. On Mac, Return activates
**Start VISION**. This source correction does not update an older download.

This is client integration, not a production admission decision. The default
remains Scenes. Object service admission and a released native Object computer
check are still required. Selecting Objects or Both cannot reuse a Scene
approval or silently fall back to Scene processing. The application explains
when the Object service is unavailable, and cannot create an account for that
unavailable work.

## Saved work and restart behavior

`work-selection.json` in the private worker folder stores the work choice and
next/unfinished lane, without an account code. An atomic write records the lane
before its indexer starts. An interrupted batch resumes that lane before a
handover; only a returned batch advances the cursor. Changing choice waits for
unfinished work. Existing account, outbox, indexes and failure files stay in
place. Both alternates Scene batches (requested count 16, subject to the service
cap) and single-location Object batches. An empty queue advances to the other
selected queue; when both queues are empty the background worker waits for its
normal retry interval. Day/night pacing controls rests between batches.

The guided and background application retain their shared folder lock, and the
batch runner also rejects a second native writer within one application. Scene
and Object indexes use separate directories and one account-bound durable
delivery outbox. A Scene lease uses only the current Scene profile; an Object
lease uses only the current Object profile. Neither lane can start with a
missing, expired or nonfinite approval.

Old Mac registrations without a work choice preserve their original arguments
and ownership receipts. New registrations include `--work-type`. Both startup
snapshots include the saved-work module, so an extracted download needs no
global Python installation.

## Object service integration still required

The native Object provider must supply `object_canary` and
`object_profile_matches` to `DesktopApp`. The released default currently has
neither provider and therefore refuses Object admission. The check must run
actual native processing of fixed reference inputs with all required models,
not treat a runtime-information response or detector-only run as qualification.

The adapter expects `GET /api/capabilities` version 1 with
`objectContributions` containing model `vision-object-index-v4`, `ready: true`,
`deviceQualificationRequired: true` and `officialGen4Required: true`. It submits
the native report's `submission` to `POST /api/object-qualifications` and can
recover an approval through `GET /api/object-qualifications?profileId=...`.
An accepted decision contains `qualified: true`, `lane: "object"`, the checked
`profileId` and a finite future `expiresAt`. Object leases include that profile.
These are integration points for the maintainer's trusted policy implementation,
not an alternate server gate or permission to enable Objects prematurely.

The current service explicitly reports Object readiness as false. Its recognized
Object qualification endpoint returns `object_verification_unavailable` without
reading a canary or recording an approval. This replaces an ambiguous missing
endpoint response; the native provider and admission implementation remain open.

## Validation scope

The saved-choice and guided-lane tests exercise independent approvals, matching
lease profiles, interrupted handover, competing writers, unavailable service
and both empty queues. Mac ownership tests round-trip all three choices and
legacy receipts. Windows scheduler tests retain saved files while registering
Both. The browser flow uses explicit offline fixtures; it is not native
inference, production qualification or credit evidence. Real native admission,
signed downloads, accepted background work and endurance remain in
[Production acceptance](PRODUCTION_ACCEPTANCE.md).
