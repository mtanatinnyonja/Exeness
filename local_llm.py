"""
Moteur LLM local du robot.
Analyse exclusivement via Ollama en localhost.
Si le LLM n'est pas disponible, le robot reste en attente.
"""

import json
import re
from typing import Dict, Optional
from urllib.parse import urlparse

try:
    import requests
except Exception:
    requests = None

from settings import (
    AI_PROVIDER, LOCAL_LLM_ENDPOINT, LOCAL_LLM_MODEL, LOCAL_LLM_TIMEOUT,
    MAX_LLM_CALLS_PER_DAY, LLM_TEMPERATURE, INITIAL_CAPITAL, MAX_RISK_PER_TRADE,
    DAILY_TARGET, DAILY_LOSS_LIMIT, DAILY_TOKEN_BUDGET, MIN_SIGNAL_SCORE,
    ONLY_ALLOW_LOCAL_LLM, LLM_MIN_CONFIDENCE, LLM_ANALYSIS_MODE,
    LLM_ANALYSIS_NOTES, LLM_MAX_CONTEXT_BARS,
)
from runtime_db import RuntimeStore


SYSTEM_PROMPT = """Tu es un trader professionnel MT5. Analyse le marché comme un humain: structure des bougies, price action, zones de support/résistance, rejets de niveaux clés. Les indicateurs sont secondaires — la lecture du graphique est prioritaire. Réponds en JSON strict. Priorité: capital preservation, ne trade que si la structure est claire."""


class LocalIntelligence:
    def __init__(self, memory):
        self.memory = memory
        self.store = RuntimeStore()
        self.requested_provider = AI_PROVIDER.lower().strip()
        self.local_llm_endpoint = LOCAL_LLM_ENDPOINT
        self.local_llm_model = LOCAL_LLM_MODEL
        self.local_llm_timeout = LOCAL_LLM_TIMEOUT
        self.max_llm_calls = MAX_LLM_CALLS_PER_DAY
        self.daily_token_budget = DAILY_TOKEN_BUDGET
        self.llm_temperature = LLM_TEMPERATURE
        self.min_confidence = LLM_MIN_CONFIDENCE
        self.analysis_mode = LLM_ANALYSIS_MODE
        self.analysis_notes = LLM_ANALYSIS_NOTES
        self.context_bars = LLM_MAX_CONTEXT_BARS
        self.provider = "ollama"
        self.last_prompt = ""
        self.last_raw_response = ""
        self.last_parsed_response = None
        self.last_analysis_instrument = ""
        self.last_analysis_timestamp = ""
        self.refresh_runtime_settings()

    def refresh_runtime_settings(self):
        settings = self.store.get_settings()
        self.requested_provider = "ollama"
        self.local_llm_endpoint = str(settings.get("local_llm_endpoint", LOCAL_LLM_ENDPOINT)).strip()
        self.local_llm_model = str(settings.get("local_llm_model", LOCAL_LLM_MODEL)).strip()
        self.local_llm_timeout = int(settings.get("local_llm_timeout", LOCAL_LLM_TIMEOUT))
        self.max_llm_calls = int(settings.get("max_llm_calls_per_day", MAX_LLM_CALLS_PER_DAY))
        self.daily_token_budget = int(settings.get("daily_token_budget", DAILY_TOKEN_BUDGET))
        self.llm_temperature = float(settings.get("llm_temperature", LLM_TEMPERATURE))
        self.min_confidence = float(settings.get("llm_min_confidence", LLM_MIN_CONFIDENCE))
        self.analysis_mode = str(settings.get("llm_analysis_mode", LLM_ANALYSIS_MODE)).strip()
        self.analysis_notes = str(settings.get("llm_analysis_notes", LLM_ANALYSIS_NOTES)).strip()
        self.context_bars = int(settings.get("llm_context_bars", LLM_MAX_CONTEXT_BARS))
        self.provider = self._select_provider()

    def _select_provider(self) -> str:
        if self._is_local_endpoint(self.local_llm_endpoint) and requests is not None:
            return "ollama"
        return "unavailable"

    def _approx_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def _is_local_endpoint(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            return parsed.hostname in {"127.0.0.1", "localhost"}
        except Exception:
            return False

    def _can_call_llm(self, prompt_tokens: int = 0) -> bool:
        if self.max_llm_calls > 0 and self.memory.get_llm_calls_today() >= self.max_llm_calls:
            return False
        token_usage = self.memory.get_token_usage_today()
        used = token_usage["prompt_tokens"] + token_usage["completion_tokens"]
        if self.daily_token_budget <= 0:
            return True
        return (used + prompt_tokens) < self.daily_token_budget

    def _extract_spread(self, market_context: str) -> float:
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*pips", market_context or "")
        return float(match.group(1)) if match else 0.0

    def _compact_memory_context(self, raw_text: str, limit: int = 800) -> str:
        compact = " ".join(str(raw_text or "").split())
        return compact[:limit]

    def _compact_details(self, details: Dict) -> Dict:
        """Keep only essential fields for LLM prompt to reduce token count."""
        keys = [
            "market_regime", "signal_bias", "rr_buy", "rr_sell",
            "rsi_14", "macd_signal", "bb_position",
            "momentum_5", "momentum_20",
            "distance_to_support_pips", "distance_to_resistance_pips",
        ]
        return {k: details[k] for k in keys if k in details}

    def _safe_wait(self, instrument: str, reason: str) -> Dict:
        return {
            "decision": "WAIT",
            "confidence": 0.0,
            "stop_loss_pips": 0,
            "take_profit_pips": 0,
            "reasoning": reason,
            "insight": f"{instrument}: WAIT | {reason}",
            "risk_note": "llm_only_mode",
        }

    def _technical_fallback_decision(self, instrument: str, signal: Dict, reason: str) -> Dict:
        details = signal.get("details", {}) or {}
        direction = signal.get("direction")
        score = int(signal.get("score", 0) or 0)
        atr_pips = max(6, int(round(float(signal.get("atr_pips", 12) or 12))))
        regime = str(details.get("market_regime", "unknown"))
        bias = float(details.get("signal_bias", 0) or 0)
        rr_buy = float(details.get("rr_buy", 0) or 0)
        rr_sell = float(details.get("rr_sell", 0) or 0)
        rr = rr_buy if direction == "BUY" else rr_sell if direction == "SELL" else 0.0
        pattern = str(signal.get("pattern") or details.get("candle_pattern") or "unknown")

        # Consulter la mémoire pour les filtres appris
        learned_filters = self.memory.memory.get("learned_filters", [])
        pattern_blocked = any(pattern.lower() in f.lower() for f in learned_filters)
        ml_prob = float(signal.get("ml_probability", 0.5) or 0.5)

        trend_ok = (
            (direction == "BUY" and regime == "trend_bullish") or
            (direction == "SELL" and regime == "trend_bearish") or
            regime == "volatile"
        )
        bias_ok = abs(bias) >= 1.0
        rr_ok = rr >= 1.2
        score_ok = score >= MIN_SIGNAL_SCORE

        if direction in {"BUY", "SELL"} and trend_ok and bias_ok and rr_ok and score_ok:
            # Bloquer si la mémoire a appris que ce pattern est perdant
            if pattern_blocked:
                return self._safe_wait(
                    instrument,
                    f"Pattern '{pattern}' bloqué par apprentissage mémoire. {reason}"
                )
            # Réduire la confiance si ML doute
            base_conf = 0.52 + (score * 0.05) + min(0.1, abs(bias) * 0.03)
            if ml_prob < 0.4:
                base_conf *= 0.8
            confidence = min(0.82, round(base_conf, 2))
            tp_pips = max(atr_pips * 2, int(round(atr_pips * max(1.6, min(3.0, rr)))))
            return {
                "decision": direction,
                "confidence": confidence,
                "stop_loss_pips": atr_pips,
                "take_profit_pips": tp_pips,
                "reasoning": f"Fallback technique: score={score}/5, regime={regime}, bias={bias:.2f}, RR={rr:.2f}, ML={ml_prob:.2f}.",
                "insight": f"{instrument}: {direction} via fallback technique (ML p={ml_prob:.2f})",
                "risk_note": "technical_fallback",
            }

        return self._safe_wait(
            instrument,
            f"Fallback prudent: score={score}/5, regime={regime}, bias={bias:.2f}, RR={rr:.2f}. {reason}"
        )

    def _coerce_json_result(self, raw_text: str) -> Optional[Dict]:
        text = (raw_text or "").strip()
        if not text:
            return None

        # Strip // and # comments that LLMs love to add in JSON
        def _strip_json_comments(s: str) -> str:
            lines = s.split("\n")
            cleaned = []
            for line in lines:
                # Remove // comments (but not inside strings)
                in_string = False
                i = 0
                result_line = line
                while i < len(line) - 1:
                    if line[i] == '"' and (i == 0 or line[i-1] != '\\'):
                        in_string = not in_string
                    if not in_string and line[i:i+2] == '//':
                        result_line = line[:i]
                        break
                    i += 1
                # Remove # comments (not inside strings)
                in_string = False
                i = 0
                temp = result_line
                while i < len(temp):
                    if temp[i] == '"' and (i == 0 or temp[i-1] != '\\'):
                        in_string = not in_string
                    if not in_string and temp[i] == '#':
                        result_line = temp[:i]
                        break
                    i += 1
                cleaned.append(result_line.rstrip())
            return "\n".join(cleaned)

        # Try cleaning comments first, then parse
        for candidate in [text, _strip_json_comments(text)]:
            try:
                return json.loads(candidate)
            except Exception:
                pass
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(candidate[start:end + 1])
                except Exception:
                    pass

        # Last resort: strip comments, extract JSON block, repair truncation
        cleaned = _strip_json_comments(text)
        start = cleaned.find("{")
        if start != -1:
            fragment = cleaned[start:]
            # Close any open string
            if fragment.count('"') % 2 == 1:
                fragment += '"'
            # Close open braces
            open_braces = fragment.count('{') - fragment.count('}')
            fragment += "}" * max(0, open_braces)
            try:
                return json.loads(fragment)
            except Exception:
                pass
        return None

    def _call_ollama(self, prompt: str, today_pnl: float, instrument: str) -> Optional[Dict]:
        if requests is None:
            self.memory.record_error("ollama", "package requests absent")
            return None
        if ONLY_ALLOW_LOCAL_LLM and not self._is_local_endpoint(self.local_llm_endpoint):
            self.memory.record_error("ollama", f"endpoint refusé: {self.local_llm_endpoint}")
            return None

        prompt_tokens = self._approx_tokens(prompt)
        if not self._can_call_llm(prompt_tokens):
            return None

        try:
            self.memory.increment_llm_calls()
            self.memory.record_token_usage(prompt_tokens=prompt_tokens, completion_tokens=0)
            self.last_prompt = SYSTEM_PROMPT + "\n\n" + prompt
            self.last_analysis_instrument = instrument
            from datetime import datetime as _dt
            self.last_analysis_timestamp = _dt.utcnow().isoformat()
            response = requests.post(
                self.local_llm_endpoint,
                headers={"Content-Type": "application/json"},
                json={
                    "model": self.local_llm_model,
                    "prompt": SYSTEM_PROMPT + "\n\n" + prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.llm_temperature,
                        "num_predict": 500,
                    },
                    "keep_alive": "10m",
                },
                timeout=self.local_llm_timeout,
            )
            response.raise_for_status()
            data = response.json()
            raw_text = (data.get("response") or "").strip()
            self.last_raw_response = raw_text
            result = self._coerce_json_result(raw_text)
            self.last_parsed_response = result
            if result is None:
                self.memory.record_error("ollama", f"réponse non-JSON: {raw_text[:180]}")
                return None

            completion_tokens = self._approx_tokens(raw_text)
            self.memory.record_token_usage(prompt_tokens=0, completion_tokens=completion_tokens)

            if result.get("insight"):
                self.memory.add_ai_insight(f"{instrument}: {result['insight']}")
            if result.get("confidence", 0) < self.min_confidence or today_pnl <= DAILY_LOSS_LIMIT:
                result["decision"] = "WAIT"
            return result
        except Exception as e:
            self.memory.record_error("ollama", str(e))
            return None

    def analyze_signal(self, instrument: str, signal: Dict, account_info: Dict, market_context: str = "", fast_mode: bool = False, candles: list = None) -> Optional[Dict]:
        self.refresh_runtime_settings()
        today_pnl = self.memory.get_daily_pnl()
        memory_context = self._compact_memory_context(self.memory.get_context_for_llm())
        spread = self._extract_spread(market_context)

        # Build price action description if candles provided
        price_action = ""
        if candles and len(candles) >= 10:
            from signal_engine import build_price_action_description
            price_action = build_price_action_description(candles, instrument)

        details = signal.get('details', {}) or {}
        regime = details.get('market_regime', 'unknown')
        rsi = details.get('rsi', 50)
        support = details.get('support', 0)
        resistance = details.get('resistance', 0)
        rr_buy = details.get('rr_buy', 0)
        rr_sell = details.get('rr_sell', 0)
        atr_pips = signal.get('atr_pips', 0)
        candle_pattern = details.get('candle_pattern', 'aucun')

        prompt = f"""=== ANALYSE {instrument} ===

STRUCTURE DU MARCHÉ (price action):
{price_action or 'Non disponible'}

CONTEXTE:
- Régime: {regime} | RSI: {rsi} | Pattern bougie: {candle_pattern}
- Support: {support} | Résistance: {resistance}
- ATR: {atr_pips} pips | Spread: {spread:.1f} pips
- RR achat: {rr_buy} | RR vente: {rr_sell}
- {market_context}

COMPTE: Balance {account_info.get('balance', 50):.0f}$ | PnL jour: {today_pnl:.2f}$ | Positions: {account_info.get('open_trades', 0)}
MÉMOIRE: {memory_context}

RÈGLES:
- Trade UNIQUEMENT si la structure price action confirme (rejets, breakouts, patterns clairs)
- Le SL doit être placé derrière un niveau structurel (support/résistance, mèche de rejet)
- Minimum RR 1.5:1 sinon WAIT
- En range sans pattern clair → WAIT
- stop_loss_pips = distance en pips jusqu'au niveau structurel (pas juste ATR)
- take_profit_pips = objectif basé sur le prochain niveau clé

JSON uniquement (pas de commentaires //, pas de #, pas d'expressions mathématiques dans les valeurs):
{{"decision":"BUY|SELL|WAIT","confidence":0.0-1.0,"stop_loss_pips":N,"take_profit_pips":N,"reasoning":"analyse price action courte","insight":"résumé"}}"""

        result = None
        from datetime import datetime as _dt
        self.last_analysis_instrument = instrument
        self.last_analysis_timestamp = _dt.utcnow().isoformat()

        if fast_mode:
            self.last_prompt = f"[MODE RAPIDE - règles locales]\n\n{prompt}"
            result = self._technical_fallback_decision(
                instrument,
                signal,
                "Décision rapide locale (règles + indicateurs, sans appel LLM)."
            )
            self.last_raw_response = json.dumps(result, ensure_ascii=False, indent=2) if result else ""
            self.last_parsed_response = result
        elif self.provider == "ollama":
            result = self._call_ollama(prompt, today_pnl, instrument)

        if result is None:
            self.last_prompt = f"[FALLBACK - LLM indisponible]\n\n{prompt}"
            result = self._technical_fallback_decision(
                instrument,
                signal,
                f"LLM Ollama a échoué (timeout/erreur/JSON invalide). Modèle: {self.local_llm_model}."
            )
            self.last_raw_response = json.dumps(result, ensure_ascii=False, indent=2) if result else ""
            self.last_parsed_response = result

        self.memory.log_session(
            f"🤖 {self.provider} → {instrument}: {result['decision']} "
            f"(conf: {result.get('confidence', 0):.2f}) | {result.get('reasoning', '')[:200]}"
        )
        return result

    def get_last_exchange(self) -> Dict:
        """Return the last prompt/response exchange for dashboard display."""
        return {
            "instrument": self.last_analysis_instrument,
            "timestamp": self.last_analysis_timestamp,
            "prompt": self.last_prompt,
            "raw_response": self.last_raw_response,
            "parsed_response": self.last_parsed_response,
            "provider": self.provider,
            "model": self.local_llm_model,
        }

    def get_market_summary(self, instruments_data: Dict) -> str:
        token_usage = self.memory.get_token_usage_today()
        return (
            f"Provider={self.provider} | LLM calls={self.memory.get_llm_calls_today()} | "
            f"Tokens={token_usage['prompt_tokens'] + token_usage['completion_tokens']}/{self.daily_token_budget}"
        )
