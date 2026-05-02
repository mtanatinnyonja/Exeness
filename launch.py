#!/usr/bin/env python3
"""
Lanceur principal — démarre le dashboard ET les agents IA en parallèle.

Usage:
    python launch.py          (dashboard port 8765 par défaut)
    python launch.py 9000     (dashboard sur port 9000)

Accès dashboard: http://localhost:8765
Arrêt: Ctrl+C
"""

import asyncio
import sys
import os
import threading
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DASHBOARD_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765


def start_dashboard():
    """Lance le dashboard dans un thread séparé."""
    from http.server import ThreadingHTTPServer
    from control_panel import Handler

    server = ThreadingHTTPServer(("0.0.0.0", DASHBOARD_PORT), Handler)
    print(f"🌐  Dashboard  →  http://localhost:{DASHBOARD_PORT}")
    server.serve_forever()


async def start_agents():
    """Lance tous les agents IA."""
    from agents_runtime import AgentsRuntime

    runtime = AgentsRuntime()

    loop = asyncio.get_running_loop()

    def _shutdown(signum, frame):
        print("\n⏹  Arrêt demandé...")
        loop.create_task(runtime.stop())

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    await runtime.start()


def main():
    print("\n" + "=" * 60)
    print("  ⚡  EXENESS — Système Multi-Agents")
    print("=" * 60)

    # Dashboard dans un thread daemon
    dashboard_thread = threading.Thread(target=start_dashboard, daemon=True)
    dashboard_thread.start()

    # Agents en asyncio
    try:
        asyncio.run(start_agents())
    except KeyboardInterrupt:
        print("\n✅  Système arrêté proprement.")


if __name__ == "__main__":
    main()
