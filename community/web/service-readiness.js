/* Availability guidance only. Device qualification and auditing stay on the server. */
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
      return scene?.ready === true && scene.scope === "audited-new-locations"
        && scene.deviceQualificationRequired === true && scene.canaryLocations === 112
        && scene.verification === "trusted-profile-canary-and-submission-audit"
        && scene.model === "vision-four-view-v4" && typeof scene.policyId === "string" && !!scene.policyId.trim();
    });
  }
  canSearch(recovering = false) {
    return this.connected && (recovering || this.status?.searchOnSite === true);
  }
  message(lanes) {
    if (!this.checked) return "Checking the service before you start…";
    if (!this.connected) return "Service unavailable. Try later; your credits and searches stay saved. Keep your code and browser data.";
    if (lanes.some(lane => lane !== "scene")) return "Objects are still being validated. Choose Scene. Your credits stay saved.";
    if (!this.canContribute(lanes)) return "Scene setup is not available yet. Try later; your credits stay saved.";
    if (!this.canSearch()) return "Run the PC check to start helping. Search is unavailable; unused credits stay saved.";
    return "Run the PC check to start helping. Search uses your saved credits.";
  }
  static async capabilities(fetcher = fetch) {
    try {
      const response = await fetcher("/api/capabilities", {
        credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(15000),
      });
      return response.ok ? await response.json() : null;
    } catch { return null; }
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
