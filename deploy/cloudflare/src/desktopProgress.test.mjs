import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import test from "node:test";

const script = readFileSync(new URL("../../../community/desktop_web/app.js", import.meta.url), "utf8");
function state(extra = {}) {
  return { phase: "ready", message: "Ready", completed: 0, units: 8, elapsedSeconds: 120,
    folder: "private local folder", busy: false, ready: true, connected: true, savedCode: true,
    qualified: true, stopping: false, pending: 0, undelivered: 0, ...extra };
}
async function screen() {
  const nodes = new Map();
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, { textContent: "", hidden: true, disabled: false,
      dataset: {}, classList: { toggle() {}, add() {} }, setAttribute() {}, removeAttribute() {} });
    return nodes.get(id);
  };
  let unavailable = false;
  const scope = { document: { getElementById: element, body: element("body") },
    location: { hash: "#disposable-local-token" }, history: { replaceState() {} }, setInterval() {},
    fetch: async () => {
      if (unavailable) throw new Error("temporary local disconnect");
      return { ok: true, json: async () => state() };
    } };
  runInNewContext(script, scope);
  await scope.poll();
  return { scope, element, setUnavailable(value) { unavailable = value; } };
}

test("PC check and current-batch progress use actual totals and never imply accepted credit", async () => {
  const { scope, element } = await screen();
  scope.render(state({ phase: "checking", busy: true, qualified: false, batchTotal: 112, batchCompleted: 48 }));
  assert.equal(element("batch-progress").hidden, false);
  assert.equal(element("progress").max, 112);
  assert.equal(element("progress").value, 48);
  assert.match(element("progress-label").textContent, /PC check: 48 of 112/);
  scope.render(state({ phase: "indexing", busy: true, batchTotal: 8, batchCompleted: 8, pending: 1, stopping: true }));
  assert.equal(element("progress").max, 8);
  assert.equal(element("progress").value, 8);
  assert.equal(element("completed").textContent, "0");
  assert.equal(element("units").textContent, "8");
  assert.match(element("pending").textContent, /1 saved batch is waiting/);
  assert.match(element("pending").textContent, /after acceptance/);
  assert.match(element("detail").textContent, /Pausing after/);
  assert.equal(element("stop").disabled, true);
  scope.render(state());
  assert.equal(element("batch-progress").hidden, true);
  assert.equal(element("pending").hidden, true);
  assert.equal(element("elapsed").textContent, "—");
});

test("unknown, stale or invalid totals do not display misleading progress", async () => {
  const { scope, element } = await screen();
  for (const extra of [{ batchTotal: 0, batchCompleted: 0 }, { batchTotal: 8, batchCompleted: 9 },
    { batchTotal: 8, batchCompleted: -1 }, { batchTotal: 8, batchCompleted: 0.5 },
    { batchTotal: "8", batchCompleted: 1 }, { phase: "error", batchTotal: 8, batchCompleted: 8 }]) {
    scope.render(state({ phase: "indexing", busy: true, ...extra }));
    assert.equal(element("batch-progress").hidden, true);
  }
});

test("successful reconnect clears only the connection notice, preserving action failure and account state", async () => {
  const { scope, element, setUnavailable } = await screen();
  scope.showError("This PC check needs review. Your report is saved.");
  setUnavailable(true);
  await scope.poll();
  assert.equal(element("connection-error").hidden, false);
  assert.match(element("connection-error").textContent, /Reconnecting/);
  assert.equal(element("units").textContent, "8");
  setUnavailable(false);
  await scope.poll();
  assert.equal(element("connection-error").hidden, true);
  assert.equal(element("connection-error").textContent, "");
  assert.equal(element("error").hidden, false);
  assert.match(element("error").textContent, /needs review/);
  assert.equal(element("units").textContent, "8");
});
