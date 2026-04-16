"""
Protections anti-manipulation broker et institutionnelle.

1. Détection de spread anormal (spread spike)
2. Détection de ghost candles (pics artificiels)
3. Protection slippage (risque d'exécution dégradée)
4. Zones de round numbers (niveaux ronds = pièges à stops)
5. News spike guard (volatilité post-news)
6. Liquidity Sweep detection (SMC)
7. Break of Structure / Change of Character (BOS/CHoCH)
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════
# 1. SPREAD SPIKE DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def detect_spread_spike(
    current_spread: float,
    candles: List[Dict],
    pip_size: float,
    lookback: int = 20,
    spike_ratio: float = 2.5,
) -> Dict:
    """
    Compare le spread actuel au spread moyen récent (via range des bougies).
    Un spread > spike_ratio × moyenne = manipulation probable (broker widening).
    """
    if not candles or len(candles) < lookback:
        return {"spike": False, "ratio": 1.0, "reason": "Données insuffisantes"}

    # Estimer le spread moyen via le range moyen récent (proxy fiable)
    recent = candles[-lookback:]
    ranges = [(c["high"] - c["low"]) / pip_size for c in recent]
    avg_range = sum(ranges) / len(ranges) if ranges else 0

    # Le spread normal est ~10-20% du range moyen d'une bougie H1
    # Si le spread dépasse spike_ratio × sa proportion normale, c'est suspect
    if avg_range <= 0:
        return {"spike": False, "ratio": 1.0, "reason": "Range nul"}

    spread_to_range = current_spread / avg_range
    # Normal: spread = ~5-15% du range. >40% = très suspect
    is_spike = spread_to_range > 0.40 or current_spread > avg_range * spike_ratio

    return {
        "spike": is_spike,
        "ratio": round(spread_to_range, 3),
        "current_spread": round(current_spread, 2),
        "avg_range": round(avg_range, 2),
        "reason": f"Spread {current_spread:.1f} = {spread_to_range*100:.0f}% du range moyen ({avg_range:.1f}p)"
                  if is_spike else "Spread normal",
        "severity": "HIGH" if spread_to_range > 0.60 else "MEDIUM" if is_spike else "LOW",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. GHOST CANDLE / PRICE SPIKE DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def detect_ghost_candle(candles: List[Dict], lookback: int = 30) -> Dict:
    """
    Détecte les ghost candles = bougies avec une mèche anormalement longue
    par rapport au body et au range moyen. Visible uniquement chez un broker
    (absent des charts d'autres sources).
    Pattern: wick > 3× body ET wick > 2× average range.
    """
    if len(candles) < lookback + 1:
        return {"detected": False, "candles": []}

    recent = candles[-(lookback + 1):-1]  # Exclure la bougie en cours
    avg_range = sum(c["high"] - c["low"] for c in recent) / len(recent) if recent else 0

    if avg_range <= 0:
        return {"detected": False, "candles": []}

    ghosts = []
    # Vérifier les 5 dernières bougies fermées
    for c in candles[-6:-1]:
        body = abs(c["close"] - c["open"])
        upper_wick = c["high"] - max(c["open"], c["close"])
        lower_wick = min(c["open"], c["close"]) - c["low"]
        total_range = c["high"] - c["low"]
        max_wick = max(upper_wick, lower_wick)

        # Ghost = mèche énorme, corps minuscule, range anormal
        body_safe = max(body, avg_range * 0.01)
        if max_wick > body_safe * 3 and total_range > avg_range * 2.0:
            direction = "up_spike" if upper_wick > lower_wick else "down_spike"
            ghosts.append({
                "direction": direction,
                "wick_ratio": round(max_wick / body_safe, 1),
                "range_ratio": round(total_range / avg_range, 1),
                "high": c["high"],
                "low": c["low"],
            })

    return {
        "detected": len(ghosts) > 0,
        "count": len(ghosts),
        "candles": ghosts[-3:],
        "reason": f"{len(ghosts)} ghost candle(s) détectée(s)" if ghosts else "Pas de ghost candle",
        "severity": "HIGH" if len(ghosts) >= 2 else "MEDIUM" if ghosts else "LOW",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3. SLIPPAGE RISK ESTIMATION
# ═══════════════════════════════════════════════════════════════════════════

def estimate_slippage_risk(
    current_spread: float,
    candles: List[Dict],
    pip_size: float,
    hour_utc: int = None,
) -> Dict:
    """
    Estime le risque de slippage basé sur:
    - Spread actuel (élevé = faible liquidité)
    - Volatilité récente (haute = plus de slippage)
    - Heure (nuit/weekend = spread élargi + faible liquidité)
    """
    if hour_utc is None:
        hour_utc = datetime.now(timezone.utc).hour

    # Heures à risque (faible liquidité)
    low_liquidity_hours = {0, 1, 2, 3, 4, 5, 20, 21, 22, 23}
    is_low_liq = hour_utc in low_liquidity_hours

    # Volatilité récente (5 dernières bougies)
    if candles and len(candles) >= 5:
        recent_5 = candles[-5:]
        vol_5 = sum((c["high"] - c["low"]) / pip_size for c in recent_5) / 5
    else:
        vol_5 = 0

    # Score de risque 0-1
    risk = 0.0
    reasons = []

    if is_low_liq:
        risk += 0.3
        reasons.append("Heure de faible liquidité")

    if current_spread > 3.0:
        risk += min(0.3, (current_spread - 3.0) * 0.05)
        reasons.append(f"Spread élevé ({current_spread:.1f}p)")

    if vol_5 > 0 and current_spread > vol_5 * 0.3:
        risk += 0.2
        reasons.append("Spread disproportionné vs volatilité")

    risk = min(1.0, risk)
    level = "HIGH" if risk >= 0.6 else "MEDIUM" if risk >= 0.3 else "LOW"

    return {
        "risk_score": round(risk, 2),
        "level": level,
        "is_low_liquidity_hour": is_low_liq,
        "reasons": reasons,
        "recommendation": "ÉVITER l'entrée" if risk >= 0.6
                          else "Réduire le sizing" if risk >= 0.3
                          else "Risque acceptable",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 4. ROUND NUMBER ZONES (piège à stops institutionnels)
# ═══════════════════════════════════════════════════════════════════════════

def detect_round_number_proximity(
    price: float,
    instrument: str,
    pip_size: float,
    proximity_pips: float = 15.0,
) -> Dict:
    """
    Détecte si le prix est proche d'un round number.
    Les round numbers (1.3000, 1900.00, etc.) concentrent les stop-loss
    → cibles prioritaires des institutions pour les liquidity grabs.
    """
    inst_upper = instrument.upper()

    # Déterminer l'intervalle des round numbers selon l'instrument
    if "XAU" in inst_upper or "GOLD" in inst_upper:
        round_interval = 10.0    # 1900, 1910, 1920...
        major_interval = 50.0    # 1900, 1950, 2000...
    elif "BTC" in inst_upper:
        round_interval = 500.0   # 60000, 60500...
        major_interval = 1000.0  # 60000, 61000...
    elif "ETH" in inst_upper:
        round_interval = 50.0
        major_interval = 100.0
    elif "JPY" in inst_upper:
        round_interval = 0.5     # 150.000, 150.500...
        major_interval = 1.0     # 150.000, 151.000...
    else:
        # Forex standard (EURUSD, GBPUSD, etc.)
        round_interval = 0.01    # 1.3000, 1.3100...
        major_interval = 0.005   # 1.3000, 1.3050...

    # Distance au round number le plus proche
    nearest_round = round(price / round_interval) * round_interval
    distance_round = abs(price - nearest_round) / pip_size

    nearest_major = round(price / major_interval) * major_interval
    distance_major = abs(price - nearest_major) / pip_size

    near_round = distance_round <= proximity_pips
    near_major = distance_major <= proximity_pips

    level = nearest_major if near_major else nearest_round if near_round else None

    return {
        "near_round_number": near_round or near_major,
        "is_major": near_major,
        "nearest_level": round(level, 5) if level else None,
        "distance_pips": round(min(distance_round, distance_major), 1),
        "reason": f"Prix à {min(distance_round, distance_major):.0f}p du round {level:.5g}"
                  if (near_round or near_major) else "Pas de round number proche",
        "warning": "⚠️ Zone de stop hunting probable — SL hors de la zone ou attendre le sweep"
                   if near_major else
                   "ℹ️ Proche d'un round number mineur"
                   if near_round else "",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5. NEWS SPIKE GUARD (volatilité post-annonce)
# ═══════════════════════════════════════════════════════════════════════════

def detect_news_spike(candles: List[Dict], lookback: int = 20) -> Dict:
    """
    Détecte un spike de volatilité brutal (souvent causé par une news
    high impact). La bougie la plus récente est anormalement grande.
    Entrer pendant un spike = slippage garanti + SL touché.
    """
    if len(candles) < lookback + 1:
        return {"spike": False, "ratio": 1.0}

    recent = candles[-(lookback + 1):-1]
    avg_range = sum(c["high"] - c["low"] for c in recent) / len(recent)
    if avg_range <= 0:
        return {"spike": False, "ratio": 1.0}

    last = candles[-1]
    last_range = last["high"] - last["low"]
    ratio = last_range / avg_range

    is_spike = ratio > 3.0  # Bougie 3x plus grande que la moyenne

    return {
        "spike": is_spike,
        "ratio": round(ratio, 2),
        "avg_range": avg_range,
        "last_range": last_range,
        "reason": f"Bougie actuelle {ratio:.1f}× la moyenne — spike de news probable"
                  if is_spike else "Volatilité normale",
        "severity": "HIGH" if ratio > 5.0 else "MEDIUM" if is_spike else "LOW",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6. LIQUIDITY SWEEP DETECTION (SMC)
# ═══════════════════════════════════════════════════════════════════════════

def detect_liquidity_sweep(candles: List[Dict], lookback: int = 50) -> Dict:
    """
    Détecte un Liquidity Sweep (Grab):
    - Le prix casse un swing high/low récent (prend la liquidité)
    - Puis reverse immédiatement (clôture de l'autre côté)
    
    C'est LE pattern le plus rentable du SMC:
    les institutions sweepent les stops → accumulent → poussent dans l'autre sens.
    
    Signal: entrer APRÈS le sweep, dans la direction du retour.
    """
    if len(candles) < lookback:
        return {"detected": False, "sweeps": []}

    window = candles[-lookback:]
    highs = [c["high"] for c in window]
    lows = [c["low"] for c in window]

    # Trouver les swing highs et swing lows significatifs
    swing_highs = _find_swing_points(window, "high", left=3, right=1)
    swing_lows = _find_swing_points(window, "low", left=3, right=1)

    sweeps = []

    # Vérifier les 5 dernières bougies pour un sweep récent
    for i in range(-5, 0):
        if abs(i) > len(candles):
            continue
        c = candles[i]

        # Sweep haussier (fake breakout au-dessus) → signal SELL
        for sh in swing_highs:
            if c["high"] > sh["level"] and c["close"] < sh["level"]:
                # Mèche au-dessus du swing high mais clôture en dessous = balayage
                sweeps.append({
                    "type": "bearish_sweep",
                    "direction": "SELL",
                    "swept_level": round(sh["level"], 5),
                    "wick_high": round(c["high"], 5),
                    "close": round(c["close"], 5),
                    "penetration": round(c["high"] - sh["level"], 5),
                    "candle_index": i,
                    "context": f"Sweep au-dessus du swing high {sh['level']:.5g} → rejet baissier",
                })

        # Sweep baissier (fake breakout en dessous) → signal BUY
        for sl in swing_lows:
            if c["low"] < sl["level"] and c["close"] > sl["level"]:
                sweeps.append({
                    "type": "bullish_sweep",
                    "direction": "BUY",
                    "swept_level": round(sl["level"], 5),
                    "wick_low": round(c["low"], 5),
                    "close": round(c["close"], 5),
                    "penetration": round(sl["level"] - c["low"], 5),
                    "candle_index": i,
                    "context": f"Sweep en dessous du swing low {sl['level']:.5g} → rejet haussier",
                })

    # Garder les plus récents
    sweeps = sweeps[-3:]

    # Déterminer le biais
    if sweeps:
        latest = sweeps[-1]
        bias = latest["direction"]
    else:
        bias = None

    return {
        "detected": len(sweeps) > 0,
        "count": len(sweeps),
        "sweeps": sweeps,
        "signal_direction": bias,
        "context": sweeps[-1]["context"] if sweeps else "Pas de liquidity sweep détecté",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 7. BREAK OF STRUCTURE / CHANGE OF CHARACTER (BOS / CHoCH)
# ═══════════════════════════════════════════════════════════════════════════

def detect_bos_choch(candles: List[Dict], lookback: int = 50) -> Dict:
    """
    BOS (Break of Structure):
    - Bullish BOS = nouveau Higher High (prix casse et clôture au-dessus du swing high précédent)
    - Bearish BOS = nouveau Lower Low (prix casse et clôture en dessous du swing low précédent)
    → Confirme la continuation de la tendance.

    CHoCH (Change of Character):
    - Bullish CHoCH = dans un downtrend, prix casse le swing high → renversement
    - Bearish CHoCH = dans un uptrend, prix casse le swing low → renversement
    → Signal de retournement de tendance.

    La différence: BOS = continuation, CHoCH = retournement.
    """
    if len(candles) < lookback:
        return {"bos": None, "choch": None, "trend": "undefined"}

    window = candles[-lookback:]

    # Identifier la structure de marché (swing highs + swing lows)
    swing_highs = _find_swing_points(window, "high", left=3, right=2)
    swing_lows = _find_swing_points(window, "low", left=3, right=2)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {"bos": None, "choch": None, "trend": "undefined",
                "context": "Structure insuffisante pour BOS/CHoCH"}

    # Déterminer la tendance en cours
    last_sh = swing_highs[-1]["level"]
    prev_sh = swing_highs[-2]["level"]
    last_sl = swing_lows[-1]["level"]
    prev_sl = swing_lows[-2]["level"]

    # Uptrend = HH + HL, Downtrend = LH + LL
    hh = last_sh > prev_sh  # Higher High
    hl = last_sl > prev_sl  # Higher Low
    lh = last_sh < prev_sh  # Lower High
    ll = last_sl < prev_sl  # Lower Low

    if hh and hl:
        trend = "bullish"
    elif lh and ll:
        trend = "bearish"
    else:
        trend = "transitional"

    current_price = candles[-1]["close"]
    bos = None
    choch = None

    # BOS: continuation de la tendance
    if trend == "bullish" and current_price > last_sh:
        bos = {
            "type": "bullish_bos",
            "direction": "BUY",
            "broken_level": round(last_sh, 5),
            "context": f"BOS haussier: prix {current_price:.5g} casse le swing high {last_sh:.5g} → continuation haussière",
        }
    elif trend == "bearish" and current_price < last_sl:
        bos = {
            "type": "bearish_bos",
            "direction": "SELL",
            "broken_level": round(last_sl, 5),
            "context": f"BOS baissier: prix {current_price:.5g} casse le swing low {last_sl:.5g} → continuation baissière",
        }

    # CHoCH: renversement de tendance
    if trend == "bearish" and current_price > last_sh:
        choch = {
            "type": "bullish_choch",
            "direction": "BUY",
            "broken_level": round(last_sh, 5),
            "context": f"CHoCH haussier: prix {current_price:.5g} casse le high {last_sh:.5g} en downtrend → renversement probable",
        }
    elif trend == "bullish" and current_price < last_sl:
        choch = {
            "type": "bearish_choch",
            "direction": "SELL",
            "broken_level": round(last_sl, 5),
            "context": f"CHoCH baissier: prix {current_price:.5g} casse le low {last_sl:.5g} en uptrend → renversement probable",
        }

    # Contexte résumé
    parts = [f"Tendance structure: {trend}"]
    parts.append(f"Swing HH={hh} HL={hl} LH={lh} LL={ll}")
    if bos:
        parts.append(bos["context"])
    if choch:
        parts.append(choch["context"])

    return {
        "trend": trend,
        "bos": bos,
        "choch": choch,
        "swing_highs": [sh["level"] for sh in swing_highs[-3:]],
        "swing_lows": [sl["level"] for sl in swing_lows[-3:]],
        "higher_high": hh,
        "higher_low": hl,
        "lower_high": lh,
        "lower_low": ll,
        "context": " | ".join(parts),
    }


# ═══════════════════════════════════════════════════════════════════════════
# HELPER: Swing point detection (partagé)
# ═══════════════════════════════════════════════════════════════════════════

def _find_swing_points(candles: List[Dict], point_type: str, left: int = 3, right: int = 2) -> List[Dict]:
    """
    Trouve les pivot points (swing highs ou swing lows) dans les candles.
    left/right = nombre de bougies de chaque côté pour confirmer le pivot.
    """
    points = []
    key = "high" if point_type == "high" else "low"
    n = len(candles)

    for i in range(left, n - right):
        val = candles[i][key]
        window = [candles[j][key] for j in range(i - left, i + right + 1)]

        if point_type == "high" and val == max(window):
            points.append({"index": i, "level": val})
        elif point_type == "low" and val == min(window):
            points.append({"index": i, "level": val})

    return points


# ═══════════════════════════════════════════════════════════════════════════
# 8. CONTEXTE COMPLET ANTI-MANIPULATION POUR L'ORCHESTRATEUR
# ═══════════════════════════════════════════════════════════════════════════

def run_all_protections(
    instrument: str,
    candles: List[Dict],
    current_spread: float,
    pip_size: float,
    price: float = None,
) -> Dict:
    """
    Lance toutes les protections en un seul appel.
    Retourne un résumé + risk_adjustment factor.
    """
    if price is None and candles:
        price = candles[-1]["close"]

    hour_utc = datetime.now(timezone.utc).hour

    spread_check = detect_spread_spike(current_spread, candles, pip_size)
    ghost_check = detect_ghost_candle(candles)
    slippage_check = estimate_slippage_risk(current_spread, candles, pip_size, hour_utc)
    news_spike = detect_news_spike(candles)
    round_num = detect_round_number_proximity(price or 0, instrument, pip_size) if price else {}
    liquidity = detect_liquidity_sweep(candles)
    structure = detect_bos_choch(candles)

    # Calculer le facteur de risque global
    risk_adj = 1.0
    warnings = []
    hard_blocks = []

    # Spread spike = hard block (broker manipulation probable)
    if spread_check.get("severity") == "HIGH":
        hard_blocks.append(f"🔴 Spread spike CRITIQUE: {spread_check['reason']}")
        risk_adj = 0.0
    elif spread_check.get("spike"):
        warnings.append(f"🟠 {spread_check['reason']}")
        risk_adj *= 0.5

    # Ghost candle = hard block
    if ghost_check.get("severity") == "HIGH":
        hard_blocks.append(f"🔴 Ghost candles multiples détectées")
        risk_adj = 0.0
    elif ghost_check.get("detected"):
        warnings.append(f"🟠 Ghost candle détectée — prudence")
        risk_adj *= 0.6

    # Slippage élevé = réduire sizing
    if slippage_check.get("level") == "HIGH":
        warnings.append(f"🟠 Risque de slippage élevé: {', '.join(slippage_check.get('reasons', []))}")
        risk_adj *= 0.4
    elif slippage_check.get("level") == "MEDIUM":
        risk_adj *= 0.7

    # News spike = hard block
    if news_spike.get("severity") == "HIGH":
        hard_blocks.append(f"🔴 Spike de news violent ({news_spike['ratio']:.1f}× la moyenne)")
        risk_adj = 0.0
    elif news_spike.get("spike"):
        warnings.append(f"🟠 Volatilité post-news ({news_spike['ratio']:.1f}×)")
        risk_adj *= 0.5

    # Round number = avertissement (pas de block, mais ajustement SL)
    if round_num.get("near_round_number") and round_num.get("is_major"):
        warnings.append(f"⚠️ {round_num['reason']} — zone de stop hunting")

    # Liquidity sweep = signal directionnel (pas un block, c'est une opportunité)
    if liquidity.get("detected"):
        warnings.append(f"📍 Liquidity sweep détecté: {liquidity['context']}")

    # BOS/CHoCH = contexte directionnel
    if structure.get("bos"):
        warnings.append(f"📈 {structure['bos']['context']}")
    if structure.get("choch"):
        warnings.append(f"🔄 {structure['choch']['context']}")

    blocked = len(hard_blocks) > 0

    # Texte compact pour le LLM
    llm_lines = []
    for hb in hard_blocks:
        llm_lines.append(hb)
    for w in warnings:
        llm_lines.append(w)
    if liquidity.get("detected"):
        llm_lines.append(f"LIQUIDITY SWEEP: {liquidity['signal_direction']} signal après sweep de {liquidity['sweeps'][-1]['swept_level']:.5g}")
    if structure.get("bos") or structure.get("choch"):
        llm_lines.append(f"STRUCTURE: {structure['context']}")

    return {
        "blocked": blocked,
        "risk_adjustment": round(max(0, risk_adj), 2),
        "hard_blocks": hard_blocks,
        "warnings": warnings,
        "spread_check": spread_check,
        "ghost_check": ghost_check,
        "slippage_check": slippage_check,
        "news_spike": news_spike,
        "round_number": round_num,
        "liquidity_sweep": liquidity,
        "structure": structure,
        "llm_context": "\n".join(llm_lines) if llm_lines else "Aucune alerte anti-manipulation",
    }
