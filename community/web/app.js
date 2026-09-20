const $ = (id) => document.getElementById(id);
const number = (value) => Number(value || 0).toLocaleString();
const PACE_WORKERS = {
  slow: 1,
  medium: Math.max(1, Math.floor((navigator.hardwareConcurrency || 2) / 2)),
  max: navigator.hardwareConcurrency || 2,
};

let signedIn = false;
let state = null;
let pauseRequested = false;
let lastMap = null;
let queryMap = null;
let jobs = [{ id: crypto.randomUUID(), name: "New search", lane: "scene" }];
let selectedJob = jobs[0].id;

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

function selectedLane() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function renderJobs() {
  const list = $("jobs");
  list.replaceChildren();
  for (const job of jobs) {
    const item = document.createElement("li");
    item.className = job.id === selectedJob ? "selected" : "";
    if (queryMap && job.id === selectedJob) item.classList.add("ready");
    item.innerHTML = `<span class="dot"></span><span>${job.name}<small>${job.lane} search</small></span>`;
    item.addEventListener("click", () => {
      selectedJob = job.id;
      $("output-name").value = job.name;
      document.querySelector(`input[name="mode"][value="${job.lane}"]`).checked = true;
      $("job-title").textContent = job.name;
      renderJobs();
      updateReady();
    });
    list.append(item);
  }
}

function updateReady() {
  const ready = Boolean(queryMap) && signedIn && Number(state?.units || 0) >= Number(state?.searchCost || Infinity);
  $("ready-badge").textContent = queryMap ? (ready ? "Ready" : "Needs credit") : "Needs JSON";
  $("ready-badge").classList.toggle("ok", ready);
  $("run-search").disabled = !ready;
  $("job-title").textContent = $("output-name").value.trim() || "New search";
}

async function refresh() {
  const publicState = await api("/api/status");
  state = await api("/api/me").catch((error) => {
    if (error.message === "unauthorized") return publicState;
    throw error;
  });
  signedIn = Boolean(state.accountId);
  const scene = state.counts.scene || { pending: 0, published: 0 };
  const object = state.counts.object || { pending: 0, published: 0 };
  const indexed = (scene.published || 0) + (object.published || 0);
  $("index-label").textContent = `${number(indexed)} indexed locations · prototype corpus`;
  $("search-cost").textContent = number(state.searchCost);
  $("units").textContent = number(state.units || 0);
  $("searches-available").textContent = number(state.searchesAvailable || 0);
  $("create-account").hidden = signedIn;
  $("process").disabled = !signedIn;
  $("pause").disabled = !signedIn;
  $("account-chip").textContent = signedIn ? `Account ${state.accountId.slice(0, 8)}` : "Not signed in";
  $("build-label").textContent = state.operational ? "Prototype · operational" : "Index + JSON only";
  if (!signedIn) $("process-status").textContent = "Create an account to begin.";
  else if ($("process-status").textContent === "Create an account to begin.")
    $("process-status").textContent = "Ready for an exclusive batch.";
  updateReady();
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

$("add-job").addEventListener("click", () => {
  const job = { id: crypto.randomUUID(), name: "New search", lane: selectedLane() };
  jobs.push(job);
  selectedJob = job.id;
  $("output-name").value = job.name;
  renderJobs();
});

$("output-name").addEventListener("input", () => {
  const job = jobs.find((item) => item.id === selectedJob);
  if (job) job.name = $("output-name").value.trim() || "New search";
  renderJobs();
  updateReady();
});

document.querySelectorAll('input[name="mode"]').forEach((input) => {
  input.addEventListener("change", () => {
    const job = jobs.find((item) => item.id === selectedJob);
    if (job) job.lane = selectedLane();
    renderJobs();
  });
});

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
  const lane = selectedLane();
  const pace = document.querySelector('input[name="pace"]:checked').value;
  const workers = PACE_WORKERS[pace];
  try {
    const lease = await api("/api/leases", "POST", { lane, count: lane === "scene" ? 4 : 1, pace });
    const outputs = await mapPool(lease.items, workers, async (item, index) => {
      $("process-status").textContent = `Processing ${index + 1} of ${lease.items.length} with ${workers} worker${workers === 1 ? "" : "s"}…`;
      return window.VISIONVisual.processItem(item);
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

$("query-map").addEventListener("change", async () => {
  const file = $("query-map").files[0];
  if (!file) return;
  queryMap = JSON.parse(await file.text());
  $("file-name").textContent = file.name;
  if (queryMap.name) {
    $("output-name").value = queryMap.name;
    const job = jobs.find((item) => item.id === selectedJob);
    if (job) job.name = queryMap.name;
    renderJobs();
  }
  updateReady();
});

$("load-sample").addEventListener("click", async () => {
  const sample = await fetch("/sample-query.json", { cache: "no-store" }).then((response) => response.json());
  queryMap = sample;
  $("file-name").textContent = "sample-query.json";
  $("output-name").value = sample.name;
  const job = jobs.find((item) => item.id === selectedJob);
  if (job) job.name = sample.name;
  renderJobs();
  updateReady();
});

function downloadMap() {
  if (!lastMap) return;
  const blob = new Blob([JSON.stringify(lastMap, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${(lastMap.name || "vision-community").replace(/\s+/g, "-")}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

$("run-search").addEventListener("click", async () => {
  const button = $("run-search");
  button.disabled = true;
  try {
    const result = await api("/api/searches", "POST", {
      idempotencyKey: crypto.randomUUID(),
      lane: selectedLane(),
      queryMap,
      outputName: $("output-name").value.trim(),
      resultCount: Number($("result-count").value),
      maxPerCountry: Number($("max-per-country").value),
    });
    lastMap = result.map || null;
    $("download-map").hidden = !lastMap;
    const list = $("results");
    list.replaceChildren();
    for (const hit of lastMap?.customCoordinates || []) {
      const item = document.createElement("li");
      const extra = hit.extra || {};
      item.innerHTML = `<span>${hit.panoId}</span><small>${hit.lat}, ${hit.lng} · rank ${extra.visionRank} · ${extra.visionScore} · ${(extra.tags || []).join(" · ")}</small>`;
      list.append(item);
    }
    $("search-status").textContent = lastMap
      ? `${lastMap.customCoordinates.length} locations. Download JSON and open it on map-making.app.`
      : "No matches.";
    await refresh();
  } catch (error) {
    $("search-status").textContent = `Search stopped: ${error.message}`;
  } finally {
    updateReady();
  }
});

$("download-map").addEventListener("click", downloadMap);

renderJobs();
refresh().catch((error) => {
  $("process-status").textContent = `Unable to reach the service: ${error.message}`;
});
