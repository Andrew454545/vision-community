const $ = (id) => document.getElementById(id);
const number = (value) => Number(value || 0).toLocaleString();
const PACE_WORKERS = {
  slow: 1,
  medium: Math.max(1, Math.floor((navigator.hardwareConcurrency || 2) / 2)),
  max: navigator.hardwareConcurrency || 2,
};
const PACE_LEASE = {
  scene: { slow: 1, medium: 4, max: 8 },
  object: { slow: 1, medium: 2, max: 4 },
};
const ERRORS = {
  no_available_work: "No more places are waiting right now. Try Objects, or wait for more work.",
  insufficient_credit: "Keep indexing. A search needs 100,000 places (or 10,000 objects).",
  verification_failed: "That place could not be checked, so it was not counted.",
  view_unavailable: "Street View did not return that place, so it was not counted.",
  expired_lease: "That batch timed out. Click Start again.",
  unauthorized: "No account on this browser. Get a free account or paste your saved code.",
  invalid_mma_map: "That file is not a map JSON we can use.",
  invalid_pano_id: "A place ID in that file is missing or invalid.",
  invalid_json: "That request could not be read. Try again.",
  invalid_country_filter: "Pick at least one country, or switch back to All countries.",
  cross_origin_request: "That request was blocked.",
  internal_error: "Something went wrong. Try again in a moment.",
  search_on_computer: "The shared index is now too large for this browser tab. Search on your computer with the command under Faster.",
};

const ALL_GENERATIONS = ["badcam", "gen1", "gen2", "gen3", "gen4", "trekker"];
const VIEW_DIRECTION_LABELS = {
  bestOfFour: "Best of available views",
  original: "Saved pan (0°)",
  opposite: "Opposite saved pan (180°)",
  right: "Right of saved pan (+90°)",
  left: "Left of saved pan (+270°)",
  originalAxis: "Saved axis (0° / 180°)",
  sideAxis: "Cross-axis (+90° / +270°)",
};

let signedIn = false;
let state = null;
let pauseRequested = false;
let lastRecovery = "";
let lastMap = null;
let queryMap = null;
let jobs = [newJob("Example search")];
let selectedJob = jobs[0].id;

function newJob(name) {
  return {
    id: crypto.randomUUID(),
    name: name || "Example search",
    lane: "scene",
    resultCount: 200,
    maxPerCountry: 25,
    countryMode: "all",
    selectedCountries: [],
    generations: ALL_GENERATIONS.slice(),
    countrySearch: "",
    viewDirection: "bestOfFour",
    excludeMap: null,
    excludeName: "",
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
  job.name = $("output-name").value.trim() || "Example search";
  job.lane = selectedLane();
  job.resultCount = Number($("result-count").value) || 200;
  job.maxPerCountry = Number($("max-per-country").value) || 25;
  job.countryMode = countryMode();
  job.selectedCountries = selectedCountries();
  job.generations = selectedGenerations();
  job.countrySearch = $("country-search").value;
  job.viewDirection = $("view-direction").value || "bestOfFour";
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
  $("view-direction").value = job.viewDirection || "bestOfFour";
  $("exclude-file-name").textContent = job.excludeName || "None";
  updateViewDirection();
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
    ? "All cameras are included"
    : `Only the camera types you ticked`;
  const mode = countryMode();
  const countries = state?.countries || [];
  const selected = selectedCountries();
  if (!countries.length) {
    $("country-help").textContent = "Country filters are not available yet.";
  } else if (mode === "all") {
    $("country-help").textContent = `Results can come from any of ${countries.length} countries.`;
  } else if (!selected.length) {
    $("country-help").textContent = "Pick at least one country, or switch back to All countries.";
  } else if (mode === "include") {
    $("country-help").textContent = `Only the ${selected.length} selected ${selected.length === 1 ? "country" : "countries"}.`;
  } else {
    $("country-help").textContent = `Skipping ${selected.length} ${selected.length === 1 ? "country" : "countries"}.`;
  }
}

function updateViewDirection() {
  const scene = selectedLane() === "scene";
  $("view-direction-block").hidden = !scene;
  $("view-direction").disabled = !scene;
}

function explain(error) {
  return ERRORS[error.message] || error.message;
}

async function copyText(text, highlight) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    try {
      if (document.execCommand("copy")) return true;
    } finally {
      area.remove();
    }
  }
  if (highlight) {
    const range = document.createRange();
    range.selectNodeContents(highlight);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }
  return false;
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

function cliCommand() {
  const origin = window.location.origin;
  const lane = selectedProcessLane();
  const pace = document.querySelector('input[name="pace"]:checked')?.value || "medium";
  const code = lastRecovery || $("recovery-code")?.value.trim() || "YOUR_CODE";
  return `python3 -m community.contribute --url ${origin} --lane ${lane} --pace ${pace} --recovery-code ${code}`;
}

function localSearchCommand() {
  const origin = window.location.origin;
  const code = lastRecovery || $("recovery-code")?.value.trim() || "YOUR_CODE";
  const lane = selectedLane();
  return `python3 -m community.local_search --url ${origin} --lane ${lane} --query community/web/sample-query.json --recovery-code ${code}`;
}

function updateCliCommand() {
  const node = $("cli-command");
  if (node) node.textContent = cliCommand();
  const searchNode = $("local-search-command");
  if (searchNode) searchNode.textContent = localSearchCommand();
}

function updateQueue() {
  const scene = pendingFor("scene");
  const object = pendingFor("object");
  const lane = selectedProcessLane();
  $("queue-label").textContent = `${number(scene)} places and ${number(object)} objects still waiting`;
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
    const direction = job.lane === "scene"
      ? VIEW_DIRECTION_LABELS[job.viewDirection || "bestOfFour"]
      : "Objects";
    meta.textContent = `${job.lane} · ${direction}`;
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
  const onSite = state?.searchOnSite !== false;
  const ready = Boolean(queryMap)
    && signedIn
    && includeReady
    && generationReady
    && Number(state?.units || 0) >= Number(state?.searchCost || Infinity)
    && onSite;
  let badge = "Get an account";
  if (!signedIn) badge = "Get an account";
  else if (!queryMap) badge = "Example still loading";
  else if (!includeReady || !generationReady) badge = "Check filters";
  else if (!onSite && Number(state?.units || 0) >= Number(state?.searchCost || Infinity)) badge = "Search on your computer";
  else if (ready) badge = "Ready to search";
  else badge = "Keep indexing";
  $("ready-badge").textContent = badge;
  $("ready-badge").classList.toggle("ok", ready);
  $("run-search").disabled = !ready;
  $("job-title").textContent = $("output-name").value.trim() || "Find matching places";
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

async function ensureSampleQuery() {
  if (queryMap) return;
  try {
    const sample = await fetch("/sample-query.json", { cache: "no-store" }).then((response) => {
      if (!response.ok) throw new Error("invalid_mma_map");
      return response.json();
    });
    useQueryMap(sample, "Example search");
  } catch {
    $("file-name").textContent = "Example could not load. Use More options to choose a file.";
  }
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
  const pending = (scene.pending || 0) + (object.pending || 0);
  $("index-label").textContent = `${number(indexed)} indexed · ${number(pending)} queued`;
  $("search-cost").textContent = number(state.searchCost);
  $("units").textContent = number(state.units || 0);
  $("searches-available").textContent = number(state.searchesAvailable || 0);
  const need = Math.max(0, Number(state.searchCost || 0) - Number(state.units || 0));
  const cost = Number(state.searchCost || 100000);
  const units = Number(state.units || 0);
  const fill = $("progress-fill");
  if (fill) fill.style.width = `${Math.min(100, cost ? (units / cost) * 100 : 0)}%`;
  if ($("progress-label")) {
    $("progress-label").textContent = need === 0
      ? "Search is unlocked"
      : `${number(units)} of ${number(cost)} toward a search`;
  }
  if ($("units-need")) {
    $("units-need").textContent = need === 0
      ? "search unlocked"
      : `${number(need)} more`;
  }
  if (!signedIn) {
    $("search-status").textContent = "Get an account, click Start, and leave this tab open.";
  } else if (!lastMap) {
    if (state.searchOnSite === false) {
      $("search-status").textContent = need === 0
        ? "The index is too large for this tab. Use the search command under Faster."
        : `Keep this tab open. ${number(need)} more until you can search on your computer.`;
    } else {
      $("search-status").textContent = need === 0
        ? "Search is ready. Press Search, then Download."
        : `Keep this tab open. ${number(need)} more until Search unlocks.`;
    }
  }
  $("create-account").hidden = signedIn;
  $("pause").disabled = !signedIn;
  $("account-chip").textContent = signedIn ? "Signed in on this browser" : "No account yet";
  $("build-label").textContent = "Leave this tab open while indexing";
  if (!signedIn) $("process-status").textContent = "Get an account, then click Start.";
  else if ($("process-status").textContent === "Get an account, then click Start."
    || $("process-status").textContent === "Create an account to begin.")
    $("process-status").textContent = "Click Start and leave this tab open.";
  saveJobFromForm();
  updateQueue();
  renderCountries();
  updateFilterHelp();
  updateReady();
  updateCliCommand();
  await ensureSampleQuery();
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
  const job = newJob("Example search");
  job.lane = selectedLane();
  jobs.push(job);
  selectedJob = job.id;
  applyJobToForm(job);
  renderJobs();
});

$("output-name").addEventListener("input", () => {
  const job = jobs.find((item) => item.id === selectedJob);
  if (job) job.name = $("output-name").value.trim() || "Example search";
  renderJobs();
  updateReady();
});

document.querySelectorAll('input[name="mode"]').forEach((input) => {
  input.addEventListener("change", () => {
    const job = jobs.find((item) => item.id === selectedJob);
    if (job) job.lane = selectedLane();
    updateViewDirection();
    renderJobs();
  });
});

document.querySelectorAll('input[name="process-lane"]').forEach((input) => {
  input.addEventListener("change", () => {
    updateQueue();
    updateCliCommand();
  });
});

document.querySelectorAll('input[name="pace"]').forEach((input) => {
  input.addEventListener("change", updateCliCommand);
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

["result-count", "max-per-country", "view-direction"].forEach((id) => {
  $(id).addEventListener("change", () => {
    saveJobFromForm();
    renderJobs();
  });
});

$("create-account").addEventListener("click", async () => {
  const button = $("create-account");
  button.disabled = true;
  try {
    const created = await api("/api/accounts", "POST", {});
    lastRecovery = created.recoveryCode || "";
    $("recovery-once").hidden = false;
    $("recovery-once-text").textContent = `Write this code down or screenshot it. It is the only way back into this account: ${lastRecovery}`;
    await refresh();
    $("process-status").textContent = "Saved? Click Start and leave this tab open.";
    updateCliCommand();
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
  $("copy-recovery").textContent = await copyText(lastRecovery, $("recovery-once-text")) ? "Copied" : "Selected — press ⌘C / Ctrl+C";
});

$("copy-cli").addEventListener("click", async () => {
  updateCliCommand();
  $("copy-cli").textContent = await copyText(cliCommand(), $("cli-command")) ? "Copied" : "Selected — press ⌘C / Ctrl+C";
});

$("copy-local-search").addEventListener("click", async () => {
  updateCliCommand();
  $("copy-local-search").textContent = await copyText(localSearchCommand(), $("local-search-command")) ? "Copied" : "Selected — press ⌘C / Ctrl+C";
});

$("recovery-code").addEventListener("input", updateCliCommand);

$("recover-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/recovery", "POST", { recoveryCode: $("recovery-code").value.trim() });
    $("recovery-once").hidden = true;
    await refresh();
    $("process-status").textContent = "Welcome back. Click Start to keep going.";
    updateCliCommand();
  } catch (error) {
    $("process-status").textContent = `Recovery stopped: ${explain(error)}`;
  }
});

$("pause").addEventListener("click", () => {
  pauseRequested = true;
  $("process-status").textContent = "Stopping after this place finishes…";
});

$("process").addEventListener("click", async () => {
  const button = $("process");
  button.disabled = true;
  button.dataset.busy = "1";
  pauseRequested = false;
  const lane = selectedProcessLane();
  const pace = document.querySelector('input[name="pace"]:checked').value;
  const workers = PACE_WORKERS[pace];
  const count = PACE_LEASE[lane][pace];
  let acceptedTotal = 0;
  let unitsTotal = 0;
  let currentLeaseId = null;
  try {
    while (!pauseRequested) {
      const lease = await api("/api/leases", "POST", { lane, count, pace });
      currentLeaseId = lease.leaseId;
      let processed = 0;
      const outputs = await mapPool(lease.items, workers, async (item) => {
        processed += 1;
        $("process-status").textContent = `Working… ${acceptedTotal + processed} places in this session`;
        return window.VISIONVisual.processItem(item);
      });
      const accepted = await api("/api/submissions", "POST", { leaseId: lease.leaseId, outputs });
      currentLeaseId = null;
      acceptedTotal += accepted.accepted;
      unitsTotal += accepted.unitsEarned;
      $("process-status").textContent = `${number(acceptedTotal)} places finished. Keep this tab open.`;
      await refresh();
    }
    $("process-status").textContent = `Paused after ${number(acceptedTotal)} places.`;
  } catch (error) {
    if (currentLeaseId) {
      await api("/api/leases/release", "POST", { leaseId: currentLeaseId }).catch(() => {});
      currentLeaseId = null;
    }
    if (error.message === "paused") {
      $("process-status").textContent = `Paused after ${number(acceptedTotal)} places.`;
    } else if (error.message === "no_available_work" && acceptedTotal) {
      $("process-status").textContent = `Caught up for now: ${number(acceptedTotal)} places finished.`;
    } else {
      $("process-status").textContent = `Processing stopped: ${explain(error)}`;
    }
  } finally {
    delete button.dataset.busy;
    updateQueue();
  }
});

$("choose-json").addEventListener("click", () => $("query-map").click());

$("choose-exclude").addEventListener("click", () => $("exclude-map").click());

$("clear-exclude").addEventListener("click", () => {
  const job = currentJob();
  if (job) {
    job.excludeMap = null;
    job.excludeName = "";
  }
  $("exclude-map").value = "";
  $("exclude-file-name").textContent = "None";
});

$("exclude-map").addEventListener("change", async () => {
  const file = $("exclude-map").files[0];
  if (!file) return;
  try {
    const documentMap = JSON.parse(await file.text());
    const coordinates = coordinatesFrom(documentMap);
    if (!coordinates.length) throw new Error("invalid_mma_map");
    const job = currentJob();
    if (job) {
      job.excludeMap = Array.isArray(documentMap)
        ? { name: "Previous map", customCoordinates: documentMap }
        : documentMap;
      job.excludeName = file.name;
    }
    $("exclude-file-name").textContent = file.name;
  } catch (error) {
    const job = currentJob();
    if (job) {
      job.excludeMap = null;
      job.excludeName = "";
    }
    $("exclude-file-name").textContent = "That file is not valid map JSON.";
  }
});

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
    useQueryMap(sample, "Example search");
  } catch (error) {
    $("search-status").textContent = `Could not load the example: ${explain(error)}`;
  }
});

function sortKeysDeep(value) {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortKeysDeep(value[key])]));
  }
  return value;
}

function downloadMap() {
  const hits = lastMap?.customCoordinates || [];
  if (!hits.length) return;
  const blob = new Blob([`${JSON.stringify(sortKeysDeep(lastMap), null, 2)}\n`], { type: "application/json" });
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
      excludeMap: currentJob()?.excludeMap || undefined,
      viewDirection: selectedLane() === "scene" ? ($("view-direction").value || "bestOfFour") : undefined,
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
      const country = Array.isArray(extra.tags) ? extra.tags.find((tag) => tag) : "";
      const title = document.createElement("span");
      title.textContent = country || hit.panoId || "";
      const detail = document.createElement("small");
      const offset = extra.visionHeadingOffset;
      const offsetLabel = selectedLane() === "scene" && Number.isFinite(offset)
        ? ` · ${offset}° from saved pan`
        : "";
      detail.textContent = `${hit.panoId || ""} · ${hit.lat}, ${hit.lng} · heading ${hit.heading}${offsetLabel} · rank ${extra.visionRank} · ${extra.visionScore} · ${extra.visionCameraGeneration || ""}`;
      item.append(title, detail);
      list.append(item);
    }
    $("search-status").textContent = hits.length
      ? `${hits.length} matching places. Click Download, then open that file on the map site.`
      : "Nothing matched. Try Best of available views, or open More options.";
    await refresh();
  } catch (error) {
    $("search-status").textContent = `Search stopped: ${explain(error)}`;
  } finally {
    updateReady();
  }
});

$("download-map").addEventListener("click", downloadMap);

renderJobs();
updateViewDirection();
updateCliCommand();
refresh().catch((error) => {
  $("process-status").textContent = `Unable to reach the service: ${explain(error)}`;
});
