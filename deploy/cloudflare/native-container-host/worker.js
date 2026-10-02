import { DurableObject, WorkerEntrypoint } from "cloudflare:workers";
import { NativeController, authorized, descriptor, failure, requestBytes } from "./controller.js";
import { MAX_REQUEST } from "../native-scene-bridge/worker.js";

const INSTANCE_NAME = "scene-cpu1";

// Reuses the existing private staging container namespace.
export class NativeHostProbe extends DurableObject {
  constructor(ctx, env) { super(ctx, env); this.controller = new NativeController(ctx, env); }
  health() { return this.controller.health(); }
  status() { return this.controller.status(); }
  activate(bundle) { return this.controller.activate(bundle); }
  restart() { return this.controller.restart(); }
  modelCheck() { return this.controller.modelCheck(); }
  service(path, bytes) { return this.controller.service(path, bytes); }
}

async function privateService(request, env, paths, maximum) {
  const path = new URL(request.url).pathname;
  if (request.method !== "POST" || !paths.includes(path)) return failure("not_found", 404);
  let bytes;
  try { bytes = await requestBytes(request, maximum); }
  catch { return failure("invalid_request", 400); }
  try { return await env.NATIVE_HOST.getByName(INSTANCE_NAME).service(path, bytes); }
  catch { return failure(); }
}

// Only explicitly named private service bindings can reach native inference.
// The default HTTP handler never dispatches public /search, /audit or /qualify.
export class NativeSceneSearch extends WorkerEntrypoint {
  fetch(request) { return privateService(request, this.env, ["/search"], MAX_REQUEST); }
}
export class NativeSceneVerification extends WorkerEntrypoint {
  fetch(request) { return privateService(request, this.env, ["/audit", "/qualify"], 6 * 1024 * 1024); }
}

async function operatorRequest(request, env, privateBinding = false) {
    const path = new URL(request.url).pathname;
    if (![["GET", "/health"], ["GET", "/operator/status"], ["POST", "/operator/bundle"],
      ["POST", "/operator/restart"], ["POST", "/operator/model-check"]].some(([method, route]) => request.method === method && path === route)) {
      return failure("not_found", 404);
    }
    if (!privateBinding && !authorized(request, env.HOST_OPERATOR_INGRESS_SECRET ?? env.PROBE_SECRET)) return failure("unauthorized", 401);
    let bundle;
    if (path === "/operator/bundle") {
      try { bundle = descriptor(JSON.parse(new TextDecoder().decode(await requestBytes(request, 4096)))); }
      catch { return failure("invalid_operator_descriptor", 400); }
    }
    try {
      const host = env.NATIVE_HOST.getByName(INSTANCE_NAME);
      if (path === "/health") return await host.health();
      if (path === "/operator/status") return await host.status();
      if (path === "/operator/restart") return await host.restart();
      if (path === "/operator/model-check") return await host.modelCheck();
      return await host.activate(bundle);
    } catch { return failure(); }
}

// Account-private operator binding for one-time checks without a public URL.
export class NativeSceneOperator extends WorkerEntrypoint {
  fetch(request) { return operatorRequest(request, this.env, true); }
}

export default { fetch(request, env) { return operatorRequest(request, env); } };
