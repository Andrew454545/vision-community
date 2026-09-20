const $ = (id) => document.getElementById(id);
const number = (value) => Number(value || 0).toLocaleString();
const PACE_WORKERS = {
  slow: 1,
  medium: Math.max(1, Math.floor((navigator.hardwareConcurrency || 2) / 2)),
  max: navigator.hardwareConcurrency || 2,
};
const ERRORS = {
  no_available_work: "No locations left in this contribute lane. Switch Scene/Objects above Process, or wait for a new catalog.",
  insufficient_credit: "Not enough units for a search. Process another batch first.",
  verification_failed: "A location failed verification and was not credited.",
  expired_lease: "That batch expired. Claim a new one.",
  unauthorized: "Session missing. Create or restore an account.",
  invalid_mma_map: "That file is not a map-making.app JSON with customCoordinates.",
  invalid_pano_id: "A panorama ID in the JSON is missing or invalid.",
  invalid_json: "The server could not read that request.",
  invalid_country_filter: "Choose at least one country, or switch back to All countries.",
  cross_origin_request: "That request was blocked.",
  internal_error: "The service hit an internal error. Try again.",
  paused: "Paused. The current location finished.",
};

const ALL_GENERATIONS = ["badcam", "gen1", "gen2", "gen3", "gen4", "trekker"];

let signedIn = false;
let state = null;
let pauseRequested = false;
let lastRecovery = "";
let lastMap = null;
let queryMap = null;
let jobs = [newJob("New search")];
let selectedJob = jobs[0].id;

function newJob(name) {
  return {
    id: crypto.randomUUID(),
    name: name || "New search",
    lane: "scene",
    resultCount: 200,
    maxPerCountry: 25,
    countryMode: "all",
    selectedCountries: [],
    generations: ALL_GENERATIONS.slice(),
    countrySearch: "",
  };
}

function currentJob() {
  return jobs.find((item) => item.id === selectedJob);
}

function countryMode() {
  return document.querySelector('input[name="country-mode"]:checked')?.value || "all";
}

function selectedGenerations() {
  return [...document.querySelectorAll('input[name="generation"]:checked')].map((input) => input.value);
}

function selectedCountries() {
  return [...document.querySelectorAll('input[name="country"]:checked')].map((input) => input.value);
}

function visibleCountryLabels() {
  return [...document.querySelectorAll("#country-list label")].filter((label) => label.style.display !== "none");
}

function saveJobFromForm() {
  const job = currentJob();
  if (!job) return;
  job.name = $("output-name").value.trim() || "New search";
  job.lane = selectedLane();
  job.resultCount = Number($("result-count").value) || 200;
  job.maxPerCountry = Number($("max-per-country").value) || 25;
  job.countryMode = countryMode();
  job.selectedCountries = selectedCountries();
  job.generations = selectedGenerations();
  job.countrySearch = $("country-search").value;
}

function applyJobToForm(job) {
  $("output-name").value = job.name;
  document.querySelector(`input[name="mode"][value="${job.lane}"]`).checked = true;
  $("result-count").value = job.resultCount;
  $("max-per-country").value = job.maxPerCountry;
  document.querySelector(`input[name="country-mode"][value="${job.countryMode || "all"}"]`).checked = true;
  $("country-search").value = job.countrySearch || "";
  document.querySelectorAll('input[name="generation"]').forEach((input) => {
    input.checked = (job.generations || ALL_GENERATIONS).includes(input.value);
  });
  $("job-title").textContent = job.name;
  renderCountries();
  updateFilterHelp();
}

function renderCountries() {
  const list = $("country-list");
  const countries = state?.countries || [];
  const job = currentJob();
  const selected = new Set(job?.selectedCountries || selectedCountries());
  const query = ($("country-search").value || "").trim().toLowerCase();
  const mode = countryMode();
  list.replaceChildren();
  if (!countries.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No indexed source has country metadata.";
    list.append(empty);
  } else {
    for (const country of countries) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "country";
      input.value = country;
      input.checked = selected.has(country);
      input.disabled = mode === "all";
      const text = document.createElement("span");
      text.textContent = country;
      label.append(input, text);
      if (query && !country.toLowerCase().includes(query)) label.style.display = "none";
      input.addEventListener("change", () => {
        saveJobFromForm();
        if (normalizeCountrySelection()) renderCountries();
        updateFilterHelp();
        updateReady();
      });
      list.append(label);
    }
  }
  const interactive = mode !== "all";
  list.classList.toggle("disabled", !interactive);
  $("country-search").disabled = !interactive;
  $("select-visible-countries").disabled = !interactive || !countries.length;
  $("clear-countries").disabled = mode === "all" && !selected.size;
}

function updateFilterHelp() {
  const gens = selectedGenerations();
  $("generation-help").textContent = gens.length === ALL_GENERATIONS.length
    ? "All generations · no generation filter"
    : `Only the selected generation${gens.length === 1 ? "" : "s"}`;
  const mode = countryMode();
  const countries = state?.countries || [];
  const selected = selectedCountries();
  if (!countries.length) {
    $("country-help").textContent = "No indexed source has country metadata.";
  } else if (mode === "all") {
    $("country-help").textContent = `All ${countries.length} indexed countries may be returned. Choose Include or Exclude to narrow the search.`;
  } else if (!selected.length) {
    $("country-help").textContent = "Choose at least one country, or switch back to All countries.";
  } else if (mode === "include") {
    $("country-help").textContent = `Only the ${selected.length} selected ${selected.length === 1 ? "country" : "countries"} may be returned.`;
  } else {
    $("country-help").textContent = `The ${selected.length} selected ${selected.length === 1 ? "country is" : "countries are"} excluded.`;
  }
}

function explain(error) {
  return ERRORS[error.message] || error.message;
}

async function api(path, method = "GET", body = null) {
  const headers = {};
  if (body !== null) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method, headers, credentials: "same-origin", cache: "no-store",
    body: body === null ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function selectedLane() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function selectedProcessLane() {
  return document.querySelector('input[name="process-lane"]:checked')?.value || "scene";
}

function pendingFor(lane) {
  return Number((state?.counts && state.counts[lane] && state.counts[lane].pending) || 0);
}

function updateQueue() {
  const scene = pendingFor("scene");
  const object = pendingFor("object");
  const lane = selectedProcessLane();
  $("queue-label").textContent = `${number(scene)} scene and ${number(object)} object locations remaining`;
  const canProcess = signedIn && pendingFor(lane) > 0 && !document.getElementById("process").dataset.busy;
  if (!document.getElementById("process").dataset.busy) $("process").disabled = !canProcess;
}

function renderJobs() {
  const list = $("jobs");
  list.replaceChildren();
  for (const job of jobs) {
    const item = document.createElement("li");
    if (job.id === selectedJob) item.classList.add("selected");
    if (queryMap && job.id === selectedJob) item.classList.add("ready");
    const dot = document.createElement("span");
    dot.className = "dot";
    const title = document.createElement("span");
    title.append(job.name);
    const meta = document.createElement("small");
    meta.textContent = `${job.lane} search`;
    title.append(meta);
    item.append(dot, title);
    item.addEventListener("click", () => {
      saveJobFromForm();
      selectedJob = job.id;
      applyJobToForm(job);
      renderJobs();
      updateReady();
    });
    list.append(item);
  }
}

function updateReady() {
  const includeReady = countryMode() !== "include" || selectedCountries().length > 0;
  const generationReady = selectedGenerations().length > 0;
  const ready = Boolean(queryMap)
    && signedIn
    && includeReady
    && generationReady
    && Number(state?.units || 0) >= Number(state?.searchCost || Infinity);
  $("ready-badge").textContent = queryMap ? (ready ? "Ready" : "Needs credit") : "Needs JSON";
  if (queryMap && signedIn && (!includeReady || !generationReady)) $("ready-badge").textContent = "Needs filters";
  $("ready-badge").classList.toggle("ok", ready);
  $("run-search").disabled = !ready;
  $("job-title").textContent = $("output-name").value.trim() || "New search";
}

function coordinatesFrom(documentMap) {
  if (!documentMap) return [];
  if (Array.isArray(documentMap.customCoordinates)) return documentMap.customCoordinates;
  if (Array.isArray(documentMap.locations)) return documentMap.locations;
  if (Array.isArray(documentMap.coordinates)) return documentMap.coordinates;
  if (Array.isArray(documentMap)) return documentMap;
  return [];
}

function normalizeCountrySelection() {
  const countries = state?.countries || [];
  if (countryMode() !== "include" || !countries.length) return false;
  if (selectedCountries().length !== countries.length) return false;
  document.querySelector('input[name="country-mode"][value="all"]').checked = true;
  const job = currentJob();
  if (job) {
    job.countryMode = "all";
    job.selectedCountries = [];
  }
  return true;
}

function useQueryMap(documentMap, label) {
  const coordinates = coordinatesFrom(documentMap);
  if (!coordinates.length) throw new Error("invalid_mma_map");
  queryMap = Array.isArray(documentMap)
    ? { name: "VISION Community", customCoordinates: documentMap }
    : documentMap;
  $("file-name").textContent = label;
  if (!Array.isArray(documentMap) && documentMap.name) {
    $("output-name").value = documentMap.name;
    const job = jobs.find((item) => item.id === selectedJob);
    if (job) job.name = documentMap.name;
    renderJobs();
  }
  updateReady();
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
  $("pause").disabled = !signedIn;
  $("account-chip").textContent = signedIn ? `Account ${state.accountId.slice(0, 8)}` : "Not signed in";
  $("build-label").textContent = state.operational ? "Prototype · operational" : "Index + JSON only";
  if (!signedIn) $("process-status").textContent = "Create an account to begin.";
  else if ($("process-status").textContent === "Create an account to begin.")
    $("process-status").textContent = "Ready for an exclusive batch.";
  saveJobFromForm();
  updateQueue();
  renderCountries();
  updateFilterHelp();
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
  saveJobFromForm();
  const job = newJob("New search");
  job.lane = selectedLane();
  jobs.push(job);
  selectedJob = job.id;
  applyJobToForm(job);
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

document.querySelectorAll('input[name="process-lane"]').forEach((input) => {
  input.addEventListener("change", updateQueue);
});

document.querySelectorAll('input[name="generation"]').forEach((input) => {
  input.addEventListener("change", () => {
    if (!selectedGenerations().length) input.checked = true;
    saveJobFromForm();
    updateFilterHelp();
    updateReady();
  });
});

document.querySelectorAll('input[name="country-mode"]').forEach((input) => {
  input.addEventListener("change", () => {
    const job = currentJob();
    if (job) job.selectedCountries = [];
    saveJobFromForm();
    renderCountries();
    updateFilterHelp();
    updateReady();
  });
});

$("country-search").addEventListener("input", () => {
  saveJobFromForm();
  renderCountries();
});

$("select-visible-countries").addEventListener("click", () => {
  for (const label of visibleCountryLabels()) {
    const input = label.querySelector("input");
    if (input) input.checked = true;
  }
  saveJobFromForm();
  if (normalizeCountrySelection()) renderCountries();
  updateFilterHelp();
  updateReady();
});

$("clear-countries").addEventListener("click", () => {
  document.querySelector('input[name="country-mode"][value="all"]').checked = true;
  $("country-search").value = "";
  const job = currentJob();
  if (job) {
    job.countryMode = "all";
    job.selectedCountries = [];
    job.countrySearch = "";
  }
  renderCountries();
  updateFilterHelp();
  updateReady();
});

["result-count", "max-per-country"].forEach((id) => {
  $(id).addEventListener("change", saveJobFromForm);
});

$("create-account").addEventListener("click", async () => {
  const button = $("create-account");
  button.disabled = true;
  try {
    const created = await api("/api/accounts", "POST", {});
    lastRecovery = created.recoveryCode || "";
    $("recovery-once").hidden = false;
    $("recovery-once-text").textContent = `Save this recovery code now. It will not be shown again: ${lastRecovery}`;
    await refresh();
    $("process-status").textContent = "Ready for an exclusive batch.";
  } catch (error) {
    $("process-status").textContent = `Account error: ${explain(error)}`;
    button.disabled = false;
  }
});

$("dismiss-recovery").addEventListener("click", () => {
  $("recovery-once").hidden = true;
  $("recovery-once-text").textContent = "";
  lastRecovery = "";
});

$("copy-recovery").addEventListener("click", async () => {
  if (!lastRecovery) return;
  try {
    await navigator.clipboard.writeText(lastRecovery);
    $("copy-recovery").textContent = "Copied";
  } catch {
    $("copy-recovery").textContent = "Copy failed";
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
    $("process-status").textContent = `Recovery stopped: ${explain(error)}`;
  }
});

$("pause").addEventListener("click", () => {
  pauseRequested = true;
  $("process-status").textContent = "Pause requested. The current location will finish, then work stops.";
});

$("process").addEventListener("click", async () => {
  const button = $("process");
  button.disabled = true;
  button.dataset.busy = "1";
  pauseRequested = false;
  const lane = selectedProcessLane();
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
    $("process-status").textContent = `Processing stopped: ${explain(error)}`;
  } finally {
    delete button.dataset.busy;
    updateQueue();
  }
});

$("choose-json").addEventListener("click", () => $("query-map").click());

$("query-map").addEventListener("change", async () => {
  const file = $("query-map").files[0];
  if (!file) return;
  try {
    useQueryMap(JSON.parse(await file.text()), file.name);
  } catch (error) {
    queryMap = null;
    $("file-name").textContent = "That file is not valid map JSON.";
    updateReady();
  }
});

$("load-sample").addEventListener("click", async () => {
  try {
    const sample = await fetch("/sample-query.json", { cache: "no-store" }).then((response) => {
      if (!response.ok) throw new Error("invalid_mma_map");
      return response.json();
    });
    useQueryMap(sample, "sample-query.json");
  } catch (error) {
    $("search-status").textContent = `Sample JSON failed: ${explain(error)}`;
  }
});

function downloadMap() {
  const hits = lastMap?.customCoordinates || [];
  if (!hits.length) return;
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
  saveJobFromForm();
  try {
    const result = await api("/api/searches", "POST", {
      idempotencyKey: crypto.randomUUID(),
      lane: selectedLane(),
      queryMap,
      outputName: $("output-name").value.trim(),
      resultCount: Number($("result-count").value),
      maxPerCountry: Number($("max-per-country").value),
      countryFilterMode: countryMode(),
      countries: selectedCountries(),
      cameraGenerations: selectedGenerations(),
    });
    lastMap = result.map || null;
    const hits = lastMap?.customCoordinates || [];
    $("download-map").hidden = hits.length === 0;
    const list = $("results");
    list.replaceChildren();
    for (const hit of hits) {
      const item = document.createElement("li");
      const extra = hit.extra || {};
      const title = document.createElement("span");
      title.textContent = hit.panoId || "";
      const detail = document.createElement("small");
      detail.textContent = `${hit.lat}, ${hit.lng} · rank ${extra.visionRank} · ${extra.visionScore} · ${(extra.tags || []).join(" · ")} · ${extra.visionCameraGeneration || ""}`;
      item.append(title, detail);
      list.append(item);
    }
    $("search-status").textContent = hits.length
      ? `${hits.length} locations. Download JSON and open it on map-making.app.`
      : "No locations matched those filters.";
    await refresh();
  } catch (error) {
    $("search-status").textContent = `Search stopped: ${explain(error)}`;
  } finally {
    updateReady();
  }
});

$("download-map").addEventListener("click", downloadMap);

renderJobs();
refresh().catch((error) => {
  $("process-status").textContent = `Unable to reach the service: ${explain(error)}`;
});
