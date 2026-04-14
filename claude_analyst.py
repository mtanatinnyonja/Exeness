"""
Analyse IA du trading agent.
Mode par défaut: Copilot/local, avec fallback Claude si une clé Anthropic est fournie.
"""

import json
import re
from typing import Dict, Optional

try:
    import requests
except Exception:
    requests = None

from config import (
    AI_PROVIDER, GEMINI_API_KEY, GEMINI_MODEL, ANTHROPIC_API_KEY, CLAUDE_MODEL,
    MAX_API_CALLS_PER_DAY, CLAUDE_TEMPERATURE, INITIAL_CAPITAL, MAX_RISK_PER_TRADE,
    DAILY_TARGET, DAILY_LOSS_LIMIT, DAILY_TOKEN_BUDGET, MIN_SIGNAL_SCORE
)
from runtime_store import RuntimeStore


SYSTEM_PROMPT = """Tu es un analyste forex conservateur.
Priorité absolue: préserver le capital, réduire le sur-trading et exploiter la mémoire locale.
Réponds uniquement en JSON strict.
"""


class ClaudeAnalyst:
    def __init__(self, memory):
        self.memory = memory
        self.api_url = "https://api.anthropic.com/v1/messages"
        self.gemini_api_base = "https://generativelanguage.googleapis.com/v1beta/models"
        self.store = RuntimeStore()
        self.requested_provider = AI_PROVIDER.lower().strip()
        self.gemini_api_key = GEMINI_API_KEY
        self.gemini_model = GEMINI_MODEL
        self.anthropic_api_key = ANTHROPIC_API_KEY
        self.claude_model = CLAUDE_MODEL
        self.max_api_calls = MAX_API_CALLS_PER_DAY
        self.daily_token_budget = DAILY_TOKEN_BUDGET
        self.provider = "local"
        self.refresh_runtime_settings()

    def refresh_runtime_settings(self):
        settings = self.store.get_settings()
        self.requested_provider = str(settings.get("ai_provider_requested", AI_PROVIDER)).lower().strip()
        self.gemini_api_key = str(settings.get("gemini_api_key", GEMINI_API_KEY)).strip()
        self.gemini_model = str(settings.get("gemini_model", GEMINI_MODEL)).strip()
        self.anthropic_api_key = str(settings.get("anthropic_api_key", ANTHROPIC_API_KEY)).strip()
        self.claude_model = str(settings.get("claude_model", CLAUDE_MODEL)).strip()
        self.max_api_calls = int(settings.get("max_api_calls_per_day", MAX_API_CALLS_PER_DAY))
        self.daily_token_budget = int(settings.get("daily_token_budget", DAILY_TOKEN_BUDGET))
        self.provider = self._select_provider()

    def _select_provider(self) -> str:
        requested = self.requested_provider
        if requested == "gemini":
            return "gemini" if self.gemini_api_key else "local"
        if requested == "claude":
            return "claude" if self.anthropic_api_key else "local"
        if requested == "auto":
            if self.gemini_api_key:
                return "gemini"
            if self.anthropic_api_key:
                return "claude"
        return "local"

    def _approx_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def _can_call_api(self, prompt_tokens: int = 0, provider: str = "claude") -> bool:
        if provider == "gemini" and not self.gemini_api_key:
            return False
        if provider == "claude" and not self.anthropic_api_key:
            return False
        if self.memory.get_api_calls_today() >= self.max_api_calls:
            return False
        token_usage = self.memory.get_token_usage_today()
        used = token_usage["prompt_tokens"] + token_usage["completion_tokens"]
        return (used + prompt_tokens) < self.daily_token_budget

    def _extract_spread(self, market_context: str) -> float:
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*pips", market_context or "")
        return float(match.group(1)) if match else 0.0

    def _local_copilot_decision(self, instrument: str, signal: Dict, account_info: Dict, market_context: str = "") -> Dict:
        score = int(signal.get("score", 0))
        direction = signal.get("direction")
        details = signal.get("details", {})
        spread = self._extract_spread(market_context)
        learning = self.memory.assess_setup(instrument, signal)
        today_pnl = self.memory.get_daily_pnl()

        confidence = 0.32 + (score * 0.09)
        rsi = float(details.get("rsi", 50))
        macd = float(details.get("macd", 0))
        macd_signal = float(details.get("macd_signal", 0))

        if direction == "BUY":
            if rsi <= 35:
                confidence += 0.08
            if macd >= macd_signal:
                confidence += 0.05
        elif direction == "SELL":
            if rsi >= 65:
                confidence += 0.08
            if macd <= macd_signal:
                confidence += 0.05

        if spread > 2.5:
            confidence -= 0.12
        if account_info.get("open_trades", 0) >= 1:
            confidence -= 0.04
        if today_pnl < 0:
            confidence -= 0.03
        confidence *= learning["risk_multiplier"]
        confidence = max(0.0, min(0.95, confidence))

        sl_pips = max(12, min(35, int(round(signal.get("atr_pips", 20) or 20))))
        tp_pips = int(round(sl_pips * (2.0 if confidence >= 0.72 else 1.6)))

        if direction is None or score < MIN_SIGNAL_SCORE or confidence < 0.60:
            decision = "WAIT"
            sl_pips = 0
            tp_pips = 0
        else:
            decision = direction

        reasoning = "Signal validé par l'analyse locale prudente."
        if learning["reasons"]:
            reasoning += " Mémoire: " + ", ".join(learning["reasons"][:2]) + "."
        if decision == "WAIT":
            reasoning = "Setup refusé pour rester conservateur et limiter les faux signaux."
            if learning["reasons"]:
                reasoning += " " + ", ".join(learning["reasons"][:2]) + "."

        return {
            "decision": decision,
            "confidence": round(confidence, 2),
            "stop_loss_pips": sl_pips,
            "take_profit_pips": tp_pips,
            "reasoning": reasoning,
            "insight": f"{instrument}: score={score}, spread={spread:.1f}, provider=local/{self.provider}",
            "risk_note": f"risk_multiplier={learning['risk_multiplier']}"
        }

    def _call_claude(self, prompt: str, today_pnl: float, instrument: str) -> Optional[Dict]:
        if requests is None:
            self.memory.record_error("claude", "package requests absent")
            return None

        prompt_tokens = self._approx_tokens(prompt)
        if not self._can_call_api(prompt_tokens, provider="claude"):
            return None

        try:
            self.memory.increment_api_calls()
            self.memory.record_token_usage(prompt_tokens=prompt_tokens, completion_tokens=0)
            response = requests.post(
                self.api_url,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.anthropic_api_key,
                    "anthropic-version": "2023-06-01"
                },
                json={
                    "model": self.claude_model,
                    "max_tokens": 350,
                    "temperature": CLAUDE_TEMPERATURE,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            raw_text = data["content"][0]["text"].strip()

            if "```json" in raw_text:
                raw_text = raw_text.split("```json", 1)[1].split("```", 1)[0].strip()
            elif raw_text.startswith("```"):
                raw_text = raw_text.split("```", 2)[1].strip()

            result = json.loads(raw_text)
            completion_tokens = self._approx_tokens(raw_text)
            self.memory.record_token_usage(prompt_tokens=0, completion_tokens=completion_tokens)

            if result.get("insight"):
                self.memory.add_claude_insight(f"{instrument}: {result['insight']}")

            if result.get("confidence", 0) < 0.6 or today_pnl <= DAILY_LOSS_LIMIT:
                result["decision"] = "WAIT"
            return result
        except Exception as e:
            self.memory.record_error("claude", str(e))
            return None

    def _call_gemini(self, prompt: str, today_pnl: float, instrument: str) -> Optional[Dict]:
        if requests is None:
            self.memory.record_error("gemini", "package requests absent")
            return None

        prompt_tokens = self._approx_tokens(prompt)
        if not self._can_call_api(prompt_tokens, provider="gemini"):
            return None

        try:
            self.memory.increment_api_calls()
            self.memory.record_token_usage(prompt_tokens=prompt_tokens, completion_tokens=0)
            response = requests.post(
                f"{self.gemini_api_base}/{self.gemini_model}:generateContent?key={self.gemini_api_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [
                        {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + prompt}]}
                    ],
                    "generationConfig": {
                        "temperature": CLAUDE_TEMPERATURE,
                        "responseMimeType": "application/json"
                    }
                },
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            result = json.loads(raw_text)
            completion_tokens = self._approx_tokens(raw_text)
            self.memory.record_token_usage(prompt_tokens=0, completion_tokens=completion_tokens)

            if result.get("insight"):
                self.memory.add_claude_insight(f"{instrument}: {result['insight']}")
            if result.get("confidence", 0) < 0.6 or today_pnl <= DAILY_LOSS_LIMIT:
                result["decision"] = "WAIT"
            return result
        except Exception as e:
            self.memory.record_error("gemini", str(e))
            return None

    def analyze_signal(self, instrument: str, signal: Dict, account_info: Dict, market_context: str = "") -> Optional[Dict]:
        self.refresh_runtime_settings()
        today_pnl = self.memory.get_daily_pnl()
        memory_context = self.memory.get_context_for_claude()

        prompt = f"""
Instrument: {instrument}
Direction suggérée: {signal.get('direction')}
Score technique: {signal.get('score')}/5
Pattern: {signal.get('pattern')}
ATR: {signal.get('atr_pips')} pips
Compte: balance={account_info.get('balance', INITIAL_CAPITAL):.2f}, pnl_jour={today_pnl:.2f}, positions={account_info.get('open_trades', 0)}
Contexte marché: {market_context}
Risque max: {MAX_RISK_PER_TRADE*100:.1f}%
Objectif jour: {DAILY_TARGET}
Limite perte: {DAILY_LOSS_LIMIT}
Mémoire:
{memory_context}
"""

        result = None
        if self.requested_provider in {"gemini", "auto"}:
            result = self._call_gemini(prompt, today_pnl, instrument)

        if result is None and self.requested_provider in {"claude", "auto"}:
            result = self._call_claude(prompt, today_pnl, instrument)

        if result is None:
            result = self._local_copilot_decision(instrument, signal, account_info, market_context)

        self.memory.log_session(
            f"🤖 {self.provider} → {instrument}: {result['decision']} "
            f"(conf: {result.get('confidence', 0):.2f}) | {result.get('reasoning', '')[:70]}"
        )
        return result

    def get_market_summary(self, instruments_data: Dict) -> str:
        token_usage = self.memory.get_token_usage_today()
        return (
            f"Provider={self.provider} | API calls={self.memory.get_api_calls_today()} | "
            f"Tokens={token_usage['prompt_tokens'] + token_usage['completion_tokens']}/{self.daily_token_budget}"
        )
