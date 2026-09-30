"use strict";
const byId = id => document.getElementById(id);
const token = location.hash.slice(1);
history.replaceState(null, "", "/");
let requesting = false;
let closed = false;
let latest = {phase:"setup",message:"Checking this PC…",completed:0,units:0,elapsedSeconds:0,folder:"",busy:false,ready:false,connected:false,savedCode:false,qualified:false,stopping:false};
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
  byId("phase").textContent = ({setup:"GETTING READY",download:"PREPARING THIS PC",checking:"RUNNING THE SHORT PC CHECK",ready:"READY",indexing:"INDEXING ON THIS PC",error:"NEEDS ATTENTION"})[state.phase] || "VISION";
  byId("message").textContent = state.message;
  byId("detail").textContent = state.phase === "indexing" ? (state.stopping ? "Pausing after the current batch." : "Working in batches of 16. Progress is confirmed after each batch.") : state.phase === "checking" ? "The service must approve this PC before regular work can start." : "Keep this page and the VISION starter window open.";
  byId("completed").textContent = state.completed.toLocaleString();
  byId("units").textContent = state.units.toLocaleString();
  byId("elapsed").textContent = Math.floor(state.elapsedSeconds / 60) + " min";
  byId("folder").textContent = state.folder;
  byId("undelivered").hidden = !(state.undelivered > 0);
  byId("undelivered").textContent = state.undelivered > 0 ? `${state.undelivered.toLocaleString()} saved batches could not be delivered because their assignment ended. They earned no credits. Their files are kept; VISION can continue with new work.` : "";
  byId("account-status").textContent = state.connected ? "Account connected for this session." : "Your code stays out of commands and diagnostic logs.";
  const busy = state.busy || requesting;
  byId("prepare").disabled = busy;
  byId("prepare").textContent = state.ready ? "Check processing files again" : "Download and check files";
  byId("connect").disabled = busy || !state.ready;
  byId("create").disabled = busy || !state.ready;
  byId("check-pc").disabled = busy || !state.ready || !state.connected || !state.savedCode || state.qualified;
  byId("check-pc").textContent = state.qualified ? "PC approved" : "Run the short PC check";
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
  try { render(await request("/api/status")); }
  catch (error) { showError(token ? "VISION is not responding. Reopen Start VISION if its starter window has closed." : "Open this page using Start VISION."); }
}
byId("prepare").onclick = () => action("/api/prepare");
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
