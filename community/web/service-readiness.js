/* Availability guidance only. Device qualification and auditing stay on the server. */
class VisionServiceReadiness {
  constructor() { this.connected = false; this.checked = false; this.status = null; this.capabilities = null; }
  update(status, capabilities) {
    this.checked = true;
    this.connected = status?.operational === true;
    this.status = status;
    this.capabilities = capabilities;
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
    if (!this.connected) return "The service is unavailable. Keep your account code and browser data. Check again later; saved credits and search requests stay saved.";
    if (lanes.some(lane => lane !== "scene")) return "Object processing is still being validated. Choose Scene to check scene setup. Your saved credits are kept.";
    if (!this.canContribute(lanes)) return "Scene setup is not available yet. The required computer check and contribution verification must be enabled first. You can restore your account and keep your credits.";
    if (!this.canSearch()) return "Scene setup is available and requires the computer check. Online search is unavailable; unused credits stay saved for later.";
    return "Scene setup is available and requires the computer check. Online search uses your saved credits.";
  }
  static async capabilities(fetcher = fetch) {
    try {
      const response = await fetcher("/api/capabilities", {
        credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(15000),
      });
      return response.ok ? await response.json() : null;
    } catch { return null; }
  }
}
globalThis.VisionServiceReadiness = VisionServiceReadiness;
