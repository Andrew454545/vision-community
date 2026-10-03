import { createHash, timingSafeEqual } from "node:crypto";
import { bounded, MAX_REQUEST as SEARCH_REQUEST, MAX_RESPONSE as SEARCH_RESPONSE } from "../native-scene-bridge/worker.js";
import { MODEL_CHECK, checkedModelReceipt } from "./model-check.js";
import { checkedBootReceipt } from "./bootstrap.js";
import { LAUNCH_CHECK, checkedLaunchReceipt, stderrClass } from "./launch-check.js";
import { MAIN_CHECK, checkedMainReceipt, checkedMainFailureReceipt } from "./main-check.js";
import { AUDIT_BUDGET_CHECK, checkedAuditBudgetReceipt } from "./audit-budget-check.js";
import { REPEATABILITY_CHECK, checkedRepeatabilityReceipt, checkedRepeatabilityFailure } from "./repeatability-check.js";

export const MAX_BUNDLE = 384 * 1024 * 1024;
const HEX = /^[0-9a-f]{64}$/;
const SEARCH_FAILURES = new Set([
  "search_identity_mismatch", "unsupported_search_lane", "search_request_mismatch",
  "invalid_search_query", "unsupported_query_mode", "road_authority_unavailable",
  "search_engine_busy", "native_search_runtime_update_required", "native_search_timeout",
  "native_search_failed", "native_output_limit", "incomplete_native_search",
  "invalid_native_search", "native_pose_mismatch", "native_filter_mismatch",
  "search_candidate_budget_exceeded", "search_response_limit", "runtime_changed",
  "adapter_changed", "engine_source_changed", "runtime_file_changed",
  "native_mount_changed", "native_model_metadata_changed",
]);
const INSTANCE = Object.freeze({ vcpu: 1, memoryMib: 3072, diskMb: 8000 });
const IDLE_MS = 180000;
const CONTROL_FAILURES = new Set(["native_configuration_unavailable", "native_runtime_identity_changed",
  "native_boot_failed", "native_boot_diagnostic_invalid",
  "native_startup_unavailable", "native_image_changed", "container_boot_failed", "container_exited_during_startup",
  "native_response_unavailable", "native_response_limit", "native_response_length",
  "operator_bundle_missing_or_changed", "operator_bundle_size_changed", "operator_bundle_changed",
  "operator_activation_unavailable", "native_transport_unavailable", "native_request_timeout",
  "native_inactivity_timeout_unavailable", "native_recovery_stop_failed"]);
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

async function responseBytes(response, maximum, statuses = [200], search = false) {
  if (!statuses.includes(response.status)
      || response.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
    const error = Error("native_response_unavailable");
    if (search && response.status === 503
        && response.headers.get("content-type")?.split(";")[0].trim().toLowerCase() === "application/json") {
      try {
        const value = JSON.parse(new TextDecoder().decode(await bounded(response.body, 512)));
        if (value && Object.keys(value).join(",") === "error" && SEARCH_FAILURES.has(value.error)) {
          error.searchFailureCode = value.error;
        }
      } catch { /* Untrusted, oversized or malformed diagnostics stay redacted. */ }
    } else await response.body?.cancel();
    throw error;
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
    this.auditBudgetCheckTimeoutMs = options.auditBudgetCheckTimeoutMs ?? 65000;
    this.repeatabilityCheckTimeoutMs = options.repeatabilityCheckTimeoutMs ?? 310000;
    this.startupBudgetMs = options.startupBudgetMs ?? 60000;
    this.launchCheckTimeoutMs = options.launchCheckTimeoutMs ?? 45000;
    this.now = options.now ?? Date.now;
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
    finally {
      try {
        if (this.ctx.container?.running) await this.armIdle();
        else await this.clearIdle();
      } catch {
        this.hydratedDigest = undefined;
        await this.recordFailure("native_idle_guard_failed");
        await this.ctx.container?.destroy().catch(() => {});
        return failure("native_idle_guard_failed");
      } finally { this.busy = false; }
    }
  }

  async armIdle() {
    const deadline = this.now() + IDLE_MS;
    await this.ctx.storage.put("idleDeadline", deadline);
    await this.ctx.storage.setAlarm(deadline);
  }

  async clearIdle() {
    await this.ctx.storage.delete("idleDeadline");
    await this.ctx.storage.deleteAlarm();
  }

  async alarm() {
    // monitor() can keep a DO in memory beyond its platform inactivity timer.
    // A durable alarm enforces idle shutdown without polling or losing the seal.
    if (this.busy) {
      await this.ctx.storage.setAlarm(this.now() + 30000);
      return;
    }
    this.busy = true;
    try {
      if (!this.ctx.container?.running) { await this.clearIdle(); return; }
      const deadline = await this.ctx.storage.get("idleDeadline");
      if (!Number.isSafeInteger(deadline)) throw Error("native_idle_guard_failed");
      if (this.now() < deadline) { await this.ctx.storage.setAlarm(deadline); return; }
      this.hydratedDigest = undefined;
      await this.ctx.container.destroy();
      await this.clearIdle();
    } catch {
      this.hydratedDigest = undefined;
      await this.recordFailure("native_idle_guard_failed");
      // A failed destroy rejects the alarm so Cloudflare retries it.
      await this.ctx.container?.destroy();
      await this.clearIdle();
    } finally { this.busy = false; }
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
      return { status: response.status, bytes: await responseBytes(response, maximum, statuses, path === "/search") };
    } catch (error) {
      // Retain only a fixed classification, never transport exception text.
      if (CONTROL_FAILURES.has(error?.message)) throw error;
      throw Error(abort.signal.aborted ? "native_request_timeout" : "native_transport_unavailable");
    } finally { clearTimeout(timer); }
  }

  async checkedHealth(timeout = 20000) {
    const { bytes } = await this.call("/health", { timeout });
    const health = JSON.parse(new TextDecoder().decode(bytes));
    if (health.status === "native_boot_unavailable") {
      const diagnostic = checkedBootReceipt(health);
      await this.ctx.storage.put("lastBootFailure", { ...diagnostic, at: Date.now() });
      throw Error("native_boot_failed");
    }
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
        // Use the immutable image's server directly. The offline exec probe
        // separately retains classified startup diagnostics; no inline Python
        // program is transported through the PID1 entrypoint configuration.
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
            catch (error) {
              if (["native_boot_failed", "native_boot_diagnostic_invalid"].includes(error?.message)) throw error;
              if (waitingForBoot) await this.wait(200);
            }
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
    try { await container.setInactivityTimeout(IDLE_MS); }
    catch { throw Error("native_inactivity_timeout_unavailable"); }
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
      lastBootFailure: await this.ctx.storage.get("lastBootFailure") ?? null,
      lastLaunchFailure: await this.ctx.storage.get("lastLaunchFailure") ?? null,
      lastRepeatabilityFailure: await this.ctx.storage.get("lastRepeatabilityFailure") ?? null,
      lastSearchFailure: await this.ctx.storage.get("lastSearchFailure") ?? null,
      productionQualified: false }, { headers: jsonHeaders }));
  }

  activate(value) {
    return this.exclusive(async () => {
      const candidate = descriptor(value), previous = await this.active();
      if (candidate.sha256 === previous?.sha256 && candidate.bytes === previous.bytes) {
        await this.ensure(previous);
        return Response.json(await this.checkedHealth(), { headers: jsonHeaders });
      }
      // A new image/helper policy may be unable to load the previous seal.
      // Boot the independently pinned runtime before loading the replacement;
      // retain the previous durable pointer until the new bundle fully validates.
      await this.ensure(null);
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

  mainCheck() { return this.launchCheck(true); }

  launchCheck(mainProgram = false) {
    return this.exclusive(async () => {
      // Refuse any sealed workload before stopping or starting compute.
      if (await this.active()) return failure("sealed_bundle_already_active", 409);
      const container = this.config();
      this.hydratedDigest = undefined;
      let timer, accepting = true, stage = "container_launch", exitCode = null, errorClass = null;
      const code = value => Number.isInteger(value) && value >= 0 && value <= 255 ? value : null;
      try {
        const deadline = new Promise((_, reject) => {
          timer = setTimeout(() => { stage = "deadline"; reject(Error("native_launch_check_failed")); }, this.launchCheckTimeoutMs);
        });
        deadline.catch(() => {});
        if (container.running) await Promise.race([container.destroy(), deadline]);
        container.start({ image: this.env.NATIVE_IMAGE, instance: INSTANCE,
          enableInternet: false, entrypoint: ["/usr/bin/sleep", "120"] });
        await Promise.race([container.setInactivityTimeout(IDLE_MS), deadline]);
        const bootExit = container.monitor().then(() => { throw Error("container_launch_failed"); }, error => {
          exitCode = code(error?.exitCode);
          throw Error("container_launch_failed");
        });
        bootExit.catch(() => {});
        const completion = (async () => {
          const process = await container.exec(["/usr/local/bin/python", "-B", "-c", mainProgram ? MAIN_CHECK : LAUNCH_CHECK], {
            env: { PYTHONPATH: "/opt/vision/client", PYTHONDONTWRITEBYTECODE: "1", PYTHONUNBUFFERED: "1",
              ...(mainProgram ? { VISION_HOST_SECRET: this.env.VISION_HOST_SECRET,
                VISION_HOST_OPERATOR_SECRET: this.env.VISION_HOST_OPERATOR_SECRET,
                VISION_ORT_THREADS: "1", ORT_NUM_THREADS: "1", OMP_NUM_THREADS: "1", RAYON_NUM_THREADS: "1" } : {}) },
          });
          stage = "python_process";
          const [stdout, stderr, result] = await Promise.all([
            bounded(process.stdout, 4096), bounded(process.stderr, 4096), process.exitCode]);
          exitCode = code(result);
          errorClass = stderrClass(stderr);
          let parsed;
          try { parsed = JSON.parse(new TextDecoder().decode(stdout)); } catch { /* Retain only bounded classes. */ }
          if (!accepting) throw Error("native_launch_check_failed");
          if (parsed?.status === "native_boot_unavailable") {
            const measurements = mainProgram ? checkedMainFailureReceipt(parsed) : {};
            const { childExitCode, stdoutBytes, stderrBytes, serverLine, ...boot } = parsed;
            const diagnostic = checkedBootReceipt(mainProgram ? boot : parsed);
            await this.ctx.storage.put("lastBootFailure", { ...diagnostic, ...measurements, at: Date.now() });
            stage = "runtime_identity";
          }
          if (result !== 0 || stderr.byteLength) throw Error("native_launch_check_failed");
          const identity = await container.inspect();
          if (!identity || identity.image !== this.env.NATIVE_IMAGE) throw Error("native_launch_check_failed");
          return mainProgram ? checkedMainReceipt(parsed, this.env.NATIVE_RUNTIME_SHA256)
            : checkedLaunchReceipt(parsed, this.env.NATIVE_RUNTIME_SHA256);
        })();
        this.ctx.waitUntil(completion.catch(() => {}));
        const receipt = await Promise.race([completion, bootExit, deadline]);
        return Response.json(receipt, { headers: jsonHeaders });
      } catch (error) {
        if (error?.message === "container_launch_failed") stage = "container_launch";
        await this.ctx.storage.put("lastLaunchFailure", { stage, exitCode, errorClass, at: Date.now() });
        await this.recordFailure("native_launch_check_failed");
        return failure("native_launch_check_failed");
      } finally {
        accepting = false;
        clearTimeout(timer);
        await container.destroy();
      }
    });
  }

  auditBudgetCheck() { return this.modelCheck("audit"); }
  repeatabilityCheck() { return this.modelCheck("repeatability"); }

  modelCheck(kind = "model") {
    return this.exclusive(async () => {
      // Diagnostics may never stop, hydrate or compete with sealed work.
      if (await this.active()) return failure("sealed_bundle_already_active", 409);
      if (this.env.NATIVE_IMAGERY_EGRESS !== "live-imagery") return failure("model_check_egress_disabled");
      const diagnostic = kind === "audit" ? { program: AUDIT_BUDGET_CHECK, validate: checkedAuditBudgetReceipt,
        seconds: "60", deadline: this.auditBudgetCheckTimeoutMs, failed: "native_audit_budget_check_failed" }
        : kind === "repeatability" ? { program: REPEATABILITY_CHECK, validate: checkedRepeatabilityReceipt,
          seconds: "300", deadline: this.repeatabilityCheckTimeoutMs, failed: "native_repeatability_check_failed" }
          : { program: MODEL_CHECK, validate: checkedModelReceipt,
            seconds: "100", deadline: this.modelCheckTimeoutMs, failed: "native_model_check_failed" };
      const { program, validate, seconds, deadline, failed } = diagnostic;
      let timer;
      try {
        await this.ensure(null);
        // timeout kills the entire native process group, including children.
        // A separate controller deadline destroys the container on uncertainty.
        const completion = (async () => {
          const process = await this.ctx.container.exec(["timeout", "--kill-after=5", seconds,
            "/usr/local/bin/python", "-B", "-c", program]);
          const [stdout, stderr, exitCode] = await Promise.all([
            bounded(process.stdout, 4096), bounded(process.stderr, 4096), process.exitCode]);
          if (kind === "repeatability" && exitCode !== 0 && !stderr.byteLength) {
            const diagnostic = checkedRepeatabilityFailure(JSON.parse(new TextDecoder().decode(stdout)));
            await this.ctx.storage.put("lastRepeatabilityFailure", { ...diagnostic, at: Date.now() });
          }
          if (exitCode !== 0 || stderr.byteLength) throw Error(failed);
          return validate(JSON.parse(new TextDecoder().decode(stdout)), this.env.NATIVE_RUNTIME_SHA256);
        })();
        this.ctx.waitUntil(completion.catch(() => {}));
        const receipt = await Promise.race([completion, new Promise((_, reject) => {
          timer = setTimeout(() => reject(Error(failed)), deadline);
        })]);
        return Response.json(receipt, { headers: jsonHeaders });
      } catch {
        await this.recordFailure(failed);
        return failure(failed);
      } finally {
        clearTimeout(timer);
        this.hydratedDigest = undefined;
        // Always stop diagnostic compute, including successful and failed boot.
        await this.ctx.container.destroy();
      }
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
      try {
        const health = await this.ensure(active);
        if (!(search ? health.searchReady : health.auditReady)) return failure("native_service_unavailable");
        const response = await this.call(path, { body: bytes, maximum: search ? SEARCH_RESPONSE : 65536,
          timeout: search ? 115000 : 55000, statuses: search ? [200] : [200, 422] });
        return new Response(response.bytes, { status: response.status, headers: jsonHeaders });
      } catch (error) {
        // Do not retry an uncertain inference request in the same call. Stop
        // its compute and recover the unchanged durable seal on the next call.
        // A failed connection must not leave cached readiness stuck forever.
        this.hydratedDigest = undefined;
        if (search && SEARCH_FAILURES.has(error?.searchFailureCode)) {
          try { await this.ctx.storage.put("lastSearchFailure", { code: error.searchFailureCode, at: Date.now() }); }
          catch { /* Missing diagnostics never grant readiness or spend credit. */ }
        }
        try { await this.ctx.container.destroy(); }
        catch { throw Error("native_recovery_stop_failed"); }
        throw error;
      }
    });
  }
}
