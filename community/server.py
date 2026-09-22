"""Loopback-only HTTP demo. Never expose this prototype to the public internet."""

from __future__ import annotations

import argparse
import base64
import json
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .service import CommunityService, ServiceError
from .source import SourceError


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
STATIC = {
    "/": (WEB / "index.html", "text/html; charset=utf-8"),
    "/app.js": (WEB / "app.js", "text/javascript; charset=utf-8"),
    "/visual.js": (WEB / "visual.js", "text/javascript; charset=utf-8"),
    "/style.css": (WEB / "style.css", "text/css; charset=utf-8"),
    "/sample-query.json": (WEB / "sample-query.json", "application/json"),
    "/prototype-query.json": (WEB / "prototype-query.json", "application/json"),
    "/robots.txt": (WEB / "robots.txt", "text/plain; charset=utf-8"),
}


def handler_for(service: CommunityService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "VisionCommunityDemo/0.1"

        def log_message(self, format, *args):
            # Do not log bearer tokens or query strings.
            pass

        def _send(self, status: int, body: bytes, content_type: str, *, cookie: str | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            if cookie is not None:
                self.send_header("Set-Cookie", cookie)
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self' https://map-making.app; img-src 'self'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, value: dict, *, cookie: str | None = None):
            self._send(
                status, json.dumps(value, separators=(",", ":")).encode(),
                "application/json", cookie=cookie,
            )

        def _account(self) -> str:
            header = self.headers.get("Authorization", "")
            if header.startswith("Bearer "):
                return service.account_for_token(header[7:])
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
            except Exception:
                raise ServiceError("unauthorized", 401)
            session = cookies.get("vision_session")
            if session is None:
                raise ServiceError("unauthorized", 401)
            return service.account_for_token(session.value)

        def _same_origin(self):
            origin = self.headers.get("Origin")
            if origin is not None:
                parsed = urlsplit(origin)
                if parsed.scheme not in ("http", "https") or parsed.netloc != self.headers.get("Host"):
                    raise ServiceError("cross_origin_request", 403)

        def _input(self) -> dict:
            if self.headers.get_content_type() != "application/json":
                raise ServiceError("json_required", 415)
            raw_length = self.headers.get("Content-Length", "")
            try:
                length = int(raw_length)
            except ValueError:
                raise ServiceError("invalid_json")
            if not 0 <= length <= 1_000_000:
                raise ServiceError("request_too_large", 413)
            try:
                data = json.loads(self.rfile.read(length))
            except (UnicodeError, json.JSONDecodeError):
                raise ServiceError("invalid_json")
            if not isinstance(data, dict):
                raise ServiceError("invalid_json")
            return data

        def do_GET(self):
            parsed = urlsplit(self.path)
            route = parsed.path
            try:
                if route == "/api/status":
                    return self._json(200, service.status())
                if route == "/api/me":
                    query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
                    return self._json(200, service.status(self._account(), lite=query.get("lite") == "1"))
                if route == "/api/views":
                    self._same_origin()
                    query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
                    return self._json(200, service.views(self._account(), query))
                if route == "/api/published-snapshot":
                    self._same_origin()
                    query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
                    after = 0
                    limit = 250
                    try:
                        after = int(query.get("after") or 0)
                        limit = int(query.get("limit") or 250)
                    except ValueError:
                        raise ServiceError("invalid_json")
                    return self._json(
                        200,
                        service.published_snapshot(
                            self._account(),
                            search_id=query.get("searchId") or "",
                            lane=query.get("lane") or "scene",
                            after=after,
                            limit=limit,
                        ),
                    )
                if route == "/api/index-manifest":
                    self._same_origin()
                    query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
                    return self._json(
                        200,
                        service.index_manifest(
                            self._account(),
                            search_id=query.get("searchId") or "",
                            lane=query.get("lane") or "scene",
                        ),
                    )
                static = STATIC.get(route)
                if static is None:
                    raise ServiceError("not_found", 404)
                return self._send(200, static[0].read_bytes(), static[1])
            except ServiceError as error:
                self._json(error.status, {"error": error.code})

        def do_POST(self):
            route = urlsplit(self.path).path
            try:
                self._same_origin()
                data = self._input()
                if route == "/api/accounts":
                    account = service.create_account()
                    session_cookie = (
                        f"vision_session={account['token']}; HttpOnly; SameSite=Strict; Path=/"
                    )
                    return self._json(
                        201,
                        {"accountId": account["accountId"], "recoveryCode": account["recoveryCode"]},
                        cookie=session_cookie,
                    )
                if route == "/api/recovery":
                    account = service.recover_account(data.get("recoveryCode"))
                    session_cookie = (
                        f"vision_session={account['token']}; HttpOnly; SameSite=Strict; Path=/"
                    )
                    return self._json(200, {"accountId": account["accountId"]}, cookie=session_cookie)
                account_id = self._account()
                if route == "/api/leases/release":
                    return self._json(
                        200,
                        service.release_lease(account_id, data.get("leaseId"), skip=data.get("skip") is True),
                    )
                if route == "/api/leases/renew":
                    return self._json(
                        200,
                        service.renew_lease(account_id, data.get("leaseId")),
                    )
                if route == "/api/leases":
                    return self._json(
                        200,
                        service.lease(
                            account_id,
                            data.get("lane"),
                            data.get("count"),
                            pace=data.get("pace"),
                            client=data.get("client") if data.get("client") in {"browser", "cli"} else None,
                            part=data.get("part"),
                        ),
                    )
                if route == "/api/submissions":
                    return self._json(
                        200,
                        service.submit(
                            account_id,
                            data.get("leaseId"),
                            data.get("outputs"),
                            object_index=data.get("objectIndex") if isinstance(data.get("objectIndex"), dict) else None,
                        ),
                    )
                if route == "/api/searches":
                    query_image = data.get("queryImage")
                    query_faces = None
                    if isinstance(query_image, str):
                        try:
                            query_faces = base64.b64decode(query_image)
                        except (ValueError, TypeError):
                            raise ServiceError("invalid_query")
                    query_map = data.get("queryMap") if isinstance(data.get("queryMap"), dict) else None
                    exclude_map = data.get("excludeMap") if isinstance(data.get("excludeMap"), (dict, list)) else None
                    return self._json(
                        200,
                        service.search(
                            account_id,
                            data.get("query"),
                            data.get("idempotencyKey"),
                            query_faces=query_faces,
                            query_map=query_map,
                            lane=data.get("lane") or "scene",
                            result_count=data.get("resultCount") if type(data.get("resultCount")) is int else 200,
                            max_per_country=data.get("maxPerCountry") if type(data.get("maxPerCountry")) is int else 25,
                            output_name=data.get("outputName") if isinstance(data.get("outputName"), str) else None,
                            country_filter_mode=data.get("countryFilterMode") if isinstance(data.get("countryFilterMode"), str) else "all",
                            countries=data.get("countries") if isinstance(data.get("countries"), list) else [],
                            camera_generations=data.get("cameraGenerations") if isinstance(data.get("cameraGenerations"), list) else [],
                            view_direction=data.get("viewDirection") if isinstance(data.get("viewDirection"), str) else None,
                            exclude_map=exclude_map,
                            execute=data.get("execute") if isinstance(data.get("execute"), str) else None,
                            prompt=data.get("prompt") if isinstance(data.get("prompt"), str) else None,
                            description_weight=data.get("descriptionWeight") if type(data.get("descriptionWeight")) is int else None,
                        ),
                    )
                raise ServiceError("not_found", 404)
            except ServiceError as error:
                self._json(error.status, {"error": error.code})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="synthetic fixture demo")
    parser.add_argument("--visual", action="store_true", help="local visual self-test; invented imagery")
    parser.add_argument("--metadata", action="store_true", help="pano-metadata catalog; no imagery stored")
    parser.add_argument("--prototype", action="store_true", help="usable VISION-like prototype (search costs 4)")
    parser.add_argument("--db", type=Path, default=ROOT / ".data" / "demo.sqlite")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    chosen = sum(bool(flag) for flag in (args.demo, args.visual, args.metadata, args.prototype))
    if chosen != 1:
        parser.error("choose exactly one of --demo, --visual, --metadata, or --prototype")
    search_cost = 4 if args.prototype else 100_000
    if args.demo:
        search_cost = 4
    # --prototype and --demo are loopback-only. The public Worker is always 100,000.
    service = CommunityService(
        args.db,
        artifacts=args.db.parent / "artifacts",
        segment_capacity=1_000,
        search_cost=search_cost,
        operational=args.prototype,
    )
    if args.demo:
        fixture = json.loads((ROOT / "demo_catalog.json").read_text(encoding="utf-8"))
        if fixture.get("rights") != "synthetic-test-data":
            parser.error("demo fixture rights marker is missing")
        service.import_synthetic(fixture["locations"])
        label = "synthetic demo"
    elif args.visual:
        catalog = json.loads((ROOT / "visual_catalog.json").read_text(encoding="utf-8"))
        try:
            service.import_jobs(catalog)
        except (ServiceError, SourceError) as error:
            parser.error(str(error))
        label = "visual self-test (invented pixels, not stored)"
    elif args.prototype:
        catalog = json.loads((ROOT / "prototype_catalog.json").read_text(encoding="utf-8"))
        try:
            service.import_jobs(catalog)
        except (ServiceError, SourceError) as error:
            parser.error(str(error))
        label = "VISION-like prototype (search costs 4)"
    else:
        catalog = json.loads((ROOT / "street_catalog.json").read_text(encoding="utf-8"))
        try:
            service.import_jobs(catalog)
        except (ServiceError, SourceError) as error:
            parser.error(str(error))
        label = "metadata catalog (pano IDs + pose; no imagery stored)"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(service))
    print(f"VISION community {label}: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
