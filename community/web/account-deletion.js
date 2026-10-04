// Keep a private receipt key before sending deletion. A lost response must not
// be mistaken for successful deletion merely because the session no longer works.
globalThis.VisionAccountDeletion = class {
  static pendingKey = "vision.community.pending-delete.v1";
  constructor(storage) { this.storage = storage; }
  read() {
    let text;
    try { text = this.storage.getItem(VisionAccountDeletion.pendingKey); }
    catch { throw new Error("deletion_storage_unavailable"); }
    if (!text) return null;
    let body;
    try { body = JSON.parse(text); } catch { throw new Error("deletion_recovery_invalid"); }
    if (!body || !/^[0-9a-f]{32}$/.test(body.accountId) || !/^[0-9a-f]{64}$/.test(body.idempotencyKey)
        || body.confirmation !== "DELETE") throw new Error("deletion_recovery_invalid");
    return body;
  }
  prepare(account, confirmation) {
    if (confirmation !== "DELETE") throw new Error("invalid_account_deletion");
    if (typeof account !== "string" || !/^[0-9a-f]{32}$/.test(account)) throw new Error("unauthorized");
    const pending = this.read();
    if (pending) {
      if (pending.accountId !== account) throw new Error("deletion_account_changed");
      return pending;
    }
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    const body = { accountId: account, confirmation: "DELETE",
      idempotencyKey: Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("") };
    try { this.storage.setItem(VisionAccountDeletion.pendingKey, JSON.stringify(body)); }
    catch { throw new Error("deletion_storage_unavailable"); }
    return body;
  }
  finish(body, response, connectedAccount) {
    const saved = this.read();
    if (!saved || saved.accountId !== body.accountId || saved.idempotencyKey !== body.idempotencyKey
        || response?.deleted !== true) throw new Error("deletion_unconfirmed");
    if (connectedAccount && connectedAccount !== body.accountId) throw new Error("deletion_account_changed");
    try {
      // A tombstone also prevents another open tab from saving a delayed result.
      this.storage.setItem(`vision-community-deleted:${body.accountId}`, "1");
      for (const key of [`vision-community-search:${body.accountId}`, `vision-community-search:${body.accountId}:result`,
        "vision-community-jobs", "vision-community-prefs", "vision-community-indexing",
        "vision-community-mma-key", "vision-community-mma-map"]) this.storage.removeItem(key);
      // Keep the receipt until all browser cleanup succeeds, so it can be retried.
      this.storage.removeItem(VisionAccountDeletion.pendingKey);
    } catch { throw new Error("deletion_storage_unavailable"); }
  }
};
