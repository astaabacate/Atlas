"""
Servidor HTTP leve para healthcheck (/health).
Utiliza apenas a stdlib (http.server) em uma thread daemon.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

logger = logging.getLogger("farol.health")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/health", "/", "/healthz"):
            payload = json.dumps({"status": "ok", "bot": "farol"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:
        # Silenciar logs normais para não poluir console
        return


def start_health_server(port: int) -> ThreadingHTTPServer:
    """Inicia o servidor de health check em uma thread daemon de fundo."""
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    t = Thread(target=server.serve_forever, daemon=True, name="health-server")
    t.start()
    logger.info("Servidor de healthcheck iniciado na porta %d", port)
    return server
