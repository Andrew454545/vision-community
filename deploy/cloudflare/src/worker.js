const STATUS = {
  operational: false,
  demo: false,
  publicCorpus: false,
  ownerBypass: false,
  r2: "not_created",
  searchCost: 100000,
  counts: {},
  searchBackend: "unprovisioned",
  reason:
    "Workers Free cannot run gated VISION-scale ranked search (10 ms CPU, 128 MB). " +
    "The R2 bucket has not been created. No Google imagery is connected.",
};

function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "content-type": "application/json",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
      "x-frame-options": "DENY",
      "content-security-policy":
        "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'",
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/status" && request.method === "GET") {
      return json(STATUS);
    }
    if (url.pathname.startsWith("/api/")) {
      return json({ error: "control_plane_unprovisioned", ...STATUS }, 503);
    }
    return env.ASSETS.fetch(request);
  },
};
