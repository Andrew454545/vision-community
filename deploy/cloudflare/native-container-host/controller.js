import { createHash, timingSafeEqual } from "node:crypto";
import { bounded, MAX_REQUEST as SEARCH_REQUEST, MAX_RESPONSE as SEARCH_RESPONSE } from "../native-scene-bridge/worker.js";
import { MODEL_CHECK, checkedModelReceipt } from "./model-check.js";

export const MAX_BUNDLE = 384 * 1024 * 1024;
const HEX = /^[0-9a-f]{64}$/;
const INSTANCE = Object.freeze({ vcpu: 1, memoryMib: 3072, diskMb: 8000 });
const IDLE_MS = 180000;
const CONTROL_FAILURES = new Set(["native_configuration_unavailable", "native_runtime_identity_changed",
  "native_startup_unavailable", "native_image_changed", "container_boot_failed", "container_exited_during_startup",
  "native_response_unavailable", "native_response_limit", "native_response_length",
  "operator_bundle_missing_or_changed", "operator_bundle_size_changed", "operator_bundle_changed",
  "operator_activation_unavailable"]);
const safeStage = (error) => CONTROL_FAILURES.has(error?.message) ? error.message : "native_control_failed";
const jsonHeaders = { "content-type": "application/json", "cache-control": "no-store" };
export const failure = (code = "native_host_unavailable", status = 503) => Response.json({ error: code }, { status, headers: jsonHeaders });

export function validSecret(value) {
  return typeof value === "string" && /^[\x21-\x7e]{32,256}$/.test(value);
}

export function authorized(request, secret) {
  if (!validSecret(secret)) return false;
  const expected = new TextEncoder().encode(`Bearer ${secret}`);
  const actual = new TextEncoder().encode(request.headers.get("authorization") ?? "");
  return actual.byteLength === expected.byteLength && timingSafeEqual(actual, expected);
}

export function descriptor(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).sort().join(",") !== "bytes,key,sha256,version"
      || value.version !== 1 || typeof value.sha256 !== "string" || !HEX.test(value.sha256)
      || value.key !== `native-host/bundles/${value.sha256}.zip`
      || !Number.isSafeInteger(value.bytes) || value.bytes < 1 || value.bytes > MAX_BUNDLE) {
    throw Error("invalid_operator_descriptor");
  }
  return { version: 1, key: value.key, sha256: value.sha256, bytes: value.bytes };
}

async function responseBytes(response, maximum, statuses = [200]) {
  if (!statuses.includes(response.status)
      || response.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
    await response.body?.cancel();
    throw Error("native_response_unavailable");
  }
  const length = response.headers.get("content-length");
  if (length !== null && (!/^[0-9]+$/.test(length) || Number(length) > maximum)) {
    await response.body?.cancel();
    throw Error("native_response_limit");
  }
  const bytes = await bounded(response.body, maximum);
  if (!bytes.byteLength || (length !== null && bytes.byteLength !== Number(length))) throw Error("native_response_length");
  return bytes;
}

export async function requestBytes(request, maximum) {
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
    throw Error("invalid_request");
  }
  const length = request.headers.get("content-length");
  if (length !== null && (!/^[0-9]+$/.test(length) || Number(length) > maximum)) throw Error("invalid_request");
  const bytes = await bounded(request.body, maximum);
  if (!bytes.byteLength || (length !== null && bytes.byteLength !== Number(length))) throw Error("invalid_request");
  return bytes;
}

export class NativeController {
  constructor(ctx, env, options = {}) {
    this.ctx = ctx;
    this.env = env;
    this.busy = false;
    this.hydratedDigest = undefined;
    this.wait = options.wait ?? ((milliseconds) => scheduler.wait(milliseconds));
    this.fixedStream = options.fixedStream ?? ((bytes) => new FixedLengthStream(bytes));
    this.modelCheckTimeoutMs = options.modelCheckTimeoutMs ?? 110000;
    this.startupBudgetMs = options.startupBudgetMs ?? 60000;
  }

  config() {
    const env = this.env, image = env.NATIVE_IMAGE;
    if (!validSecret(env.VISION_HOST_SECRET) || !validSecret(env.VISION_HOST_OPERATOR_SECRET)
        || env.VISION_HOST_SECRET === env.VISION_HOST_OPERATOR_SECRET
        || typeof env.NATIVE_RUNTIME_SHA256 !== "string" || !HEX.test(env.NATIVE_RUNTIME_SHA256)
        || typeof image !== "string" || !/^registry\.cloudflare\.com\/272760294910ef0b246980278aeb36e2\/vision-community-native-scene@sha256:[0-9a-f]{64}$/.test(image)
        || !this.ctx.container || this.ctx.container.images?.native !== image
        || ![undefined, "disabled", "live-imagery"].includes(env.NATIVE_IMAGERY_EGRESS)
        || env.OPERATOR_BUCKET_NAME !== "vision-community-staging" || !env.OPERATOR_BUNDLES?.get) {
      throw Error("native_configuration_unavailable");
    }
    return this.ctx.container;
  }

  async recordFailure(stage) {
    // One bounded metadata record, with no request, prompt, account or address.
    try { await this.ctx.storage.put("lastControlFailure", { stage, at: Date.now() }); }
    catch { /* Failure to retain metadata never grants readiness. */ }
  }

  async exclusive(operation) {
    if (this.busy) return failure("native_host_busy");
    this.busy = true;
    try { return await operation(); }
    catch (error) { await this.recordFailure(safeStage(error)); return failure(); }
    finally { this.busy = false; }
  }

  async call(path, { body, operator = false, maximum = 65536, timeout = 20000, statuses = [200] } = {}) {
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), timeout);
    try {
      const response = await this.ctx.container.getTcpPort(8080).fetch(`http://container${path}`, {
        method: body === undefined ? "GET" : "POST", redirect: "manual", signal: abort.signal,
        headers: { authorization: `Bearer ${operator ? this.env.VISION_HOST_OPERATOR_SECRET : this.env.VISION_HOST_SECRET}`,
          ...(body === undefined ? {} : { "content-type": "application/json" }) }, body,
      });
      return { status: response.status, bytes: await responseBytes(response, maximum, statuses) };
    } finally { clearTimeout(timer); }
  }

  async checkedHealth(timeout = 20000) {
    const { bytes } = await this.call("/health", { timeout });
    const health = JSON.parse(new TextDecoder().decode(bytes));
    if (health.status !== "native_host_available" || health.runtimeSha256 !== this.env.NATIVE_RUNTIME_SHA256
        || health.activeNativeProcessesMaximum !== 1
        || ["identityOnly", "auditReady", "searchReady"].some((key) => typeof health[key] !== "boolean")) {
      throw Error("native_runtime_identity_changed");
    }
    return health;
  }

  async upload(bundle) {
    bundle = descriptor(bundle);
    const object = await this.env.OPERATOR_BUNDLES.get(bundle.key);
    if (!object || object.size !== bundle.bytes || !object.body) {
      await object?.body?.cancel();
      throw Error("operator_bundle_missing_or_changed");
    }
    const checksum = createHash("sha256");
    let count = 0;
    const hash = new TransformStream({ transform(chunk, controller) {
      count += chunk.byteLength;
      if (count > bundle.bytes) throw Error("operator_bundle_size_changed");
      checksum.update(chunk);
      controller.enqueue(chunk);
    } });
    const framing = this.fixedStream(bundle.bytes);
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 120000);
    const transfer = object.body.pipeThrough(hash).pipeTo(framing.writable, { signal: abort.signal });
    // Attach rejection handling immediately while fetch consumes the stream.
    this.ctx.waitUntil(transfer.catch(() => {}));
    try {
      const response = await this.ctx.container.getTcpPort(8080).fetch("http://container/operator/bundle", {
        method: "POST", redirect: "manual", signal: abort.signal,
        headers: { authorization: `Bearer ${this.env.VISION_HOST_OPERATOR_SECRET}`,
          "content-type": "application/zip", "x-vision-bundle-sha256": bundle.sha256 },
        body: framing.readable,
      });
      const bytes = await responseBytes(response, 65536);
      await transfer;
      if (count !== bundle.bytes || checksum.digest("hex") !== bundle.sha256) throw Error("operator_bundle_changed");
      const health = JSON.parse(new TextDecoder().decode(bytes));
      if (health.runtimeSha256 !== this.env.NATIVE_RUNTIME_SHA256 || health.identityOnly !== false
          || health.auditReady !== true || typeof health.searchReady !== "boolean"
          || health.activeNativeProcessesMaximum !== 1) throw Error("operator_activation_unavailable");
      return health;
    } finally {
      abort.abort();
      await transfer.catch(() => {});
      clearTimeout(timer);
    }
  }

  async ensure(active) {
    const container = this.config();
    const digest = active?.sha256 ?? null;
    // After DO eviction/crash, container health cannot attest which bundle was
    // activated. Reboot from the persisted pointer instead of trusting RAM or
    // potentially uncommitted container state. No external I/O under a DO lock.
    if (!container.running || this.hydratedDigest !== digest) {
      this.hydratedDigest = undefined;
      if (container.running) await container.destroy();
      container.start({ image: this.env.NATIVE_IMAGE, instance: INSTANCE,
        enableInternet: this.env.NATIVE_IMAGERY_EGRESS === "live-imagery",
        entrypoint: ["/usr/local/bin/python", "-B", "/opt/vision/server.py"],
        env: { VISION_HOST_SECRET: this.env.VISION_HOST_SECRET,
          VISION_HOST_OPERATOR_SECRET: this.env.VISION_HOST_OPERATOR_SECRET,
          PYTHONPATH: "/opt/vision/client", PYTHONDONTWRITEBYTECODE: "1", PYTHONUNBUFFERED: "1",
          VISION_ORT_THREADS: "1", ORT_NUM_THREADS: "1", OMP_NUM_THREADS: "1", RAYON_NUM_THREADS: "1" } });
      await container.setInactivityTimeout(IDLE_MS);
      let timer, waitingForBoot = true;
      const started = Date.now(), deadline = started + this.startupBudgetMs;
      const bootExit = container.monitor().then(() => {
        throw Error("container_exited_during_startup");
      }, async (error) => {
        if (waitingForBoot) {
          // Native paths, exception text and inherited credentials stay private.
          await this.ctx.storage.put("lastContainerExit", {
            at: Date.now(), exitCode: Number.isInteger(error?.exitCode) && error.exitCode >= 0 && error.exitCode <= 255 ? error.exitCode : null,
          });
        }
        throw Error("container_boot_failed");
      });
      // monitor observes this lifecycle without polling; later normal idle exits
      // are ignored after startup and do not create a spurious failure marker.
      bootExit.catch(() => {});
      try {
        const readiness = (async () => {
          for (let attempt = 0; attempt < 300 && waitingForBoot && Date.now() < deadline; attempt++) {
            try { return await this.checkedHealth(Math.min(2000, Math.max(1, deadline - Date.now()))); }
            catch { if (waitingForBoot) await this.wait(200); }
          }
          throw Error("native_startup_unavailable");
        })();
        readiness.catch(() => {});
        await Promise.race([readiness, bootExit, new Promise((_, reject) => {
          timer = setTimeout(() => reject(Error("native_startup_unavailable")), this.startupBudgetMs);
        })]);
      } catch (error) {
        await container.destroy().catch(() => {});
        throw error;
      } finally {
        waitingForBoot = false;
        clearTimeout(timer);
      }
      const identity = await container.inspect();
      if (!identity || identity.image !== this.env.NATIVE_IMAGE) throw Error("native_image_changed");
      if (active) await this.upload(active);
      this.hydratedDigest = digest;
    }
    await container.setInactivityTimeout(IDLE_MS);
    return this.checkedHealth();
  }

  async active() {
    const value = await this.ctx.storage.get("activeBundle");
    return value === undefined ? null : descriptor(value);
  }

  health() {
    return this.exclusive(async () => {
      const health = await this.ensure(await this.active());
      return Response.json({ ...health, productionQualified: false }, { headers: jsonHeaders });
    });
  }

  status() {
    return this.exclusive(async () => Response.json({ activeBundle: await this.active(),
      lastControlFailure: await this.ctx.storage.get("lastControlFailure") ?? null,
      lastContainerExit: await this.ctx.storage.get("lastContainerExit") ?? null,
      productionQualified: false }, { headers: jsonHeaders }));
  }

  activate(value) {
    return this.exclusive(async () => {
      const candidate = descriptor(value), previous = await this.active();
      await this.ensure(previous);
      if (candidate.sha256 === previous?.sha256 && candidate.bytes === previous.bytes) {
        return Response.json(await this.checkedHealth(), { headers: jsonHeaders });
      }
      try {
        const health = await this.upload(candidate);
        // Persist before acknowledging activation. On an uncertain write,
        // destroy candidate state; the next call resolves the durable pointer.
        await this.ctx.storage.put("activeBundle", candidate);
        this.hydratedDigest = candidate.sha256;
        return Response.json({ ...health, bundleSha256: candidate.sha256 }, { headers: jsonHeaders });
      } catch {
        this.hydratedDigest = undefined;
        await this.recordFailure("operator_activation_failed");
        await this.ctx.container.destroy();
        return failure("operator_activation_failed");
      }
    });
  }

  restart() {
    return this.exclusive(async () => {
      this.config();
      this.hydratedDigest = undefined;
      await this.ctx.container.destroy();
      return Response.json({ stopped: true, activeBundleRetained: (await this.active()) !== null }, { headers: jsonHeaders });
    });
  }

  modelCheck() {
    return this.exclusive(async () => {
      if (this.env.NATIVE_IMAGERY_EGRESS !== "live-imagery") return failure("model_check_egress_disabled");
      await this.ensure(await this.active());
      let timer;
      try {
        // timeout kills the entire native process group, including children.
        // A separate controller deadline destroys the container on uncertainty.
        const completion = (async () => {
          const process = await this.ctx.container.exec(["timeout", "--kill-after=5", "100",
            "/usr/local/bin/python", "-B", "-c", MODEL_CHECK]);
          const [stdout, stderr, exitCode] = await Promise.all([
            bounded(process.stdout, 4096), bounded(process.stderr, 4096), process.exitCode]);
          if (exitCode !== 0 || stderr.byteLength) throw Error("native_model_check_failed");
          return checkedModelReceipt(JSON.parse(new TextDecoder().decode(stdout)), this.env.NATIVE_RUNTIME_SHA256);
        })();
        this.ctx.waitUntil(completion.catch(() => {}));
        const receipt = await Promise.race([completion, new Promise((_, reject) => {
          timer = setTimeout(() => reject(Error("native_model_check_timeout")), this.modelCheckTimeoutMs);
        })]);
        return Response.json(receipt, { headers: jsonHeaders });
      } catch {
        this.hydratedDigest = undefined;
        await this.recordFailure("native_model_check_failed");
        await this.ctx.container.destroy();
        return failure("native_model_check_failed");
      } finally { clearTimeout(timer); }
    });
  }

  service(path, bytes) {
    const search = path === "/search";
    if (!search && !["/audit", "/qualify"].includes(path)) return Promise.resolve(failure("not_found", 404));
    if (!(bytes instanceof Uint8Array) || !bytes.byteLength || bytes.byteLength > (search ? SEARCH_REQUEST : 6 * 1024 * 1024)) {
      return Promise.resolve(failure("invalid_request", 400));
    }
    return this.exclusive(async () => {
      const active = await this.active();
      if (!active) return failure("native_service_unavailable");
      const health = await this.ensure(active);
      if (!(search ? health.searchReady : health.auditReady)) return failure("native_service_unavailable");
      const response = await this.call(path, { body: bytes, maximum: search ? SEARCH_RESPONSE : 65536,
        timeout: search ? 115000 : 55000, statuses: search ? [200] : [200, 422] });
      return new Response(response.bytes, { status: response.status, headers: jsonHeaders });
    });
  }
}
