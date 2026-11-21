import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import test from "node:test";

const account = "a".repeat(32), other = "b".repeat(32);
function fixture() {
  const values = new Map();
  const storage = { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key) };
  const scope = { crypto };
  for (const file of ["account-deletion.js", "search-journal.js"]) {
    runInNewContext(readFileSync(new URL(`../../../community/web/${file}`, import.meta.url), "utf8"), scope);
  }
  return { values, storage, create: () => new scope.VisionAccountDeletion(storage),
    journal: () => new scope.VisionSearchJournal(storage), pendingKey: scope.VisionAccountDeletion.pendingKey };
}

test("deletion saves its private receipt before delivery and recovers the same request after restart", () => {
  const { create } = fixture();
  const first = create().prepare(account, "DELETE");
  assert.match(first.idempotencyKey, /^[0-9a-f]{64}$/);
  assert.equal(JSON.stringify(create().read()), JSON.stringify(first));
  assert.equal(create().prepare(account, "DELETE").idempotencyKey, first.idempotencyKey);
  assert.throws(() => create().prepare(other, "DELETE"), /deletion_account_changed/);
  assert.throws(() => create().prepare(account, "delete"), /invalid_account_deletion/);
});

test("only confirmed deletion clears target account journals and exact app keys, preserving other accounts and unrelated storage", () => {
  const { create, values, journal } = fixture();
  const one = journal().prepare(account, { prompt: "private query" });
  const two = journal().prepare(other, { prompt: "other query" });
  journal().complete(other, two.body.idempotencyKey, { map: "other result" });
  values.set("unrelated-settings", "leave alone");
  values.set("vision-community-jobs", "private saved prompt");
  values.set("vision-community-mma-key", "private map-app credential");
  const body = create().prepare(account, "DELETE");
  assert.throws(() => create().finish(body, { deleted: false }, account), /deletion_unconfirmed/);
  assert.ok(values.has(`vision-community-search:${account}`));
  create().finish(body, { deleted: true }, account);
  assert.equal(create().read(), null);
  assert.equal(values.has(`vision-community-search:${account}`), false);
  assert.equal(values.has("vision-community-jobs"), false);
  assert.equal(values.has("vision-community-mma-key"), false);
  assert.equal(values.get("unrelated-settings"), "leave alone");
  assert.equal(journal().result(other).map, "other result");
  // A response that was already in flight in a different tab cannot rewrite it.
  journal().complete(account, one.body.idempotencyKey, { map: "late private result" });
  assert.equal(values.has(`vision-community-search:${account}:result`), false);
  assert.throws(() => journal().prepare(account, { prompt: "new query" }), /account_deleted/);
});

test("an account change during deletion preserves the new account and keeps the saved receipt", () => {
  const { create, values } = fixture();
  const body = create().prepare(account, "DELETE");
  values.set("vision-community-jobs", "other user's current jobs");
  assert.throws(() => create().finish(body, { deleted: true }, other), /deletion_account_changed/);
  assert.equal(values.get("vision-community-jobs"), "other user's current jobs");
  assert.ok(create().read());
});

test("browser storage failures keep the deletion receipt until cleanup succeeds", () => {
  const { create, storage, values } = fixture();
  const body = create().prepare(account, "DELETE");
  const remove = storage.removeItem;
  storage.removeItem = () => { throw Error("storage denied"); };
  assert.throws(() => create().finish(body, { deleted: true }, account), /deletion_storage_unavailable/);
  assert.ok(create().read());
  assert.equal(values.get(`vision-community-deleted:${account}`), "1");
  storage.removeItem = remove;
  create().finish(body, { deleted: true }, null);
  assert.equal(create().read(), null);
});

test("pending deletion blocks new paid searches, while malformed receipts and denied storage are preserved", () => {
  const { create, journal, values, pendingKey, storage } = fixture();
  create().prepare(account, "DELETE");
  assert.throws(() => journal().prepare(account, { prompt: "a new search" }), /account_deletion_pending/);
  assert.ok(journal().prepare(other, { prompt: "other account's search" }));
  values.set(pendingKey, "damaged receipt");
  assert.throws(() => create().read(), /deletion_recovery_invalid/);
  assert.equal(values.get(pendingKey), "damaged receipt");
  values.delete(pendingKey);
  storage.setItem = () => { throw Error("storage denied"); };
  assert.throws(() => create().prepare(account, "DELETE"), /deletion_storage_unavailable/);
  assert.equal(create().read(), null);
});
