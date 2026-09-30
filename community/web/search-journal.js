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
    try { text = this.storage.getItem(this.key(account)); }
    catch { throw new Error("search_storage_unavailable"); }
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
  result(account) {
    const saved = this.storage.getItem(`${this.key(account)}:result`);
    if (!saved) return null;
    try { return JSON.parse(saved); } catch { return null; }
  }
  complete(account, key, result = null) {
    if (this.read(account)?.idempotencyKey !== key) return;
    if (result) {
      try { this.storage.setItem(`${this.key(account)}:result`, JSON.stringify(result)); }
      catch { throw new Error("search_storage_unavailable"); }
    }
    this.storage.removeItem(this.key(account));
  }
};
