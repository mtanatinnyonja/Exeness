#!/usr/bin/env python3
"""
Point d'entrée compatible.
Conserve la commande python main.py tout en redirigeant vers le robot local actuel.
"""

import sys
from run_bot import (
    run_once,
    run_daemon,
    show_status,
    detect_broker,
    run_backtest,
    show_settings,
)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"

    if mode == "daemon":
        run_daemon()
    elif mode == "status":
        show_status()
    elif mode == "detect":
        detect_broker()
    elif mode == "backtest":
        run_backtest()
    elif mode == "settings":
        show_settings()
    else:
        run_once()

