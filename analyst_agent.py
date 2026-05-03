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
from scalping_strategy import calculate_scalp_signal
from settings import PRIMARY_TIMEFRAME, CONFIRM_TIMEFRAME, INSTRUMENTS, STRATEGY_MODE, SCALP_TIMEFRAME
from runtime_db import RuntimeStore

_DATA_DIR = Path("data")
_SCAN_FILE = _DATA_DIR / "scan_results.json"


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
        self.min_broadcast_score = 3  # Score 3+ pour XAU (backtest validé)

    def _get_runtime_settings(self) -> Dict[str, Any]:
        try:
            return self.store.get_settings()
        except Exception:
            return {}

    def _get_instruments(self) -> List[str]:
        """Forcé sur XAUUSDm uniquement."""
        return ["XAUUSDm"]

    def _classic_candidate(self, signal: Dict[str, Any], signal_confirm: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        direction = signal.get("direction")
        score = int(signal.get("score", 0) or 0)
        if direction not in ("BUY", "SELL") or score < self.min_broadcast_score:
            return None

        confirm_ok = True
        if signal_confirm and isinstance(signal_confirm, dict):
            confirm_dir = signal_confirm.get("direction")
            confirm_score = int(signal_confirm.get("score", 0) or 0)
            confirm_ok = confirm_dir == direction and confirm_score >= max(2, score - 1)

        if not confirm_ok:
            return None

        return {
            "source": "classic",
            "direction": direction,
            "score": min(score, 5),
            "details": signal.get("details", {}) or {},
            "signal_confirm": signal_confirm,
        }

    def _scalp_candidate(self, scalp_signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        direction = scalp_signal.get("signal")
        raw_score = int(scalp_signal.get("score", 0) or 0)
        if direction not in ("BUY", "SELL") or raw_score <= 0:
            return None

        sl_pips = float(scalp_signal.get("sl_pips", 0.0) or 0.0)
        tp_pips = float(scalp_signal.get("tp_pips", 0.0) or 0.0)
        rr = round(tp_pips / sl_pips, 2) if sl_pips > 0 else 0.0
        quality_score = round(min(1.0, max(0.35, raw_score / 6.0)), 2)
        details = dict(scalp_signal.get("details", {}) or {})
        details.update({
            "atr_pips": float(scalp_signal.get("atr_pips", 0.0) or 0.0),
            "quality_score": quality_score,
            "signal_source": "scalping",
            "scalp_mode": scalp_signal.get("mode", "momentum"),
            "scalp_reasons": scalp_signal.get("reasons", []),
            "distance_to_support_pips": sl_pips if direction == "BUY" else tp_pips,
            "distance_to_resistance_pips": tp_pips if direction == "BUY" else sl_pips,
            "rr_buy": rr if direction == "BUY" else 0.0,
            "rr_sell": rr if direction == "SELL" else 0.0,
        })
        return {
            "source": "scalping",
            "direction": direction,
            "score": min(raw_score, 5),
            "details": details,
            "signal_confirm": None,
        }

    def _select_candidate(self, strategy_mode: str, classic: Optional[Dict[str, Any]], scalp: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        mode = str(strategy_mode or STRATEGY_MODE).strip().lower()
        if mode == "classic":
            return classic
        if mode == "scalping":
            return scalp

        if classic and scalp:
            if classic["direction"] != scalp["direction"]:
                return None
            merged_details = dict(classic.get("details", {}) or {})
            merged_details.update(scalp.get("details", {}) or {})
            merged_details["signal_source"] = "hybrid"
            return {
                "source": "hybrid",
                "direction": classic["direction"],
                "score": min(max(int(classic["score"]), int(scalp["score"])) + 1, 5),
                "details": merged_details,
                "signal_confirm": classic.get("signal_confirm"),
            }
        return classic or scalp
    
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
            runtime_settings = self._get_runtime_settings()
            instruments = self._get_instruments()  # relit les settings à chaque cycle
            candidates = []
            rejected = []
            trending = []

            # Analyser chaque instrument en rotation
            for instrument in instruments:
                result = await self._analyze_instrument(instrument, runtime_settings)
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
                        inst = str(instrument).upper()
                        if inst.startswith("BTC"):
                            max_sp = 80.0
                        elif inst.startswith("XAU"):
                            max_sp = 35.0
                        else:
                            max_sp = 5.0
                        rejected.append({
                            "symbol": instrument,
                            "reason": result.get("reason", "no_signal"),
                            "spread": round(float(result.get("spread", 0.0) or 0.0), 1),
                            "max_spread": max_sp,
                        })
                await asyncio.sleep(0.1)  # Anti-spam

            # Écrire les résultats du scan
            self._write_scan_results(candidates, rejected, trending)
            # Heartbeat (via base class)
            self.write_heartbeat({"cycle": self.cycle_count})

            # Attendre 15s avant prochain cycle (XAU bouge vite, scan plus fréquent)
            await asyncio.sleep(15)
    
    async def _analyze_instrument(self, instrument: str, runtime_settings: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
        """Analyse un instrument et envoie un signal. Retourne le résultat."""
        try:
            if str(instrument).upper() != "XAUUSDM":
                self.log("DEBUG", f"{instrument} ignoré — bot spécialisé XAUUSDm uniquement")
                return None

            settings = runtime_settings or {}
            strategy_mode = str(settings.get("strategy_mode", STRATEGY_MODE)).strip().lower()

            # Récupérer les données XAU
            candles_h1 = self.broker.get_candles("XAUUSDm", "H1", 150)
            if len(candles_h1) < 20:
                return {"symbol": instrument, "reason": "not_enough_data"}

            candles_d1 = []
            try:
                candles_d1 = self.broker.get_candles("XAUUSDm", "D1", 100)
            except Exception as e:
                self.log("WARN", f"{instrument}: D1 indisponible ({str(e)[:80]})")            

            candles_h4 = []
            try:
                candles_h4 = self.broker.get_candles(instrument, "H4", 60)
            except Exception:
                pass

            candles_m15 = self.broker.get_candles("XAUUSDm", "M15", 100)
            spread = self.broker.get_spread_pips(instrument)

            scalp_signal = None
            candles_m5 = []
            if strategy_mode in {"scalping", "hybrid"}:
                scalp_timeframe = str(settings.get("scalp_timeframe", SCALP_TIMEFRAME)).strip().upper() or SCALP_TIMEFRAME
                candles_m5 = self.broker.get_candles("XAUUSDm", scalp_timeframe, 100)
                scalp_signal = calculate_scalp_signal(
                    candles_m5,
                    instrument=instrument,
                    spread_pips=spread,
                    config=settings,
                )

            self.log("INFO", f"XAUUSDm cycle {self.cycle_count} | H1:{len(candles_h1)}c D1:{len(candles_d1)}c M5:{len(candles_m5)}c | Spread:{spread:.1f}p")
            
            # Calcul du signal
            signal = calculate_mtf_signal(candles_h1, candles_d1, instrument, candles_h4=candles_h4)
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

            classic_candidate = self._classic_candidate(signal, signal_confirm)
            scalp_candidate = self._scalp_candidate(scalp_signal or {})
            selected = self._select_candidate(strategy_mode, classic_candidate, scalp_candidate)

            result = {
                "symbol": instrument,
                "signal_direction": selected["direction"] if selected else "WAIT",
                "score": selected["score"] if selected else 0,
                "spread": spread,
                "regime": signal.get("details", {}).get("market_regime", ""),
                "session": session.get("label", "") if isinstance(session, dict) else str(session),
                "source": selected["source"] if selected else strategy_mode,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            }

            if selected and selected.get("direction") in ("BUY", "SELL"):
                await self.send_message(
                    recipient="*",  # Broadcast
                    event_type="signal",
                    payload={
                        "signal_id": f"{instrument}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
                        "instrument": instrument,
                        "direction": selected["direction"],
                        "score": int(selected["score"]),
                        "details": selected.get("details", {}),
                        "market_context": market_context,
                        "session": session,
                        "strategies": strategies,
                        "signal_confirm": selected.get("signal_confirm"),
                        "signal_source": selected.get("source", strategy_mode),
                        "spread": spread,
                    }
                )
                self.log("INFO", f"{instrument}: Signal {selected['direction']} validé via {selected['source']} (force {selected['score']}/5)")
            elif classic_candidate and scalp_candidate and classic_candidate["direction"] != scalp_candidate["direction"]:
                result["reason"] = "classic_scalp_conflict"
                self.log("DEBUG", f"{instrument}: Conflit classic/scalping, signal ignoré")
            elif signal.get("direction") in ("BUY", "SELL"):
                self.log("DEBUG", f"{instrument}: Signal filtré ({strategy_mode})")

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
