import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { stageScene, auditScene, qualifyDevice } from "./scenePipeline.js";
import { deleteAccount, migrateAccountPrivacy } from "./accountPrivacy.js";
import { sha256Hex } from "./model.js";

function d1(database) {
  return {
    prepare(query) {
      function statement(args = []) {
        const execute = () => {
          const result = database.prepare(query).run(...args);
          return { success: true, meta: { changes: Number(result.changes) } };
        };
        return { bind: (...bound) => statement(bound),
          first: async () => database.prepare(query).get(...args) || null,
          all: async () => ({ results: database.prepare(query).all(...args) }),
          run: async () => execute(), execute };
      }
      return statement();
    },
    async batch(statements) {
      database.exec("BEGIN IMMEDIATE");
      try {
        const results = statements.map((statement) => statement.execute());
        database.exec("COMMIT");
        return results;
      } catch (error) { database.exec("ROLLBACK"); throw error; }
    },
  };
}

async function fixture(t, decision = "approved") {
  const sql = new DatabaseSync(":memory:");
  t.after(() => sql.close());
  sql.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  sql.exec("ALTER TABLE pose_catalog ADD COLUMN assignee TEXT; ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER;");
  const now = Math.floor(Date.now() / 1000);
  sql.prepare("INSERT INTO accounts (id, token_hash) VALUES ('anonymous', 'hash')").run();
  sql.prepare("INSERT INTO scene_qualifications VALUES ('qualification', 'anonymous', ?, 'test-policy', ?, ?, ?)")
    .run("a".repeat(64), "b".repeat(64), now + 3600, now);
  sql.prepare("INSERT INTO leases (id, account_id, lane, expires_at, state, scene_qualification_id) VALUES ('lease', 'anonymous', 'scene', ?, 'active', 'qualification')")
    .run(now + 3600);
  sql.exec(`INSERT INTO locations (id,asset_id,capture,lane,model,state,active_lease,lat,lon,heading,pitch,zoom)
    VALUES (1,'synthetic-panorama','2026-09','scene','community-visual-v1','leased','lease',10,20,90,0,0);
    INSERT INTO lease_items VALUES ('lease',1);`);
  const objects = new Map();
  const env = { DB: d1(sql), SCENE_POLICY_ID: "test-policy", INDEX: {
    async put(key, bytes) { objects.set(key, new Uint8Array(bytes)); },
    async get(key) { return objects.has(key) ? new Response(objects.get(key)) : null; },
  }, SCENE_VERIFIER: { async fetch(request) {
    const body = await request.json();
    return Response.json({ policyId: body.policyId, submissionSha256: body.submissionSha256, decision });
  } } };
  const embedding = new Uint8Array(3080);
  await migrateAccountPrivacy(env);
  for (let view = 0; view < 4; view++) { embedding[view * 770 + 1] = 60; embedding[view * 770 + 2] = 7; }
  const row = sql.prepare("SELECT * FROM locations WHERE id=1").get();
  const staged = await stageScene(env, "anonymous", "lease", [{ row, embedding, digest: await sha256Hex(embedding) }], now);
  assert.equal(staged.unitsEarned, 0);
  assert.equal(staged.pendingAudit, true);
  return { sql, env, objects };
}

test("concurrent approved audits publish and credit exactly once", async (t) => {
  const { sql, env } = await fixture(t);
  const results = await Promise.all([auditScene(env, "anonymous", "lease"), auditScene(env, "anonymous", "lease")]);
  assert.equal(results.reduce((total, result) => total + result.unitsEarned, 0), 1);
  assert.equal(sql.prepare("SELECT units FROM accounts").get().units, 1);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger").get().n, 1);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM published_index").get().n, 1);
  assert.equal((await auditScene(env, "anonymous", "lease")).unitsEarned, 0);
});

test("rejected audits are terminal without publication or credits", async (t) => {
  const { sql, env } = await fixture(t, "rejected");
  const rejected = await auditScene(env, "anonymous", "lease");
  assert.equal(rejected.rejected, true);
  assert.equal(rejected.pending, 0);
  assert.equal((await auditScene(env, "anonymous", "lease")).unitsEarned, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM published_index").get().n, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger").get().n, 0);
});

test("changed queue ownership cannot be credited after the verifier returns", async (t) => {
  const { sql, env } = await fixture(t);
  const original = env.SCENE_VERIFIER.fetch;
  env.SCENE_VERIFIER.fetch = async (request) => {
    sql.exec("UPDATE locations SET queue_state='pending' WHERE id=1");
    return original(request);
  };
  await assert.rejects(auditScene(env, "anonymous", "lease"), /scene_submission_conflict/);
  assert.equal(sql.prepare("SELECT units FROM accounts").get().units, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger").get().n, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM published_index").get().n, 0);
});

test("a publication error rolls back credit and leaves the candidate pending", async (t) => {
  const { sql, env } = await fixture(t);
  sql.exec("INSERT INTO published_index (location_id,index_text,output_sha256,published_at) VALUES (1,'','preexisting',0)");
  await assert.rejects(auditScene(env, "anonymous", "lease"), /UNIQUE constraint failed/);
  assert.equal(sql.prepare("SELECT units FROM accounts").get().units, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger").get().n, 0);
  assert.equal(sql.prepare("SELECT state FROM scene_candidates").get().state, "pending");
});

test("an unavailable verifier preserves quarantine for retry", async (t) => {
  const { sql, env } = await fixture(t);
  env.SCENE_VERIFIER.fetch = () => { throw new Error("offline"); };
  assert.equal((await auditScene(env, "anonymous", "lease")).pendingAudit, true);
  assert.equal(sql.prepare("SELECT units FROM accounts").get().units, 0);
  assert.equal(sql.prepare("SELECT state FROM scene_candidates").get().state, "pending");
});

test("deletion while the verifier audits a candidate prevents publication and any credit", async t => {
  const { sql, env } = await fixture(t);
  const original = env.SCENE_VERIFIER.fetch;
  env.SCENE_VERIFIER.fetch = async request => {
    const response = await original(request);
    await deleteAccount(env, "anonymous", { accountId: "anonymous", confirmation: "DELETE", idempotencyKey: "c".repeat(64) });
    return response;
  };
  const result = await auditScene(env, "anonymous", "lease");
  assert.equal(result.unitsEarned, 0);
  assert.equal(result.rejected, true);
  assert.equal(sql.prepare("SELECT units FROM accounts").get().units, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM published_index").get().n, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='verified_work'").get().n, 0);
  assert.equal(sql.prepare("SELECT records_json FROM scene_candidates").get().records_json, "[]");
});

test("a delayed device qualification cannot recreate access after deletion", async t => {
  const { sql, env } = await fixture(t);
  const bytes = new Uint8Array(3080), blob = new Uint8Array(112 * 3080);
  const canary = { locations: 112, records: Array(112).fill(Buffer.from(bytes).toString("base64")),
    outputSha256: await sha256Hex(blob) };
  env.SCENE_VERIFIER.fetch = async request => {
    const body = await request.json();
    await deleteAccount(env, "anonymous", { accountId: "anonymous", confirmation: "DELETE", idempotencyKey: "c".repeat(64) });
    return Response.json({ ...body, approved: true, expiresAt: Math.floor(Date.now() / 1000) + 3600 });
  };
  await assert.rejects(qualifyDevice(env, "anonymous", { profileId: "a".repeat(64), canary }, () => true), /account_not_active/);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM scene_qualifications WHERE expires_at>0").get().n, 0);
});
