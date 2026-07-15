"""HTTP server for the Jarvis web dashboard.

Pure stdlib — no Flask, no dependencies. Serves the dashboard HTML and exposes
JSON API endpoints so the browser can poll state in real-time.

Usage:
    python -m jarvis.serve [--db PATH] [--port PORT]
    python main.py serve [--db PATH] [--port PORT]
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

from .core import State, Monitor, Defaults
from .core.logging import read_events


class JarvisHandler(SimpleHTTPRequestHandler):
    """Routes requests to the dashboard HTML or JSON API."""

    db_path: str = "jarvis_state.db"
    templates_dir: str = ""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "" or path == "/":
            self._serve_dashboard()
        elif path == "/api/status":
            self._serve_status()
        elif path == "/api/tasks":
            self._serve_tasks()
        elif path == "/api/log":
            self._serve_log()
        else:
            self.send_error(404, "Not Found")

    def _serve_dashboard(self):
        html_path = os.path.join(self.templates_dir, "dashboard.html")
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        except FileNotFoundError:
            self.send_error(500, "Dashboard HTML not found")

    def _serve_status(self):
        try:
            s = State(self.db_path)
            monitor = Monitor(Defaults().min_free_ram_mb, Defaults().max_cpu_percent)
            goal = s.get_goal()
            health = monitor.health()
            tasks = s.list_tasks()
            running = [t for t in tasks if t.status.value in ("open", "doing")]
            done = s.done_today()
            failed = s.failed_count()

            # Check hermes status from log
            hermes_running = False
            hermes_launched = False
            events = read_events(os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "jarvis.log"), limit=10)
            for e in reversed(events):
                if e.get("event") == "hermes_launch":
                    hermes_launched = True
                    hermes_running = False
                    break
                if e.get("event") == "hermes_up":
                    hermes_running = True
                    hermes_launched = False
                    break

            data = {
                "cycle": s.get_cycle(),
                "goal": goal.statement if goal else None,
                "health": health,
                "hermes": {
                    "running": hermes_running,
                    "launched": hermes_launched,
                },
                "tasks": {
                    "open": len(running),
                    "done_24h": done,
                    "failed": failed,
                    "cap": Defaults().max_open_tasks,
                },
            }
            s.close()
            self._json_response(data)
        except Exception as e:
            self._json_response({"error": str(e)}, status=500)

    def _serve_tasks(self):
        try:
            s = State(self.db_path)
            tasks = s.list_tasks()
            data = [t.to_dict() for t in tasks]
            s.close()
            self._json_response(data)
        except Exception as e:
            self._json_response({"error": str(e)}, status=500)

    def _serve_log(self):
        try:
            log_path = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "jarvis.log")
            events = read_events(log_path, limit=30)
            self._json_response(events)
        except Exception as e:
            self._json_response({"error": str(e)}, status=500)

    def _json_response(self, data, status=200):
        content = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        # Suppress default request logging to keep terminal clean
        pass


def serve(db_path: str = "jarvis_state.db", port: int = 8080):
    """Start the Jarvis web dashboard server."""
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")

    JarvisHandler.db_path = os.path.abspath(db_path)
    JarvisHandler.templates_dir = templates_dir

    server = HTTPServer(("127.0.0.1", port), JarvisHandler)
    print(f"Jarvis dashboard: http://localhost:{port}")
    print(f"State DB: {os.path.abspath(db_path)}")
    print("Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Jarvis web dashboard server")
    p.add_argument("--db", default="jarvis_state.db", help="path to state DB")
    p.add_argument("--port", type=int, default=8080, help="port to listen on")
    args = p.parse_args()
    serve(args.db, args.port)
