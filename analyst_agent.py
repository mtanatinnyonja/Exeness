"""
Agent Analyste — Lit le marché, identifie les setups, envoie des signaux.
Tourne en boucle autonome, indépendant de tout orchestrateur.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from agent_framework import Agent, get_message_bus
from mt5_bridge import build_broker
from signal_engine import calculate_signal_score, calculate_mtf_signal
from smart_strategies import build_strategies_context, get_session_score
from market_context import analyze_market_context
from learning_store import AgentMemory
from settings import PRIMARY_TIMEFRAME, CONFIRM_TIMEFRAME, INSTRUMENTS
from runtime_db import RuntimeStore

_DATA_DIR = Path("data")
_SCAN_FILE = _DATA_DIR / "scan_results.json"
_HB_FILE = _DATA_DIR / "agents_heartbeat.json"


class AnalystAgent(Agent):
    """Analyste autonome — Lit marché en continu, publie signaux."""
    
    def __init__(self, instruments: Optional[List[str]] = None):
        super().__init__("AnalystAgent")
        self.broker = build_broker()
        self.memory = AgentMemory()
        self.store = RuntimeStore()
        self._instruments_override = instruments  # si passé manuellement
        self.cycle_count = 0
        self.last_analysis = {}  # instrument -> timestamp dernière analyse
        self.min_broadcast_score = 3

    def _get_instruments(self) -> List[str]:
        """Lit les paires depuis les paramètres du dashboard (preferred_symbols)."""
        settings = self.store.get_settings()
        pref_raw = settings.get("preferred_symbols", "")
        if pref_raw:
            raw_str = str(pref_raw).strip().strip("[]").replace("'", "").replace('"', "")
            pairs = [s.strip() for s in raw_str.split(",") if s.strip()]
            if pairs:
                return pairs
        return self._instruments_override or INSTRUMENTS or ["EURUSDm", "XAUUSDm", "BTCUSDm"]
    
    async def on_startup(self):
        """Initialisation."""
        instruments = self._get_instruments()
        self.log("INFO", f"Démarré. Instruments: {instruments}")
        await self.bus.subscribe(self.name, ["start_analysis", "market_tick"])
    
    async def run(self):
        """Boucle autonome — analyse le marché en continu."""
        _DATA_DIR.mkdir(exist_ok=True)
        while self.running:
            self.cycle_count += 1
            instruments = self._get_instruments()  # relit les settings à chaque cycle
            candidates = []
            rejected = []
            trending = []

            # Analyser chaque instrument en rotation
            for instrument in instruments:
                result = await self._analyze_instrument(instrument)
                if result:
                    if result.get("signal_direction") in ("BUY", "SELL"):
                        candidates.append(result)
                        if result.get("score", 0) >= 4:
                            trending.append({
                                "symbol": instrument,
                                "direction": result["signal_direction"],
                                "trending_score": result["score"],
                            })
                    else:
                        rejected.append({"symbol": instrument, "reason": result.get("reason", "no_signal")})
                await asyncio.sleep(0.1)  # Anti-spam

            # Écrire les résultats du scan
            self._write_scan_results(candidates, rejected, trending)
            # Heartbeat (via base class)
            self.write_heartbeat({"cycle": self.cycle_count})

            # Attendre 30s avant prochain cycle
            await asyncio.sleep(30)
    
    async def _analyze_instrument(self, instrument: str) -> Optional[Dict]:
        """Analyse un instrument et envoie un signal. Retourne le résultat."""
        try:
            # Récupérer les données
            candles_h1 = self.broker.get_candles(instrument, PRIMARY_TIMEFRAME, 100)
            if len(candles_h1) < 20:
                return {"symbol": instrument, "reason": "not_enough_data"}

            candles_d1 = []
            try:
                candles_d1 = self.broker.get_candles(instrument, "D1", 100)
            except Exception as e:
                self.log("WARN", f"{instrument}: D1 indisponible, fallback H1 ({str(e)[:80]})")
            
            candles_m15 = self.broker.get_candles(instrument, CONFIRM_TIMEFRAME, 60)
            
            # Calcul du signal
            signal = calculate_mtf_signal(candles_h1, candles_d1, instrument)
            signal_confirm = None
            if len(candles_m15) >= 20:
                signal_confirm = calculate_signal_score(candles_m15, instrument)
            
            # Contexte marché
            market_context = analyze_market_context(candles_h1, instrument)
            session = get_session_score(instrument)
            
            # Strategies
            strategies = build_strategies_context(
                instrument, candles_h1, [], [],
                signal_direction=signal.get("direction"),
                signal_score=signal.get("score", 0),
                open_positions=[]
            )

            spread = self.broker.get_spread_pips(instrument)
            result = {
                "symbol": instrument,
                "signal_direction": signal.get("direction", "WAIT"),
                "score": signal.get("score", 0),
                "spread": spread,
                "regime": signal.get("details", {}).get("market_regime", ""),
                "session": session.get("label", "") if isinstance(session, dict) else str(session),
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            }

            # Envoyer le signal seulement s'il est directionnel et suffisamment robuste.
            direction = signal.get("direction")
            score = int(signal.get("score", 0) or 0)
            confirm_ok = True
            if signal_confirm and isinstance(signal_confirm, dict):
                confirm_dir = signal_confirm.get("direction")
                confirm_score = int(signal_confirm.get("score", 0) or 0)
                confirm_ok = confirm_dir == direction and confirm_score >= max(2, score - 1)

            if direction in ("BUY", "SELL") and score >= self.min_broadcast_score and confirm_ok:
                await self.send_message(
                    recipient="*",  # Broadcast
                    event_type="signal",
                    payload={
                        "signal_id": f"{instrument}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
                        "instrument": instrument,
                        "direction": direction,
                        "score": score,
                        "details": signal.get("details", {}),
                        "market_context": market_context,
                        "session": session,
                        "strategies": strategies,
                        "signal_confirm": signal_confirm,
                        "spread": spread,
                    }
                )
                self.log("INFO", f"{instrument}: Signal {direction} validé (force {score}/5)")
            elif direction in ("BUY", "SELL"):
                reason = "score trop faible" if score < self.min_broadcast_score else "confirmation M15 absente"
                self.log("DEBUG", f"{instrument}: Signal filtré ({reason})")

            self.last_analysis[instrument] = time.time()
            return result

        except Exception as e:
            self.log("ERROR", f"{instrument}: {str(e)[:100]}")
            return {"symbol": instrument, "reason": str(e)[:60]}

    def _write_scan_results(self, candidates: List[Dict], rejected: List[Dict], trending: List[Dict]):
        """Écrit les résultats du scan dans data/scan_results.json."""
        try:
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "cycle": self.cycle_count,
                "candidates": candidates,
                "rejected": rejected,
                "trending": trending,
            }
            _SCAN_FILE.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        except Exception as e:
            self.log("ERROR", f"scan_results write: {e}")

    def _write_heartbeat(self):
        """Met à jour le heartbeat de cet agent dans data/agents_heartbeat.json."""
        try:
            hb = {}
            if _HB_FILE.exists():
                try:
                    hb = json.loads(_HB_FILE.read_text(encoding="utf-8"))
                except Exception:
                    hb = {}
            hb[self.name] = {
                "status": "running",
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "cycle": self.cycle_count,
            }
            _HB_FILE.write_text(json.dumps(hb, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
