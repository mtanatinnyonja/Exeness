"""
Structure de communication pour les agents IA de trading.

Ce module construit des messages clairs entre Analyste, Risk Manager,
Décideur et, si activé, un Relecteur final.
"""

from typing import Dict, List


def build_conversation_header(instrument: str, ctx: Dict) -> str:
    market_context = ctx.get("market_context", {})
    signal = ctx.get("signal", {})
    details = signal.get("details", {})
    return (
        f"INSTRUMENT: {instrument}\n"
        f"Signal: {signal.get('direction','WAIT')} score={signal.get('score',0)}/5\n"
        f"Regime: {details.get('market_regime','?')} | Market: {market_context.get('category','?')} ({market_context.get('reason','?')})\n"
        f"RSI={details.get('rsi',0):.1f} | ATR={signal.get('atr_pips',0)}p | Spread={ctx.get('spread',0):.1f}p\n"
        f"Confluence: {ctx['strategies']['confluence']['quality']} ({ctx['strategies']['confluence']['confluence_score']}/{ctx['strategies']['confluence']['max_score']})\n"
        f"Position ouvertes: {len(ctx.get('open_positions', []))} | Trades today: {ctx.get('trades_today', 0)}\n"
        f"Plan: {ctx.get('trade_plan', {}).get('direction', 'WAIT')} conf={ctx.get('trade_plan', {}).get('confidence', 0):.2f} "
        f"blocked={ctx.get('trade_plan', {}).get('is_blocking', False)}"
    )


def build_agent_message(role: str, content: str) -> str:
    return f"--- {role} ---\n{content.strip()}\n"


def build_analyst_prompt(instrument: str, ctx: Dict) -> str:
    header = build_conversation_header(instrument, ctx)
    plan = ctx.get("trade_plan", {})
    plan_text = (
        f"Plan initial: direction={plan.get('direction')} confidence={plan.get('confidence'):.2f} "
        f"blocked={plan.get('is_blocking')} notes={plan.get('notes', [])}\n"
    ) if plan else ""
    return (
        f"{header}\n"
        f"{plan_text}"
        "Tu es l'Analyste. Lis le contexte, explique pourquoi tu penses que c'est un bon ou mauvais setup, "
        "et propose une direction claire. Réponds en JSON unique.\n"
        "Format attendu: {\"direction\": \"BUY|SELL|NEUTRAL\", \"force\": 1-5, \"setup\": \"texte court\", \"reasoning\": \"texte court\"}"
    )


def build_risk_prompt(instrument: str, ctx: Dict, analyste: Dict) -> str:
    header = build_conversation_header(instrument, ctx)
    return (
        f"{header}\n"
        "Tu es le Risk Manager. Analyse la proposition de l'Analyste et évalue les risques. "
        "Sois exigeant et explique les conditions de blocage. Réponds en JSON unique.\n"
        f"Analyste: direction={analyste.get('direction')} force={analyste.get('force')} setup={analyste.get('setup')} reasoning={analyste.get('reasoning')}\n"
        "Format attendu: {\"approved\": true/false, \"risk_score\": 1-10, \"sl_pips\": N, \"tp_pips\": N, \"risk_notes\": \"texte court\"}"
    )


def build_decider_prompt(instrument: str, ctx: Dict, analyste: Dict, risk: Dict) -> str:
    header = build_conversation_header(instrument, ctx)
    return (
        f"{header}\n"
        "Tu es le Décideur final. Tu reçois l'analyse de l'Analyste et l'évaluation du Risk Manager. "
        "Prends une décision raisonnée comme un trader humain. En cas de doute, choisis WAIT. "
        "Réponds en JSON unique.\n"
        f"Analyste: direction={analyste.get('direction')} force={analyste.get('force')} reasoning={analyste.get('reasoning')}\n"
        f"Risk: approved={risk.get('approved')} risk_score={risk.get('risk_score')} sl={risk.get('sl_pips')} tp={risk.get('tp_pips')} notes={risk.get('risk_notes')}\n"
        "Format attendu: {\"decision\": \"BUY|SELL|WAIT\", \"confidence\": 0.0-1.0, \"stop_loss_pips\": N, \"take_profit_pips\": N, \"reasoning\": \"texte court\"}"
    )


def build_reviewer_prompt(instrument: str, ctx: Dict, analyste: Dict, risk: Dict, decideur: Dict) -> str:
    header = build_conversation_header(instrument, ctx)
    return (
        f"{header}\n"
        "Tu es le Relecteur. Vérifie l'ensemble de la discussion et dis si la décision finale est sensée. "
        "Ne change pas le setup, mais commente et bloque si tu vois un artefact de bot ou une incohérence. "
        "Réponds en JSON unique.\n"
        f"Analyste: direction={analyste.get('direction')} force={analyste.get('force')} setup={analyste.get('setup')}\n"
        f"Risk: approved={risk.get('approved')} risk_score={risk.get('risk_score')} sl={risk.get('sl_pips')} tp={risk.get('tp_pips')}\n"
        f"Décideur: decision={decideur.get('decision')} confidence={decideur.get('confidence')} reasoning={decideur.get('reasoning')}\n"
        "Format attendu: {\"allow\": true/false, \"reasoning\": \"texte court\"}"
    )
