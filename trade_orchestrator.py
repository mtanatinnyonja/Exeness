"""
Orchestrateur principal de l'agent de trading.
Gère le cycle: instruments → agent IA → exécution → trailing → réconciliation.
"""

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from settings import (
    INSTRUMENTS, MIN_SIGNAL_SCORE, SIGNAL_COOLDOWN_MINUTES,
    MAX_OPEN_POSITIONS, MAX_RISK_PER_TRADE,
    MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR, TRADE_DAYS,
    PRIMARY_TIMEFRAME, CONFIRM_TIMEFRAME, DAILY_LOSS_LIMIT, DAILY_TARGET,
)
from learning_store import AgentMemory
from mt5_bridge import build_broker
from signal_engine import calculate_signal_score, _MIN_CANDLES
from agent_core import TradingAgent
from runtime_db import RuntimeStore
from economic_calendar import EconomicCalendar
from smart_strategies import (
    get_session_score, calculate_htf_bias, get_smart_money_context,
    calculate_trail_levels, check_correlation_risk, build_strategies_context,
)
from telegram_notifier import TelegramNotifier
from market_protection import run_all_protections

_status_rotation_idx = 0


class TradeOrchestrator:
    def __init__(self, quiet: bool = False):
        self.memory = AgentMemory()
        self.store = RuntimeStore()
        self.broker = build_broker()
        self.agent = TradingAgent(self.broker, self.memory, self.store)
        self.calendar = EconomicCalendar()
        self.telegram = TelegramNotifier()
        self.last_signal_time = {}
        self._last_scan = {"mode": "unknown", "candidates": [], "rejected": [], "selected": []}

        if not quiet:
            self.memory.log_session(
                f"🚀 Agent démarré | broker={getattr(self.broker, 'name', 'unknown')} | ia={self.agent.provider}"
            )
            broker_note = getattr(self.broker, "status_message", "") or getattr(self.broker, "last_error", "")
            if broker_note:
                self.memory.log_session(f"🔌 {broker_note}")
            try:
                self.telegram.notify_bot_started(
                    getattr(self.broker, 'name', 'unknown'),
                    self.agent.provider,
                    self.get_target_instruments(),
                )
            except Exception:
                pass

    def _get_market_status(self) -> Dict:
        try:
            symbols = self.get_target_instruments()
            if hasattr(self.broker, "get_market_status"):
                status = self.broker.get_market_status(symbols)
                if isinstance(status, dict):
                    return status
        except Exception as e:
            self.memory.record_error("market_status", str(e))

        now = datetime.now(timezone.utc)
        scheduled = now.weekday() in TRADE_DAYS and MARKET_OPEN_HOUR <= now.hour < MARKET_CLOSE_HOUR
        return {
            "open": scheduled,
            "symbol": None,
            "tick_age_sec": None,
            "reason": "Fenêtre horaire théorique active" if scheduled else "Fenêtre horaire théorique fermée",
        }

    def is_market_open(self) -> bool:
        return bool(self._get_market_status().get("open"))

    def _max_spread_allowed(self, instrument: str) -> float:
        name = str(instrument).upper()
        if name.startswith("XAU"):
            return 45.0
        if name.startswith(("BTC", "ETH")):
            return 120.0
        return 3.0

    def _build_live_snapshot(self, instrument: str) -> Dict:
        candles_live = self.broker.get_candles(instrument, "M1", 60)
        candles_h1 = self.broker.get_candles(instrument, PRIMARY_TIMEFRAME, 120)
        signal = calculate_signal_score(candles_h1, instrument)
        details = signal.get("details", {}) or {}

        bid, ask = self.broker.get_current_price(instrument)
        live_price = (float(bid) + float(ask)) / 2 if (bid or ask) else float(details.get("price", 0) or 0)
        closes_base = [float(c.get("close", 0) or 0) for c in candles_live[-29:]]
        closes = closes_base + ([round(live_price, 5)] if live_price else [])
        highs = [float(c.get("high", 0) or 0) for c in candles_live[-30:]]
        lows = [float(c.get("low", 0) or 0) for c in candles_live[-30:]]

        previous_close = closes[-2] if len(closes) >= 2 else (closes[-1] if closes else 0)
        change_pct = ((live_price - previous_close) / previous_close * 100) if previous_close else 0.0
        change_5m = ((live_price - closes[-6]) / closes[-6] * 100) if len(closes) >= 6 and closes[-6] else 0.0
        spread = self.broker.get_spread_pips(instrument)

        return {
            "instrument": instrument,
            "price": round(live_price, 5),
            "bid": round(float(bid), 5),
            "ask": round(float(ask), 5),
            "support": float(details.get("support", min(lows) if lows else 0) or 0),
            "resistance": float(details.get("resistance", max(highs) if highs else 0) or 0),
            "rsi": float(details.get("rsi", 50) or 50),
            "regime": str(details.get("market_regime", "unknown")),
            "momentum_5": float(details.get("momentum_5", 0) or 0),
            "momentum_20": float(details.get("momentum_20", 0) or 0),
            "trend_strength": float(details.get("trend_strength", 0) or 0),
            "rr_buy": float(details.get("rr_buy", 0) or 0),
            "rr_sell": float(details.get("rr_sell", 0) or 0),
            "signal_bias": float(details.get("signal_bias", 0) or 0),
            "atr_pips": float(signal.get("atr_pips", 0) or 0),
            "spread": float(spread or 0),
            "price_change_pct": round(change_pct, 4),
            "price_change_5m_pct": round(change_5m, 4),
            "candle_pattern": str(details.get("candle_pattern") or "—"),
            "human_summary": str(details.get("human_summary") or "Lecture technique locale."),
            "closes": [round(v, 5) for v in closes[-30:]],
        }

    def _rank_trending_pairs(self, symbols: List[str]) -> List[Dict]:
        """Rank pairs by trending strength for dashboard prioritization."""
        ranked = []
        for sym in symbols:
            try:
                candles = self.broker.get_candles(sym, PRIMARY_TIMEFRAME, 60)
                if not candles or len(candles) < 20:
                    ranked.append({"symbol": sym, "trending_score": 0, "direction": None, "trend_strength": 0, "signal_bias": 0, "rsi": 50, "regime": "unknown", "quality": 0})
                    continue
                sig = calculate_signal_score(candles, sym)
                det = sig.get("details", {}) or {}
                trend_str = abs(float(det.get("trend_strength", 0) or 0))
                sig_bias = abs(float(det.get("signal_bias", 0) or 0))
                quality = float(det.get("quality_score", 0) or 0)
                score = sig.get("score", 0)
                # Trending score: combine signal strength, trend, and quality
                trending = round(score * 0.3 + sig_bias * 0.3 + trend_str * 10 + quality * 2, 2)
                ranked.append({
                    "symbol": sym,
                    "trending_score": trending,
                    "direction": sig.get("direction"),
                    "trend_strength": round(trend_str, 4),
                    "signal_bias": float(det.get("signal_bias", 0) or 0),
                    "rsi": float(det.get("rsi", 50) or 50),
                    "regime": str(det.get("market_regime", "unknown")),
                    "quality": quality,
                    "score": score,
                })
            except Exception:
                ranked.append({"symbol": sym, "trending_score": 0, "direction": None, "trend_strength": 0, "signal_bias": 0, "rsi": 50, "regime": "unknown", "quality": 0})
        ranked.sort(key=lambda x: x["trending_score"], reverse=True)
        return ranked

    def is_cooldown_active(self, instrument: str) -> bool:
        last_time = self.last_signal_time.get(instrument)
        if not last_time:
            return False
        elapsed = (datetime.now(timezone.utc) - last_time).total_seconds() / 60
        return elapsed < SIGNAL_COOLDOWN_MINUTES

    def get_target_instruments(self) -> List[str]:
        settings = self.store.get_settings()
        max_symbols = int(settings.get("max_symbols_per_cycle", 10))
        preferred = settings.get("preferred_symbols") or []
        selection_mode = str(settings.get("symbol_selection_mode", "smart")).lower()

        visible = []
        try:
            if hasattr(self.broker, "list_visible_symbols"):
                visible = self.broker.list_visible_symbols()
        except Exception as e:
            self.memory.record_error("symbols", str(e))

        if not visible:
            self._last_scan = {"mode": "fallback", "candidates": [], "rejected": [], "selected": list(INSTRUMENTS)[:max_symbols]}
            return list(INSTRUMENTS)[:max_symbols]

        # Filtre symboles: si renseigné → UNIQUEMENT ces paires (dans les deux modes)
        if preferred:
            filtered = [s for s in visible if any(s.upper() == p.upper() for p in preferred)]
            if not filtered:
                self.memory.log_session(f"⚠️ Aucun symbole filtré trouvé dans MT5, fallback sur visibles")
                filtered = visible
            scan_pool = filtered
        else:
            scan_pool = visible

        # Mode smart = scan par spread, mode preferred = ordre tel quel
        if selection_mode == "preferred":
            result = scan_pool[:max_symbols]
            self._last_scan = {"mode": "preferred", "candidates": [], "rejected": [], "selected": result}
            return result

        return self._smart_scan_instruments(scan_pool, preferred, max_symbols)

    def _smart_scan_instruments(self, visible: List[str], preferred: List[str], max_symbols: int) -> List[str]:
        """
        Scan silencieux: évalue chaque paire sur le spread.
        Trie par favorabilité, prend les meilleures.
        Le pool visible est déjà filtré par preferred_symbols si renseigné.
        """
        candidates = []
        rejected = []
        for symbol in visible:
            try:
                spread = self.broker.get_spread_pips(symbol)
                max_spread = self._max_spread_allowed(symbol)
                if spread > max_spread:
                    rejected.append({
                        "symbol": symbol,
                        "spread": round(spread, 2),
                        "max_spread": round(max_spread, 1),
                        "reason": f"Spread {spread:.1f} > max {max_spread:.1f}",
                    })
                    continue

                # Score de priorité: spread bas = meilleur
                spread_ratio = spread / max(0.1, max_spread)  # 0 = parfait, 1 = limite
                priority = 1.0 - spread_ratio
                # Bonus pour preferred_symbols
                is_preferred = any(symbol.upper() == p.upper() for p in preferred)
                if is_preferred:
                    priority += 0.5
                # Bonus pour paires majeures connues (plus liquides)
                name_upper = symbol.upper().replace("M", "").replace(".", "")
                majors = {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "XAUUSD"}
                is_major = any(m in name_upper for m in majors)
                if is_major:
                    priority += 0.2

                tags = []
                if is_preferred:
                    tags.append("preferred")
                if is_major:
                    tags.append("major")

                candidates.append({
                    "symbol": symbol,
                    "spread": round(spread, 2),
                    "max_spread": round(max_spread, 1),
                    "priority": round(priority, 3),
                    "spread_pct": round(spread_ratio * 100, 1),
                    "tags": tags,
                })
            except Exception:
                continue  # Paire non-tradeable, on skip

        # Trier par priorité descendante
        candidates.sort(key=lambda x: x["priority"], reverse=True)
        selected = [c["symbol"] for c in candidates[:max_symbols]]

        # Stocker les détails du scan pour le dashboard
        self._last_scan = {
            "mode": "smart",
            "total_visible": len(visible + rejected),
            "candidates": candidates,
            "rejected": rejected,
            "selected": selected,
        }

        return selected

    def run_cycle(self):
        self.memory.log_session("═══ Cycle démarré ═══")

        market_status = self._get_market_status()
        if not market_status.get("open"):
            self.memory.log_session(f"⏸️ Marché fermé - cycle ignoré | {market_status.get('reason', 'pas de cotation récente')}")
            return

        try:
            account = self.broker.get_account_summary()
            open_positions = self.broker.get_open_positions()
            self.memory.log_session(
                f"💰 Balance: ${account.get('balance', 0):.2f} | "
                f"P&L: ${account.get('unrealized_pnl', 0):.2f} | "
                f"Positions: {len(open_positions)}"
            )
        except Exception as e:
            self.memory.record_error("broker", str(e))
            self.memory.log_session(f"❌ Erreur broker: {e}")
            return

        settings = self.store.get_settings()
        max_open_positions = int(settings.get("max_open_positions", MAX_OPEN_POSITIONS))
        daily_loss_limit = float(settings.get("daily_loss_limit", DAILY_LOSS_LIMIT))

        # Reconcile closed trades (SL/TP hit on MT5 side)
        self._reconcile_closed_trades(open_positions)

        if len(open_positions) >= max_open_positions:
            self.memory.log_session(f"⚠️ Max positions global atteint ({len(open_positions)}/{max_open_positions})")
            self._check_existing_positions(open_positions)
            return

        today_pnl = self.memory.get_daily_pnl()
        if daily_loss_limit < 0 and today_pnl <= daily_loss_limit:
            self.memory.log_session(f"🛑 Perte journalière limite atteinte: ${today_pnl:.2f}")
            self._close_all_positions(open_positions, "limite de perte journalière")
            try:
                self.telegram.notify_daily_loss_limit(today_pnl, daily_loss_limit)
            except Exception:
                pass
            return
        # Pas d'objectif journalier fixe: on trade tant que le money management est respecté
        if today_pnl > 0:
            self.memory.log_session(f"📈 P&L jour: +${today_pnl:.2f} — on continue")

        signal_floor = max(2, int(MIN_SIGNAL_SCORE) - 1) if today_pnl < 0 else max(2, int(MIN_SIGNAL_SCORE) - 1)

        instruments = self.get_target_instruments()

        if not instruments:
            self.memory.log_session("⚠️ Aucun symbole visible dans MT5 - rien à analyser")
            return

        self.memory.log_session(f"📡 Symboles actifs: {', '.join(instruments)} | seuil signal={signal_floor}/5")

        for instrument in instruments:
            self._analyze_instrument(instrument, account, min_signal_required=signal_floor)
            time.sleep(0.2)

        self.memory.log_session("═══ Cycle terminé ═══")

    def _analyze_instrument(self, instrument: str, account: Dict, min_signal_required: int = MIN_SIGNAL_SCORE):
        if self.is_cooldown_active(instrument):
            self.memory.log_session(f"⏳ {instrument}: cooldown actif")
            return

        # News filter
        try:
            news_check = self.calendar.should_pause_trading(instrument)
            if news_check["pause"]:
                self.memory.log_session(f"📰 {instrument}: PAUSE NEWS — {news_check['reason']}")
                return
        except Exception as cal_err:
            self.memory.record_error("calendar", str(cal_err))

        try:
            open_positions = self.broker.get_open_positions()

            # L'agent gère TOUT: technique, protections, HTF, SMC, mémoire, LLM
            decision = self.agent.analyze(instrument, account, open_positions)

            if not decision:
                return

            self.last_signal_time[instrument] = datetime.now(timezone.utc)

            # Record signal sample for history
            signal = decision.get("signal", {})
            self.store.record_signal_sample(instrument, signal, decision.get("spread", 0), decision)

            if decision["decision"] in ("BUY", "SELL"):
                instrument_positions = [
                    p for p in open_positions
                    if str(p.get("instrument", "")).upper() == instrument.upper()
                ]
                if self._manage_existing_position(instrument, instrument_positions, decision):
                    return
                self._execute_trade(instrument, decision, signal, account)
            else:
                instrument_positions = [
                    p for p in open_positions
                    if str(p.get("instrument", "")).upper() == instrument.upper()
                ]
                if instrument_positions:
                    self.memory.log_session(
                        f"🧭 {instrument}: position existante surveillée"
                    )
                self.memory.log_session(
                    f"⏸️ {instrument}: WAIT — {decision.get('reasoning', '')[:200]}"
                )

        except Exception as e:
            self.memory.record_error(f"analysis:{instrument}", str(e))
            self.memory.log_session(f"❌ Erreur analyse {instrument}: {e}")

    def _execute_trade(self, instrument: str, decision: Dict, signal: Dict, account: Dict):
        direction = decision["decision"]
        atr = max(6, int(round(float(signal.get("atr_pips", 20) or 20))))
        raw_sl = int(decision.get("stop_loss_pips", atr) or atr)
        sl_pips = max(atr, raw_sl)
        raw_tp = int(decision.get("take_profit_pips", sl_pips * 2) or sl_pips * 2)
        rr_ratio = max(1.5, raw_tp / sl_pips) if sl_pips > 0 else 2.0
        tp_pips = max(sl_pips, int(sl_pips * rr_ratio))
        confidence = float(decision.get("confidence", 0.5))
        risk_multiplier = float(decision.get("risk_multiplier", 1.0))

        settings = self.store.get_settings()
        balance = max(1.0, account.get("balance", 0))
        max_risk_pct = float(settings.get("max_risk_per_trade", MAX_RISK_PER_TRADE))
        risk_usd = max(0.5, balance * max_risk_pct * risk_multiplier)

        # --- Money management: skip trade if SL can't be structural ---
        pip_value = getattr(self.broker, '_pip_value_per_lot', lambda x: 10.0)(instrument)
        vol_min = getattr(self.broker, '_volume_min', lambda x: 0.01)(instrument)
        min_risk_at_sl = vol_min * sl_pips * pip_value
        max_allowed_risk = balance * 0.05  # Hard cap 5% of balance
        # Minimum acceptable SL = 50% of the structural SL (below that it's random)
        min_acceptable_sl = max(int(atr * 0.5), int(sl_pips * 0.5))

        if min_risk_at_sl > risk_usd and min_risk_at_sl > max_allowed_risk:
            # SL too wide for this capital at min volume → check if reduced SL is still viable
            new_sl = max(6, int(max_allowed_risk / max(0.001, vol_min * pip_value)))
            if new_sl < min_acceptable_sl:
                # Capital insufficient for a meaningful SL → skip trade entirely
                self.memory.log_session(
                    f"⛔ Skip {instrument}: SL structurel={sl_pips}p, capital ne permet que {new_sl}p "
                    f"(min acceptable={min_acceptable_sl}p). Capital insuffisant."
                )
                return
            self.memory.log_session(
                f"⚠️ Money mgmt: SL {sl_pips}→{new_sl}p (capital ${balance:.0f}, risque max ${max_allowed_risk:.2f})"
            )
            sl_pips = new_sl
            tp_pips = max(sl_pips, int(sl_pips * rr_ratio))

        volume = self.broker.calculate_volume(instrument, risk_usd, sl_pips)
        actual_risk = volume * sl_pips * pip_value

        self.memory.log_session(
            f"📈 Ordre: {direction} {instrument} | vol={volume} | SL={sl_pips}p | TP={tp_pips}p | risque=${actual_risk:.2f}"
        )

        order = self.broker.place_market_order(
            instrument=instrument,
            direction=direction,
            volume=volume,
            stop_loss_pips=sl_pips,
            take_profit_pips=tp_pips,
            comment=f"LOCAL|{signal.get('pattern', '')[:20]}|{int(confidence * 100)}"
        )

        if order:
            trade_id = self.memory.add_trade({
                "instrument": instrument,
                "direction": direction,
                "volume": volume,
                "entry_price": order.get("entry_price", 0.0),
                "stop_loss": order.get("stop_loss", 0.0),
                "take_profit": order.get("take_profit", 0.0),
                "broker_id": order.get("broker_id"),
                "position_ticket": order.get("position_ticket"),
                "pattern": signal.get("pattern"),
                "signal_score": signal.get("score", 0),
                "confidence": confidence,
                "sl_pips": sl_pips,
                "tp_pips": tp_pips,
                "risk_usd": round(actual_risk, 2),
                "reasoning": decision.get("reasoning", ""),
                "status": order.get("status", "open")
            })
            self.memory.log_session(
                f"✅ Trade #{trade_id} créé: {direction} {instrument} vol={volume} @ {order.get('entry_price', 0):.5f} [{order.get('status', 'open')}]"
            )
            try:
                self.telegram.notify_trade_opened(
                    instrument, direction, volume,
                    order.get("entry_price", 0), sl_pips, tp_pips,
                    confidence, actual_risk, decision.get("reasoning", ""),
                )
            except Exception:
                pass
        else:
            self.memory.log_session(f"❌ Échec ordre {instrument}")

    def _reconcile_closed_trades(self, open_positions: List[Dict]):
        """Detect trades closed on MT5 side (SL/TP/manual) and update memory."""
        # Build sets of open tickets AND open instruments for matching
        open_tickets = set()
        open_instrument_tickets = {}  # instrument -> set of tickets
        for p in open_positions:
            t = p.get("ticket")
            inst = str(p.get("instrument", "")).upper()
            if t is not None:
                open_tickets.add(int(t))
            open_instrument_tickets.setdefault(inst, set())
            if t is not None:
                open_instrument_tickets[inst].add(int(t))

        for trade in self.memory.trades:
            if trade.get("status") not in ("open",):
                continue
            instrument = str(trade.get("instrument", "")).upper()

            # Match by position_ticket first, then broker_id, then by instrument
            pos_ticket = trade.get("position_ticket")
            broker_id = trade.get("broker_id")
            still_open = False
            if pos_ticket and int(pos_ticket) in open_tickets:
                still_open = True
            elif broker_id and int(broker_id) in open_tickets:
                still_open = True
            elif instrument in open_instrument_tickets and open_instrument_tickets[instrument]:
                # Instrument still has positions — assume still open (legacy trades without ticket)
                still_open = True

            if not still_open:
                # Try to get actual PnL from MT5 deal history (position_ticket first, then broker_id)
                pnl_est = self._get_deal_pnl(trade.get("position_ticket"))
                if pnl_est is None:
                    pnl_est = self._get_deal_pnl(trade.get("broker_id"))
                if pnl_est is None:
                    pnl_est = 0.0
                close_reason = "TP" if pnl_est > 0 else "SL" if pnl_est < 0 else "fermé"

                self.memory.update_trade(trade.get("id"), {
                    "status": "closed",
                    "pnl": round(pnl_est, 2),
                    "close_reason": close_reason,
                    "closed_at": datetime.now(timezone.utc).isoformat(),
                })
                emoji = "💰" if pnl_est >= 0 else "💸"
                self.memory.log_session(
                    f"{emoji} {instrument}: trade #{trade.get('id')} fermé ({close_reason}) | P&L = ${pnl_est:+.2f}"
                )
                try:
                    self.telegram.notify_trade_closed(
                        instrument, trade.get("direction", "?"), pnl_est, close_reason
                    )
                except Exception:
                    pass

    def _get_deal_pnl(self, order_id) -> Optional[float]:
        """Get realized PnL from MT5 deal history for a given order/position."""
        if not order_id or not hasattr(self.broker, 'mt5'):
            return None
        try:
            oid = int(order_id)
        except (ValueError, TypeError):
            return None
        try:
            # Method 1: Direct position-based lookup (most reliable)
            deals = self.broker.mt5.history_deals_get(position=oid)
            if deals and len(deals) > 0:
                total_pnl = 0.0
                for deal in deals:
                    total_pnl += float(getattr(deal, 'profit', 0)) + float(getattr(deal, 'swap', 0)) + float(getattr(deal, 'commission', 0))
                return round(total_pnl, 2)
        except Exception:
            pass
        try:
            # Method 2: Scan recent deal history by order/position_id
            from datetime import timedelta
            start = datetime.now(timezone.utc) - timedelta(days=7)
            end = datetime.now(timezone.utc) + timedelta(hours=1)
            deals = self.broker.mt5.history_deals_get(start, end)
            if not deals:
                return None
            total_pnl = 0.0
            found = False
            for deal in deals:
                if getattr(deal, 'order', None) == oid or getattr(deal, 'position_id', None) == oid:
                    total_pnl += float(getattr(deal, 'profit', 0)) + float(getattr(deal, 'swap', 0)) + float(getattr(deal, 'commission', 0))
                    found = True
            return round(total_pnl, 2) if found else None
        except Exception:
            return None

    def _check_existing_positions(self, positions: List[Dict]):
        for pos in positions:
            upnl = float(pos.get("unrealized_pnl", 0))
            emoji = "📈" if upnl >= 0 else "📉"
            instrument = pos.get("instrument", "")
            direction = str(pos.get("direction", "")).upper()
            self.memory.log_session(
                f"{emoji} Position {instrument} {direction}: P&L non réalisé = ${upnl:.2f}"
            )

            # Trailing stop / break-even management
            try:
                entry = float(pos.get("entry_price") or pos.get("open_price") or 0)
                current = float(pos.get("current_price") or 0)
                ticket = pos.get("ticket")
                if not entry or not current or not ticket or not direction:
                    continue

                candles = self.broker.get_candles(instrument, PRIMARY_TIMEFRAME, 20)
                from signal_engine import calculate_atr
                atr = calculate_atr(candles) if len(candles) >= 15 else 0
                pip_size = self.broker._pip_size(instrument) if hasattr(self.broker, '_pip_size') else 0.0001

                if atr > 0:
                    sl_pips = float(pos.get("sl_pips", 0) or 0)
                    trail = calculate_trail_levels(direction, entry, current, atr, sl_pips, pip_size)

                    if trail["action"] != "hold" and trail.get("new_sl"):
                        # Vérifie que le nouveau SL est meilleur que l'ancien
                        old_sl = float(pos.get("stop_loss") or 0)
                        new_sl = trail["new_sl"]
                        better = (direction == "BUY" and new_sl > old_sl) or \
                                 (direction == "SELL" and (old_sl == 0 or new_sl < old_sl))

                        if better and hasattr(self.broker, 'modify_position'):
                            try:
                                self.broker.modify_position(ticket, new_sl=new_sl)
                                self.memory.log_session(
                                    f"🔄 {instrument}: {trail['reason']} (SL {old_sl:.5f} → {new_sl:.5f})"
                                )
                            except Exception as mod_err:
                                self.memory.record_error("trailing", str(mod_err))
                        elif better:
                            self.memory.log_session(
                                f"📋 {instrument}: trail recommandé — {trail['reason']}"
                            )
            except Exception as trail_err:
                self.memory.record_error("trailing", f"{instrument}: {trail_err}")

    def _close_all_positions(self, positions: List[Dict], reason: str):
        for pos in positions:
            try:
                pnl = self.broker.close_position(pos.get("instrument"))
                self.memory.log_session(
                    f"🔒 Fermeture auto {pos.get('instrument')} | raison: {reason} | pnl={float(pnl or 0):.2f}"
                )
            except Exception as e:
                self.memory.log_session(f"❌ Fermeture auto échouée {pos.get('instrument')}: {e}")

    def _manage_existing_position(self, instrument: str, positions: List[Dict], decision: Dict) -> bool:
        if not positions:
            return False

        wanted = str(decision.get("decision", "WAIT")).upper()
        for pos in positions:
            current_dir = str(pos.get("direction", "")).upper()
            if current_dir == wanted:
                self.memory.log_session(f"🟢 {instrument}: position {current_dir} déjà ouverte, pas de doublon")
                return True
            if current_dir and wanted in {"BUY", "SELL"} and current_dir != wanted:
                try:
                    pnl = self.broker.close_position(instrument)
                    self.memory.log_session(
                        f"🔄 {instrument}: fermeture auto {current_dir} puis inversion vers {wanted} | pnl={float(pnl or 0):.2f}"
                    )
                except Exception as e:
                    self.memory.log_session(f"❌ {instrument}: impossible de fermer avant inversion: {e}")
                    return True
        return False

    def preview_ai_decision(self, instrument: str = None) -> Dict:
        symbols = self.get_target_instruments()
        target = instrument or (symbols[0] if symbols else None)
        if not target:
            return {
                "instrument": None,
                "signal": {},
                "decision": {
                    "decision": "WAIT",
                    "confidence": 0.0,
                    "reasoning": "Aucun symbole visible dans MT5 pour lancer le test IA."
                },
                "provider": self.agent.provider,
                "spread": 0.0,
            }

        account = self.broker.get_account_summary()
        candles_needed = max(120, _MIN_CANDLES + 10)
        candles = self.broker.get_candles(target, PRIMARY_TIMEFRAME, candles_needed)
        signal = calculate_signal_score(candles, target)

        spread = self.broker.get_spread_pips(target)
        open_positions = self.broker.get_open_positions()
        decision = self.agent.analyze(target, account, open_positions)
        if not decision:
            decision = {"decision": "WAIT", "confidence": 0.0, "reasoning": "Analyse indisponible"}
        return {
            "instrument": target,
            "signal": signal,
            "decision": decision,
            "provider": self.agent.provider,
            "spread": spread,
            "market_snapshot": self._build_live_snapshot(target),
            "last_ai_exchange": self.agent.get_last_exchange(),
        }

    def get_status(self, focus_symbol: str = "") -> Dict:
        try:
            account = self.broker.get_account_summary()
            positions = self.broker.get_open_positions()
        except Exception as e:
            self.memory.record_error("status", str(e))
            account = {"balance": 0, "unrealized_pnl": 0, "nav": 0, "open_trades": 0, "connected": False}
            positions = []

        runtime_settings = self.store.get_settings()
        ml_stats = self.store.get_ml_stats()
        ml_history = self.store.get_recent_ml_samples(28)
        ml_model_state = {"trained": False, "model_type": "removed", "sample_count": 0}
        llm_calls = self.memory.get_llm_calls_today()
        active_symbols = self.get_target_instruments()
        market_status = self._get_market_status()

        # Trending-aware rotation: rank pairs by signal strength, show best first
        global _status_rotation_idx
        live_snapshot = None
        trending_pairs = []
        if active_symbols:
            # Quick signal scan for all active pairs (cached per cycle, lightweight)
            try:
                trending_pairs = self._rank_trending_pairs(active_symbols)
            except Exception:
                trending_pairs = [{"symbol": s, "trending_score": 0, "direction": None, "trend_strength": 0} for s in active_symbols]

            # Pick the best trending pair for the live snapshot (rotate among top pairs)
            ranked_symbols = [t["symbol"] for t in trending_pairs if t["trending_score"] > 0] or active_symbols
            _status_rotation_idx = (_status_rotation_idx + 1) % len(ranked_symbols)
            try:
                live_snapshot = self._build_live_snapshot(ranked_symbols[_status_rotation_idx])
            except Exception as e:
                self.memory.record_error("live_snapshot", str(e))

        raw_logs = self.memory.memory.get("session_log", [])[-200:]
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_open": bool(market_status.get("open")),
            "market_status": market_status,
            "active_symbols": active_symbols,
            "account": account,
            "open_positions": positions,
            "daily_pnl": self.memory.get_daily_pnl(),
            "total_pnl": self.memory.memory.get("total_pnl", 0),
            "win_rate": self.memory.get_win_rate(),
            "total_trades": self.memory.memory.get("total_trades", 0),
            "llm_calls_today": llm_calls,
            "api_calls_today": llm_calls,
            "recent_trades": self.memory.get_recent_trades(5),
            "session_log": raw_logs[-60:],
            "best_patterns": self.memory.get_best_patterns()[:3],
            "broker": {
                "name": getattr(self.broker, "name", "unknown"),
                "connected": getattr(self.broker, "connected", False),
                "safe_to_trade": getattr(self.broker, "safe_to_trade", False),
                "status_message": getattr(self.broker, "status_message", ""),
            },
            "settings": runtime_settings,
            "ai_provider": self.agent.provider,
            "token_usage": self.memory.get_token_usage_today(),
            "ml_stats": ml_stats,
            "ml_model_state": ml_model_state,
            "ml_history": ml_history,
            "learned_filters": self.memory.memory.get("learned_filters", [])[-5:],
            "runtime_mode": "local-only",
            "live_snapshot": live_snapshot,
            "trending_pairs": trending_pairs,
            "last_ai_exchange": self.agent.get_last_exchange(),
            "economic_calendar": self._get_calendar_summary(),
            "pro_strategies": self._get_strategies_summary(active_symbols, positions),
            "market_protections": self._get_protections_summary(active_symbols),
            "smart_scan": self._last_scan,
        }

    def _get_calendar_summary(self) -> Dict:
        try:
            return {
                "upcoming": self.calendar.get_dashboard_summary(),
                "news_pause": self.calendar.should_pause_trading(
                    self.get_target_instruments()[0] if self.get_target_instruments() else "EURUSD"
                ),
            }
        except Exception:
            return {"upcoming": [], "news_pause": {"pause": False, "reason": "", "events": []}}

    def _get_strategies_summary(self, symbols: List[str], positions: List[Dict]) -> Dict:
        try:
            session = get_session_score(symbols[0] if symbols else "EURUSD")
            # HTF bias for the first active symbol
            target = symbols[0] if symbols else None
            htf = {}
            smc_summary = {}
            if target:
                try:
                    c_h4 = self.broker.get_candles(target, "H4", 60)
                    c_d1 = self.broker.get_candles(target, "D1", 30)
                    htf = calculate_htf_bias(c_h4, c_d1)
                    c_h1 = self.broker.get_candles(target, PRIMARY_TIMEFRAME, 120)
                    smc_summary = get_smart_money_context(c_h1, target)
                except Exception:
                    pass
            return {
                "session": session,
                "htf_bias": {
                    "h4": htf.get("h4_bias", "?"),
                    "d1": htf.get("d1_bias", "?"),
                    "combined": htf.get("combined_bias", "?"),
                    "trade_with": htf.get("trade_with"),
                    "context": htf.get("context", ""),
                },
                "smart_money": {
                    "fvg_count": smc_summary.get("fvg_count", 0),
                    "ob_count": smc_summary.get("ob_count", 0),
                    "bias": smc_summary.get("smart_money_bias", "neutral"),
                    "zones": smc_summary.get("zones_text", ""),
                },
                "open_correlations": [
                    check_correlation_risk(s, "BUY", positions)
                    for s in symbols[:3]
                ] if positions else [],
            }
        except Exception:
            return {"session": {}, "htf_bias": {}, "smart_money": {}, "open_correlations": []}

    def _get_protections_summary(self, symbols: List[str]) -> Dict:
        """Résumé des protections anti-manipulation pour le dashboard."""
        try:
            target = symbols[0] if symbols else None
            if not target:
                return {"status": "no_symbol", "alerts": []}
            candles = self.broker.get_candles(target, PRIMARY_TIMEFRAME, 60)
            spread = self.broker.get_spread_pips(target)
            pip_sz = self.broker._pip_size(target)
            price = candles[-1]["close"] if candles else 0
            result = run_all_protections(target, candles, spread, pip_sz, price)
            return {
                "symbol": target,
                "blocked": result["blocked"],
                "risk_adjustment": result["risk_adjustment"],
                "alerts": result["hard_blocks"] + result["warnings"],
                "spread_spike": result["spread_check"].get("spike", False),
                "ghost_candle": result["ghost_check"].get("detected", False),
                "news_spike": result["news_spike"].get("spike", False),
                "slippage_level": result["slippage_check"].get("level", "LOW"),
                "round_number": result["round_number"].get("near_round_number", False),
                "liquidity_sweep": result["liquidity_sweep"].get("detected", False),
                "sweep_direction": result["liquidity_sweep"].get("signal_direction"),
                "structure_trend": result["structure"].get("trend", "undefined"),
                "bos": result["structure"].get("bos") is not None,
                "choch": result["structure"].get("choch") is not None,
                "bos_detail": result["structure"].get("bos", {}).get("context", ""),
                "choch_detail": result["structure"].get("choch", {}).get("context", ""),
            }
        except Exception:
            return {"status": "error", "alerts": []}