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
  no_available_work: "No more work is waiting for that choice right now. Try Scene, Objects, or Both.",
  insufficient_credit: "Keep indexing. A search needs 100,000 scenes (or 10,000 objects).",
  verification_failed: "That scene could not be checked, so it was not counted.",
  view_unavailable: "Street View did not return that scene, so it was not counted.",
  expired_lease: "That batch timed out. Indexing will take the next one.",
  unauthorized: "No account on this browser. Get a free account or paste your saved code.",
  invalid_mma_map: "That file is not a map JSON we can use.",
  invalid_query: "Add a description, a JSON file, or both.",
  invalid_pano_id: "A scene ID in that file is missing or invalid.",
  invalid_json: "That request could not be read. Try again.",
  invalid_country_filter: "Pick at least one country, or switch back to All countries.",
  cross_origin_request: "That request was blocked.",
  internal_error: "Something went wrong. Try again in a moment.",
  search_on_computer: "The shared index is now too large for this browser tab. Search on your computer with the command under Index.",
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
const queryMaps = new Map();
let jobs = [newJob("")];
let selectedJob = jobs[0].id;
let wakeLock = null;
const JOBS_KEY = "vision-community-jobs";
const PREFS_KEY = "vision-community-prefs";
const REFRESH_EVERY_BATCHES = 8;

function newJob(name) {
  return {
    id: crypto.randomUUID(),
    name: name || "",
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
    excludePrevious: true,
    objectConfidence: "balanced",
    queryLabel: "",
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
  job.name = $("output-name").value.trim();
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
  job.excludePrevious = Boolean($("exclude-previous")?.checked);
  job.objectConfidence = document.querySelector('input[name="object-confidence"]:checked')?.value || "balanced";
  job.queryLabel = queryMap ? ($("file-name")?.textContent || "") : "";
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
        excludePrevious: Boolean(job.excludePrevious),
        objectConfidence: job.objectConfidence || "balanced",
        queryLabel: job.queryLabel || "",
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
  $("job-title").textContent = job.name || "New search";
  $("view-direction").value = job.viewDirection || "bestOfFour";
  if ($("prompt")) $("prompt").value = job.prompt || "";
  const weight = [0, 25, 50, 75, 100].includes(job.descriptionWeight) ? job.descriptionWeight : 50;
  const weightInput = document.querySelector(`input[name="description-weight"][value="${weight}"]`);
  if (weightInput) weightInput.checked = true;
  $("exclude-file-name").textContent = job.excludeName || "None";
  if ($("exclude-previous")) $("exclude-previous").checked = Boolean(job.excludePrevious);
  const confidence = document.querySelector(`input[name="object-confidence"][value="${job.objectConfidence || "balanced"}"]`);
  if (confidence) confidence.checked = true;
  const storedQuery = queryMaps.get(job.id);
  queryMap = storedQuery?.map || null;
  if ($("file-name")) $("file-name").textContent = queryMap ? (storedQuery.label || job.queryLabel || "JSON loaded") : "No JSON yet";
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
        updateCliCommand();
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
  const count = $("country-count");
  if (count) {
    count.textContent = mode === "all"
      ? `All ${countries.length} indexed countries`
      : `${selected.length} selected`;
  }
  if (!countries.length) {
    $("country-help").textContent = "No indexed source has country metadata.";
  } else if (mode === "all") {
    $("country-help").textContent = "All indexed countries may be returned. Choose Include or Exclude to narrow the search.";
  } else if (!selected.length) {
    $("country-help").textContent = "Choose at least one country, or switch back to All countries.";
  } else if (mode === "include") {
    $("country-help").textContent = "Only selected countries may be returned.";
  } else {
    $("country-help").textContent = "Selected countries will not be returned.";
  }
}

const OBJECT_GUIDANCE = {
  highRecall: "Finds more small, distant, or partly hidden objects; expect more false positives.",
  balanced: "Best starting point for most searches; balances missed objects and false positives.",
  precise: "Favors stronger detections with fewer false positives; subtle objects may be missed.",
};

function updateViewDirection() {
  const scene = selectedLane() === "scene";
  $("view-direction-block").hidden = !scene;
  $("view-direction").disabled = !scene;
  if ($("json-row")) $("json-row").hidden = !scene;
  if ($("blend-block")) $("blend-block").hidden = !scene;
  if ($("detection-block")) $("detection-block").hidden = scene;
  const road = $("reject-road");
  if (road) {
    road.disabled = !scene;
    road.closest("label")?.setAttribute(
      "title",
      scene ? "" : "Road names are not in the object index yet.",
    );
  }
  if ($("prompt")) {
    $("prompt").placeholder = scene
      ? "What should the locations look like?"
      : "bird, bird nest, beetle, red airplane";
  }
  if ($("prompt-label")) {
    $("prompt-label").textContent = scene ? "Description" : "Object types";
  }
  updateBlendMeta();
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

function updateBlendMeta() {
  const count = $("result-count")?.value || "200";
  const direction = $("view-direction")?.value === "bestOfFour"
    ? "Best available view"
    : (VIEW_DIRECTION_LABELS[$("view-direction")?.value] || "Best available view");
  if ($("blend-meta")) $("blend-meta").textContent = `${direction} · 100 m dedupe · ${count} requested`;
  if ($("detection-meta")) $("detection-meta").textContent = `Exact object aim · 100 m dedupe · ${count} requested`;
  const confidence = document.querySelector('input[name="object-confidence"]:checked')?.value || "balanced";
  if ($("detection-guidance")) $("detection-guidance").textContent = OBJECT_GUIDANCE[confidence] || OBJECT_GUIDANCE.balanced;
}

function updateQueryInputs() {
  const canBlend = Boolean(queryMap && hasPrompt());
  document.querySelectorAll('input[name="description-weight"]').forEach((input) => {
    input.disabled = !canBlend;
  });
  const choose = $("choose-json");
  if (choose) choose.classList.toggle("active", Boolean(queryMap));
  if ($("file-name") && !queryMap && ($("file-name").textContent === "Example search is loaded" || $("file-name").textContent === "Example search")) {
    $("file-name").textContent = "No JSON yet";
  }
  updateBlendMeta();
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

const INDEXING_KEY = "vision-community-indexing";

function indexingKeepsGoing(error) {
  const message = String(error && error.message || "");
  if ([
    "view_unavailable",
    "verification_failed",
    "expired_lease",
    "lease_lost",
    "internal_error",
    "network_error",
    "index_unavailable",
  ].includes(message)) return true;
  if (/^HTTP (408|429|500|502|503|504)$/.test(message)) return true;
  if (message === "Failed to fetch" || message.includes("NetworkError")) return true;
  return false;
}

async function api(path, method = "GET", body = null) {
  const headers = {};
  if (body !== null) headers["Content-Type"] = "application/json";
  let lastError = null;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const response = await fetch(path, {
        method, headers, credentials: "same-origin", cache: "no-store",
        body: body === null ? undefined : JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (response.ok) return data;
      const error = new Error(data.error || `HTTP ${response.status}`);
      const retryable = response.status === 429 || response.status >= 500;
      if (!retryable || attempt === 3) throw error;
      lastError = error;
    } catch (error) {
      const retryable = error instanceof TypeError || error.message === "Failed to fetch";
      if (!retryable) throw error;
      lastError = error;
      if (attempt === 3) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)));
  }
  throw lastError || new Error("network_error");
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
  if (lane === "both") return count === 1 ? "scene or object" : "scenes and objects";
  if (lane === "object") return count === 1 ? "object" : "objects";
  return count === 1 ? "scene" : "scenes";
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

function indexCommand(lane) {
  const origin = window.location.origin;
  const pace = document.querySelector('input[name="pace"]:checked')?.value || "medium";
  const code = lastRecovery || $("recovery-code")?.value.trim() || "YOUR_CODE";
  const part = selectedPart();
  const extra = part ? ` --part ${part}` : "";
  if (lane === "scene") {
    return `python3 -m community.vision_index --url ${origin} --pace ${pace}${extra} --recovery-code ${code}`;
  }
  return `python3 -m community.object_index --url ${origin} --pace ${pace}${extra} --recovery-code ${code}`;
}

function cliCommand() {
  return selectedProcessLanes().map((lane) => indexCommand(lane)).join("\n");
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'"'"'`)}'`;
}

function sceneSearchCommand() {
  const origin = window.location.origin;
  const code = lastRecovery || $("recovery-code")?.value.trim() || "YOUR_CODE";
  const parts = ["python3 -m community.vision_index", "--url", origin, "--search"];
  const prompt = typedPrompt();
  if (queryMap) parts.push("--query", "vision-query.json");
  if (prompt) parts.push("--prompt", shellQuote(prompt));
  parts.push("--result-count", String(Number($("result-count")?.value) || 200));
  parts.push("--max-per-country", String(Number($("max-per-country")?.value) || 25));
  parts.push("--description-weight", String(selectedDescriptionWeight()));
  parts.push("--view-direction", $("view-direction")?.value || "bestOfFour");
  const name = $("output-name")?.value.trim();
  if (name) parts.push("--output-name", shellQuote(name));
  const mode = countryMode();
  if (mode !== "all") {
    parts.push("--country-mode", mode);
    const countries = selectedCountries();
    if (countries.length) parts.push("--countries", shellQuote(countries.join(",")));
  }
  const generations = selectedGenerations();
  if (generations.length && generations.length < ALL_GENERATIONS.length) {
    parts.push("--camera-generations", generations.join(","));
  }
  if ($("reject-road")?.checked) parts.push("--reject-road-names");
  const job = currentJob();
  if ($("exclude-previous")?.checked && job?.excludeMap) parts.push("--exclude", "vision-exclude.json");
  parts.push("--recovery-code", code);
  return parts.join(" ");
}

function localSearchCommand() {
  if (selectedLane() === "scene") return sceneSearchCommand();
  const origin = window.location.origin;
  const code = lastRecovery || $("recovery-code")?.value.trim() || "YOUR_CODE";
  const lane = selectedLane();
  const parts = ["python3 -m community.local_search", "--url", origin, "--lane", lane];
  const prompt = typedPrompt();
  if (queryMap) parts.push("--query", "vision-query.json");
  if (prompt) parts.push("--prompt", shellQuote(prompt));
  if (!prompt && !queryMap) parts.push("--prompt", shellQuote("a street view panorama"));
  if (queryMap && prompt) parts.push("--description-weight", String(selectedDescriptionWeight()));
  parts.push("--result-count", String(Number($("result-count")?.value) || 200));
  parts.push("--max-per-country", String(Number($("max-per-country")?.value) || 25));
  if (lane === "scene") parts.push("--view-direction", $("view-direction")?.value || "bestOfFour");
  const name = $("output-name")?.value.trim();
  if (name) parts.push("--output-name", shellQuote(name));
  const mode = countryMode();
  if (mode !== "all") {
    parts.push("--country-mode", mode);
    const countries = selectedCountries();
    if (countries.length) parts.push("--countries", shellQuote(countries.join(",")));
  }
  const generations = selectedGenerations();
  if (generations.length && generations.length < ALL_GENERATIONS.length) {
    parts.push("--camera-generations", generations.join(","));
  }
  const job = currentJob();
  if ($("exclude-previous")?.checked && job?.excludeMap) parts.push("--exclude", "vision-exclude.json");
  parts.push("--recovery-code", code);
  return parts.join(" ");
}

function downloadJson(filename, payload) {
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1500);
}

async function copyComputerSearch() {
  saveJobFromForm();
  updateCliCommand();
  if (queryMap) downloadJson("vision-query.json", queryMap);
  const job = currentJob();
  if ($("exclude-previous")?.checked && job?.excludeMap) downloadJson("vision-exclude.json", job.excludeMap);
  const block = $("command-block");
  if (block) block.open = true;
  $("index-sheet")?.showModal();
  const copied = await copyText(localSearchCommand(), $("local-search-command"));
  const scene = selectedLane() === "scene";
  $("build-label").textContent = "Search on this computer";
  $("search-status").textContent = copied
    ? (scene
      ? "Copied. Paste it into Terminal. It uses the same four-view search as VISION and writes a map JSON."
      : "Copied. Paste it into Terminal. It searches the shared index on this computer and writes a map JSON.")
    : "Select the search command, copy it, and paste it into Terminal.";
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

function processPrompt() {
  const choice = selectedProcessLane();
  if (!signedIn) {
    if (choice === "object") return "Get an account, then copy the object command into Terminal.";
    if (choice === "both") return "Get an account, then copy both commands into Terminal.";
    return "Get an account, then copy the scene command into Terminal.";
  }
  if (choice === "object") return "Copy the object command into Terminal. It keeps going until you stop it or the queue is empty.";
  if (choice === "both") return "Copy both commands. Paste each one into its own Terminal window.";
  return "Copy the scene command into Terminal. It keeps going until you stop it or the queue is empty.";
}

function updateProcessHelp() {
  const choice = selectedProcessLane();
  const help = $("process-lane-help");
  if (help) {
    if (choice === "object") {
      help.textContent = "Objects use the same indexer as VISION: six-face cube, RF-DETR, YOLOE, and OWLv2. Copy the command into Terminal. Each finished object counts as 10 toward a search.";
    } else if (choice === "both") {
      help.textContent = "Scenes and objects both use the VISION indexers in Terminal. Paste each command into its own Terminal window. Scenes count as 1. Objects count as 10.";
    } else {
      help.textContent = "Scenes use the same four-view indexer as VISION. Copy the command into Terminal. Each finished scene counts as 1 toward a search.";
    }
  }
  const start = $("process");
  if (start && !start.dataset.busy) {
    start.textContent = choice === "object" ? "Copy object command" : choice === "both" ? "Copy scene and object commands" : "Copy scene command";
  }
  const status = $("process-status");
  if (status && (
    status.textContent.startsWith("Get an account")
    || status.textContent.startsWith("Create an account")
    || status.textContent.startsWith("Copy the ")
    || status.textContent.startsWith("Copy both ")
  )) {
    status.textContent = processPrompt();
  }
}

function updateQueue() {
  const scene = pendingFor("scene");
  const object = pendingFor("object");
  const choice = selectedProcessLane();
  const work = workForSelection();
  $("queue-label").textContent = `${number(scene)} scenes and ${number(object)} objects still waiting`;
  if ($("batch-label")) {
    $("batch-label").textContent = work?.summary
      || "You will get your own batch. Other people get different batches.";
  }
  updateProcessHelp();
  const canProcess = signedIn && pendingForSelection() > 0 && !$("process").dataset.busy;
  if (!$("process").dataset.busy) $("process").disabled = !canProcess;
}

function jobHasInput(job) {
  if (job.prompt) return true;
  return job.id === selectedJob && Boolean(queryMap);
}

function jobSummary(job) {
  const selected = job.id === selectedJob;
  const input = selected ? queryInputLabel() : (job.prompt ? "Description" : "Needs input");
  if (job.lane === "object") {
    const label = job.prompt || (selected && queryMap ? "JSON reference" : "Needs an object");
    return `Objects · ${label} · ${job.resultCount || 200} locations`;
  }
  if (input === "Needs input") return "Needs input";
  return `${input} · ${job.resultCount || 200} locations`;
}

function renderJobs() {
  const list = $("jobs");
  list.replaceChildren();
  let readyJobs = 0;
  for (const job of jobs) {
    const item = document.createElement("li");
    const ready = jobHasInput(job);
    if (ready) readyJobs += 1;
    if (job.id === selectedJob) item.classList.add("selected");
    if (ready) item.classList.add("ready");
    const dot = document.createElement("span");
    dot.className = "dot";
    const title = document.createElement("span");
    title.className = "job-copy";
    const name = document.createElement("strong");
    name.className = "job-name";
    name.textContent = job.name || "Untitled search";
    const meta = document.createElement("small");
    meta.textContent = jobSummary(job);
    title.append(name, meta);
    item.append(dot, title);
    if (jobs.length > 1 && job.id === selectedJob) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "trash";
      remove.title = "Delete search";
      remove.textContent = "⌫";
      remove.addEventListener("click", (event) => {
        event.stopPropagation();
        jobs = jobs.filter((entry) => entry.id !== job.id);
        selectedJob = jobs[0].id;
        applyJobToForm(currentJob());
        persistJobs();
        renderJobs();
        updateReady();
      });
      item.append(remove);
    }
    item.addEventListener("click", () => {
      saveJobFromForm();
      selectedJob = job.id;
      applyJobToForm(job);
      renderJobs();
      updateReady();
    });
    list.append(item);
  }
  if ($("ready-count")) $("ready-count").textContent = `${readyJobs} ready`;
}

function updateReady() {
  const includeReady = countryMode() !== "include" || selectedCountries().length > 0;
  const generationReady = selectedGenerations().length > 0;
  const onSite = state?.searchOnSite !== false;
  const hasInput = hasQueryInput();
  const credited = Number(state?.units || 0) >= Number(state?.searchCost || Infinity);
  const ready = hasInput && includeReady && generationReady && (signedIn ? credited : true);
  $("ready-badge").textContent = hasInput ? "Ready" : "Needs input";
  $("ready-badge").classList.toggle("ok", hasInput);
  $("run-search").disabled = !ready;
  $("run-search").textContent = "Run Search";
  if (!signedIn) {
    $("run-search").title = "Get an account, then Run Search copies a Terminal command";
  } else if (credited && hasInput && (selectedLane() === "scene" || onSite === false)) {
    $("run-search").title = selectedLane() === "scene"
      ? "Copies a Terminal command that searches the same way as VISION"
      : "Copies a Terminal command that searches the shared index on this computer";
  } else {
    $("run-search").title = "";
  }
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
  queryMaps.set(selectedJob, { map: queryMap, label });
  const owner = currentJob();
  if (owner) owner.queryLabel = label;
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
  const objectCount = Number(object.published || 0);
  const objectLabel = `${number(objectCount)} ${objectCount === 1 ? "object" : "objects"}`;
  $("index-label").textContent = objectCount
    ? `${number(scene.published || 0)} scenes · ${objectLabel}`
    : `${number(scene.published || 0)} scenes`;
  const cutoff = $("import-cutoff");
  if (cutoff && cutoff.options[0]) cutoff.options[0].textContent = `All imports · ${number(indexed)} locations`;
  paintBalance();
  const need = Math.max(0, Number(state.searchCost || 0) - Number(state.units || 0));
  if (!signedIn) {
    $("search-status").textContent = "Get an account from Index, then copy the scene command.";
  } else if (!lastMap) {
    if (selectedLane() === "scene" || state.searchOnSite === false) {
      $("search-status").textContent = need === 0
        ? (selectedLane() === "scene"
          ? "Run Search copies a Terminal command. It uses the same four-view search as VISION."
          : "Run Search copies a Terminal command. It searches the shared index on this computer.")
        : `${number(indexed)} indexed locations · ${number(need)} more until you can search.`;
    } else {
      $("search-status").textContent = need === 0
        ? `${number(indexed)} indexed locations`
        : `${number(indexed)} indexed locations · ${number(need)} more until Search unlocks.`;
    }
  }
  $("create-account").hidden = signedIn;
  $("pause").disabled = !signedIn;
  $("account-chip").textContent = signedIn ? "Signed in on this browser" : "No account yet";
  if (!($("process").dataset.busy && need === 0)) {
    $("build-label").textContent = document.hidden && $("process").dataset.busy
      ? "Bring this tab to the front — indexing slows in the background."
      : ($("process").dataset.busy ? "Indexing" : "Ready");
  }
  if (!signedIn || $("process-status").textContent.startsWith("Get an account")
    || $("process-status").textContent.startsWith("Create an account")) {
    $("process-status").textContent = processPrompt();
  }
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
  const job = newJob("");
  job.lane = selectedLane();
  jobs.push(job);
  selectedJob = job.id;
  applyJobToForm(job);
  renderJobs();
});

$("output-name").addEventListener("input", () => {
  const job = jobs.find((item) => item.id === selectedJob);
  if (job) job.name = $("output-name").value.trim();
  persistJobs();
  renderJobs();
  updateReady();
});

document.querySelectorAll('input[name="mode"]').forEach((input) => {
  input.addEventListener("change", () => {
    const job = jobs.find((item) => item.id === selectedJob);
    if (job) job.lane = selectedLane();
    persistJobs();
    updateViewDirection();
    renderJobs();
    updateCliCommand();
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
    updateCliCommand();
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
    updateCliCommand();
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

["result-count", "max-per-country", "view-direction", "reject-road", "exclude-previous"].forEach((id) => {
  $(id)?.addEventListener("change", () => {
    saveJobFromForm();
    updateBlendMeta();
    renderJobs();
    updateCliCommand();
  });
});

$("duplicate-job")?.addEventListener("click", () => {
  saveJobFromForm();
  const source = currentJob();
  if (!source) return;
  const job = {
    ...source,
    id: crypto.randomUUID(),
    name: source.name ? `${source.name} copy` : "",
    excludeMap: source.excludeMap || null,
  };
  if (queryMaps.has(source.id)) queryMaps.set(job.id, queryMaps.get(source.id));
  jobs.push(job);
  selectedJob = job.id;
  applyJobToForm(job);
  persistJobs();
  renderJobs();
  updateReady();
});

$("open-index")?.addEventListener("click", () => $("index-sheet")?.showModal());
$("close-index")?.addEventListener("click", () => $("index-sheet")?.close());
$("show-outputs")?.addEventListener("click", () => {
  const block = $("command-block");
  if (block) block.open = true;
  $("index-sheet")?.showModal();
});
document.querySelectorAll('input[name="object-confidence"]').forEach((input) => {
  input.addEventListener("change", updateBlendMeta);
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
    $("process-status").textContent = selectedProcessLane() === "object"
      ? "Saved? Copy the object command into Terminal. It keeps going until you stop it or the queue is empty."
      : "Saved? Copy the index command into Terminal. It keeps going until you stop it or the queue is empty.";
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
    $("process-status").textContent = selectedProcessLane() === "object"
      ? "Welcome back. Copy the object command into Terminal. It keeps going until you stop it or the queue is empty."
      : "Welcome back. Copy the index command into Terminal. It keeps going until you stop it or the queue is empty.";
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
  pauseRequested = false;
  updateCliCommand();
  const choice = selectedProcessLane();
  const copied = await copyText(cliCommand(), $("cli-command"));
  const copiedText = choice === "both"
    ? "Copied both commands. Paste each one into its own Terminal window. They keep going until you stop them or the queue is empty."
    : choice === "object"
      ? "Copied the VISION object index command. Paste it into Terminal. It keeps going until you stop it or the queue is empty."
      : "Copied the VISION index command. Paste it into Terminal. It keeps going until you stop it or the queue is empty.";
  $("process-status").textContent = copied
    ? copiedText
    : "Select the index command, copy it, and paste it into Terminal. It keeps going until you stop it or the queue is empty.";
  button.disabled = false;
  updateProcessHelp();
  updateQueue();
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
      job.excludePrevious = true;
    }
    if ($("exclude-previous")) $("exclude-previous").checked = true;
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
  queryMaps.delete(selectedJob);
  const job = currentJob();
  if (job) job.queryLabel = "";
  $("query-map").value = "";
  $("file-name").textContent = "No JSON yet";
  saveJobFromForm();
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
  if ($("last-run")) $("last-run").hidden = !hasHits;
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
  $("search-status").textContent = "Adding scenes to your map…";
  $("send-mma").disabled = true;
  try {
    const result = await mmaSendMap(lastMap, {
      apiKey: key,
      mapId: selected === "__new__" ? undefined : selected,
      newMap: selected === "__new__",
    });
    mmaSaveConnection(key, selected);
    $("search-status").textContent = `Added ${result.added} scenes${result.name ? ` to ${result.name}` : ""}.`;
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
  if (!signedIn) {
    $("index-sheet")?.showModal();
    $("search-status").textContent = "Get an account from Index, then run the search again.";
    updateReady();
    return;
  }
  const credited = Number(state?.units || 0) >= Number(state?.searchCost || Infinity);
  if (!credited) {
    $("search-status").textContent = "Keep indexing until the bar is full. A search needs 100,000 scenes, or 10,000 objects.";
    updateReady();
    return;
  }
  if (selectedLane() === "scene" || state?.searchOnSite === false) {
    try {
      await copyComputerSearch();
    } finally {
      updateReady();
    }
    return;
  }
  try {
    const result = await api("/api/searches", "POST", {
      idempotencyKey: crypto.randomUUID(),
      lane: selectedLane(),
      queryMap: queryMap || undefined,
      prompt: typedPrompt() || undefined,
      descriptionWeight: selectedDescriptionWeight(),
      excludeMap: ($("exclude-previous")?.checked && currentJob()?.excludeMap) || undefined,
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
        ? `${hits.length} matching ${selectedLane() === "object" ? "objects" : "scenes"}. Copy for the local app, or download the JSON.`
        : mmaStoredKey()
          ? `${hits.length} matching ${selectedLane() === "object" ? "objects" : "scenes"}. Click Add to my map.`
          : `${hits.length} matching ${selectedLane() === "object" ? "objects" : "scenes"}. Connect a map app, or download the JSON.`)
      : "Nothing matched. Try Best of available views, or widen the filters.";
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
refresh().then(() => {
  localStorage.removeItem(INDEXING_KEY);
}).catch((error) => {
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
