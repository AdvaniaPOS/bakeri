from __future__ import annotations

import argparse
import http.server
import shutil
import socketserver
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlsplit


class FrontendProxyHandler(http.server.SimpleHTTPRequestHandler):
    dist_root: Path
    api_base: str

    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def _proxy(self) -> None:
        target = f"{self.api_base}{self.path}"
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length) if content_length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "connection", "content-length", "accept-encoding"}
        }
        request = urllib.request.Request(target, data=body, headers=headers, method=self.command)

        try:
            with urllib.request.urlopen(request) as response:
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() in {"transfer-encoding", "connection"}:
                        continue
                    self.send_header(key, value)
                self.end_headers()
                if self.command != "HEAD":
                    shutil.copyfileobj(response, self.wfile)
        except urllib.error.HTTPError as exc:
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() in {"transfer-encoding", "connection"}:
                    continue
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(exc.read())
        except Exception as exc:  # pragma: no cover - dev helper
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(f"Proxy error: {exc}".encode("utf-8"))

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy()
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy()
            return
        super().do_HEAD()

    def do_POST(self) -> None:
        self._proxy()

    def do_PUT(self) -> None:
        self._proxy()

    def do_PATCH(self) -> None:
        self._proxy()

    def do_DELETE(self) -> None:
        self._proxy()

    def do_OPTIONS(self) -> None:
        self._proxy()

    def translate_path(self, path: str) -> str:
        clean_path = unquote(urlsplit(path).path)
        candidate = self.dist_root / clean_path.lstrip("/")
        if clean_path in ("", "/") or not candidate.exists():
            return str(self.dist_root / "index.html")
        return str(candidate)

    def log_message(self, format: str, *args) -> None:
        print(format % args)


class ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--dist-root",
        default=str(Path(__file__).resolve().parents[1] / "frontend" / "dist"),
    )
    args = parser.parse_args()

    dist_root = Path(args.dist_root).resolve()
    if not dist_root.exists():
        raise SystemExit(f"Missing dist directory: {dist_root}")

    handler = FrontendProxyHandler
    handler.dist_root = dist_root
    handler.api_base = args.api_base.rstrip("/")

    with ThreadingTCPServer((args.host, args.port), lambda *a, **kw: handler(*a, directory=str(dist_root), **kw)) as httpd:
        print(f"Frontend proxy running on http://{args.host}:{args.port}")
        print(f"Serving static files from {dist_root}")
        print(f"Proxying /api/* to {handler.api_base}")
        httpd.serve_forever()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
