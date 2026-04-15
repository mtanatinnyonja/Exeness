#!/usr/bin/env python3
"""
Lanceur principal du robot MT5 local.
Usage:
  python run_bot.py once
  python run_bot.py daemon
  python run_bot.py status
  python run_bot.py detect
  python run_bot.py backtest
"""

import sys
import time
import json
import signal
from datetime import datetime, timezone
from trade_orchestrator import TradeOrchestrator
from mt5_bridge import build_broker
from signal_engine import calculate_signal_score
from settings import CHECK_INTERVAL_MINUTES, MIN_SIGNAL_SCORE
from runtime_db import RuntimeStore


def run_once():
    print(f"\n[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] Démarrage cycle local...")
    agent = TradeOrchestrator()
    agent.run_cycle()
    print("Cycle terminé.\n")


def run_daemon():
    store = RuntimeStore()
    settings = store.get_settings()
    print("🤖 Robot MT5 local démarré")
    print(f"   Intervalle: {settings.get('check_interval_minutes', CHECK_INTERVAL_MINUTES)} minutes")
    print("   Ctrl+C pour arrêter\n")

    agent = TradeOrchestrator()
    running = True

    def handle_stop(sig, frame):
        nonlocal running
        print("\n⛔ Signal arrêt reçu...")
        running = False

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    while running:
        try:
            agent.run_cycle()
        except Exception as e:
            print(f"❌ Erreur cycle: {e}")

        if running:
            settings = store.get_settings()
            interval = int(settings.get('check_interval_minutes', CHECK_INTERVAL_MINUTES))
            print(f"😴 Prochain cycle dans {interval} min...")
            for _ in range(interval * 60):
                if not running:
                    break
                time.sleep(1)

    print("👋 Robot arrêté proprement.")


def show_status():
    agent = TradeOrchestrator(quiet=True)
    print(json.dumps(agent.get_status(), indent=2, default=str, ensure_ascii=False))


def detect_broker():
    broker = build_broker()
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "broker": {
            "name": getattr(broker, "name", "unknown"),
            "connected": getattr(broker, "connected", False),
            "safe_to_trade": getattr(broker, "safe_to_trade", False),
            "status_message": getattr(broker, "status_message", ""),
            "last_error": getattr(broker, "last_error", ""),
        }
    }
    try:
        payload["account"] = broker.get_account_summary()
        if hasattr(broker, "get_active_symbols"):
            payload["active_symbols"] = broker.get_active_symbols()
    except Exception as e:
        payload["account_error"] = str(e)
    print(json.dumps(payload, indent=2, default=str, ensure_ascii=False))


def show_settings():
    broker = build_broker()
    payload = RuntimeStore().get_settings()
    payload["broker"] = getattr(broker, "name", "unknown")
    if hasattr(broker, "list_visible_symbols"):
        try:
            payload["active_symbols_now"] = broker.list_visible_symbols()
        except Exception as e:
            payload["active_symbols_error"] = str(e)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def run_backtest():
    print("🔬 Backtest local en cours...\n")
    broker = build_broker()

    # Dynamique: utilise les symboles visibles dans MT5
    instruments = []
    if hasattr(broker, "list_visible_symbols"):
        instruments = broker.list_visible_symbols()
    if not instruments:
        print("⚠️ Aucun symbole visible dans MT5 pour le backtest")
        return

    for instrument in instruments:
        print(f"=== {instrument} ===")
        try:
            candles = broker.get_candles(instrument, "H1", 300)
            print(f"Données: {len(candles)} bougies H1")

            signals = 0
            buys = 0
            sells = 0
            for i in range(60, len(candles) - 20):
                sig = calculate_signal_score(candles[:i])
                if sig["score"] >= MIN_SIGNAL_SCORE and sig["direction"]:
                    signals += 1
                    if sig["direction"] == "BUY":
                        buys += 1
                    else:
                        sells += 1

            print(f"Signaux détectés: {signals}")
            print(f"  BUY: {buys} | SELL: {sells}")
            freq = signals / max(1, (len(candles) - 80)) * 100
            print(f"  Fréquence: ~{freq:.1f}% des bougies\n")
        except Exception as e:
            print(f"Erreur: {e}\n")


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
