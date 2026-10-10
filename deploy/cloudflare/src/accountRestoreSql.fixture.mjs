// Synthetic local restore fixtures; never uses accounts, imagery or live services.
import { DatabaseSync } from "node:sqlite";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { preparePrivateRestore, RESOURCE_PROFILES } from "../tools/account-restore.mjs";

export const deletedId = "a".repeat(32), retainedId = "b".repeat(32);
export const privateQuery = "synthetic ' quote; newline\nNUL\0 🍀";
export const digest = raw => createHash("sha256").update(raw).digest("hex");
export function makeSqlFixture(root, environment = "staging") {
  const backup = join(root, "backup.sqlite"), sql = new DatabaseSync(backup);
  try {
    sql.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
    sql.exec(readFileSync(new URL("../tools/initialize-schema.mjs", import.meta.url), "utf8")
      .match(/CREATE TABLE IF NOT EXISTS index_shards \([\s\S]*?\n\);/)[0]);
    sql.exec("ALTER TABLE pose_catalog ADD COLUMN assignee TEXT; ALTER TABLE pose_catalog ADD COLUMN assigned_at INTEGER");
    sql.prepare("INSERT INTO accounts (id,token_hash,recovery_hash,units) VALUES (?,?,?,?)").run(deletedId, "old-token", "old-recovery", 20);
    sql.prepare("INSERT INTO accounts (id,token_hash,units) VALUES (?,?,?)").run(retainedId, "other-token", 40);
    sql.prepare("INSERT INTO searches VALUES (?,?,?,?,?)").run("old-private", deletedId, "old", "deleted private query", "{}");
    sql.prepare("INSERT INTO searches VALUES (?,?,?,?,?)").run("retained-private", retainedId, "retained", privateQuery, Buffer.from([0, 255, 39]));
    sql.exec(`INSERT INTO ledger (account_id,units,reason,reference) VALUES ('${deletedId}',20,'fixture','old-credit');
      INSERT INTO locations (id,asset_id,capture,lane,model) VALUES (9007199254740993,'high-water','synthetic','scene','synthetic');
      DELETE FROM locations;
      INSERT INTO locations (id,asset_id,capture,lane,model,state,contributor_id) VALUES (1,'retained','synthetic','scene','synthetic','published','${deletedId}');
      INSERT INTO published_index (location_id,index_text,output_sha256,published_at,four_view_key) VALUES (1,'synthetic','synthetic',1,'four-view-v4/synthetic.i8')`);
    sql.prepare("UPDATE locations SET heading=?,lat=?,lon=? WHERE id=1").run(Math.PI, 0.10000000000000002, -1e-200);
  } finally { sql.close(); }
  const ledger = { version: 1, scope: "vision-community-account-deletions", resource: RESOURCE_PROFILES[environment],
    exportedAt: 200, receipts: [{ accountId: deletedId, requestKey: "c".repeat(64), deletedAt: 150, unitsForfeited: 20 }] };
  const deletions = join(root, "account-deletions.private.json"), bytes = Buffer.from(JSON.stringify(ledger) + "\n");
  writeFileSync(deletions, bytes);
  const repairedDir = join(root, "repaired");
  preparePrivateRestore({ backup, backupSha256: digest(readFileSync(backup)), deletions, deletionsSha256: digest(bytes),
    notBefore: 100, now: 210, environment, out: repairedDir });
  return { repairedDir, reportSha256: digest(readFileSync(join(repairedDir, "restore-report.json"))), environment };
}
