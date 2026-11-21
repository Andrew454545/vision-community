// Real workerd SQLite storage and alarm delivery; synthetic compute only.
// The fixture class is appended only to this local test, never deployed.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(resolve(process.argv[2])));
const bundle = await readFile(resolve(process.argv[3]), "utf8");
const seal = { version: 1, key: `native-host/bundles/${"a".repeat(64)}.zip`, sha256: "a".repeat(64), bytes: 1 };
const fixture = `
export class LocalIdleAlarmFixture extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.synthetic = { running: false, stops: 0,
      destroy: async () => { this.synthetic.running = false; this.synthetic.stops++; } };
    this.control = new NativeController({ storage: ctx.storage, container: this.synthetic,
      waitUntil: promise => ctx.waitUntil(promise) }, {});
  }
  async seed(scenario) {
    await this.ctx.storage.put('activeBundle', ${JSON.stringify(seal)});
    this.synthetic.running = true;
    await this.control.armIdle();
    if (scenario !== 'renewed') await this.ctx.storage.put('idleDeadline', Date.now() - 1);
    this.control.busy = scenario === 'busy';
    await this.ctx.storage.setAlarm(Date.now() + 25);
    return { seeded: true };
  }
  async release() {
    this.control.busy = false;
    await this.ctx.storage.put('idleDeadline', Date.now() - 1);
    await this.ctx.storage.setAlarm(Date.now() + 25);
    return { released: true };
  }
  async alarm() {
    await this.control.alarm();
    const count = await this.ctx.storage.get('callbacks') ?? 0;
    await this.ctx.storage.put('callbacks', count + 1);
  }
  async inspect() {
    return { running: this.synthetic.running, stops: this.synthetic.stops,
      callbacks: await this.ctx.storage.get('callbacks') ?? 0,
      seal: await this.ctx.storage.get('activeBundle'),
      idleDeadline: await this.ctx.storage.get('idleDeadline') ?? null,
      alarm: await this.ctx.storage.getAlarm() };
  }
}
`;
const options = { workers: [
  { name: "idle-gateway", modules: true, compatibilityDate: "2026-10-02",
    serviceBindings: { FIXTURE: "local-idle-fixture" },
    script: `export default { fetch(request, env) { return env.FIXTURE.fetch(request); } };` },
  { name: "local-idle-fixture", modules: true, script: bundle + fixture,
    compatibilityDate: "2026-10-02", compatibilityFlags: ["nodejs_compat"],
    durableObjects: { IDLE_FIXTURE: { className: "LocalIdleAlarmFixture", useSQLite: true } },
    serviceBindings: {},
    // A named entrypoint keeps the production default handler untouched.
  },
] };
// Route solely to the test class, through a named private binding.
options.workers[1].script += `
export class LocalIdleFixtureGateway extends WorkerEntrypoint {
  async fetch(request) {
    const [scenario, action] = new URL(request.url).pathname.slice(1).split('/');
    if (!['expired','renewed','busy'].includes(scenario)) return new Response(null, {status:404});
    const stub = this.env.IDLE_FIXTURE.getByName(scenario);
    if (action === 'seed') return Response.json(await stub.seed(scenario));
    if (action === 'release') return Response.json(await stub.release());
    return Response.json(await stub.inspect());
  }
}
`;
options.workers[0].serviceBindings.FIXTURE = { name: "local-idle-fixture", entrypoint: "LocalIdleFixtureGateway" };
const instance = new Miniflare(convertV4MiniflareOptions(options));
async function call(scenario, action = "inspect") {
  const response = await instance.dispatchFetch(`https://idle.invalid/${scenario}/${action}`);
  if (response.status !== 200) assert.fail((await response.text()).slice(0,2048));
  return response.json();
}
async function delivered(scenario, count = 1) {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    const state = await call(scenario);
    if (state.callbacks >= count) return state;
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  assert.fail(`actual SQLite alarm was not delivered for ${scenario}`);
}
try {
  await call("expired", "seed");
  const expired = await delivered("expired");
  assert.equal(expired.running, false);
  assert.equal(expired.stops, 1);
  assert.deepEqual(expired.seal, seal);
  assert.equal(expired.idleDeadline, null);
  assert.equal(expired.alarm, null);

  await call("renewed", "seed");
  const renewed = await delivered("renewed");
  assert.equal(renewed.running, true);
  assert.equal(renewed.stops, 0);
  assert.equal(renewed.alarm, renewed.idleDeadline);
  assert.ok(renewed.alarm > Date.now() + 170000);
  assert.deepEqual(renewed.seal, seal);

  await call("busy", "seed");
  const busy = await delivered("busy");
  assert.equal(busy.running, true);
  assert.equal(busy.stops, 0);
  assert.ok(busy.alarm > Date.now() + 25000);
  await call("busy", "release");
  const released = await delivered("busy", 2);
  assert.equal(released.running, false);
  assert.equal(released.stops, 1);
  assert.equal(released.alarm, null);
  assert.deepEqual(released.seal, seal);
  console.log(JSON.stringify({ status: "ACTUAL_WORKERD_SQLITE_NATIVE_IDLE_ALARMS_PASSED",
    checks: 3, syntheticCompute: true, modelInference: false, productionQualified: false }));
} finally { await instance.dispose(); }
