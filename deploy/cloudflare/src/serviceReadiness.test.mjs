import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import test from "node:test";

const scope = { AbortSignal };
runInNewContext(readFileSync(new URL("../../../community/web/service-readiness.js", import.meta.url), "utf8"), scope);
const Readiness = scope.VisionServiceReadiness;
const capabilities = () => ({ version: 1, sceneContributions: {
  ready: true, scope: "audited-new-locations", deviceQualificationRequired: true,
  canaryLocations: 112, verification: "trusted-profile-canary-and-submission-audit",
  model: "vision-four-view-v4", policyId: "approved-policy",
} });

test("unreachable service blocks new processing/search while preserving recovery guidance", () => {
  const readiness = new Readiness();
  assert.match(readiness.message(["scene"]), /Checking/);
  assert.equal(readiness.canContribute(["scene"]), false);
  assert.equal(readiness.canSearch(true), false);
  readiness.update({ operational: true, searchOnSite: true, units: 100000 }, capabilities());
  assert.equal(readiness.canContribute(["scene"]), true);
  readiness.fail();
  assert.equal(readiness.canContribute(["scene"]), false);
  assert.equal(readiness.canSearch(true), false);
  assert.equal(readiness.status.units, 100000);
  assert.match(readiness.message(["scene"]), /browser data/);
  readiness.update({ operational: true, searchOnSite: true }, capabilities());
  assert.equal(readiness.canSearch(), true);
});

test("legacy, malformed and unapproved admission contracts never enable scene commands", () => {
  for (const invalid of [null, {}, { version: "1" }, { version: 2 },
    { version: 1, sceneContributions: { ready: true, scope: "preapproved-locations-only" } }]) {
    const readiness = new Readiness();
    readiness.update({ operational: true }, invalid);
    assert.equal(readiness.canContribute(["scene"]), false);
  }
  for (const [key, invalid] of Object.entries({ ready: "true", scope: "preapproved-locations-only",
    deviceQualificationRequired: false, canaryLocations: 100, verification: "structural-only",
    model: "other-model", policyId: " " })) {
    const receipt = capabilities();
    receipt.sceneContributions[key] = invalid;
    const readiness = new Readiness();
    readiness.update({ operational: true }, receipt);
    assert.equal(readiness.canContribute(["scene"]), false, key);
  }
});

test("object and both never advertise an unqualified portable processing profile", () => {
  const readiness = new Readiness();
  readiness.update({ operational: true, searchOnSite: true }, capabilities());
  assert.equal(readiness.canContribute(["scene"]), true);
  assert.equal(readiness.canContribute(["object"]), false);
  assert.equal(readiness.canContribute(["scene", "object"]), false);
  assert.equal(readiness.canContribute([]), false);
  assert.match(readiness.message(["object"]), /still being validated/);
  readiness.update({ operational: "true", searchOnSite: true }, capabilities());
  assert.equal(readiness.connected, false);
});

test("search outage keeps scene qualification available and permits saved-request recovery", () => {
  const readiness = new Readiness();
  readiness.update({ operational: true, searchOnSite: false }, capabilities());
  assert.equal(readiness.canContribute(["scene"]), true);
  assert.equal(readiness.canSearch(), false);
  assert.equal(readiness.canSearch(true), true);
  assert.match(readiness.message(["scene"]), /unused credits stay saved/);
});

test("capability check bounds the request and safely handles missing endpoints, bad JSON and network errors", async () => {
  let seen;
  const receipt = capabilities();
  const result = await Readiness.capabilities(async (path, options) => {
    seen = { path, options };
    return { ok: true, json: async () => receipt };
  });
  assert.equal(result, receipt);
  assert.equal(seen.path, "/api/capabilities");
  assert.equal(seen.options.cache, "no-store");
  assert.equal(seen.options.credentials, "same-origin");
  assert.ok(seen.options.signal instanceof AbortSignal);
  assert.equal(await Readiness.capabilities(async () => ({ ok: false })), null);
  assert.equal(await Readiness.capabilities(async () => ({ ok: true, json: async () => { throw new SyntaxError(); } })), null);
  assert.equal(await Readiness.capabilities(async () => { throw new TypeError("offline"); }), null);
});
