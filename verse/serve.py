"""Serve Verse locally and open it in the default browser.

    python serve.py            # http://127.0.0.1:8777
    python serve.py --port 9000 --no-browser

Only the Python standard library is used, so this runs anywhere Python 3.8+ is
installed. The app also works from file:// (the canon is shipped as a script,
not fetched), but a server avoids pop-up and module restrictions in some browsers.
"""
import argparse
import functools
import http.server
import io
import os
import re
import socket
import socketserver
import sys
import threading
import urllib.parse
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))

# (src|href)="assets/..." — the only URLs the shell loads by itself.
ASSET_REF = re.compile(rb'((?:src|href)=")(assets/[^"]+)(")')


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".css": "text/css",
        ".html": "text/html",
    }

    def send_head(self):
        # Answer every request with a fresh body. A 304 tells the app window to
        # keep what it cached, and a file edited in the same second it was first
        # fetched looks unmodified — which is how a relaunch ends up showing the
        # previous UI.
        for name in ("If-Modified-Since", "If-None-Match"):
            if name in self.headers:
                del self.headers[name]

        path = self.translate_path(urllib.parse.urlsplit(self.path).path)
        if os.path.isfile(path) and path.lower().endswith((".html", ".htm")):
            return self._send_stamped(path)
        return super().send_head()

    def _send_stamped(self, path):
        """Serve an HTML page with its asset URLs versioned by file mtime.

        The window caches by URL. Versioning the asset URLs is the only thing a
        cache cannot ignore, so an app update is picked up on the next launch
        even though the profile folder (and its cache) is deliberately kept.
        """
        try:
            with open(path, "rb") as fh:
                body = fh.read()
            root = os.path.dirname(path)

            def stamp(match):
                rel = match.group(2).decode("utf-8", "replace")
                target = os.path.join(root, urllib.parse.unquote(rel.split("?")[0]))
                try:
                    version = str(int(os.path.getmtime(target)))
                except OSError:
                    version = "0"
                return match.group(1) + match.group(2) + b"?v=" + version.encode() + match.group(3)

            body = ASSET_REF.sub(stamp, body)
        except OSError:
            self.send_error(404, "File not found")
            return None

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return io.BytesIO(body)

    def end_headers(self):
        # The app window keeps its own disk cache; nothing here should persist.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):  # quiet, one line per request
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def free_port(host, start):
    for port in range(start, start + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((host, port)) != 0:
                return port
    return start


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    port = free_port("127.0.0.1", args.port)
    handler = functools.partial(Handler, directory=ROOT)
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True

    url = f"http://127.0.0.1:{port}/index.html"
    print(f"Verse running at {url}\nPress Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
