"use strict";
const byId = id => document.getElementById(id);
const token = location.hash.slice(1);
history.replaceState(null, "", "/");
let requesting = false;
let closed = false;
let latest = {phase:"setup",message:"Checking this computer…",completed:0,units:0,elapsedSeconds:0,folder:"",busy:false,ready:false,connected:false,savedCode:false,qualified:false,stopping:false};
async function request(path, body) {
  const options = {headers: {"X-Vision-Token": token}, cache: "no-store"};
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "This action could not finish.");
  return result;
}
function showError(message) {
  byId("error").textContent = message;
  byId("error").hidden = !message;
}
function render(state) {
  latest = state;
  byId("windows-background").hidden = state.backgroundAvailable !== true;
  byId("mac-background").hidden = state.backgroundAvailable === true;
  byId("phase").textContent = ({setup:"GETTING READY",download:"PREPARING THIS COMPUTER",checking:"RUNNING THE SHORT COMPUTER CHECK",ready:"READY",indexing:"INDEXING ON THIS COMPUTER",error:"NEEDS ATTENTION"})[state.phase] || "VISION";
  byId("message").textContent = state.message;
  byId("detail").textContent = state.phase === "indexing" ? (state.stopping ? "Pausing after the current batch. Please wait." : "Keep your computer awake and connected. Your credits update when results are accepted.") : state.phase === "checking" ? "Please wait. Regular work starts after the computer check is approved." : "Keep this page and the small VISION starter window open.";
  const step = !state.ready ? 1 : !state.connected || !state.savedCode ? 2 : !state.qualified ? 3 : 4;
  const next = state.busy ? "Please wait for this step to finish." : state.connected && !state.savedCode ? "Next: Save your private account code in step 2." : `Next: Step ${step} — ${["set up this computer", "create an account, or use your saved code", "run the computer check", "start helping"][step - 1]}.`;
  if (byId("next-step").textContent !== next) byId("next-step").textContent = next;
  byId("go-next").textContent = `Go to step ${step}`;
  byId("go-next").disabled = state.busy || requesting;
  byId("go-next").dataset.step = step;
  for (let n = 1; n <= 4; n++) {
    byId(`step-${n}`).classList.toggle("current", n === step);
    if (n === step) byId(`step-${n}`).setAttribute("aria-current", "step");
    else byId(`step-${n}`).removeAttribute("aria-current");
  }
  byId("completed").textContent = state.completed.toLocaleString();
  byId("units").textContent = state.units.toLocaleString();
  byId("elapsed").textContent = state.busy ? Math.floor(state.elapsedSeconds / 60) + " min" : "—";
  const hasProgress = state.busy && ["indexing", "checking"].includes(state.phase)
    && Number.isSafeInteger(state.batchTotal) && state.batchTotal > 0
    && Number.isSafeInteger(state.batchCompleted) && state.batchCompleted >= 0 && state.batchCompleted <= state.batchTotal;
  byId("batch-progress").hidden = !hasProgress;
  if (hasProgress) {
    byId("progress").max = state.batchTotal;
    byId("progress").value = state.batchCompleted;
    byId("progress-label").textContent = `${state.phase === "checking" ? "Computer check" : "Current batch"}: ${state.batchCompleted.toLocaleString()} of ${state.batchTotal.toLocaleString()} locations processed.`;
  }
  byId("pending").hidden = !(state.pending > 0);
  byId("pending").textContent = state.pending > 0 ? `${state.pending.toLocaleString()} saved ${state.pending === 1 ? "batch is" : "batches are"} waiting for delivery or a service check. Credits appear after acceptance.${state.busy ? "" : " Choose Start helping to resume."}` : "";
  byId("folder").textContent = state.folder;
  byId("undelivered").hidden = !(state.undelivered > 0);
  byId("undelivered").textContent = state.undelivered > 0 ? `${state.undelivered.toLocaleString()} saved batches could not be delivered because their assignment ended. They earned no credits. Their files are kept; VISION can continue with new work.` : "";
  byId("account-status").textContent = state.connected ? "Your account is connected." : "Keep your private code. You will also use it on the search website.";
  const busy = state.busy || requesting;
  byId("prepare").disabled = busy;
  byId("prepare").textContent = state.ready ? "Check setup again" : "Set up this computer";
  byId("connect").disabled = busy || !state.ready;
  byId("create").disabled = busy || !state.ready;
  byId("check-pc").disabled = busy || !state.ready || !state.connected || !state.savedCode || state.qualified;
  byId("check-pc").textContent = state.qualified ? "Computer approved" : "Run the computer check";
  byId("start").disabled = busy || !state.ready || !state.connected || !state.savedCode || !state.qualified;
  byId("stop").disabled = state.phase !== "indexing" || !state.busy || state.stopping;
  byId("quit").disabled = busy;
}
async function action(path, body={}) {
  if (requesting) return;
  requesting = true; showError(""); render(latest);
  try { return await request(path, body); }
  catch (error) { showError(error.message); }
  finally { requesting = false; await poll(); }
}
async function poll() {
  if (closed) return;
  try {
    render(await request("/api/status"));
    byId("connection-error").hidden = true;
    byId("connection-error").textContent = "";
  }
  catch (error) {
    byId("connection-error").textContent = token ? "Reconnecting to VISION… If the starter window closed, reopen Start VISION." : "Open this page using Start VISION.";
    byId("connection-error").hidden = false;
  }
}
byId("prepare").onclick = () => action("/api/prepare");
byId("go-next").onclick = () => {
  const step = Number(byId("go-next").dataset.step);
  byId(`step-${step}`).scrollIntoView({block: "start"});
  const target = step === 2 ? (latest.connected && !latest.savedCode ? "saved-code" : "create") : ({1: "prepare", 3: "check-pc", 4: "start"})[step];
  byId(target).focus({preventScroll: true});
};
byId("connect").onclick = async () => {
  const result = await action("/api/connect", {code: byId("code").value});
  if (result) { byId("code").value = ""; byId("recovery").textContent = ""; byId("new-code").hidden = true; }
};
byId("create").onclick = async () => {
  const result = await action("/api/connect", {create: true});
  if (result && result.recoveryCode) { byId("recovery").textContent = result.recoveryCode; byId("new-code").hidden = false; }
};
byId("copy-code").onclick = async () => {
  try { await navigator.clipboard.writeText(byId("recovery").textContent); byId("copy-code").textContent = "Copied"; }
  catch { showError("Select the account code and copy it manually."); }
};
byId("saved-code").onclick = async () => { const result = await action("/api/saved-code"); if (result) { byId("recovery").textContent = ""; byId("new-code").hidden = true; } };
byId("check-pc").onclick = () => action("/api/check-pc");
byId("start").onclick = () => action("/api/start");
byId("stop").onclick = () => action("/api/stop");
byId("quit").onclick = async () => {
  try { await request("/api/quit", {}); closed = true; document.body.classList.add("closed"); byId("message").textContent = "VISION is closed. You can close this tab."; byId("quit").disabled = true; showError(""); }
  catch (error) { showError(error.message); }
};
poll();
setInterval(poll, 2000);
