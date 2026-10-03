import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { NativeController, authorized, descriptor, requestBytes } from "./controller.js";
import { MODEL_CHECK } from "./model-check.js";
import { checkedBootReceipt } from "./bootstrap.js";
import { LAUNCH_CHECK, checkedLaunchReceipt, stderrClass } from "./launch-check.js";
import { MAIN_CHECK, checkedMainReceipt, checkedMainFailureReceipt } from "./main-check.js";

const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const image = `registry.cloudflare.com/272760294910ef0b246980278aeb36e2/vision-community-native-scene@sha256:${"2".repeat(64)}`;
const runtime = "3".repeat(64);
const sample = new TextEncoder().encode("synthetic operator ZIP transport fixture; no model/data");
const bundle = { version: 1, sha256: sha(sample), bytes: sample.byteLength, key: `native-host/bundles/${sha(sample)}.zip` };

function fixture() {
  const values = new Map(), calls = [], pending = [];
  const control = { starts: [], destroys: 0, uploads: 0, calls, values, wrongRuntime: false,
    searchReady: false, badSize: false, corrupt: false, missing: false, failCommit: false, now: 1000 };
  const health = () => control.bootDiagnostic ?? ({ status: "native_host_available", runtimeSha256: control.wrongRuntime ? "f".repeat(64) : runtime,
    identityOnly: !control.active, auditReady: !!control.active, searchReady: control.active && control.searchReady || false,
    activeNativeProcessesMaximum: 1 });
  const container = {
    images: { native: image }, running: false,
    start(options) { this.running = true; control.starts.push(options); control.active = false; },
    async destroy() { this.running = false; control.destroys++; control.active = false; },
    async setInactivityTimeout(milliseconds) { assert.equal(milliseconds, 180000); },
    async inspect() { return { image, labels: {} }; },
    monitor() { return control.bootFailure ? Promise.reject(control.bootFailure) : new Promise(() => {}); },
    getTcpPort(port) {
      assert.equal(port, 8080);
      return { async fetch(url, init) {
        const path = new URL(url).pathname;
        calls.push(path);
        assert.equal(init.redirect, "manual");
        assert.equal(init.headers.authorization, "Bearer " + (path === "/operator/bundle" ? "b" : "a").repeat(64));
        if (path === "/health") return Response.json(health());
        if (path === "/operator/bundle") {
          const bytes = new Uint8Array(await new Response(init.body).arrayBuffer());
          control.uploads++;
          if (sha(bytes) !== init.headers["x-vision-bundle-sha256"]) return Response.json({ error: "operator_bundle_changed" }, { status: 503 });
          control.active = true;
          return Response.json(health());
        }
        control.forwarded = init.body;
        if (control.hold) await control.hold;
        return Response.json({ accepted: true }, { status: control.rejection ? 422 : 200 });
      } };
    },
  };
  const ctx = { container, storage: {
    async get(key) { return values.get(key); },
    async delete(key) { values.delete(key); },
    async setAlarm(deadline) { if (control.failAlarm) throw Error("synthetic alarm failure"); control.alarm = deadline; },
    async deleteAlarm() { control.alarm = null; },
    async put(key, value) {
      if (key === "activeBundle" && control.failCommit) throw Error("synthetic storage failure");
      values.set(key, structuredClone(value));
    },
  }, waitUntil(promise) { pending.push(promise); } };
  const env = { VISION_HOST_SECRET: "a".repeat(64), VISION_HOST_OPERATOR_SECRET: "b".repeat(64),
    NATIVE_IMAGE: image, NATIVE_RUNTIME_SHA256: runtime, OPERATOR_BUCKET_NAME: "vision-community-staging",
    OPERATOR_BUNDLES: { async get(key) {
      assert.equal(key, bundle.key);
      if (control.missing) return null;
      const bytes = control.corrupt ? new Uint8Array(sample).fill(0) : sample;
      return { size: control.badSize ? sample.byteLength + 1 : sample.byteLength,
        body: new ReadableStream({ start(controller) {
          controller.enqueue(bytes.subarray(0, 7)); controller.enqueue(bytes.subarray(7)); controller.close();
        } }) };
    } } };
  const options = { wait: async () => {}, fixedStream: () => new TransformStream(), now: () => control.now };
  const host = new NativeController(ctx, env, options);
  return { host, ctx, env, control, options, pending };
}

test("durable idle alarm stops monitored compute and preserves the sealed pointer across eviction", async () => {
  const { host, ctx, env, control, options } = fixture();
  assert.equal((await host.activate(bundle)).status, 200);
  assert.equal(control.alarm, control.now + 180000);
  const saved = structuredClone(control.values.get("activeBundle"));
  const reopened = new NativeController(ctx, env, options);
  control.now = control.alarm;
  await reopened.alarm();
  assert.equal(ctx.container.running, false);
  assert.deepEqual(control.values.get("activeBundle"), saved);
  assert.equal(control.alarm, null);
  assert.equal(control.values.has("idleDeadline"), false);
  assert.equal((await reopened.health()).status, 200);
  assert.equal(control.uploads, 2);
});

test("an old alarm honors renewed activity rather than stopping a recently used container", async () => {
  const { host, ctx, control } = fixture();
  await host.health();
  const old = control.alarm;
  control.now += 120000;
  await host.health();
  const renewed = control.alarm;
  control.now = old;
  await host.alarm();
  assert.equal(ctx.container.running, true);
  assert.equal(control.destroys, 0);
  assert.equal(control.alarm, renewed);
});

test("idle alarm defers while a bounded native operation owns the shared slot", async () => {
  const { host, ctx, control } = fixture();
  await host.activate(bundle);
  let release;
  control.searchReady = true;
  control.hold = new Promise(resolve => { release = resolve; });
  const pending = host.service("/search", new TextEncoder().encode("{}"));
  while (!control.calls.includes("/search")) await new Promise(resolve => setImmediate(resolve));
  control.now = control.alarm;
  await host.alarm();
  assert.equal(ctx.container.running, true);
  assert.equal(control.alarm, control.now + 30000);
  release();
  assert.equal((await pending).status, 200);
  assert.equal(control.alarm, control.now + 180000);
});

test("failure to arm idle shutdown makes the result unavailable and stops uncertain compute", async () => {
  const { host, ctx, control } = fixture();
  control.failAlarm = true;
  const response = await host.health();
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: "native_idle_guard_failed" });
  assert.equal(ctx.container.running, false);
  assert.equal(control.values.get("lastControlFailure").stage, "native_idle_guard_failed");
  assert.equal(host.busy, false);
});

test("missing idle metadata stops an unidentified running container without starting another", async () => {
  const { host, ctx, control } = fixture();
  ctx.container.running = true;
  await host.alarm();
  assert.equal(ctx.container.running, false);
  assert.equal(control.starts.length, 0);
  assert.equal(control.values.get("lastControlFailure").stage, "native_idle_guard_failed");
});

test("a classified bootstrap failure stops startup immediately and retains only bounded diagnostics", async () => {
  const { host, control, ctx } = fixture();
  control.bootDiagnostic = { status: "native_boot_unavailable", phase: "runtime_identity", code: "runtime_file_changed", errno: null };
  assert.equal((await host.health()).status, 503);
  assert.equal(control.calls.filter(p => p === "/health").length, 1);
  assert.equal(ctx.container.running, false);
  const saved = control.values.get("lastBootFailure");
  assert.deepEqual({ ...saved, at: 0 }, { phase: "runtime_identity", code: "runtime_file_changed", errno: null, at: 0 });
  assert.equal(control.values.get("lastControlFailure").stage, "native_boot_failed");
});

test("unrecognized bootstrap data cannot leak paths or credential values into saved status", async () => {
  const { host, control, ctx } = fixture();
  control.bootDiagnostic = { status: "native_boot_unavailable", phase: "runtime_identity", code: "sensitive native path and secret", errno: null };
  assert.equal((await host.health()).status, 503);
  assert.equal(ctx.container.running, false);
  assert.equal(control.values.has("lastBootFailure"), false);
  assert.equal(control.values.get("lastControlFailure").stage, "native_boot_diagnostic_invalid");
  const good = { status: "native_boot_unavailable", phase: "state_directory", code: "native_boot_failed", errno: 13 };
  assert.deepEqual(checkedBootReceipt(good), { phase: "state_directory", code: "native_boot_failed", errno: 13 });
  for (const change of [{ phase: "private/path" }, { extra: "secret" }, { errno: -1 }, { errno: true }, { errno: 4096 }]) {
    assert.throws(() => checkedBootReceipt({ ...good, ...change }), /native_boot_diagnostic_invalid/);
  }
});

test("operator authentication fails closed without starting or reading a body", () => {
  const good = "a".repeat(64);
  assert.equal(authorized(new Request("https://host/health"), good), false);
  assert.equal(authorized(new Request("https://host/health", { headers: { authorization: "Bearer " + good } }), good), true);
  assert.equal(authorized(new Request("https://host/health", { headers: { authorization: "Bearer " + "z".repeat(64) } }), good), false);
  assert.equal(authorized(new Request("https://host/health"), "short"), false);
});

test("operator descriptors cannot name arbitrary objects, URLs, traversal or fields", () => {
  assert.deepEqual(descriptor(bundle), bundle);
  for (const changed of [{ key: "geonections-images/anything" }, { key: "../policy.zip" },
    { key: "https://other.test/private.zip" }, { bytes: 384 * 1024 ** 2 + 1 },
    { bytes: 0 }, { sha256: "F".repeat(64) }, { extra: "not allowed" }, { version: 2 }]) {
    assert.throws(() => descriptor({ ...bundle, ...changed }), /invalid_operator_descriptor/);
  }
});

test("JSON framing is bounded and exact bytes survive Unicode and scientific notation", async () => {
  const raw = '{"query":{"lat":1e-7,"text":"é + 👁"}}';
  const request = () => new Request("https://host/search", { method: "POST", headers: { "content-type": "application/json" }, body: raw });
  assert.equal(new TextDecoder().decode(await requestBytes(request(), 1024)), raw);
  await assert.rejects(requestBytes(request(), 4));
  await assert.rejects(requestBytes(new Request("https://host/search", { method: "POST", body: raw }), 1024));
});

test("identity startup pins image/runtime/pool/resources without approving inference", async () => {
  const { host, control } = fixture();
  const response = await host.health();
  assert.equal(response.status, 200);
  assert.equal((await response.json()).productionQualified, false);
  assert.equal(control.starts.length, 1);
  assert.equal(control.starts[0].enableInternet, false);
  assert.deepEqual(control.starts[0].instance, { vcpu: 1, memoryMib: 3072, diskMb: 8000 });
  assert.deepEqual(control.starts[0].entrypoint, ["/usr/local/bin/python", "-B", "/opt/vision/server.py"]);
  assert.equal(control.starts[0].env.PYTHONPATH, "/opt/vision/client");
  for (const name of ["VISION_ORT_THREADS", "ORT_NUM_THREADS", "OMP_NUM_THREADS", "RAYON_NUM_THREADS"]) assert.equal(control.starts[0].env[name], "1");
});

test("real imagery egress requires explicit operator configuration", async () => {
  const { host, env, control } = fixture();
  env.NATIVE_IMAGERY_EGRESS = "live-imagery";
  assert.equal((await host.health()).status, 200);
  assert.equal(control.starts[0].enableInternet, true);
});

test("missing/wrong pins, resources and secrets refuse startup", async () => {
  for (const change of [{ VISION_HOST_SECRET: "short" }, { VISION_HOST_OPERATOR_SECRET: "a".repeat(64) },
    { NATIVE_IMAGE: image.replace(/@sha256:.+/, ":latest") }, { NATIVE_RUNTIME_SHA256: "short" },
    { OPERATOR_BUCKET_NAME: "geonections-images" }, { NATIVE_IMAGERY_EGRESS: "anything" }]) {
    const { host, env, control } = fixture();
    Object.assign(env, change);
    assert.equal((await host.health()).status, 503);
    assert.equal(control.starts.length, 0);
  }
});

test("wrong actual runtime cannot activate a bundle or serve a request", async () => {
  const { host, control } = fixture();
  control.wrongRuntime = true;
  assert.equal((await host.activate(bundle)).status, 503);
  assert.equal(control.uploads, 0);
  assert.equal(control.values.has("activeBundle"), false);
});

test("valid activation persists only after streamed digest/native checks; retry is idempotent", async () => {
  const { host, control, pending } = fixture();
  assert.equal((await host.activate(bundle)).status, 200);
  await Promise.all(pending);
  assert.deepEqual(control.values.get("activeBundle"), bundle);
  assert.equal(control.uploads, 1);
  assert.equal((await host.activate(bundle)).status, 200);
  assert.equal(control.uploads, 1);
});

test("missing, resized or tampered operator objects preserve the durable pointer", async () => {
  for (const name of ["missing", "badSize", "corrupt"]) {
    const { host, control } = fixture();
    control[name] = true;
    assert.equal((await host.activate(bundle)).status, 503);
    assert.equal(control.values.has("activeBundle"), false);
    assert.equal(control.values.get("lastControlFailure").stage, "operator_activation_failed");
    assert.equal(control.destroys, 1);
  }
});

test("failed durable commit destroys unacknowledged candidate state", async () => {
  const { host, control } = fixture();
  control.failCommit = true;
  assert.equal((await host.activate(bundle)).status, 503);
  assert.equal(control.values.has("activeBundle"), false);
  assert.equal(control.active, false);
  assert.equal(control.destroys, 1);
});

test("container loss rehydrates the same pinned bundle before service resumes", async () => {
  const { host, ctx, control } = fixture();
  assert.equal((await host.activate(bundle)).status, 200);
  ctx.container.running = false;
  control.active = false;
  assert.equal((await host.health()).status, 200);
  assert.equal(control.starts.length, 2);
  assert.equal(control.uploads, 2);
  assert.deepEqual(control.values.get("activeBundle"), bundle);
});

test("DO eviction reboots uncertain container state from its durable pointer", async () => {
  const { host, ctx, env, options, control } = fixture();
  assert.equal((await host.activate(bundle)).status, 200);
  const reopened = new NativeController(ctx, env, options);
  assert.equal((await reopened.health()).status, 200);
  assert.equal(control.destroys, 1);
  assert.equal(control.uploads, 2);
});

test("service rejects absent search/policy without consuming native inference", async () => {
  const { host, control } = fixture();
  const bytes = new TextEncoder().encode("{}");
  assert.equal((await host.service("/search", bytes)).status, 503);
  assert.equal(control.starts.length, 0);
  assert.equal((await host.activate(bundle)).status, 200);
  assert.equal((await host.service("/search", bytes)).status, 503);
  assert.equal(control.calls.includes("/search"), false);
});

test("private service preserves bytes and distinct native rejection status", async () => {
  const { host, control } = fixture();
  assert.equal((await host.activate(bundle)).status, 200);
  const bytes = new TextEncoder().encode('{"records":{"lat":1e-7,"text":"é"}}');
  control.rejection = true;
  assert.equal((await host.service("/audit", bytes)).status, 422);
  assert.deepEqual(control.forwarded, bytes);
});

test("shared request slot refuses concurrent search, activation and restart", async () => {
  const { host, control } = fixture();
  assert.equal((await host.activate(bundle)).status, 200);
  control.searchReady = true;
  let release, started;
  control.hold = new Promise((resolve) => { release = resolve; });
  const signal = new Promise((resolve) => { started = resolve; });
  const call = host.call.bind(host);
  host.call = async (path, options) => { if (path === "/search") started(); return call(path, options); };
  const running = host.service("/search", new TextEncoder().encode("{}"));
  await signal;
  for (const response of [await host.health(), await host.activate(bundle), await host.restart()]) {
    assert.equal(response.status, 503);
    assert.equal((await response.json()).error, "native_host_busy");
  }
  release();
  assert.equal((await running).status, 200);
});

test("explicit restart preserves pointer; missing rehydration fails closed", async () => {
  const { host, control } = fixture();
  assert.equal((await host.activate(bundle)).status, 200);
  assert.equal((await host.restart()).status, 200);
  assert.deepEqual(control.values.get("activeBundle"), bundle);
  control.missing = true;
  assert.equal((await host.service("/audit", new TextEncoder().encode("{}"))).status, 503);
  assert.equal(control.calls.filter((path) => path === "/audit").length, 0);
});

function modelReceipt() {
  return { status: "native_model_check_passed", runtimeSha256: runtime, locations: 1, views: 4,
    fetchErrors: 0, inferenceErrors: 0, bytes: 3080, outputSha256: "e".repeat(64),
    sceneGraph: "fp32", executionProvider: "cpu", threads: 1, elapsedSeconds: 4.5,
    peakChildRssKiB: 1024, productionQualified: false };
}
function stream(value) {
  return new Blob([value]).stream();
}

function launchReceipt() {
  return { status: "native_launch_check_passed", runtimeSha256: runtime, pythonVersion: "3.12.15",
    uid: 10001, modelFilesValidated: true, httpServerChecked: true,
    serviceAuthChecked: true, operatorAuthChecked: true, productionQualified: false };
}

test("exact server diagnostic keeps credentials private, validates main receipt and always stops", async () => {
  const { host, ctx, control, pending } = fixture();
  const receipt = { ...launchReceipt(), status: "native_main_check_passed", mainProgramChecked: true };
  ctx.container.exec = async (argv, options) => {
    assert.deepEqual(argv, ["/usr/local/bin/python", "-B", "-c", MAIN_CHECK]);
    assert.equal(options.env.VISION_HOST_SECRET, "a".repeat(64));
    assert.equal(options.env.VISION_HOST_OPERATOR_SECRET, "b".repeat(64));
    assert.equal(options.env.VISION_ORT_THREADS, "1");
    return { stdout: stream(JSON.stringify(receipt)), stderr: stream(""), exitCode: Promise.resolve(0) };
  };
  assert.deepEqual(await (await host.mainCheck()).json(), receipt);
  assert.equal(control.starts[0].enableInternet, false);
  assert.equal(control.starts[0].env, undefined);
  assert.equal(ctx.container.running, false);
  for (const key of ["mainProgramChecked", "httpServerChecked", "productionQualified", "runtimeSha256"]) {
    const damaged = { ...receipt, [key]: key === "runtimeSha256" ? "f".repeat(64) : !receipt[key] };
    assert.throws(() => checkedMainReceipt(damaged, runtime));
  }
  control.values.set("activeBundle", bundle);
  const starts = control.starts.length;
  assert.equal((await host.mainCheck()).status, 409);
  assert.equal(control.starts.length, starts);
  await Promise.all(pending);
});

test("main diagnostic preserves a fixed startup classification without exposing environment", async () => {
  const { host, ctx, control, pending } = fixture();
  ctx.container.exec = async () => ({ stdout: stream(JSON.stringify({ status: "native_boot_unavailable",
    phase: "main_program", code: "native_module_missing", errno: null,
    childExitCode: 1, stdoutBytes: 0, stderrBytes: 80, serverLine: 321 })), stderr: stream(""), exitCode: Promise.resolve(1) });
  assert.equal((await host.mainCheck()).status, 503);
  assert.equal(control.values.get("lastBootFailure").code, "native_module_missing");
  assert.equal(control.values.get("lastBootFailure").childExitCode, 1);
  assert.equal(control.values.get("lastBootFailure").stderrBytes, 80);
  assert.equal(ctx.container.running, false);
  assert.ok(!JSON.stringify([...control.values]).includes("a".repeat(64)));
  await Promise.all(pending);
});

test("main failure measurements reject raw details and invalid numeric bounds", () => {
  const receipt = { status: "native_boot_unavailable", phase: "main_program", code: "native_main_program_failed",
    errno: null, childExitCode: -9, stdoutBytes: 0, stderrBytes: 8192, serverLine: 321 };
  assert.deepEqual(checkedMainFailureReceipt(receipt), { childExitCode: -9, stdoutBytes: 0, stderrBytes: 8192, serverLine: 321 });
  for (const patch of [{ childExitCode: -256 }, { childExitCode: "1" }, { stdoutBytes: 8193 },
    { stderrBytes: -1 }, { serverLine: "private-path" }, { serverLine: 10000 }, { stderr: "private-token /sensitive/path" }]) {
    assert.throws(() => checkedMainFailureReceipt({ ...receipt, ...patch }), /native_boot_diagnostic_invalid/);
  }
});

test("isolated launch checks pinned Python and private HTTP without inherited secrets or imagery and always stops compute", async () => {
  const { host, ctx, control, pending } = fixture();
  ctx.container.exec = async (argv, options) => {
    assert.deepEqual(argv, ["/usr/local/bin/python", "-B", "-c", LAUNCH_CHECK]);
    assert.deepEqual(options.env, { PYTHONPATH: "/opt/vision/client", PYTHONDONTWRITEBYTECODE: "1", PYTHONUNBUFFERED: "1" });
    return { stdout: stream(JSON.stringify(launchReceipt())), stderr: stream(""), exitCode: Promise.resolve(0) };
  };
  assert.deepEqual(await (await host.launchCheck()).json(), launchReceipt());
  assert.deepEqual(control.starts[0].entrypoint, ["/usr/bin/sleep", "120"]);
  assert.equal(control.starts[0].enableInternet, false);
  assert.equal(control.starts[0].env, undefined);
  assert.equal(ctx.container.running, false);
  assert.equal(control.values.has("activeBundle"), false);
  assert.equal(control.uploads, 0);
  await Promise.all(pending);
});

test("isolated launch preserves a sealed workload and never starts a replacement", async () => {
  const { host, control } = fixture();
  control.values.set("activeBundle", bundle);
  const response = await host.launchCheck();
  assert.equal(response.status, 409);
  assert.equal(control.starts.length, 0);
  assert.equal(control.destroys, 0);
  assert.deepEqual(control.values.get("activeBundle"), bundle);
});

test("isolated launch retains only classified Python or VM failures", async () => {
  for (const vmFailure of [false, true]) {
    const { host, ctx, control, pending } = fixture();
    if (vmFailure) control.bootFailure = Object.assign(Error("private VM path or credential"), { exitCode: 1 });
    ctx.container.exec = async () => ({ stdout: stream(""),
      stderr: stream("Traceback with private paths\nModuleNotFoundError: private dependency and synthetic-secret"),
      exitCode: Promise.resolve(1) });
    assert.equal((await host.launchCheck()).status, 503);
    assert.equal(ctx.container.running, false);
    const failure = control.values.get("lastLaunchFailure");
    assert.equal(failure.stage, vmFailure ? "container_launch" : "python_process");
    assert.equal(failure.exitCode, 1);
    assert.equal(JSON.stringify(failure).includes("synthetic-secret"), false);
    assert.equal(JSON.stringify(failure).includes("private"), false);
    await Promise.all(pending);
  }
  assert.equal(stderrClass(new TextEncoder().encode("unknown sensitive log")), null);
  assert.throws(() => checkedLaunchReceipt({ ...launchReceipt(), secret: "private" }, runtime));
  assert.throws(() => checkedLaunchReceipt({ ...launchReceipt(), runtimeSha256: "f".repeat(64) }, runtime));
  assert.throws(() => checkedLaunchReceipt({ ...launchReceipt(), httpServerChecked: false }, runtime));
  assert.throws(() => checkedLaunchReceipt({ ...launchReceipt(), operatorAuthChecked: false }, runtime));
});

test("isolated launch has a hard deadline even if process creation stalls", async () => {
  const { ctx, env, options, control } = fixture();
  ctx.container.exec = () => new Promise(() => {});
  const host = new NativeController(ctx, env, { ...options, launchCheckTimeoutMs: 5 });
  assert.equal((await host.launchCheck()).status, 503);
  assert.equal(ctx.container.running, false);
  assert.equal(control.values.get("lastLaunchFailure").stage, "deadline");
});

test("isolated launch deadline also covers a stalled platform inactivity setting", async () => {
  const { ctx, env, options, control } = fixture();
  ctx.container.setInactivityTimeout = () => new Promise(() => {});
  const host = new NativeController(ctx, env, { ...options, launchCheckTimeoutMs: 5 });
  assert.equal((await host.launchCheck()).status, 503);
  assert.equal(ctx.container.running, false);
  assert.equal(control.values.get("lastLaunchFailure").stage, "deadline");
});

test("fixed model check refuses implicit egress without starting compute", async () => {
  const { host, control } = fixture();
  const response = await host.modelCheck();
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: "model_check_egress_disabled" });
  assert.equal(control.starts.length, 0);
});

test("model diagnostic runs only the fixed bounded command and cannot grant readiness", async () => {
  const { host, ctx, env, control, pending } = fixture();
  env.NATIVE_IMAGERY_EGRESS = "live-imagery";
  ctx.container.exec = async (argv) => {
    assert.deepEqual(argv, ["timeout", "--kill-after=5", "100", "/usr/local/bin/python", "-B", "-c", MODEL_CHECK]);
    return { stdout: stream(JSON.stringify(modelReceipt())), stderr: stream(""), exitCode: Promise.resolve(0) };
  };
  const response = await host.modelCheck();
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), modelReceipt());
  assert.equal(control.values.has("activeBundle"), false);
  assert.equal(control.active, false);
  await Promise.all(pending);
});

test("damaged, leaked, oversized or failed diagnostic output is redacted and destroys uncertain state", async () => {
  for (const change of [{ receipt: { ...modelReceipt(), runtimeSha256: "f".repeat(64) } },
    { receipt: { ...modelReceipt(), threads: 4 } }, { receipt: { ...modelReceipt(), secret: "synthetic-secret" } },
    { stdout: "x".repeat(4097) }, { stderr: "sensitive native paths" }, { code: 1 }]) {
    const { host, ctx, env, control, pending } = fixture();
    env.NATIVE_IMAGERY_EGRESS = "live-imagery";
    ctx.container.exec = async () => ({ stdout: stream(change.stdout ?? JSON.stringify(change.receipt ?? modelReceipt())),
      stderr: stream(change.stderr ?? ""), exitCode: Promise.resolve(change.code ?? 0) });
    const response = await host.modelCheck();
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), { error: "native_model_check_failed" });
    assert.equal(control.destroys, 1);
    assert.deepEqual(Object.keys(control.values.get("lastControlFailure")).sort(), ["at", "stage"]);
    await Promise.all(pending);
  }
});

test("controller deadline stops uncertain diagnostic compute and retains only a failure marker", async () => {
  const { ctx, env, control, options } = fixture();
  env.NATIVE_IMAGERY_EGRESS = "live-imagery";
  ctx.container.exec = () => new Promise(() => {});
  const host = new NativeController(ctx, env, { ...options, modelCheckTimeoutMs: 5 });
  const response = await host.modelCheck();
  assert.equal(response.status, 503);
  assert.equal(control.destroys, 1);
  assert.equal(control.values.get("lastControlFailure").stage, "native_model_check_failed");
});

test("nonzero container boot exit is identified without retaining exception text or credentials", async () => {
  const { host, control } = fixture();
  control.bootFailure = Object.assign(Error("sensitive native path and synthetic-secret"), { exitCode: 1 });
  const response = await host.health();
  assert.equal(response.status, 503);
  assert.equal(control.destroys, 1);
  assert.equal(control.values.get("lastControlFailure").stage, "container_boot_failed");
  assert.deepEqual(Object.keys(control.values.get("lastContainerExit")).sort(), ["at", "exitCode"]);
  assert.equal(control.values.get("lastContainerExit").exitCode, 1);
  assert.equal(JSON.stringify(await (await host.status()).json()).includes("synthetic-secret"), false);
});

test("startup has a separate hard deadline even if the port request ignores cancellation", async () => {
  const { ctx, env, options, control } = fixture();
  ctx.container.getTcpPort = () => ({ fetch() { return new Promise(() => {}); } });
  const host = new NativeController(ctx, env, { ...options, startupBudgetMs: 5 });
  const response = await host.health();
  assert.equal(response.status, 503);
  assert.equal(control.destroys, 1);
  assert.equal(control.values.get("lastControlFailure").stage, "native_startup_unavailable");
});
