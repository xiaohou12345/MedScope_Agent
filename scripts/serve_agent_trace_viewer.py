from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DEFAULT_ROOT = Path("output/fake/onfh_xray_six_experiments_20260611")
DEFAULT_VIEWER = "/trace_viewer_v2.html"


class TraceViewerHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self) -> None:
        if self.path in {"", "/"}:
            self.path = DEFAULT_VIEWER
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self.path in {"", "/"}:
            self.path = DEFAULT_VIEWER
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        super().do_HEAD()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve MedScope trace viewer files.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"viewer root does not exist: {root}")
    handler = partial(TraceViewerHandler, directory=str(root))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {root} at http://{args.host}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
