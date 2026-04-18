"""
Trade planner pour un agent IA plus discret et humain.
"""

from typing import Dict, List


def plan_trade_idea(ctx: Dict, open_positions: List[Dict], config: Dict) -> Dict:
    signal = ctx.get("signal", {})
    details = signal.get("details", {})
    market_context = ctx.get("market_context", {"category": "unknown", "reason": "?"})
    score = int(signal.get("score", 0) or 0)
    direction = signal.get("direction")
    bias = abs(float(details.get("signal_bias", 0) or 0))
    category = market_context.get("category", "unknown")

    plan = {
        "decision": "WAIT",
        "direction": None,
        "confidence": 0.0,
        "is_blocking": False,
        "reasoning": "Analyse du plan de trading en cours",
        "notes": [],
    }

    if direction not in ("BUY", "SELL"):
        plan["reasoning"] = "Pas de direction technique claire"
        plan["notes"].append("signal absent ou indéterminé")
        return plan

    plan["direction"] = direction
    plan["confidence"] = min(1.0, max(0.0, score / 5.0 + 0.1))
    plan["decision"] = direction

    if score < config["human_like_min_score"]:
        plan["notes"].append(f"score trop faible ({score} < {config['human_like_min_score']})")
        plan["confidence"] = min(plan["confidence"], 0.35)
        plan["is_blocking"] = True

    if category == "range" and score < 4:
        plan["notes"].append("range sans confirmation suffisante")
        plan["confidence"] = min(plan["confidence"], 0.30)
        plan["is_blocking"] = True

    if category == "uncertain" and score < 4:
        plan["notes"].append("marché incertain et signal faible")
        plan["confidence"] = min(plan["confidence"], 0.25)
        plan["is_blocking"] = True

    if bias < config["human_like_min_bias"] and score < 4:
        plan["notes"].append("biais du signal faible")
        plan["confidence"] = min(plan["confidence"], 0.30)
        plan["is_blocking"] = True

    if len(open_positions) >= config["max_open_positions"]:
        plan["notes"].append("trop de positions ouvertes")
        plan["is_blocking"] = True
        plan["confidence"] = 0.0

    if config.get("max_trades_per_day", 0) > 0:
        trades_today = config.get("trades_today", 0)
        if trades_today >= config["max_trades_per_day"]:
            plan["notes"].append(
                f"plafond de trades journaliers atteint ({trades_today}/{config['max_trades_per_day']})"
            )
            plan["is_blocking"] = True
            plan["confidence"] = 0.0

    if config.get("recent_trades", 0) >= config.get("max_recent_trades", 2):
        plan["notes"].append("trop de trades récents")
        plan["is_blocking"] = True
        plan["confidence"] = min(plan["confidence"], 0.25)

    # Adapter la probabilité sur l'objectif journalier souple
    target_trades = max(1, config.get("target_trades_per_day", 2))
    trades_today = max(0, config.get("trades_today", 0))
    if trades_today < config.get("min_trades_per_day", 1):
        urgency_bonus = 0.05 * (config.get("min_trades_per_day", 1) - trades_today)
        plan["confidence"] = min(1.0, plan["confidence"] + urgency_bonus)
        plan["notes"].append("objectif de trade journalier actif")

    plan["probability"] = round(
        min(
            1.0,
            plan["confidence"] * (
                1.0 + max(0.0, (target_trades - trades_today) / max(1, target_trades)) * 0.2
            )
        ),
        2
    )
    plan["reasoning"] = (
        f"Plan {direction} score={score} category={category} bias={bias:.2f}",
        f"prob={plan['probability']:.2f}",
        f"notes={', '.join(plan['notes'])}" if plan["notes"] else "notes=ok"
    )
    plan["reasoning"] = " | ".join([p for p in plan["reasoning"] if p])

    return plan
