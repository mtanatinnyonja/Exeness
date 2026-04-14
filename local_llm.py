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


SYSTEM_PROMPT = """Tu es un analyste MT5 expert, précis et conservateur.
Tu travailles uniquement avec des données locales MT5.
Priorité absolue: préserver le capital, éviter les faux signaux, attendre quand le doute existe.
Réponds uniquement en JSON strict.
"""


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

    def _coerce_json_result(self, raw_text: str) -> Optional[Dict]:
        text = (raw_text or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                return None
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
            response = requests.post(
                self.local_llm_endpoint,
                headers={"Content-Type": "application/json"},
                json={
                    "model": self.local_llm_model,
                    "prompt": SYSTEM_PROMPT + "\n\n" + prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": self.llm_temperature,
                        "num_predict": 260,
                    },
                },
                timeout=self.local_llm_timeout,
            )
            response.raise_for_status()
            data = response.json()
            raw_text = (data.get("response") or "").strip()
            result = self._coerce_json_result(raw_text)
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

    def analyze_signal(self, instrument: str, signal: Dict, account_info: Dict, market_context: str = "") -> Optional[Dict]:
        self.refresh_runtime_settings()
        today_pnl = self.memory.get_daily_pnl()
        memory_context = self.memory.get_context_for_llm()
        spread = self._extract_spread(market_context)

        prompt = f"""
Mode d'analyse: {self.analysis_mode}
Instructions utilisateur: {self.analysis_notes}
Instrument: {instrument}
Direction suggérée: {signal.get('direction') or 'WAIT'}
Score technique: {signal.get('score')}/5
Pattern: {signal.get('pattern')}
ATR: {signal.get('atr_pips')} pips
Spread actuel: {spread:.2f} pips
Compte: balance={account_info.get('balance', INITIAL_CAPITAL):.2f}, pnl_jour={today_pnl:.2f}, positions={account_info.get('open_trades', 0)}
Contexte marché: {market_context}
Risque max: {MAX_RISK_PER_TRADE*100:.1f}%
Objectif jour: {DAILY_TARGET}
Limite perte: {DAILY_LOSS_LIMIT}
Indicateurs détaillés:
{json.dumps(signal.get('details', {}), ensure_ascii=False)}
Mémoire:
{memory_context}
Fenêtre contexte estimée: {self.context_bars} bougies

Réponse attendue uniquement en JSON:
{{
  "decision":"BUY|SELL|WAIT",
  "confidence":0.0,
  "stop_loss_pips":20,
  "take_profit_pips":40,
  "reasoning":"explication courte et précise",
  "insight":"résumé marché"
}}
"""

        result = None
        if self.provider == "ollama":
            result = self._call_ollama(prompt, today_pnl, instrument)

        if result is None:
            result = self._safe_wait(
                instrument,
                f"LLM Ollama indisponible. Installe ou démarre Ollama avec le modèle {self.local_llm_model}."
            )

        self.memory.log_session(
            f"🤖 {self.provider} → {instrument}: {result['decision']} "
            f"(conf: {result.get('confidence', 0):.2f}) | {result.get('reasoning', '')[:90]}"
        )
        return result

    def get_market_summary(self, instruments_data: Dict) -> str:
        token_usage = self.memory.get_token_usage_today()
        return (
            f"Provider={self.provider} | LLM calls={self.memory.get_llm_calls_today()} | "
            f"Tokens={token_usage['prompt_tokens'] + token_usage['completion_tokens']}/{self.daily_token_budget}"
        )


ClaudeAnalyst = LocalIntelligence
