#!/usr/bin/env python3
"""
Dashboard web léger pour monitorer l'agent.
Tout le HTML et le Handler sont dans control_panel.py.
Lance avec: python dashboard.py [port]
Accès: http://localhost:8765
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from http.server import ThreadingHTTPServer
from control_panel import Handler


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"🌐 Dashboard: http://localhost:{port}")
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()