import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { stageScene, auditScene, qualifyDevice, auditBatchLimit, verifierConfigured, pipelineCapabilities } from "./scenePipeline.js";
import { deleteAccount, cleanupAccountArtifacts, migrateAccountPrivacy } from "./accountPrivacy.js";
import { sha256Hex } from "./model.js";
import { PRIVACY_FENCE, writeSceneArtifact } from "./artifactWrites.js";
import { syntheticR2 } from "./syntheticR2.mjs";

const leaseId = "d".repeat(32);

test('staging policy identities cannot authorize production or a mixed bucket', async () => {
  let calls = 0;
  const env = { SCENE_VERIFIER: { fetch() { calls++; } }, SCENE_POLICY_ID: 'staging.measured-candidate',
    DEPLOYMENT_ENVIRONMENT: 'staging', INDEX_BUCKET_NAME: 'vision-community-staging' };
  assert.equal(verifierConfigured(env), true);
  for (const change of [{ DEPLOYMENT_ENVIRONMENT: 'production' }, { DEPLOYMENT_ENVIRONMENT: undefined },
    { INDEX_BUCKET_NAME: 'vision-community' }, { INDEX_BUCKET_NAME: undefined }]) {
    const blocked = { ...env, ...change };
    assert.equal(verifierConfigured(blocked), false);
    await assert.rejects(qualifyDevice(blocked, 'anonymous', {}, () => true), /scene_verification_unavailable/);
  }
  assert.equal(calls, 0);
});

test('native audit capacity is bounded independently of user processing pace', () => {
  const env = { SCENE_VERIFIER: { fetch() {} }, SCENE_POLICY_ID: 'synthetic-test-only' };
  assert.equal(auditBatchLimit(env), 8);
  assert.equal(pipelineCapabilities(env).sceneContributions.maxBatchLocations, 8);
  for (const value of ['1', '16', '64', '128']) {
    assert.equal(auditBatchLimit({ ...env, SCENE_AUDIT_MAX_LOCATIONS: value }), Number(value));
  }
  for (const value of ['', '0', '-1', '129', '16.5', '016', 'all', 16, null]) {
    const broken = { ...env, SCENE_AUDIT_MAX_LOCATIONS: value };
    assert.equal(auditBatchLimit(broken), null);
    assert.equal(verifierConfigured(broken), false);
  }
});

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

async function fixture(t, decision = "approved", stage = true) {
  const sql = new DatabaseSync(":memory:");
  t.after(() => sql.close());
  sql.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  sql.exec("ALTER TABLE pose_catalog ADD COLUMN assignee TEXT; ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER;");
  const now = Math.floor(Date.now() / 1000);
  sql.prepare("INSERT INTO accounts (id, token_hash) VALUES ('anonymous', 'hash')").run();
  sql.prepare("INSERT INTO scene_qualifications VALUES ('qualification', 'anonymous', ?, 'test-policy', ?, ?, ?)")
    .run("a".repeat(64), "b".repeat(64), now + 3600, now);
  sql.prepare("INSERT INTO leases (id, account_id, lane, expires_at, state, scene_qualification_id) VALUES (?, 'anonymous', 'scene', ?, 'active', 'qualification')")
    .run(leaseId, now + 3600);
  sql.exec(`INSERT INTO locations (id,asset_id,capture,lane,model,state,active_lease,lat,lon,heading,pitch,zoom,country,camera_generation)
    VALUES (1,'synthetic-panorama','2026-09','scene','community-visual-v1','leased','${leaseId}',10,20,90,0,0,'Italy','gen4');
    INSERT INTO lease_items VALUES ('${leaseId}',1);`);
  const objects = new Map();
  const env = { DB: d1(sql), SCENE_POLICY_ID: "test-policy", INDEX: syntheticR2(objects), SCENE_VERIFIER: { async fetch(request) {
    const body = await request.json();
    return Response.json({ policyId: body.policyId, submissionSha256: body.submissionSha256, decision });
  } } };
  const embedding = new Uint8Array(3080);
  await migrateAccountPrivacy(env);
  for (let view = 0; view < 4; view++) { embedding[view * 770 + 1] = 60; embedding[view * 770 + 2] = 7; }
  const row = sql.prepare("SELECT * FROM locations WHERE id=1").get();
  const verified = [{ row, embedding, digest: await sha256Hex(embedding) }];
  if (stage) {
    const staged = await stageScene(env, "anonymous", leaseId, verified, now);
    assert.equal(staged.unitsEarned, 0);
    assert.equal(staged.pendingAudit, true);
  }
  return { sql, env, objects, verified, now };
}

test("concurrent approved audits publish and credit exactly once", async (t) => {
  const { sql, env } = await fixture(t);
  const results = await Promise.all([auditScene(env, "anonymous", leaseId), auditScene(env, "anonymous", leaseId)]);
  assert.equal(results.reduce((total, result) => total + result.unitsEarned, 0), 1);
  assert.equal(sql.prepare("SELECT units FROM accounts").get().units, 1);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger").get().n, 1);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM published_index").get().n, 1);
  assert.equal((await auditScene(env, "anonymous", leaseId)).unitsEarned, 0);
});

test("native audit metadata includes authoritative country and camera generation in its fingerprint", async t => {
  const { env, sql } = await fixture(t);
  const stored = JSON.parse(sql.prepare("SELECT records_json FROM scene_candidates").get().records_json)[0];
  assert.equal(stored.country, "Italy");
  assert.equal(stored.cameraGeneration, "gen4");
  const original = env.SCENE_VERIFIER.fetch;
  env.SCENE_VERIFIER.fetch = async request => {
    const copy = request.clone(), body = await copy.json();
    assert.equal(body.records[0].country, "Italy");
    assert.equal(body.records[0].cameraGeneration, "gen4");
    const blob = Buffer.from(body.indexBase64, "base64");
    assert.equal(await sha256Hex(Buffer.concat([Buffer.from(JSON.stringify(body.records)+"\n"),blob])), body.submissionSha256);
    return original(request);
  };
  assert.equal((await auditScene(env, "anonymous", leaseId)).unitsEarned, 1);
});

test("rejected audits are terminal without publication or credits", async (t) => {
  const { sql, env } = await fixture(t, "rejected");
  const rejected = await auditScene(env, "anonymous", leaseId);
  assert.equal(rejected.rejected, true);
  assert.equal(rejected.pending, 0);
  assert.equal((await auditScene(env, "anonymous", leaseId)).unitsEarned, 0);
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
  await assert.rejects(auditScene(env, "anonymous", leaseId), /scene_submission_conflict/);
  assert.equal(sql.prepare("SELECT units FROM accounts").get().units, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger").get().n, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM published_index").get().n, 0);
});

test("a publication error rolls back credit and leaves the candidate pending", async (t) => {
  const { sql, env } = await fixture(t);
  sql.exec("INSERT INTO published_index (location_id,index_text,output_sha256,published_at) VALUES (1,'','preexisting',0)");
  await assert.rejects(auditScene(env, "anonymous", leaseId), /UNIQUE constraint failed/);
  assert.equal(sql.prepare("SELECT units FROM accounts").get().units, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger").get().n, 0);
  assert.equal(sql.prepare("SELECT state FROM scene_candidates").get().state, "pending");
});

test("an unavailable verifier preserves quarantine for retry", async (t) => {
  const { sql, env } = await fixture(t);
  env.SCENE_VERIFIER.fetch = () => { throw new Error("offline"); };
  assert.equal((await auditScene(env, "anonymous", leaseId)).pendingAudit, true);
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
  await assert.rejects(auditScene(env, "anonymous", leaseId), /account_not_active/);
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

test("qualification service outages stay retryable and do not mark a PC unqualified", async t => {
  const { sql, env } = await fixture(t);
  const bytes = new Uint8Array(3080), blob = new Uint8Array(112 * 3080);
  const canary = { locations: 112, records: Array(112).fill(Buffer.from(bytes).toString("base64")),
    outputSha256: await sha256Hex(blob) };
  const before = sql.prepare("SELECT COUNT(*) AS n FROM scene_qualifications").get().n;
  for (const verifier of [() => { throw Error("offline"); }, () => new Response("unavailable", { status: 503 })]) {
    env.SCENE_VERIFIER.fetch = verifier;
    await assert.rejects(qualifyDevice(env, "anonymous", { profileId: "a".repeat(64), canary }, () => true),
      error => error.message === "scene_verification_unavailable" && error.status === 503);
  }
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM scene_qualifications").get().n, before);
});

test("an explicit negative qualification remains a PC rejection", async t => {
  const { env } = await fixture(t);
  const blob = new Uint8Array(112 * 3080);
  const canary = { locations: 112, records: Array(112).fill(Buffer.alloc(3080).toString("base64")),
    outputSha256: await sha256Hex(blob) };
  for (const response of [Response.json({ approved: false }), Response.json({ approved: false }, { status: 422 }),
    Response.json({ error: "scene_device_not_qualified" }, { status: 422 })]) {
    env.SCENE_VERIFIER.fetch = () => response;
    await assert.rejects(qualifyDevice(env, "anonymous", { profileId: "a".repeat(64), canary }, () => true),
      error => error.message === "scene_device_not_qualified" && error.status === 422);
  }
});

const deletion = { accountId: "anonymous", confirmation: "DELETE", idempotencyKey: "c".repeat(64) };
function noCredit(sql) {
  assert.equal(sql.prepare("SELECT units FROM accounts").get().units, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM published_index").get().n, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM ledger WHERE reason='verified_work'").get().n, 0);
}

test("deletion during quarantine upload fences a late create before any candidate exists", async t => {
  const { sql, env, objects, verified, now } = await fixture(t, "approved", false);
  const put = env.INDEX.put;
  let lateKey;
  env.INDEX.put = async (key, value, options) => {
    if (!options?.customMetadata?.visionPrivacyFence) {
      lateKey = key;
      assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM account_artifact_writes").get().n, 1);
      assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM scene_candidates").get().n, 0);
      await deleteAccount(env, "anonymous", deletion);
      await cleanupAccountArtifacts(env, "anonymous");
    }
    return put(key, value, options);
  };
  await assert.rejects(stageScene(env, "anonymous", leaseId, verified, now), /index_artifact_fenced/);
  assert.equal(new TextDecoder().decode(objects.get(lateKey)), PRIVACY_FENCE);
  assert.equal(sql.prepare("SELECT state FROM account_cleanup").get().state, "fenced");
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM scene_candidates").get().n, 0);
  noCredit(sql);
});

test("deletion after R2 commits but before upload returns removes the payload and blocks staging", async t => {
  const { sql, env, objects, verified, now } = await fixture(t, "approved", false);
  const put = env.INDEX.put;
  let uploadedKey;
  env.INDEX.put = async (key, value, options) => {
    const result = await put(key, value, options);
    if (!options?.customMetadata?.visionPrivacyFence) {
      uploadedKey = key;
      await deleteAccount(env, "anonymous", deletion);
      await cleanupAccountArtifacts(env, "anonymous");
    }
    return result;
  };
  await assert.rejects(stageScene(env, "anonymous", leaseId, verified, now), /account_not_active/);
  assert.equal(new TextDecoder().decode(objects.get(uploadedKey)), PRIVACY_FENCE);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM scene_candidates").get().n, 0);
  noCredit(sql);
});

test("deletion during final publication upload fences both scene copies and cannot earn credit", async t => {
  const { sql, env, objects } = await fixture(t);
  const put = env.INDEX.put;
  env.INDEX.put = async (key, value, options) => {
    if (key.startsWith("four-view-v4/") && !options?.customMetadata?.visionPrivacyFence) {
      assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM account_artifact_writes").get().n, 2);
      await deleteAccount(env, "anonymous", deletion);
      await cleanupAccountArtifacts(env, "anonymous");
    }
    return put(key, value, options);
  };
  await assert.rejects(auditScene(env, "anonymous", leaseId), /index_artifact_fenced/);
  assert.equal(objects.size, 2);
  for (const bytes of objects.values()) assert.equal(new TextDecoder().decode(bytes), PRIVACY_FENCE);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM account_cleanup WHERE state='fenced'").get().n, 2);
  assert.equal(sql.prepare("SELECT records_json FROM scene_candidates").get().records_json, "[]");
  noCredit(sql);
});

test("cleanup retains published scene bytes even if their final key is mistakenly queued", async t => {
  const { sql, env, objects } = await fixture(t);
  await auditScene(env, "anonymous", leaseId);
  const publishedKey = `four-view-v4/${leaseId}.i8`, published = objects.get(publishedKey).slice();
  await deleteAccount(env, "anonymous", deletion);
  sql.prepare("INSERT INTO account_cleanup VALUES (?,'anonymous',1,'pending')").run(publishedKey);
  await cleanupAccountArtifacts(env);
  assert.deepEqual(objects.get(publishedKey), published);
  assert.equal(sql.prepare("SELECT state FROM account_cleanup WHERE artifact_key=?").get(publishedKey).state, "retained");
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM published_index").get().n, 1);
});

test("a failed durable intent cannot start an R2 upload", async t => {
  const { sql, env, objects, verified, now } = await fixture(t, "approved", false);
  sql.exec("CREATE TRIGGER reject_intent BEFORE INSERT ON account_artifact_writes BEGIN SELECT RAISE(ABORT,'simulated intent failure'); END;");
  await assert.rejects(stageScene(env, "anonymous", leaseId, verified, now), /simulated intent failure/);
  assert.equal(objects.size, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM account_artifact_writes").get().n, 0);
  noCredit(sql);
});

test("lease loss before journaling stops upload without misclassifying the live account as deleted", async t => {
  const { sql, env, objects, verified, now } = await fixture(t, "approved", false);
  sql.exec("UPDATE leases SET state='expired'");
  await assert.rejects(stageScene(env, "anonymous", leaseId, verified, now), error => error.message === "lease_lost" && error.status === 409);
  assert.equal(objects.size, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM account_artifact_writes").get().n, 0);
  assert.equal(sql.prepare("SELECT deleted_at FROM accounts").get().deleted_at, null);
  noCredit(sql);
});

test("an unconfirmed upload never stages a candidate or grants credit", async t => {
  const { sql, env, verified, now } = await fixture(t, "approved", false);
  for (const response of [undefined, { size: 1 }]) {
    env.INDEX.put = async () => response;
    await assert.rejects(stageScene(env, "anonymous", leaseId, verified, now), error => error.message === "index_write_unconfirmed" && error.status === 503);
    assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM scene_candidates").get().n, 0);
  }
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM account_artifact_writes").get().n, 1);
  noCredit(sql);
});

test("failed uploads remain discoverable for deletion cleanup without a staged candidate", async t => {
  const { sql, env, objects, verified, now } = await fixture(t, "approved", false);
  const put = env.INDEX.put;
  env.INDEX.put = async () => { throw Error("synthetic upload interrupted"); };
  await assert.rejects(stageScene(env, "anonymous", leaseId, verified, now), /synthetic upload interrupted/);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM scene_candidates").get().n, 0);
  await deleteAccount(env, "anonymous", deletion);
  await cleanupAccountArtifacts(env);
  assert.equal(sql.prepare("SELECT state FROM account_cleanup").get().state, "pending");
  env.INDEX.put = put;
  await cleanupAccountArtifacts(env);
  assert.equal(sql.prepare("SELECT state FROM account_cleanup").get().state, "fenced");
  assert.equal(objects.size, 1);
  noCredit(sql);
});

test("artifact intents and create-only bytes are immutable across retries", async t => {
  const { sql, env, objects, verified, now } = await fixture(t);
  const key = sql.prepare("SELECT artifact_key FROM account_artifact_writes").get().artifact_key;
  const original = objects.get(key).slice();
  const changed = original.slice(); changed[1] ^= 1;
  await assert.rejects(writeSceneArtifact(env, "anonymous", leaseId, key, changed, now), /index_artifact_changed/);
  assert.deepEqual(objects.get(key), original);
  assert.throws(() => sql.exec("UPDATE account_artifact_writes SET sha256='changed'"), /artifact_write_intent_immutable/);
  assert.equal(await writeSceneArtifact(env, "anonymous", leaseId, key, original, now), verified[0].digest);
});

test("damaged cleanup ownership or an active owner cannot fence an artifact", async t => {
  const { sql, env, objects } = await fixture(t);
  const key = sql.prepare("SELECT artifact_key FROM account_artifact_writes").get().artifact_key;
  const original = objects.get(key).slice();
  sql.prepare("INSERT INTO account_cleanup VALUES (?,'anonymous',1,'pending')").run(key);
  await cleanupAccountArtifacts(env);
  assert.equal(sql.prepare("SELECT state FROM account_cleanup").get().state, "needs_review");
  assert.deepEqual(objects.get(key), original);
  sql.exec("INSERT INTO accounts (id,token_hash,units,deleted_at) VALUES ('other-deleted','other-hash',0,1)");
  sql.prepare("UPDATE account_cleanup SET state='pending',account_id='other-deleted' WHERE artifact_key=?").run(key);
  await cleanupAccountArtifacts(env);
  assert.equal(sql.prepare("SELECT state FROM account_cleanup").get().state, "needs_review");
  assert.deepEqual(objects.get(key), original);
});
