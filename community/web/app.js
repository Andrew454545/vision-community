const $ = (id) => document.getElementById(id);
const number = (value) => Number(value || 0).toLocaleString();
let signedIn = false;
let state = null;
let pauseRequested = false;
const PACE_WORKERS = { slow: 1, medium: Math.max(1, Math.floor((navigator.hardwareConcurrency || 2) / 2)), max: navigator.hardwareConcurrency || 2 };

async function api(path, method = "GET", body = null) {
  const headers = {};
  if (body !== null) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method, headers, credentials: "same-origin", cache: "no-store",
    body: body === null ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function refresh() {
  const publicState = await api("/api/status");
  state = await api("/api/me").catch((error) => {
    if (error.message === "unauthorized") {
      return publicState;
    }
    throw error;
  });
  signedIn = Boolean(state.accountId);
  const scene = state.counts.scene || { pending: 0, published: 0 };
  const object = state.counts.object || { pending: 0, published: 0 };
  $("scene-published").textContent = number(scene.published);
  $("object-published").textContent = number(object.published);
  $("work-remaining").textContent = number(scene.pending + object.pending);
  $("search-cost").textContent = number(state.searchCost);
  $("units").textContent = number(state.units || 0);
  $("searches-available").textContent = number(state.searchesAvailable || 0);
  $("account-state").hidden = !signedIn;
  $("account-id").textContent = state.accountId ? state.accountId.slice(0, 8) : "";
  $("create-account").hidden = signedIn;
  $("process").disabled = !signedIn;
  $("pause").disabled = !signedIn;
  $("search-form").querySelector("button").disabled = !signedIn || Number(state.units || 0) < state.searchCost;
  $("build-label").textContent = state.operational ? "Public service" : "Not operational";
  if (state.r2 === "not_created") {
    $("notice-title").textContent = "Not a public VISION corpus";
    $("notice-body").textContent = "Google Street View is not connected. Credits and searches are enforced on the server. The R2 bucket has not been created. Slow, medium, and max change concurrent device work.";
  }
  if (!signedIn) $("process-status").textContent = "Create an account to begin.";
  else if ($("process-status").textContent === "Create an account to begin.")
    $("process-status").textContent = "Ready for an exclusive batch.";
}

function wait(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

async function fixtureHash(item) {
  const indexText = item.label.toLowerCase().trim().replace(/\s+/g, " ");
  const message = `VISION-FIXTURE-V2\n${item.assetId}\n${item.capture}\n${item.lane}\n${item.model}\n${indexText}`;
  const bytes = new TextEncoder().encode(message);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return {
    indexText,
    outputSha256: Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join(""),
  };
}

async function mapPool(items, limit, mapper) {
  const outputs = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      if (pauseRequested) throw new Error("paused");
      const index = next;
      next += 1;
      outputs[index] = await mapper(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, worker));
  return outputs;
}

$("create-account").addEventListener("click", async () => {
  const button = $("create-account");
  button.disabled = true;
  try {
    const created = await api("/api/accounts", "POST", {});
    $("recovery-once").hidden = false;
    $("recovery-once").textContent = `Save this recovery code now. It will not be shown again: ${created.recoveryCode}`;
    await refresh();
    $("process-status").textContent = "Ready for an exclusive batch.";
  } catch (error) {
    $("process-status").textContent = `Account error: ${error.message}`;
    button.disabled = false;
  }
});

$("recover-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/recovery", "POST", { recoveryCode: $("recovery-code").value.trim() });
    $("recovery-once").hidden = true;
    await refresh();
    $("process-status").textContent = "Session restored.";
  } catch (error) {
    $("process-status").textContent = `Recovery stopped: ${error.message}`;
  }
});

$("pause").addEventListener("click", () => {
  pauseRequested = true;
  $("process-status").textContent = "Pause requested. The current location will finish, then work stops.";
});

$("process").addEventListener("click", async () => {
  const button = $("process");
  button.disabled = true;
  pauseRequested = false;
  const lane = $("lane").value;
  const pace = document.querySelector('input[name="pace"]:checked').value;
  const workers = PACE_WORKERS[pace];
  try {
    const lease = await api("/api/leases", "POST", { lane, count: lane === "scene" ? 4 : 1, pace });
    const outputs = await mapPool(lease.items, workers, async (item, index) => {
      $("process-status").textContent = `Processing ${index + 1} of ${lease.items.length} with ${workers} worker${workers === 1 ? "" : "s"}…`;
      if (item.model === "community-visual-v1") {
        return window.VISIONVisual.processItem(item);
      }
      return { locationId: item.locationId, ...await fixtureHash(item) };
    });
    const accepted = await api("/api/submissions", "POST", { leaseId: lease.leaseId, outputs });
    $("process-status").textContent = `${accepted.accepted} locations verified and published. +${accepted.unitsEarned} units.`;
    await refresh();
  } catch (error) {
    $("process-status").textContent = `Processing stopped: ${error.message}`;
  } finally {
    button.disabled = !signedIn;
  }
});

$("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("search-form").querySelector("button");
  button.disabled = true;
  const query = $("query").value.trim();
  const file = $("query-image").files[0];
  try {
    const body = { idempotencyKey: crypto.randomUUID(), lane: $("lane").value };
    if (file) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      bytes.forEach((value) => { binary += String.fromCharCode(value); });
      body.queryImage = btoa(binary);
    } else {
      body.query = query;
    }
    const result = await api("/api/searches", "POST", body);
    const list = $("results");
    list.replaceChildren();
    for (const hit of result.results) {
      const item = document.createElement("li");
      const content = document.createElement("span");
      content.textContent = hit.label || `score ${hit.score}`;
      const detail = document.createElement("small");
      detail.textContent = `${hit.lane} · location ${hit.locationId}`;
      content.append(detail);
      item.append(content);
      list.append(item);
    }
    $("search-status").textContent = result.demo
      ? (result.results.length ? `${result.results.length} fixture matches. One search used.` : "No fixture matches. One search used.")
      : (result.results.length ? `${result.results.length} ranked visual matches. One search used.` : "No visual matches. One search used.");
    await refresh();
  } catch (error) {
    $("search-status").textContent = `Search stopped: ${error.message}`;
  } finally {
    button.disabled = !signedIn || Number(state?.units || 0) < Number(state?.searchCost || Infinity);
  }
});

refresh().catch((error) => {
  $("process-status").textContent = `Unable to reach the local service: ${error.message}`;
});
