// Persist the request key before delivery. After a lost response or browser
// restart, retry this exact request so the server can return the paid result.
globalThis.VisionSearchJournal = class {
  constructor(storage) { this.storage = storage; }
  key(account) {
    if (typeof account !== "string" || !/^[0-9a-f]{32}$/.test(account)) throw new Error("unauthorized");
    return `vision-community-search:${account}`;
  }
  read(account) {
    let text;
    const key = this.key(account);
    try {
      if (this.storage.getItem(`vision-community-deleted:${account}`)) throw new Error("account_deleted");
      const pendingDeletion = this.storage.getItem("vision.community.pending-delete.v1");
      if (pendingDeletion) {
        let saved;
        try { saved = JSON.parse(pendingDeletion); } catch { throw new Error("deletion_recovery_invalid"); }
        if (saved?.accountId === account) throw new Error("account_deletion_pending");
      }
      text = this.storage.getItem(key);
    }
    catch (error) {
      if (["account_deleted", "account_deletion_pending", "deletion_recovery_invalid"].includes(error.message)) throw error;
      throw new Error("search_storage_unavailable");
    }
    if (!text) return null;
    let saved;
    try { saved = JSON.parse(text); } catch { throw new Error("search_recovery_invalid"); }
    if (!saved || saved.accountId !== account || typeof saved.idempotencyKey !== "string" || saved.idempotencyKey.length < 8)
      throw new Error("search_recovery_invalid");
    return saved;
  }
  prepare(account, query) {
    const pending = this.read(account);
    if (pending) return { body: pending, recovering: true };
    const body = { ...query, accountId: account, idempotencyKey: crypto.randomUUID() };
    try { this.storage.setItem(this.key(account), JSON.stringify(body)); }
    catch { throw new Error("search_storage_unavailable"); }
    return { body, recovering: false };
  }
  approvePrice(account, key, maxCostUnits) {
    const pending = this.read(account);
    if (!pending || pending.idempotencyKey !== key) throw new Error("search_recovery_invalid");
    if (!Number.isSafeInteger(maxCostUnits) || maxCostUnits <= 0) throw new Error("invalid_search_quote");
    // Only explicit user consent can raise the quote. Preserve the request key
    // and query so a concurrent/already-paid result still replays for free.
    const body = { ...pending, maxCostUnits };
    try { this.storage.setItem(this.key(account), JSON.stringify(body)); }
    catch { throw new Error("search_storage_unavailable"); }
    return body;
  }
  result(account) {
    if (this.storage.getItem(`vision-community-deleted:${account}`)) return null;
    const saved = this.storage.getItem(`${this.key(account)}:result`);
    if (!saved) return null;
    try { return JSON.parse(saved); } catch { return null; }
  }
  complete(account, key, result = null) {
    if (this.storage.getItem(`vision-community-deleted:${account}`)) return;
    if (this.read(account)?.idempotencyKey !== key) return;
    if (result) {
      try { this.storage.setItem(`${this.key(account)}:result`, JSON.stringify(result)); }
      catch { throw new Error("search_storage_unavailable"); }
    }
    this.storage.removeItem(this.key(account));
  }
};
