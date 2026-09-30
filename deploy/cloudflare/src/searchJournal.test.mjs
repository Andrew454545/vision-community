import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import test from "node:test";

function fixture() {
  const values = new Map();
  const storage = { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key) };
  const scope = { crypto };
  runInNewContext(readFileSync(new URL("../../../community/web/search-journal.js", import.meta.url), "utf8"), scope);
  return { create: () => new scope.VisionSearchJournal(storage), storage };
}

test("lost search response is recovered with the same key and exact original query after restart", () => {
  const { create } = fixture();
  const account = "a".repeat(32);
  const first = create().prepare(account, { prompt: "red door", queryMap: { customCoordinates: [{ panoId: "example", heading: 90 }] } });
  const restarted = create().prepare(account, { prompt: "a different search" });
  assert.equal(restarted.recovering, true);
  assert.equal(JSON.stringify(restarted.body), JSON.stringify(first.body));
  assert.equal(restarted.body.idempotencyKey, first.body.idempotencyKey);
});

test("accounts cannot recover each other's query or results", () => {
  const { create } = fixture();
  const journal = create(), one = "a".repeat(32), two = "b".repeat(32);
  const first = journal.prepare(one, { prompt: "private query" });
  assert.equal(journal.read(two), null);
  journal.complete(one, first.body.idempotencyKey, { map: { name: "Saved result" } });
  assert.equal(create().result(one).map.name, "Saved result");
  assert.equal(create().result(two), null);
});

test("results are saved before clearing the request and a new deliberate search has a new key", () => {
  const { create, storage } = fixture();
  const journal = create(), account = "a".repeat(32);
  const first = journal.prepare(account, { prompt: "red door" });
  journal.complete(account, "unrelated-key", { map: {} });
  assert.ok(journal.read(account));
  const savedSet = storage.setItem;
  storage.setItem = () => { throw Error("storage full"); };
  assert.throws(() => journal.complete(account, first.body.idempotencyKey, { map: {} }), /search_storage_unavailable/);
  assert.equal(journal.read(account).idempotencyKey, first.body.idempotencyKey);
  storage.setItem = savedSet;
  journal.complete(account, first.body.idempotencyKey, { map: {} });
  assert.equal(journal.read(account), null);
  assert.notEqual(journal.prepare(account, { prompt: "red door" }).body.idempotencyKey, first.body.idempotencyKey);
});

test("blocked browser storage prevents a new paid request; damaged recovery is preserved", () => {
  const { create, storage } = fixture();
  const journal = create(), account = "a".repeat(32);
  storage.setItem(journal.key(account), "damaged saved request");
  assert.throws(() => journal.prepare(account, { prompt: "new search" }), /search_recovery_invalid/);
  storage.removeItem(journal.key(account));
  storage.setItem = () => { throw Error("storage denied"); };
  assert.throws(() => journal.prepare(account, { prompt: "new search" }), /search_storage_unavailable/);
  assert.equal(journal.read(account), null);
});
