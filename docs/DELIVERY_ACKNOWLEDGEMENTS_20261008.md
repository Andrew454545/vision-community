# Complete-batch delivery acknowledgements

The app previously allowed a successful reply to accept fewer locations than
the saved batch, then removed the entire batch's retry payload. An empty fresh
success had the same problem. This could lose delivery recovery after a broken
service reply during long-running processing.

Scenes and Objects now require the accepted count to match the entire submitted
batch. The existing explicit already-published replay remains supported,
including a Scene audit's zero-new-work response. A partial count, empty fresh
success or non-boolean replay flag produces a retryable error; the journal row,
payload, checksum and previous state remain unchanged. Reopening the app retries
that saved work. Pending audits and rejections retain their existing behavior.

The same count check applies to a guided submission without a journal. Recovery
still depends on a coherent response from the configured authenticated service;
these checks are not independent proof of publication or model execution.

Local Windows validation:

- 58 focused delivery, journal, storage-pressure and HTTP-recovery tests pass
  without skips. Real loopback HTTP and SQLite exercise interrupted replies,
  fresh Python processes, partial acknowledgements, explicit replay, unchanged
  saved payloads and one synthetic credit award.
- The initial sandboxed run could not reach its loopback services; its failure
  log is retained. The passing run has loopback access and uses disposable
  synthetic data, with no hosted account, contribution or credit change.

This source change does not update an older installed download or satisfy Mac,
accepted native work, trusted Object admission or endurance acceptance.
