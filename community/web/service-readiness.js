/* Availability guidance only. Device qualification and upload admission stay on the server. */
class VisionServiceReadiness {
  constructor() { this.connected = false; this.checked = false; this.status = null; this.capabilities = null; }
  update(status, capabilities) {
    if (status?.operational !== true) { this.fail(); return false; }
    this.checked = true;
    this.connected = status?.operational === true;
    this.status = status;
    this.capabilities = capabilities;
    return true;
  }
  fail() { this.checked = true; this.connected = false; }
  canContribute(lanes) {
    if (!this.connected || this.capabilities?.version !== 1 || !lanes?.length) return false;
    return lanes.every(lane => {
      // No approved portable object admission contract has been published yet.
      if (lane !== "scene") return false;
      const scene = this.capabilities.sceneContributions;
      const audited = (scene?.admissionMode === undefined || scene.admissionMode === "audited-v1")
        && scene?.scope === "audited-new-locations"
        && scene.verification === "trusted-profile-canary-and-submission-audit";
      const qualified = scene?.admissionMode === "qualified-device-v1"
        && scene.scope === "qualified-new-locations"
        && scene.verification === "trusted-profile-canary-and-upload-integrity";
      return scene?.ready === true && (audited || qualified)
        && scene.deviceQualificationRequired === true && scene.canaryLocations === 112
        && scene.model === "vision-four-view-v4" && typeof scene.policyId === "string" && !!scene.policyId.trim();
    });
  }
  canSearch(recovering = false, lane = "scene") {
    // Old saved requests remain recoverable, including requests from later lanes.
    return this.connected && (recovering || (lane === "scene" && this.status?.searchOnSite === true));
  }
  message(lanes) {
    if (!this.checked) return "Checking the service before you start…";
    if (!this.connected) return "Service unavailable. Try later; your credits and searches stay saved. Keep your code and browser data.";
    if (lanes.some(lane => lane !== "scene")) return "Objects will follow later. Choose Scene. Your credits stay saved.";
    if (!this.canContribute(lanes)) return "Scene setup is not available yet. Try later; your credits stay saved.";
    if (!this.canSearch()) return "Run the computer check to start processing Scenes. Search is unavailable; unused credits stay saved.";
    return "Run the computer check to start processing Scenes. Search uses your saved credits.";
  }
  static async capabilities(fetcher = fetch) {
    try {
      const response = await fetcher("/api/capabilities", {
        credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(15000),
      });
      return response.ok ? await response.json() : null;
    } catch { return null; }
  }
  static mergeAccountControls(previous, next) {
    const count = value => Number.isSafeInteger(value) && value >= 0;
    const cost = next?.searchCost;
    const signedIn = typeof next?.accountId === "string" && /^[0-9a-f]{32}$/.test(next.accountId);
    const queued = next?.searchDelivery === "queued";
    const allowed = new Set(["accountControlVersion", "operational", "environment", "model", "creditContractVersion",
      "accountId", "units", "bankedUnits", "reservedUnits", "searchesAvailable", "searchCost", "searchBackend",
      "searchOnSite", "searchReady", "searchDelivery", "searchResultLimits", "indexDownloads", "accountDeletionAvailable"]);
    if (!next || typeof next !== "object" || Array.isArray(next)
        || Object.keys(next).some(key => !allowed.has(key))
        || next.accountControlVersion !== 1 || next.creditContractVersion !== 1 || next.operational !== true
        || !["staging", "preview"].includes(next.environment) || typeof next.model !== "string" || !next.model
        || !signedIn && next.accountId !== null || !count(next.units) || !count(next.searchesAvailable)
        || cost !== null && (!Number.isSafeInteger(cost) || cost < 1)
        || next.searchesAvailable !== (cost === null ? 0 : Math.floor(next.units / cost))
        || ![true, false].includes(next.searchOnSite) || next.searchReady !== next.searchOnSite
        || (cost === null || !signedIn) && next.searchOnSite !== false
        || next.searchBackend !== "online" || !["immediate", "queued"].includes(next.searchDelivery)
        || next.indexDownloads !== false || next.accountDeletionAvailable !== true
        || !next.searchResultLimits || Object.keys(next.searchResultLimits).sort().join(",") !== "object,scene"
        || ![next.searchResultLimits.scene, next.searchResultLimits.object].every(n => Number.isSafeInteger(n) && n > 0 && n <= 10000)
        || signedIn && queued && (!count(next.bankedUnits) || !count(next.reservedUnits)
          || next.bankedUnits - next.reservedUnits !== next.units)
        || (!signedIn || !queued) && ("bankedUnits" in next || "reservedUnits" in next)
        || !signedIn && next.units !== 0) throw new Error("invalid_service_response");
    // These are shared corpus labels/counts, never account work or credentials.
    // A changed/revoked session must discard every prior account-specific field.
    const shared = {};
    for (const key of ["countries", "cameraGenerations", "counts", "r2", "visualPublished", "objectIndexes", "sceneIndexes"])
      if (previous && key in previous) shared[key] = previous[key];
    const sameAccount = signedIn && previous?.accountId === next.accountId;
    const result = {...(sameAccount ? previous : shared), ...next};
    // Changing delivery mode must not retain a previous reservation summary.
    if (!queued) { delete result.bankedUnits; delete result.reservedUnits; }
    return result;
  }
  static async readResponse(response, path = "") {
    let data;
    try { data = await response.json(); }
    catch { throw new Error("invalid_service_response"); }
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("invalid_service_response");
    if (response.ok && path === "/api/searches" && (!/^[0-9a-f]{32}$/.test(data.searchId || "")
      || !Array.isArray(data.results) || !Array.isArray(data.map?.customCoordinates))) {
      throw new Error("invalid_service_response");
    }
    return data;
  }
}
globalThis.VisionServiceReadiness = VisionServiceReadiness;

globalThis.VisionSearchPricing = Object.freeze({
  cost(status) {
    return Number.isSafeInteger(status?.searchCost) && status.searchCost > 0 ? status.searchCost : null;
  },
  canAfford(status) {
    const cost = this.cost(status);
    return cost !== null && Number.isSafeInteger(status?.units) && status.units >= cost;
  },
  message(status) {
    const cost = this.cost(status);
    if (cost === null) return "The search price is unavailable. Your credits stay saved.";
    const units = Number.isSafeInteger(status?.units) && status.units >= 0 ? status.units : 0;
    const need = Math.max(0, cost - units);
    return `A search costs ${cost.toLocaleString()} units.${need ? ` Keep indexing: ${need.toLocaleString()} more needed.` : " You have enough saved credit."}`;
  },
});
