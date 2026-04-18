"""
Stratégies professionnelles avancées.
- Kill Zones / Sessions (ICT)
- Higher Timeframe Bias (H4/D1)
- Smart Money Concepts: Fair Value Gaps + Order Blocks
- Trailing Stop / Break-Even management
- Filtre de corrélation inter-paires
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════
# 1. KILL ZONES / TRADING SESSIONS (ICT)
# ═══════════════════════════════════════════════════════════════════════════

# Kill zones = fenêtres horaires où les institutions bougent le marché
KILL_ZONES = {
    "asian": {"start": 0, "end": 3, "label": "Asian Session", "quality": 0.4},
    "london_open": {"start": 7, "end": 10, "label": "London Kill Zone", "quality": 1.0},
    "ny_open": {"start": 12, "end": 15, "label": "New York Kill Zone", "quality": 1.0},
    "london_close": {"start": 15, "end": 17, "label": "London Close", "quality": 0.7},
    "dead_zone_1": {"start": 3, "end": 7, "label": "Pré-London (faible)", "quality": 0.2},
    "dead_zone_2": {"start": 17, "end": 20, "label": "Post-NY (faible)", "quality": 0.2},
    "night": {"start": 20, "end": 24, "label": "Night Session", "quality": 0.1},
}

# Instruments qui bougent mieux dans certaines sessions
SESSION_PREFERENCE = {
    "EUR": ["london_open", "ny_open"],
    "GBP": ["london_open", "ny_open"],
    "USD": ["ny_open", "london_open"],
    "JPY": ["asian", "london_open"],
    "AUD": ["asian", "london_open"],
    "NZD": ["asian", "london_open"],
    "CAD": ["ny_open"],
    "CHF": ["london_open", "ny_open"],
    "XAU": ["london_open", "ny_open"],
    "BTC": ["ny_open", "london_open", "asian"],
}


def get_current_session() -> Dict:
    """Retourne la session de trading active et sa qualité."""
    now = datetime.now(timezone.utc)
    hour = now.hour

    active = None
    for name, zone in KILL_ZONES.items():
        if zone["start"] <= hour < zone["end"]:
            active = {"name": name, **zone}
            break

    if not active:
        active = {"name": "off_hours", "start": 0, "end": 0, "label": "Hors session", "quality": 0.1}

    return {
        "session": active["name"],
        "label": active["label"],
        "quality": active["quality"],
        "utc_hour": hour,
        "is_kill_zone": active["quality"] >= 0.7,
    }


def get_session_score(instrument: str) -> Dict:
    """Score de qualité de la session actuelle pour un instrument donné."""
    session = get_current_session()
    quality = session["quality"]

    # Bonus si l'instrument est dans sa session préférée
    currencies = _extract_currencies(instrument)
    preferred_sessions = set()
    for ccy in currencies:
        preferred_sessions.update(SESSION_PREFERENCE.get(ccy, []))

    if session["session"] in preferred_sessions:
        quality = min(1.0, quality + 0.2)

    return {
        **session,
        "instrument_quality": round(quality, 2),
        "preferred": session["session"] in preferred_sessions,
        "recommendation": _session_recommendation(quality),
    }


def _session_recommendation(quality: float) -> str:
    if quality >= 0.8:
        return "OPTIMAL — Kill Zone active, volume institutionnel élevé"
    if quality >= 0.5:
        return "ACCEPTABLE — Session secondaire, prudence sur le sizing"
    if quality >= 0.2:
        return "FAIBLE — Hors kill zone, éviter les entrées agressives"
    return "ÉVITER — Session morte, spread élargi, faux signaux probables"


def _extract_currencies(instrument: str) -> List[str]:
    name = instrument.upper().replace("M", "").replace(".", "")
    known = ["EUR", "USD", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "XAU", "XAG", "BTC", "ETH"]
    found = []
    for ccy in known:
        if ccy in name:
            found.append(ccy)
    return found if found else ["USD"]


# ═══════════════════════════════════════════════════════════════════════════
# 2. HIGHER TIMEFRAME BIAS (H4 / D1)
# ═══════════════════════════════════════════════════════════════════════════

def calculate_htf_bias(candles_h4: List[Dict], candles_d1: List[Dict] = None) -> Dict:
    """
    Détermine le biais directionnel basé sur les timeframes supérieurs.
    Règle pro: ne JAMAIS trader contre le trend H4/D1.
    """
    result = {
        "h4_bias": "neutral",
        "d1_bias": "neutral",
        "combined_bias": "neutral",
        "strength": 0.0,
        "trade_with": None,  # Direction à privilégier
        "context": "",
    }

    if candles_h4 and len(candles_h4) >= 20:
        result["h4_bias"] = _determine_bias(candles_h4, "H4")

    if candles_d1 and len(candles_d1) >= 10:
        result["d1_bias"] = _determine_bias(candles_d1, "D1")

    # Combinaison des biais
    h4 = result["h4_bias"]
    d1 = result["d1_bias"]

    if h4 == d1 and h4 != "neutral":
        result["combined_bias"] = h4
        result["strength"] = 1.0
        result["trade_with"] = "BUY" if h4 == "bullish" else "SELL"
        result["context"] = f"H4+D1 alignés {h4} — trader uniquement {result['trade_with']}"
    elif h4 != "neutral" and d1 == "neutral":
        result["combined_bias"] = h4
        result["strength"] = 0.6
        result["trade_with"] = "BUY" if h4 == "bullish" else "SELL"
        result["context"] = f"H4 {h4}, D1 neutre — biais modéré {result['trade_with']}"
    elif d1 != "neutral" and h4 == "neutral":
        result["combined_bias"] = d1
        result["strength"] = 0.7
        result["trade_with"] = "BUY" if d1 == "bullish" else "SELL"
        result["context"] = f"D1 {d1}, H4 neutre — biais directionnel {result['trade_with']}"
    elif h4 != d1 and h4 != "neutral" and d1 != "neutral":
        result["combined_bias"] = "conflict"
        result["strength"] = 0.0
        result["trade_with"] = None
        result["context"] = f"CONFLIT H4={h4} vs D1={d1} — ATTENDRE alignement"
    else:
        result["context"] = "Pas de biais clair — marché indécis"

    return result


def _determine_bias(candles: List[Dict], label: str) -> str:
    """Détermine bullish/bearish/neutral à partir de la structure."""
    closes = [c["close"] for c in candles]
    if len(closes) < 10:
        return "neutral"

    # EMA 20 vs EMA 50
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, min(50, len(closes)))

    # Dernier prix relatif aux EMAs
    price = closes[-1]
    above_ema20 = price > ema20
    above_ema50 = price > ema50
    ema20_above_50 = ema20 > ema50

    # Structure HH/HL ou LH/LL sur les 5 dernières swings
    highs = [c["high"] for c in candles[-10:]]
    lows = [c["low"] for c in candles[-10:]]
    swing_highs = _find_swings(highs, "high")
    swing_lows = _find_swings(lows, "low")

    bullish_count = 0
    bearish_count = 0

    if above_ema20 and above_ema50 and ema20_above_50:
        bullish_count += 2
    elif not above_ema20 and not above_ema50 and not ema20_above_50:
        bearish_count += 2

    # Higher highs / higher lows
    if len(swing_highs) >= 2 and swing_highs[-1] > swing_highs[-2]:
        bullish_count += 1
    if len(swing_lows) >= 2 and swing_lows[-1] > swing_lows[-2]:
        bullish_count += 1
    if len(swing_highs) >= 2 and swing_highs[-1] < swing_highs[-2]:
        bearish_count += 1
    if len(swing_lows) >= 2 and swing_lows[-1] < swing_lows[-2]:
        bearish_count += 1

    # Net move over the period
    net = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] else 0
    if net > 0.3:
        bullish_count += 1
    elif net < -0.3:
        bearish_count += 1

    if bullish_count >= 3:
        return "bullish"
    if bearish_count >= 3:
        return "bearish"
    return "neutral"


def _ema(data: List[float], period: int) -> float:
    if len(data) < period:
        return data[-1] if data else 0
    k = 2.0 / (period + 1)
    ema = sum(data[:period]) / period
    for val in data[period:]:
        ema = val * k + ema * (1 - k)
    return ema


def _find_swings(values: List[float], swing_type: str, lookback: int = 2) -> List[float]:
    swings = []
    for i in range(lookback, len(values) - lookback):
        if swing_type == "high" and values[i] == max(values[i - lookback:i + lookback + 1]):
            swings.append(values[i])
        elif swing_type == "low" and values[i] == min(values[i - lookback:i + lookback + 1]):
            swings.append(values[i])
    return swings


# ═══════════════════════════════════════════════════════════════════════════
# 3. SMART MONEY CONCEPTS — Fair Value Gaps + Order Blocks
# ═══════════════════════════════════════════════════════════════════════════

def detect_fair_value_gaps(candles: List[Dict], min_gap_atr_ratio: float = 0.3) -> List[Dict]:
    """
    Détecte les Fair Value Gaps (FVG) — zones de déséquilibre prix.
    Un FVG bullish = gap entre le high de bougie[i-2] et le low de bougie[i].
    Un FVG bearish = gap entre le low de bougie[i-2] et le high de bougie[i].
    Le prix tend à revenir combler ces gaps → zones d'entrée idéales.
    """
    if len(candles) < 5:
        return []

    # Calcul ATR pour filtrer les petits gaps insignifiants
    atr = _simple_atr(candles, 14)
    if atr <= 0:
        return []

    fvgs = []
    for i in range(2, len(candles)):
        c_prev2 = candles[i - 2]
        c_curr = candles[i]

        # FVG Bullish: low actuel > high de i-2 (gap haussier)
        if c_curr["low"] > c_prev2["high"]:
            gap_size = c_curr["low"] - c_prev2["high"]
            if gap_size >= atr * min_gap_atr_ratio:
                fvgs.append({
                    "type": "bullish_fvg",
                    "top": c_curr["low"],
                    "bottom": c_prev2["high"],
                    "midpoint": (c_curr["low"] + c_prev2["high"]) / 2,
                    "size": gap_size,
                    "candle_index": i,
                    "filled": False,
                })

        # FVG Bearish: high actuel < low de i-2 (gap baissier)
        if c_curr["high"] < c_prev2["low"]:
            gap_size = c_prev2["low"] - c_curr["high"]
            if gap_size >= atr * min_gap_atr_ratio:
                fvgs.append({
                    "type": "bearish_fvg",
                    "top": c_prev2["low"],
                    "bottom": c_curr["high"],
                    "midpoint": (c_prev2["low"] + c_curr["high"]) / 2,
                    "size": gap_size,
                    "candle_index": i,
                    "filled": False,
                })

    # Vérifier si les FVGs ont été comblés par les bougies suivantes
    price = candles[-1]["close"]
    for fvg in fvgs:
        idx = fvg["candle_index"]
        for j in range(idx + 1, len(candles)):
            if fvg["type"] == "bullish_fvg" and candles[j]["low"] <= fvg["bottom"]:
                fvg["filled"] = True
                break
            if fvg["type"] == "bearish_fvg" and candles[j]["high"] >= fvg["top"]:
                fvg["filled"] = True
                break

    # Retourner seulement les FVGs non comblés (zones actives)
    active = [f for f in fvgs if not f["filled"]]
    return active[-5:]  # Garder les 5 plus récents


def detect_order_blocks(candles: List[Dict]) -> List[Dict]:
    """
    Détecte les Order Blocks (OB) — dernière bougie opposée avant un move impulsif.
    OB Bullish = dernière bougie baissière avant une impulsion haussière.
    OB Bearish = dernière bougie haussière avant une impulsion baissière.
    Les institutions placent leurs ordres ici → le prix y revient souvent.
    """
    if len(candles) < 5:
        return []

    atr = _simple_atr(candles, 14)
    if atr <= 0:
        return []

    obs = []
    for i in range(1, len(candles) - 2):
        c = candles[i]
        c_next = candles[i + 1]
        c_next2 = candles[i + 2]
        body = c["close"] - c["open"]
        next_body = c_next["close"] - c_next["open"]
        next2_body = c_next2["close"] - c_next2["open"]

        # OB Bullish: bougie baissière suivie de 2 bougies haussières fortes
        if body < 0 and next_body > atr * 0.5 and next2_body > 0:
            obs.append({
                "type": "bullish_ob",
                "top": max(c["open"], c["close"]),
                "bottom": c["low"],
                "midpoint": (c["high"] + c["low"]) / 2,
                "candle_index": i,
                "strength": abs(next_body) / atr,
            })

        # OB Bearish: bougie haussière suivie de 2 bougies baissières fortes
        if body > 0 and next_body < -atr * 0.5 and next2_body < 0:
            obs.append({
                "type": "bearish_ob",
                "top": c["high"],
                "bottom": min(c["open"], c["close"]),
                "midpoint": (c["high"] + c["low"]) / 2,
                "candle_index": i,
                "strength": abs(next_body) / atr,
            })

    # Vérifier si le prix est proche d'un OB actif
    price = candles[-1]["close"]
    for ob in obs:
        ob["price_near"] = ob["bottom"] <= price <= ob["top"]
        ob["distance_pct"] = abs(price - ob["midpoint"]) / price * 100 if price else 0

    return obs[-6:]  # 6 plus récents


def get_smart_money_context(candles: List[Dict], instrument: str = "") -> Dict:
    """Résumé Smart Money pour le LLM et le dashboard."""
    fvgs = detect_fair_value_gaps(candles)
    obs = detect_order_blocks(candles)
    price = candles[-1]["close"] if candles else 0

    # FVGs proches du prix actuel
    nearby_fvgs = [f for f in fvgs if abs(price - f["midpoint"]) / price < 0.005] if price else []
    nearby_obs = [o for o in obs if o.get("distance_pct", 99) < 0.3]

    bullish_zones = [z for z in (nearby_fvgs + nearby_obs) if "bullish" in z["type"]]
    bearish_zones = [z for z in (nearby_fvgs + nearby_obs) if "bearish" in z["type"]]

    bias = "neutral"
    if bullish_zones and not bearish_zones:
        bias = "bullish"
    elif bearish_zones and not bullish_zones:
        bias = "bearish"

    context_lines = []
    for f in fvgs[-3:]:
        context_lines.append(f"FVG {f['type'].split('_')[0]}: {f['bottom']:.5f}-{f['top']:.5f}")
    for o in obs[-3:]:
        context_lines.append(f"OB {o['type'].split('_')[0]}: {o['bottom']:.5f}-{o['top']:.5f} (force={o['strength']:.1f})")

    return {
        "fvg_count": len(fvgs),
        "ob_count": len(obs),
        "nearby_bullish": len(bullish_zones),
        "nearby_bearish": len(bearish_zones),
        "smart_money_bias": bias,
        "zones_text": " | ".join(context_lines) if context_lines else "Aucune zone SMC active",
        "fvgs": fvgs,
        "order_blocks": obs,
    }


def _simple_atr(candles: List[Dict], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period if trs else 0.0


# ═══════════════════════════════════════════════════════════════════════════
# 4. TRAILING STOP / BREAK-EVEN MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def calculate_trail_levels(
    direction: str, entry_price: float, current_price: float,
    atr: float, sl_pips: float, pip_size: float
) -> Dict:
    """
    Calcule les niveaux de trailing stop et break-even.
    Logique institutionnelle:
    - Move SL to break-even quand le prix a bougé de 1×ATR en faveur
    - Trail le SL à 1.5×ATR derrière le prix quand profit > 2×ATR
    - Serrer le trail à 1×ATR quand profit > 3×ATR
    """
    if not entry_price or not current_price or not atr or atr <= 0:
        return {"action": "hold", "new_sl": None, "reason": "données insuffisantes"}

    if direction == "BUY":
        profit_pips = (current_price - entry_price) / pip_size
        trail_price = current_price - atr  # Trail standard
        tight_trail = current_price - atr * 0.7  # Trail serré
        breakeven = entry_price + pip_size * 2  # +2 pips pour couvrir spread
    elif direction == "SELL":
        profit_pips = (entry_price - current_price) / pip_size
        trail_price = current_price + atr
        tight_trail = current_price + atr * 0.7
        breakeven = entry_price - pip_size * 2
    else:
        return {"action": "hold", "new_sl": None, "reason": "direction inconnue"}

    atr_in_pips = atr / pip_size if pip_size else 0

    # Phase 1: Break-even (profit >= 1×ATR)
    if profit_pips >= atr_in_pips * 1.0 and profit_pips < atr_in_pips * 2.0:
        return {
            "action": "move_to_breakeven",
            "new_sl": round(breakeven, 5),
            "reason": f"Profit {profit_pips:.0f}p >= 1×ATR ({atr_in_pips:.0f}p) → SL à break-even",
            "profit_pips": round(profit_pips, 1),
        }

    # Phase 2: Trail standard (profit >= 2×ATR)
    if profit_pips >= atr_in_pips * 2.0 and profit_pips < atr_in_pips * 3.0:
        return {
            "action": "trail_standard",
            "new_sl": round(trail_price, 5),
            "reason": f"Profit {profit_pips:.0f}p >= 2×ATR → trail à 1×ATR derrière",
            "profit_pips": round(profit_pips, 1),
        }

    # Phase 3: Trail serré (profit >= 3×ATR)
    if profit_pips >= atr_in_pips * 3.0:
        return {
            "action": "trail_tight",
            "new_sl": round(tight_trail, 5),
            "reason": f"Profit {profit_pips:.0f}p >= 3×ATR → trail serré (0.7×ATR)",
            "profit_pips": round(profit_pips, 1),
        }

    return {
        "action": "hold",
        "new_sl": None,
        "reason": f"Profit {profit_pips:.0f}p < 1×ATR ({atr_in_pips:.0f}p) — pas encore de trailing",
        "profit_pips": round(profit_pips, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5. FILTRE DE CORRÉLATION INTER-PAIRES
# ═══════════════════════════════════════════════════════════════════════════

# Paires fortement corrélées (corrélation > 0.80)
CORRELATION_GROUPS = [
    {"group": "EUR_basket", "pairs": ["EURUSD", "EURUSDm", "EURGBP", "EURGBPm", "GBPUSD", "GBPUSDm"], "corr": 0.85},
    {"group": "safe_haven", "pairs": ["USDJPY", "USDJPYm", "USDCHF", "USDCHFm"], "corr": 0.82},
    {"group": "commodity", "pairs": ["AUDUSD", "AUDUSDm", "NZDUSD", "NZDUSDm"], "corr": 0.88},
    {"group": "gold_usd", "pairs": ["XAUUSD", "XAUUSDm", "EURUSD", "EURUSDm"], "corr": -0.75},
    {"group": "cad_oil", "pairs": ["USDCAD", "USDCADm", "CADJPY", "CADJPYm"], "corr": 0.78},
]


def check_correlation_risk(
    instrument: str, direction: str, open_positions: List[Dict]
) -> Dict:
    """
    Vérifie si un nouveau trade créerait un risque de corrélation.
    Si on est déjà long EURUSD, on ne doit pas ouvrir long GBPUSD (même basket).
    """
    if not open_positions:
        return {"blocked": False, "warnings": [], "reason": "Pas de position ouverte — pas de risque de corrélation"}

    inst_upper = instrument.upper()
    warnings = []
    blocked = False

    for group in CORRELATION_GROUPS:
        if inst_upper not in [p.upper() for p in group["pairs"]]:
            continue

        for pos in open_positions:
            pos_inst = str(pos.get("instrument", "")).upper()
            pos_dir = str(pos.get("direction", "")).upper()

            if pos_inst == inst_upper:
                continue  # Même instrument, géré ailleurs

            if pos_inst in [p.upper() for p in group["pairs"]]:
                corr = group["corr"]
                same_direction = (direction.upper() == pos_dir)

                # Corrélation positive + même direction = risque doublé
                if corr > 0 and same_direction:
                    warnings.append(
                        f"⚠️ {instrument} {direction} corrélé à {pos_inst} {pos_dir} "
                        f"(groupe {group['group']}, corr={corr})"
                    )
                    if corr >= 0.85:
                        blocked = True

                # Corrélation négative + directions opposées = aussi un problème
                if corr < 0 and not same_direction:
                    warnings.append(
                        f"⚠️ {instrument} {direction} inversement corrélé à {pos_inst} {pos_dir} "
                        f"(corr={corr}) — risque identique"
                    )

    return {
        "blocked": blocked,
        "warnings": warnings,
        "reason": warnings[0] if warnings else "Pas de corrélation détectée",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6. CONFLUENCE SCORE — Combinaison de toutes les stratégies
# ═══════════════════════════════════════════════════════════════════════════

def calculate_confluence(
    session_score: Dict, htf_bias: Dict, smc: Dict,
    signal_direction: str, signal_score: int
) -> Dict:
    """
    Score de confluence combinant toutes les stratégies pro.
    Plus le score est haut, plus le trade est de qualité institutionnelle.
    """
    points = 0
    max_points = 5
    details = []

    # 1. Session / Kill Zone (0-1 point)
    sq = session_score.get("instrument_quality", 0)
    if sq >= 0.7:
        points += 1
        details.append(f"✅ Kill Zone active ({session_score.get('label', '')})")
    elif sq >= 0.4:
        points += 0.5
        details.append(f"⚠️ Session acceptable ({session_score.get('label', '')})")
    else:
        details.append(f"❌ Hors session optimale")

    # 2. HTF Bias alignment (0-1.5 points)
    htf_dir = htf_bias.get("trade_with")
    if htf_dir and signal_direction:
        if htf_dir == signal_direction:
            bonus = 1.5 if htf_bias["strength"] >= 0.8 else 1.0
            points += bonus
            details.append(f"✅ HTF aligné ({htf_bias.get('context', '')})")
        else:
            points -= 0.5
            details.append(f"❌ CONTRE le biais HTF ({htf_bias.get('context', '')})")
    elif htf_bias.get("combined_bias") == "conflict":
        details.append(f"⚠️ Conflit HTF — prudence")

    # 3. Smart Money zones (0-1 point)
    smc_bias = smc.get("smart_money_bias", "neutral")
    if smc_bias != "neutral":
        if (smc_bias == "bullish" and signal_direction == "BUY") or \
           (smc_bias == "bearish" and signal_direction == "SELL"):
            points += 1
            details.append(f"✅ Zone SMC confirme ({smc.get('zones_text', '')[:60]})")
        else:
            points -= 0.5
            details.append(f"⚠️ Zone SMC oppose le signal")
    elif smc.get("fvg_count", 0) + smc.get("ob_count", 0) > 0:
        points += 0.3
        details.append(f"ℹ️ Zones SMC détectées mais pas proches du prix")

    # 4. Signal technique de base (0-1.5 points)
    if signal_score >= 4:
        points += 1.5
        details.append(f"✅ Signal technique fort ({signal_score}/5)")
    elif signal_score >= 3:
        points += 1.0
        details.append(f"✅ Signal technique correct ({signal_score}/5)")
    elif signal_score >= 2:
        points += 0.5
        details.append(f"⚠️ Signal technique faible ({signal_score}/5)")

    score = max(0, min(max_points, round(points, 1)))
    quality = "A" if score >= 4 else "B" if score >= 3 else "C" if score >= 2 else "D"

    return {
        "confluence_score": score,
        "max_score": max_points,
        "quality": quality,
        "details": details,
        "recommendation": _confluence_recommendation(score, quality),
    }


def _confluence_recommendation(score: float, quality: str) -> str:
    if quality == "A":
        return "TRADE — Confluence maximale, setup institutionnel"
    if quality == "B":
        return "TRADE — Bonne confluence, sizing normal"
    if quality == "C":
        return "PRUDENCE — Confluence limitée, réduire le sizing"
    return "ÉVITER — Pas assez de confluence, attendre un meilleur setup"


# ═══════════════════════════════════════════════════════════════════════════
# 7. CONTEXT BUILDER POUR LE LLM
# ═══════════════════════════════════════════════════════════════════════════

def build_strategies_context(
    instrument: str, candles_h1: List[Dict],
    candles_h4: List[Dict] = None, candles_d1: List[Dict] = None,
    signal_direction: str = None, signal_score: int = 0,
    open_positions: List[Dict] = None,
) -> Dict:
    """
    Construit le contexte complet de toutes les stratégies pro
    pour l'orchestrateur et le LLM.
    """
    session = get_session_score(instrument)
    htf = calculate_htf_bias(candles_h4 or [], candles_d1)
    smc = get_smart_money_context(candles_h1, instrument)
    confluence = calculate_confluence(session, htf, smc, signal_direction, signal_score)
    correlation = check_correlation_risk(
        instrument,
        signal_direction or "WAIT",
        open_positions or []
    )

    # Texte compact pour le prompt LLM
    llm_lines = []
    llm_lines.append(f"SESSION: {session['label']} (qualité={session['instrument_quality']})")
    llm_lines.append(f"HTF BIAS: {htf['context']}")
    if smc["zones_text"] != "Aucune zone SMC active":
        llm_lines.append(f"SMART MONEY: {smc['zones_text']}")
    llm_lines.append(f"CONFLUENCE: {confluence['confluence_score']}/{confluence['max_score']} ({confluence['quality']}) — {confluence['recommendation']}")
    if correlation["warnings"]:
        llm_lines.append(f"CORRÉLATION: {correlation['reason']}")

    return {
        "session": session,
        "htf_bias": htf,
        "smart_money": smc,
        "confluence": confluence,
        "correlation": correlation,
        "llm_context": "\n".join(llm_lines),
        "should_trade": confluence["quality"] in ("A", "B") and not correlation["blocked"],
    }
