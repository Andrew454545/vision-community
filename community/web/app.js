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
  no_available_work: "No more work is waiting for that choice right now. Try Places, Objects, or Both.",
  insufficient_credit: "Keep indexing. A search needs 100,000 places (or 10,000 objects).",
  verification_failed: "That place could not be checked, so it was not counted.",
  view_unavailable: "Street View did not return that place, so it was not counted.",
  expired_lease: "That batch timed out. Click Start again.",
  unauthorized: "No account on this browser. Get a free account or paste your saved code.",
  invalid_mma_map: "That file is not a map JSON we can use.",
  invalid_query: "Add a description, a JSON file, or both.",
  invalid_pano_id: "A place ID in that file is missing or invalid.",
  invalid_json: "That request could not be read. Try again.",
  invalid_country_filter: "Pick at least one country, or switch back to All countries.",
  cross_origin_request: "That request was blocked.",
  internal_error: "Something went wrong. Try again in a moment.",
  search_on_computer: "The shared index is now too large for this browser tab. Search on your computer with the command under Faster.",
  part_taken: "Someone else is already indexing that batch. Leave the batch box blank, or try another number.",
  invalid_part: "That batch number is not valid. Leave it blank and we will pick a free batch.",
  mma_unauthorized: "That map-making.app key was not accepted. Create a new API key and paste it again.",
  mma_request_failed: "map-making.app did not accept that request. Try Connect again, or pick another map.",
  mma_create_failed: "Could not create a new map. Create one on map-making.app, then pick it here.",
  mma_missing_key: "Paste your map-making.app API key under Connect a map app.",
  mma_no_map: "Pick a map, or choose New map each search.",
  mma_unreachable: "Could not reach map-making.app. Check your connection and try again.",
  empty_mma_map: "There is no search map to send yet. Run Search first.",
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
let wakeLock = null;
const JOBS_KEY = "vision-community-jobs";
const PREFS_KEY = "vision-community-prefs";
const REFRESH_EVERY_BATCHES = 8;

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
    prompt: "",
    descriptionWeight: 50,
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
  if (document.querySelectorAll('#country-list input[name="country"]').length) {
    job.selectedCountries = selectedCountries();
  }
  job.generations = selectedGenerations();
  job.countrySearch = $("country-search").value;
  job.viewDirection = $("view-direction").value || "bestOfFour";
  job.prompt = ($("prompt")?.value || "").trim();
  const weight = document.querySelector('input[name="description-weight"]:checked')?.value;
  job.descriptionWeight = weight == null ? 50 : Number(weight);
  persistJobs();
}

function persistJobs() {
  try {
    localStorage.setItem(JOBS_KEY, JSON.stringify({
      selectedJob,
      jobs: jobs.map((job) => ({
        id: job.id,
        name: job.name,
        lane: job.lane,
        resultCount: job.resultCount,
        maxPerCountry: job.maxPerCountry,
        countryMode: job.countryMode,
        selectedCountries: job.selectedCountries || [],
        generations: job.generations,
        countrySearch: job.countrySearch || "",
        viewDirection: job.viewDirection,
        prompt: job.prompt || "",
        descriptionWeight: job.descriptionWeight,
        excludeName: job.excludeName || "",
      })),
    }));
  } catch {
    return;
  }
}

function restoreJobs() {
  try {
    const saved = JSON.parse(localStorage.getItem(JOBS_KEY) || "null");
    if (!saved || !Array.isArray(saved.jobs) || !saved.jobs.length) return;
    jobs = saved.jobs.map((job) => ({
      ...newJob(job.name),
      ...job,
      excludeMap: null,
    }));
    selectedJob = jobs.some((job) => job.id === saved.selectedJob) ? saved.selectedJob : jobs[0].id;
    applyJobToForm(currentJob());
  } catch {
    return;
  }
}

function persistPrefs() {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify({
      processLane: selectedProcessLane(),
      pace: document.querySelector('input[name="pace"]:checked')?.value || "medium",
      mmaTarget: mmaTarget(),
    }));
  } catch {
    return;
  }
}

function restorePrefs() {
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || "null");
    if (!saved || typeof saved !== "object") return;
    const lane = document.querySelector(`input[name="process-lane"][value="${saved.processLane}"]`);
    if (lane) lane.checked = true;
    const pace = document.querySelector(`input[name="pace"][value="${saved.pace}"]`);
    if (pace) pace.checked = true;
    const target = document.querySelector(`input[name="mma-target"][value="${saved.mmaTarget}"]`);
    if (target) target.checked = true;
  } catch {
    return;
  }
}

function paintBalance() {
  const cost = Number(state?.searchCost || 100000);
  const units = Number(state?.units || 0);
  const need = Math.max(0, cost - units);
  $("search-cost").textContent = number(cost);
  $("units").textContent = number(units);
  $("searches-available").textContent = number(state?.searchesAvailable || Math.floor(units / cost));
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
  if ($("process").dataset.busy && need === 0) {
    $("build-label").textContent = "Search is unlocked. Pause to search, or keep indexing for another search.";
  }
}

function applyCredit(unitsEarned) {
  if (!state) state = {};
  state.units = Number(state.units || 0) + Number(unitsEarned || 0);
  const cost = Number(state.searchCost || 100000);
  state.searchesAvailable = Math.floor(state.units / cost);
  paintBalance();
  updateReady();
}

async function holdWakeLock() {
  if (!navigator.wakeLock?.request) return;
  try {
    wakeLock = await navigator.wakeLock.request("screen");
    wakeLock.addEventListener("release", () => {
      wakeLock = null;
    });
  } catch {
    wakeLock = null;
  }
}

async function releaseWakeLock() {
  try {
    await wakeLock?.release();
  } catch {
    return;
  } finally {
    wakeLock = null;
  }
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
  if ($("prompt")) $("prompt").value = job.prompt || "";
  const weight = [0, 25, 50, 75, 100].includes(job.descriptionWeight) ? job.descriptionWeight : 50;
  const weightInput = document.querySelector(`input[name="description-weight"][value="${weight}"]`);
  if (weightInput) weightInput.checked = true;
  $("exclude-file-name").textContent = job.excludeName || "None";
  updateViewDirection();
  updateQueryInputs();
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
  if ($("prompt")) {
    $("prompt").placeholder = scene
      ? "What should the locations look like?"
      : "bird, clock, red airplane";
  }
  if ($("prompt-label")) {
    $("prompt-label").textContent = scene ? "Description" : "Object types";
  }
}

function typedPrompt() {
  return ($("prompt")?.value || "").trim();
}

function hasPrompt() {
  return Boolean(typedPrompt());
}

function selectedDescriptionWeight() {
  const value = Number(document.querySelector('input[name="description-weight"]:checked')?.value);
  return [0, 25, 50, 75, 100].includes(value) ? value : 50;
}

function hasQueryInput() {
  return Boolean(queryMap) || hasPrompt();
}

function queryInputLabel() {
  if (queryMap && hasPrompt()) return "JSON + description";
  if (queryMap) return "JSON reference";
  if (hasPrompt()) return "Description";
  return "Needs input";
}

function updateQueryInputs() {
  const blend = $("blend-block");
  if (blend) blend.hidden = !(queryMap && hasPrompt());
  if ($("file-name") && !queryMap && ($("file-name").textContent === "Example search is loaded" || $("file-name").textContent === "Example search")) {
    $("file-name").textContent = "No JSON yet";
  }
  updateReady();
  updateCliCommand();
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

function selectedProcessLanes() {
  const choice = selectedProcessLane();
  if (choice === "both") return ["scene", "object"];
  if (choice === "object") return ["object"];
  return ["scene"];
}

function laneNoun(lane, count = 1) {
  if (lane === "both") return count === 1 ? "place or object" : "places and objects";
  if (lane === "object") return count === 1 ? "object" : "objects";
  return count === 1 ? "place" : "places";
}

function pendingFor(lane) {
  return Number((state?.counts && state.counts[lane] && state.counts[lane].pending) || 0);
}

function pendingForSelection() {
  return selectedProcessLanes().reduce((total, lane) => total + pendingFor(lane), 0);
}

function selectedPart() {
  const raw = $("batch-number")?.value?.trim();
  if (!raw) return null;
  const part = Number(raw);
  return Number.isInteger(part) && part > 0 ? part : null;
}

function cliCommand() {
  const origin = window.location.origin;
  const lanes = selectedProcessLanes();
  const pace = document.querySelector('input[name="pace"]:checked')?.value || "medium";
  const code = lastRecovery || $("recovery-code")?.value.trim() || "YOUR_CODE";
  const part = selectedPart();
  const extra = part ? ` --part ${part}` : "";
  return lanes.map((lane) => (
    `python3 -m community.contribute --url ${origin} --lane ${lane} --pace ${pace}${extra} --recovery-code ${code}`
  )).join("\n");
}

function localSearchCommand() {
  const origin = window.location.origin;
  const code = lastRecovery || $("recovery-code")?.value.trim() || "YOUR_CODE";
  const lane = selectedLane();
  const parts = [`python3 -m community.local_search --url ${origin} --lane ${lane}`];
  if (queryMap) parts.push("--query community/web/sample-query.json");
  const prompt = typedPrompt();
  if (prompt) parts.push(`--prompt ${JSON.stringify(prompt)}`);
  if (queryMap && prompt) parts.push(`--description-weight ${selectedDescriptionWeight()}`);
  parts.push(`--recovery-code ${code}`);
  return parts.join(" ");
}

function updateCliCommand() {
  const node = $("cli-command");
  if (node) node.textContent = cliCommand();
  const searchNode = $("local-search-command");
  if (searchNode) searchNode.textContent = localSearchCommand();
}

function workForSelection() {
  const lanes = selectedProcessLanes();
  const byLane = state?.workByLane || {};
  if (lanes.length === 1) return byLane[lanes[0]] || (lanes[0] === "scene" ? state?.work : null);
  const parts = lanes.map((lane) => byLane[lane]).filter(Boolean);
  if (!parts.length) return null;
  const first = parts[0];
  return {
    ...first,
    lane: "both",
    summary: parts.map((item) => item.summary).filter(Boolean).join(" "),
  };
}

function updateProcessHelp() {
  const choice = selectedProcessLane();
  const help = $("process-lane-help");
  if (help) {
    if (choice === "object") {
      help.textContent = "Objects use the six-face cube (front, back, left, right, up, down). Each finished object counts as 10 toward a search.";
    } else if (choice === "both") {
      help.textContent = "Both indexes places and objects in turn. Places count as 1. Objects count as 10.";
    } else {
      help.textContent = "Places look around each panorama using saved pan and the four compass views. Each finished place counts as 1 toward a search.";
    }
  }
  const start = $("process");
  if (start && !start.dataset.busy) {
    start.textContent = choice === "object" ? "Start objects" : choice === "both" ? "Start both" : "Start places";
  }
}

function updateQueue() {
  const scene = pendingFor("scene");
  const object = pendingFor("object");
  const choice = selectedProcessLane();
  const work = workForSelection();
  $("queue-label").textContent = `${number(scene)} places and ${number(object)} objects still waiting`;
  if ($("batch-label")) {
    $("batch-label").textContent = work?.summary
      || "You will get your own batch. Other people get different batches.";
  }
  updateProcessHelp();
  const canProcess = signedIn && pendingForSelection() > 0 && !$("process").dataset.busy;
  if (!$("process").dataset.busy) $("process").disabled = !canProcess;
}

function renderJobs() {
  const list = $("jobs");
  list.replaceChildren();
  for (const job of jobs) {
    const item = document.createElement("li");
    if (job.id === selectedJob) item.classList.add("selected");
    if (hasQueryInput() && job.id === selectedJob) item.classList.add("ready");
    const dot = document.createElement("span");
    dot.className = "dot";
    const title = document.createElement("span");
    title.append(job.name);
    const meta = document.createElement("small");
    const input = queryInputLabel();
    meta.textContent = job.lane === "scene"
      ? `${input} · ${VIEW_DIRECTION_LABELS[job.viewDirection || "bestOfFour"]}`
      : `${input} · Objects`;
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
  const hasInput = hasQueryInput();
  const ready = hasInput
    && signedIn
    && includeReady
    && generationReady
    && Number(state?.units || 0) >= Number(state?.searchCost || Infinity)
    && onSite;
  let badge = "Get an account";
  if (!signedIn) badge = "Get an account";
  else if (!hasInput) badge = "Add a description or JSON";
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
  updateQueryInputs();
}

async function ensureSampleQuery() {
  return;
}

$("prompt")?.addEventListener("input", () => {
  saveJobFromForm();
  updateQueryInputs();
  renderJobs();
});

document.querySelectorAll('input[name="description-weight"]').forEach((input) => {
  input.addEventListener("change", () => {
    saveJobFromForm();
    updateQueryInputs();
  });
});

async function refresh(options = {}) {
  const lite = Boolean(options.lite);
  const previous = state;
  let next;
  try {
    next = await api(lite ? "/api/me?lite=1" : "/api/me");
  } catch (error) {
    if (error.message !== "unauthorized") throw error;
    next = await api("/api/status");
  }
  if (lite && previous && next.accountId) {
    state = {
      ...previous,
      ...next,
      countries: next.countries?.length ? next.countries : previous.countries,
      cameraGenerations: next.cameraGenerations?.length ? next.cameraGenerations : previous.cameraGenerations,
      r2: next.r2?.bucket ? next.r2 : previous.r2,
      work: next.work || previous.work,
      workByLane: next.workByLane || previous.workByLane,
    };
  } else {
    state = next;
  }
  signedIn = Boolean(state.accountId);
  const scene = state.counts?.scene || { pending: 0, published: 0 };
  const object = state.counts?.object || { pending: 0, published: 0 };
  const indexed = (scene.published || 0) + (object.published || 0);
  const pending = (scene.pending || 0) + (object.pending || 0);
  $("index-label").textContent = `${number(indexed)} indexed · ${number(pending)} queued`;
  paintBalance();
  const need = Math.max(0, Number(state.searchCost || 0) - Number(state.units || 0));
  if (!signedIn) {
    $("search-status").textContent = "Get an account, click Start, and keep this tab in front.";
  } else if (!lastMap) {
    if (state.searchOnSite === false) {
      $("search-status").textContent = need === 0
        ? "The index is too large for this tab. Use the search command under Faster."
        : `Keep this tab in front. ${number(need)} more until you can search on your computer.`;
    } else {
      $("search-status").textContent = need === 0
        ? "Search is ready. Press Search, then add the results to your map."
        : `Keep this tab in front. ${number(need)} more until Search unlocks.`;
    }
  }
  $("create-account").hidden = signedIn;
  $("pause").disabled = !signedIn;
  $("account-chip").textContent = signedIn ? "Signed in on this browser" : "No account yet";
  if (!($("process").dataset.busy && need === 0)) {
    $("build-label").textContent = document.hidden && $("process").dataset.busy
      ? "Bring this tab to the front — indexing slows in the background."
      : "Keep this tab in front while indexing";
  }
  if (!signedIn) $("process-status").textContent = "Get an account, then click Start.";
  else if ($("process-status").textContent === "Get an account, then click Start."
    || $("process-status").textContent === "Create an account to begin.")
    $("process-status").textContent = "Click Start. Keep this tab in front.";
  if (!lite) {
    saveJobFromForm();
    renderCountries();
    updateFilterHelp();
  }
  updateQueue();
  updateReady();
  updateCliCommand();
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
  persistJobs();
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
    persistPrefs();
    updateQueue();
    updateCliCommand();
  });
});

document.querySelectorAll('input[name="pace"]').forEach((input) => {
  input.addEventListener("change", () => {
    persistPrefs();
    updateCliCommand();
  });
});
$("batch-number")?.addEventListener("input", updateCliCommand);

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
    const copied = lastRecovery ? await copyText(lastRecovery) : false;
    $("recovery-once-text").textContent = copied
      ? `Copied. Also write this code down — it is the only way back into this account: ${lastRecovery}`
      : `Write this code down or screenshot it. It is the only way back into this account: ${lastRecovery}`;
    if (copied) $("copy-recovery").textContent = "Copied";
    await refresh();
    $("process-status").textContent = "Saved? Click Start. Keep this tab in front.";
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
  $("process-status").textContent = "Stopping after this batch finishes…";
});

$("process").addEventListener("click", async () => {
  const button = $("process");
  button.disabled = true;
  button.dataset.busy = "1";
  pauseRequested = false;
  const lanes = selectedProcessLanes();
  const choice = selectedProcessLane();
  const noun = laneNoun(choice, 2);
  const pace = document.querySelector('input[name="pace"]:checked').value;
  const workers = PACE_WORKERS[pace];
  let acceptedTotal = 0;
  let unitsTotal = 0;
  let currentLeaseId = null;
  document.querySelectorAll('input[name="process-lane"]').forEach((input) => {
    input.disabled = true;
  });
  button.textContent = choice === "object" ? "Indexing objects…" : choice === "both" ? "Indexing both…" : "Indexing places…";
  $("build-label").textContent = "Keep this tab in front while indexing";
  await holdWakeLock();
  let batchesSinceRefresh = 0;

  async function processLane(lane) {
    const body = { lane, count: PACE_LEASE[lane][pace], pace };
    const part = selectedPart();
    if (part) body.part = part;
    const lease = await api("/api/leases", "POST", body);
    if (lease.work) {
      state = {
        ...(state || {}),
        work: lane === "scene" ? lease.work : state?.work,
        workByLane: { ...(state?.workByLane || {}), [lane]: lease.work },
      };
      updateQueue();
    }
    currentLeaseId = lease.leaseId;
    const laneNounText = laneNoun(lane, 2);
    let processed = 0;
    const outputs = await mapPool(lease.items, workers, async (item) => {
      processed += 1;
      $("process-status").textContent = `Working on ${laneNounText}… ${acceptedTotal + processed} finished in this session`;
      return window.VISIONVisual.processItem(item);
    });
    const accepted = await api("/api/submissions", "POST", { leaseId: lease.leaseId, outputs });
    currentLeaseId = null;
    acceptedTotal += accepted.accepted;
    unitsTotal += accepted.unitsEarned;
    applyCredit(accepted.unitsEarned);
    $("process-status").textContent = `${number(acceptedTotal)} ${noun} finished. Keep this tab in front.`;
    batchesSinceRefresh += 1;
    if (batchesSinceRefresh >= REFRESH_EVERY_BATCHES) {
      batchesSinceRefresh = 0;
      await refresh({ lite: true });
    }
  }

  try {
    while (!pauseRequested) {
      let progressed = false;
      let lastEmpty = null;
      for (const lane of lanes) {
        if (pauseRequested) break;
        try {
          await processLane(lane);
          progressed = true;
        } catch (error) {
          if (error.message === "paused") throw error;
          if (error.message === "no_available_work") {
            lastEmpty = error;
            continue;
          }
          throw error;
        }
      }
      if (!progressed) {
        if (lastEmpty) throw lastEmpty;
        break;
      }
    }
    $("process-status").textContent = `Paused after ${number(acceptedTotal)} ${noun}.`;
  } catch (error) {
    if (currentLeaseId) {
      await api("/api/leases/release", "POST", { leaseId: currentLeaseId }).catch(() => {});
      currentLeaseId = null;
    }
    if (error.message === "paused") {
      $("process-status").textContent = `Paused after ${number(acceptedTotal)} ${noun}.`;
    } else if (error.message === "no_available_work" && acceptedTotal) {
      $("process-status").textContent = `Caught up for now: ${number(acceptedTotal)} ${noun} finished.`;
    } else {
      $("process-status").textContent = `Processing stopped: ${explain(error)}`;
    }
  } finally {
    delete button.dataset.busy;
    document.querySelectorAll('input[name="process-lane"]').forEach((input) => {
      input.disabled = false;
    });
    await releaseWakeLock();
    await refresh().catch(() => {});
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
    useQueryMap(sample, "Example JSON");
  } catch (error) {
    $("search-status").textContent = `Could not load the example: ${explain(error)}`;
  }
});

$("clear-json").addEventListener("click", () => {
  queryMap = null;
  $("query-map").value = "";
  $("file-name").textContent = "No JSON yet";
  updateQueryInputs();
  renderJobs();
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

function mapJsonText() {
  if (!lastMap) return "";
  return `${JSON.stringify(sortKeysDeep(lastMap), null, 2)}\n`;
}

function showResultActions(hasHits) {
  $("download-map").hidden = !hasHits;
  $("send-mma").hidden = !hasHits;
  $("copy-mma").hidden = !hasHits;
}

function mmaTarget() {
  return document.querySelector('input[name="mma-target"]:checked')?.value || "cloud";
}

function updateMmaSummary() {
  const summary = $("mma-connect-summary");
  if (!summary) return;
  if (mmaTarget() === "local") {
    summary.textContent = "Connect a map app · Local app";
  } else if (mmaStoredKey() || ($("mma-api-key")?.value || "").trim()) {
    summary.textContent = "Connect a map app · Connected";
  } else {
    summary.textContent = "Connect a map app";
  }
}

function updateMmaTarget() {
  const local = mmaTarget() === "local";
  if ($("mma-cloud-block")) $("mma-cloud-block").hidden = local;
  if ($("mma-local-block")) $("mma-local-block").hidden = !local;
  if ($("send-mma")) $("send-mma").textContent = local ? "Copy for local app" : "Add to my map";
  persistPrefs();
  updateMmaSummary();
}

function fillMmaMaps(maps, selected) {
  const select = $("mma-map-select");
  if (!select) return;
  const current = selected || mmaStoredMap() || "__new__";
  select.replaceChildren();
  const fresh = document.createElement("option");
  fresh.value = "__new__";
  fresh.textContent = "New map each search";
  select.append(fresh);
  for (const item of maps || []) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name;
    select.append(option);
  }
  select.value = [...select.options].some((option) => option.value === current) ? current : "__new__";
}

async function connectMapApp() {
  const key = ($("mma-api-key")?.value || "").trim();
  if (!key) {
    $("mma-connect-status").textContent = explain(new Error("mma_missing_key"));
    return;
  }
  $("mma-connect-status").textContent = "Checking that key…";
  try {
    const maps = await mmaListMaps(key);
    mmaSaveConnection(key, $("mma-map-select")?.value || "__new__");
    fillMmaMaps(maps);
    $("mma-connect-status").textContent = maps.length
      ? `Connected. ${maps.length} map${maps.length === 1 ? "" : "s"} found.`
      : "Connected. New maps will be created when you add results.";
    updateMmaSummary();
  } catch (error) {
    $("mma-connect-status").textContent = explain(error);
  }
}

function disconnectMapApp() {
  mmaSaveConnection("", "");
  if ($("mma-api-key")) $("mma-api-key").value = "";
  fillMmaMaps([]);
  $("mma-connect-status").textContent = "Not connected";
  updateMmaSummary();
}

async function copyForLocalMma() {
  const text = mapJsonText();
  if (!text) return;
  const ok = await copyText(text);
  $("search-status").textContent = ok
    ? "Copied. Open Map Making App, open a map, then paste or drop the downloaded file onto the window."
    : "Could not copy. Use Download, then drop that file onto Map Making App.";
}

async function sendToMapMaking() {
  if (!lastMap?.customCoordinates?.length) {
    $("search-status").textContent = explain(new Error("empty_mma_map"));
    return;
  }
  if (mmaTarget() === "local") {
    await copyForLocalMma();
    return;
  }
  const key = ($("mma-api-key")?.value || "").trim() || mmaStoredKey();
  if (!key) {
    $("mma-connect")?.setAttribute("open", "");
    $("mma-connect-status").textContent = explain(new Error("mma_missing_key"));
    $("search-status").textContent = explain(new Error("mma_missing_key"));
    return;
  }
  const selected = $("mma-map-select")?.value || "__new__";
  $("search-status").textContent = "Adding places to your map…";
  $("send-mma").disabled = true;
  try {
    const result = await mmaSendMap(lastMap, {
      apiKey: key,
      mapId: selected === "__new__" ? undefined : selected,
      newMap: selected === "__new__",
    });
    mmaSaveConnection(key, selected);
    $("search-status").textContent = `Added ${result.added} places${result.name ? ` to ${result.name}` : ""}.`;
    if (result.url) {
      const link = document.createElement("a");
      link.href = result.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = " Open in map-making.app";
      $("search-status").append(link);
    }
  } catch (error) {
    $("search-status").textContent = `Could not add to the map: ${explain(error)}`;
  } finally {
    $("send-mma").disabled = false;
  }
}

async function restoreMapApp() {
  const key = mmaStoredKey();
  if ($("mma-api-key") && key) $("mma-api-key").value = key;
  fillMmaMaps([], mmaStoredMap());
  updateMmaTarget();
  if (!key) return;
  try {
    const maps = await mmaListMaps(key);
    fillMmaMaps(maps, mmaStoredMap());
    $("mma-connect-status").textContent = `Connected. ${maps.length} map${maps.length === 1 ? "" : "s"} ready.`;
  } catch {
    $("mma-connect-status").textContent = "Saved key could not be checked yet.";
  }
  updateMmaSummary();
}

$("run-search").addEventListener("click", async () => {
  const button = $("run-search");
  button.disabled = true;
  saveJobFromForm();
  try {
    const result = await api("/api/searches", "POST", {
      idempotencyKey: crypto.randomUUID(),
      lane: selectedLane(),
      queryMap: queryMap || undefined,
      prompt: typedPrompt() || undefined,
      descriptionWeight: selectedDescriptionWeight(),
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
    showResultActions(hits.length > 0);
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
      ? (mmaTarget() === "local"
        ? `${hits.length} matching ${selectedLane() === "object" ? "objects" : "places"}. Copy for the local app, or download the JSON.`
        : mmaStoredKey()
          ? `${hits.length} matching ${selectedLane() === "object" ? "objects" : "places"}. Click Add to my map.`
          : `${hits.length} matching ${selectedLane() === "object" ? "objects" : "places"}. Connect a map app, or download the JSON.`)
      : "Nothing matched. Try Best of available views, or open More options.";
    await refresh();
  } catch (error) {
    $("search-status").textContent = `Search stopped: ${explain(error)}`;
  } finally {
    updateReady();
  }
});

$("download-map").addEventListener("click", downloadMap);
$("send-mma")?.addEventListener("click", sendToMapMaking);
$("copy-mma")?.addEventListener("click", copyForLocalMma);
$("mma-connect-btn")?.addEventListener("click", connectMapApp);
$("mma-disconnect")?.addEventListener("click", disconnectMapApp);
$("mma-map-select")?.addEventListener("change", () => {
  mmaSaveConnection(mmaStoredKey() || ($("mma-api-key")?.value || ""), $("mma-map-select").value);
});
document.querySelectorAll('input[name="mma-target"]').forEach((input) => {
  input.addEventListener("change", updateMmaTarget);
});

renderJobs();
updateViewDirection();
updateCliCommand();
restorePrefs();
restoreJobs();
renderJobs();
updateProcessHelp();
updateMmaTarget();
restoreMapApp().catch(() => {});
refresh().catch((error) => {
  $("process-status").textContent = `Unable to reach the service: ${explain(error)}`;
});

document.addEventListener("visibilitychange", async () => {
  if (!$("process").dataset.busy) return;
  if (document.hidden) {
    const need = Math.max(0, Number(state?.searchCost || 100000) - Number(state?.units || 0));
    if (need > 0) {
      $("build-label").textContent = "Bring this tab to the front — indexing slows in the background.";
    }
    return;
  }
  await holdWakeLock();
  paintBalance();
});

window.addEventListener("beforeunload", (event) => {
  if (!$("process").dataset.busy) return;
  event.preventDefault();
  event.returnValue = "";
});
