"""
Calendrier économique en temps réel via ForexFactory (gratuit, pas de clé API).
Fournit les événements high/medium impact pour filtrer les trades avant les news.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None

# ForexFactory JSON public feed — mis à jour chaque semaine
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Mapping devise → pays pour filtrer les événements pertinents
CURRENCY_COUNTRY_MAP = {
    "USD": "USD", "EUR": "EUR", "GBP": "GBP", "JPY": "JPY",
    "AUD": "AUD", "CAD": "CAD", "CHF": "CHF", "NZD": "NZD",
    "CNY": "CNY", "XAU": "USD",  # Gold is USD-sensitive
}

# Événements critiques qui causent des spikes de volatilité
CRITICAL_EVENTS = {
    "Non-Farm Employment Change", "Non-Farm Payrolls", "NFP",
    "CPI m/m", "Core CPI m/m", "CPI y/y", "Core CPI y/y",
    "Interest Rate Decision", "Federal Funds Rate",
    "GDP q/q", "GDP m/m", "GDP q/y",
    "Unemployment Rate", "Employment Change",
    "Retail Sales m/m", "Core Retail Sales m/m",
    "FOMC Statement", "ECB Press Conference", "BOE Rate Decision",
    "PPI m/m", "Core PPI m/m",
}


class EconomicCalendar:
    def __init__(self, cache_minutes: int = 30):
        self._cache: List[Dict] = []
        self._cache_ts: float = 0
        self._cache_minutes = cache_minutes

    def _fetch_events(self) -> List[Dict]:
        if requests is None:
            return []
        now = time.time()
        if self._cache and (now - self._cache_ts) < self._cache_minutes * 60:
            return self._cache
        try:
            resp = requests.get(FF_CALENDAR_URL, timeout=15)
            resp.raise_for_status()
            raw = resp.json()
            events = []
            for ev in raw:
                try:
                    dt_str = ev.get("date", "")
                    dt = datetime.fromisoformat(dt_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                    events.append({
                        "title": ev.get("title", ""),
                        "country": ev.get("country", ""),
                        "date": dt,
                        "impact": ev.get("impact", "Low"),
                        "forecast": ev.get("forecast", ""),
                        "previous": ev.get("previous", ""),
                    })
                except Exception:
                    continue
            self._cache = events
            self._cache_ts = now
            return events
        except Exception:
            return self._cache

    def get_upcoming_events(self, hours_ahead: int = 4, min_impact: str = "Medium") -> List[Dict]:
        """Retourne les événements importants dans les prochaines heures."""
        events = self._fetch_events()
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours_ahead)
        impact_levels = {"High": 3, "Medium": 2, "Low": 1}
        min_level = impact_levels.get(min_impact, 2)

        upcoming = []
        for ev in events:
            if ev["date"] < now - timedelta(minutes=30):
                continue
            if ev["date"] > cutoff:
                continue
            if impact_levels.get(ev["impact"], 0) < min_level:
                continue
            upcoming.append(ev)
        return sorted(upcoming, key=lambda e: e["date"])

    def get_recent_events(self, hours_back: int = 2, min_impact: str = "High") -> List[Dict]:
        """Retourne les événements high impact qui viennent de sortir (post-news volatilité)."""
        events = self._fetch_events()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours_back)
        impact_levels = {"High": 3, "Medium": 2, "Low": 1}
        min_level = impact_levels.get(min_impact, 3)

        recent = []
        for ev in events:
            if ev["date"] < cutoff or ev["date"] > now:
                continue
            if impact_levels.get(ev["impact"], 0) < min_level:
                continue
            recent.append(ev)
        return sorted(recent, key=lambda e: e["date"], reverse=True)

    def should_pause_trading(self, instrument: str, minutes_before: int = 15, minutes_after: int = 30) -> Dict:
        """
        Vérifie si un instrument doit être mis en pause à cause d'un événement imminent.
        Retourne {pause: bool, reason: str, events: [...]}
        
        Règle pro : on ne trade pas 15min avant ni 30min après un High Impact event
        qui concerne la devise de l'instrument.
        """
        events = self._fetch_events()
        now = datetime.now(timezone.utc)
        instrument_upper = instrument.upper()

        # Extraire les devises concernées par l'instrument
        relevant_currencies = set()
        for currency in CURRENCY_COUNTRY_MAP:
            if currency in instrument_upper:
                relevant_currencies.add(CURRENCY_COUNTRY_MAP[currency])
        if not relevant_currencies:
            relevant_currencies = {"USD", "EUR"}  # fallback pour paires inconnues

        blocking_events = []
        for ev in events:
            if ev["impact"] != "High":
                continue
            if ev["country"] not in relevant_currencies and ev["country"] != "All":
                continue
            window_start = ev["date"] - timedelta(minutes=minutes_before)
            window_end = ev["date"] + timedelta(minutes=minutes_after)
            if window_start <= now <= window_end:
                minutes_to = int((ev["date"] - now).total_seconds() / 60)
                blocking_events.append({
                    "title": ev["title"],
                    "country": ev["country"],
                    "time_utc": ev["date"].strftime("%H:%M"),
                    "minutes_to_event": minutes_to,
                    "forecast": ev["forecast"],
                    "previous": ev["previous"],
                })

        if blocking_events:
            names = ", ".join(e["title"] for e in blocking_events[:2])
            return {
                "pause": True,
                "reason": f"High impact event: {names}",
                "events": blocking_events,
            }
        return {"pause": False, "reason": "", "events": []}

    def get_context_for_llm(self, instrument: str) -> str:
        """Génère un résumé texte des événements pour le prompt LLM."""
        upcoming = self.get_upcoming_events(hours_ahead=6, min_impact="Medium")
        recent_high = self.get_recent_events(hours_back=3, min_impact="High")
        pause = self.should_pause_trading(instrument)

        instrument_upper = instrument.upper()
        relevant_currencies = set()
        for currency in CURRENCY_COUNTRY_MAP:
            if currency in instrument_upper:
                relevant_currencies.add(CURRENCY_COUNTRY_MAP[currency])

        lines = []
        if pause["pause"]:
            lines.append(f"⚠️ ALERTE NEWS: {pause['reason']} — NE PAS TRADER")

        if recent_high:
            lines.append("Events high impact récents:")
            for ev in recent_high[:3]:
                lines.append(f"  - {ev['country']} {ev['title']} ({ev['date'].strftime('%H:%M')} UTC)")

        relevant_upcoming = [e for e in upcoming if e["country"] in relevant_currencies or e["country"] == "All"]
        if relevant_upcoming:
            lines.append("Events à venir (pertinents):")
            for ev in relevant_upcoming[:5]:
                delta = ev["date"] - datetime.now(timezone.utc)
                hours = int(delta.total_seconds() / 3600)
                mins = int((delta.total_seconds() % 3600) / 60)
                lines.append(
                    f"  - [{ev['impact']}] {ev['country']} {ev['title']} dans {hours}h{mins:02d}m"
                    f" (prev: {ev['previous']}, fcst: {ev['forecast']})"
                )

        if not lines:
            lines.append("Pas d'événement majeur imminent.")

        return "\n".join(lines)

    def get_dashboard_summary(self) -> List[Dict]:
        """Résumé pour le dashboard — prochains événements importants."""
        upcoming = self.get_upcoming_events(hours_ahead=12, min_impact="Medium")
        result = []
        for ev in upcoming[:8]:
            delta = ev["date"] - datetime.now(timezone.utc)
            total_min = int(delta.total_seconds() / 60)
            result.append({
                "title": ev["title"],
                "country": ev["country"],
                "impact": ev["impact"],
                "time_utc": ev["date"].strftime("%H:%M"),
                "minutes_to": total_min,
                "forecast": ev["forecast"],
                "previous": ev["previous"],
            })
        return result
