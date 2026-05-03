#!/usr/bin/env python3
"""
Dashboard web léger pour monitorer l'agent
Lance avec: python web/dashboard.py
Accès: http://localhost:8080
"""

import json
import os
import sys
import time
import base64
import hashlib
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

TRADES_HISTORY_FILE = Path("data/trades_history.json")
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _parse_iso_utc(value):
  if not value:
    return None
  try:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
      dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
  except Exception:
    return None


def _format_duration(seconds: int) -> str:
  s = max(0, int(seconds or 0))
  h = s // 3600
  m = (s % 3600) // 60
  sec = s % 60
  if h > 0:
    return f"{h}h {m:02d}m"
  if m > 0:
    return f"{m}m {sec:02d}s"
  return f"{sec}s"


def _load_trades_history() -> list:
  try:
    if not TRADES_HISTORY_FILE.exists():
      return []
    raw = json.loads(TRADES_HISTORY_FILE.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []
  except Exception:
    return []


def _build_performance_payload() -> dict:
  from mt5_bridge import build_broker
  from circuit_breaker import CircuitBreaker

  trades = _load_trades_history()
  now_utc = datetime.now(timezone.utc)

  broker = build_broker()
  account = broker.get_account_summary() if hasattr(broker, "get_account_summary") else {"balance": 0.0}
  balance_now = float(account.get("balance", 0.0) or 0.0)

  cb = CircuitBreaker()
  cb_status = cb.get_status()
  circuit_breaker = {
    "is_paused": bool(cb_status.get("is_paused", False)),
    "reason": str(cb_status.get("reason", "") or ""),
  }

  normalized = []
  for t in trades:
    row = dict(t)
    opened_at = _parse_iso_utc(row.get("timestamp"))
    closed_at = _parse_iso_utc(row.get("closed_at"))
    if closed_at is None and str(row.get("status", "")).lower() == "closed":
      closed_at = opened_at
    pnl = float(row.get("pnl", 0.0) or 0.0)
    status = str(row.get("status", "open") or "open").lower()
    end_dt = closed_at if status == "closed" and closed_at else now_utc
    duration_sec = int((end_dt - opened_at).total_seconds()) if opened_at else 0
    row["_opened_at"] = opened_at
    row["_closed_at"] = closed_at
    row["_pnl"] = pnl
    row["_status"] = status
    row["duration_seconds"] = max(0, duration_sec)
    row["duration"] = _format_duration(duration_sec)
    normalized.append(row)

  closed_trades = [t for t in normalized if t.get("_status") == "closed"]
  today = now_utc.date()
  closed_today = [
    t for t in closed_trades
    if ((t.get("_closed_at") or t.get("_opened_at")) and (t.get("_closed_at") or t.get("_opened_at")).date() == today)
  ]

  cumulative_pnl_day = round(sum(float(t.get("_pnl", 0.0) or 0.0) for t in closed_today), 2)
  wins = sum(1 for t in closed_today if float(t.get("_pnl", 0.0) or 0.0) > 0)
  total = len(closed_today)
  win_rate = round((wins / total) * 100, 1) if total else 0.0

  closed_sorted = sorted(
    closed_trades,
    key=lambda t: (t.get("_closed_at") or t.get("_opened_at") or now_utc),
  )
  total_closed_pnl = sum(float(t.get("_pnl", 0.0) or 0.0) for t in closed_sorted)
  start_balance = round(balance_now - total_closed_pnl, 2)

  equity_curve = []
  running = start_balance
  if closed_sorted:
    first_dt = closed_sorted[0].get("_closed_at") or closed_sorted[0].get("_opened_at") or now_utc
    equity_curve.append({"timestamp": first_dt.isoformat(), "balance": round(start_balance, 2)})
    for t in closed_sorted:
      running += float(t.get("_pnl", 0.0) or 0.0)
      point_dt = t.get("_closed_at") or t.get("_opened_at") or now_utc
      equity_curve.append({"timestamp": point_dt.isoformat(), "balance": round(running, 2)})
  else:
    equity_curve.append({"timestamp": now_utc.isoformat(), "balance": round(balance_now, 2)})

  recent20 = sorted(
    normalized,
    key=lambda t: (t.get("_closed_at") or t.get("_opened_at") or now_utc),
    reverse=True,
  )[:20]
  recent_trades = [
    {
      "instrument": t.get("instrument", "?"),
      "direction": t.get("direction", "?"),
      "pnl": round(float(t.get("_pnl", 0.0) or 0.0), 2),
      "duration": t.get("duration", "0s"),
      "duration_seconds": int(t.get("duration_seconds", 0) or 0),
      "status": t.get("_status", "open"),
      "timestamp": (t.get("_closed_at") or t.get("_opened_at") or now_utc).isoformat(),
    }
    for t in recent20
  ]

  return {
    "cumulative_pnl_day": cumulative_pnl_day,
    "recent_trades": recent_trades,
    "circuit_breaker": circuit_breaker,
    "equity_curve": equity_curve[-250:],
    "win_rate_day": {
      "wins": wins,
      "total": total,
      "rate": win_rate,
    },
  }

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent IA MT5 · Trading Autonome</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #040c14;
    --bg2: #070f1a;
    --bg3: #0d1a28;
    --border: rgba(0,200,255,0.07);
    --border2: rgba(0,200,255,0.18);
    --border3: rgba(0,200,255,0.35);
    --text: #d8eaf8;
    --muted: #5a7a98;
    --muted2: #3d5a72;
    --accent: #00c8ff;
    --accent2: #00ffcc;
    --accent3: #7c6af7;
    --green: #00ffa3;
    --red: #ff4466;
    --amber: #ffb820;
    --teal: #00e5ff;
    --mono: 'JetBrains Mono', Consolas, 'Courier New', monospace;
    --sans: 'Space Grotesk', 'Bahnschrift', 'Segoe UI', sans-serif;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    min-height: 100vh;
    font-size: 14px;
    overflow-x: hidden;
  }
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      linear-gradient(rgba(0,200,255,0.025) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,200,255,0.025) 1px, transparent 1px);
    background-size: 48px 48px;
    pointer-events: none;
    z-index: 0;
    animation: gridDrift 60s linear infinite;
  }
  body::after {
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px);
    pointer-events: none;
    z-index: 0;
  }
  @keyframes gridDrift {
    from { background-position: 0 0; }
    to { background-position: 48px 48px; }
  }
  @keyframes blink {
    0%, 100% { opacity: 1; box-shadow: 0 0 8px var(--green); }
    50% { opacity: 0.3; box-shadow: none; }
  }
  .wrapper { position: relative; z-index: 1; max-width: 1280px; margin: 0 auto; padding: 24px 20px; }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 28px;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--border2);
    position: relative;
  }
  header::after {
    content: '';
    position: absolute;
    bottom: -1px;
    left: 0;
    width: 200px;
    height: 1px;
    background: linear-gradient(90deg, var(--accent), transparent);
  }
  .logo { display: flex; align-items: center; gap: 14px; }
  .logo-icon {
    width: 42px;
    height: 42px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 12px;
    font-size: 20px;
    background: linear-gradient(135deg, var(--accent), var(--accent3));
    box-shadow: 0 0 20px rgba(0,200,255,0.3), inset 0 1px 0 rgba(255,255,255,0.1);
  }
  .logo-text { font-size: 20px; font-weight: 700; letter-spacing: -0.03em; }
  .logo-sub { font-size: 10px; color: var(--muted); font-family: var(--mono); letter-spacing: 0.12em; text-transform: uppercase; }
  #status-badge {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 16px;
    border-radius: 999px;
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 500;
    border: 1px solid var(--border2);
    letter-spacing: 0.05em;
  }
  #status-badge.open { background: rgba(0,255,163,0.12); border-color: rgba(0,255,163,0.3); color: var(--green); }
  #status-badge.closed { background: rgba(90,122,152,0.08); border-color: var(--border); color: var(--muted); }
  .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .open .dot { background: var(--green); box-shadow: 0 0 8px var(--green); animation: blink 2s infinite; }
  .closed .dot { background: var(--muted2); }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 18px; }
  .kpi, .panel, .mini-kpi, .market-box, .sparkline-box, .live-ai-box, .ai-exchange {
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 14px;
  }
  .kpi {
    padding: 16px;
    position: relative;
    overflow: hidden;
    transition: border-color 0.25s, transform 0.15s;
  }
  .kpi::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--accent), transparent);
    opacity: 0;
    transition: opacity 0.25s;
  }
  .kpi:hover, .panel:hover { border-color: var(--border2); }
  .kpi:hover::before { opacity: 1; }
  .kpi-label { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 10px; }
  .kpi-value { font-family: var(--mono); font-size: 24px; font-weight: 600; line-height: 1; }
  .kpi-sub, .refresh-info, .cb-label, .market-note, .agent-ts { font-size: 10px; color: var(--muted); font-family: var(--mono); }
  .positive { color: var(--green); text-shadow: 0 0 12px rgba(0,255,163,0.3); }
  .negative { color: var(--red); text-shadow: 0 0 12px rgba(255,68,102,0.3); }
  .neutral { color: var(--text); }
  .accent { color: var(--accent); }
  .main-grid { display: grid; grid-template-columns: 1fr 340px; gap: 14px; margin-bottom: 14px; }
  .panel { overflow: hidden; transition: border-color 0.25s; }
  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 13px 18px;
    border-bottom: 1px solid var(--border);
    background: rgba(0,200,255,0.02);
  }
  .panel-title { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.12em; color: var(--muted); }
  .panel-body { padding: 16px 18px; }
  #log-container {
    height: 320px;
    overflow-y: auto;
    padding: 14px 18px;
    font-family: var(--mono);
    font-size: 11.5px;
    line-height: 1.9;
    scrollbar-width: thin;
    scrollbar-color: var(--border2) transparent;
  }
  .log-line { padding: 1px 0; border-bottom: 1px solid rgba(0,200,255,0.03); }
  .log-time { color: var(--muted2); margin-right: 8px; }
  .position-item, .pattern-row, .agent-card, .cb-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
  }
  .position-item:last-child, .pattern-row:last-child, .agent-card:last-child, .cb-row:last-child { border: none; }
  .pos-instrument, .pattern-name, .agent-name { font-family: var(--mono); font-weight: 600; font-size: 12px; }
  .pos-dir, .ai-pill, .feature-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 9px;
    border-radius: 999px;
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.04em;
  }
  .pos-dir.buy, .ai-pill.buy, .feature-pill.on { background: rgba(0,255,163,0.1); color: var(--green); border: 1px solid rgba(0,255,163,0.25); }
  .pos-dir.sell, .ai-pill.sell { background: rgba(255,68,102,0.1); color: var(--red); border: 1px solid rgba(255,68,102,0.25); }
  .ai-pill.wait, .feature-pill.warn { background: rgba(255,184,32,0.1); color: var(--amber); border: 1px solid rgba(255,184,32,0.25); }
  .feature-pill.off { background: rgba(90,122,152,0.08); color: var(--muted); border: 1px solid var(--border); }
  .feature-dot, .agent-ring { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .feature-dot { background: currentColor; }
  .agent-ring.running { background: var(--green); box-shadow: 0 0 10px var(--green); animation: blink 2s infinite; }
  .agent-ring.stopped { background: var(--red); box-shadow: 0 0 6px var(--red); }
  .agent-ring.unknown { background: var(--muted2); }
  .trades-table { width: 100%; border-collapse: collapse; }
  .trades-table th { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; padding: 0 0 10px; text-align: left; border-bottom: 1px solid var(--border); }
  .trades-table td { padding: 9px 0; border-bottom: 1px solid var(--border); font-family: var(--mono); font-size: 12px; }
  .trades-table tr:last-child td { border: none; }
  .api-bar-track, .metric-track { height: 6px; background: var(--bg3); border-radius: 999px; overflow: hidden; }
  .api-bar-fill, .metric-fill, .pattern-bar-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    box-shadow: 0 0 8px rgba(0,200,255,0.35);
  }
  .pattern-bar-track { width: 80px; height: 4px; background: var(--bg3); border-radius: 999px; overflow: hidden; }
  .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
  .field label { display: block; font-size: 10px; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.08em; }
  .field input, .field select {
    width: 100%;
    padding: 10px 12px;
    background: var(--bg3);
    color: var(--text);
    border: 1px solid var(--border2);
    border-radius: 8px;
    font-family: var(--mono);
    font-size: 12px;
    outline: none;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  .field input:focus, .field select:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(0,200,255,0.1); }
  .btn {
    padding: 10px 16px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    color: #04080e;
    border: none;
    border-radius: 8px;
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
    box-shadow: 0 0 16px rgba(0,200,255,0.2);
  }
  .btn.secondary { background: var(--bg3); color: var(--text); border: 1px solid var(--border2); box-shadow: none; }
  .live-ai-box {
    position: relative;
    overflow: hidden;
    padding: 14px;
    margin-top: 12px;
    border-color: var(--border2);
    background: linear-gradient(135deg, rgba(0,200,255,0.04), rgba(124,106,247,0.04));
  }
  .live-ai-box::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
  }
  .mini-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-top: 10px; }
  .mini-kpi { padding: 8px; text-align: center; background: rgba(0,200,255,0.04); }
  .mini-kpi .label { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  .mini-kpi .value { font-family: var(--mono); font-size: 13px; margin-top: 4px; font-weight: 500; }
  .ai-bars { display: flex; align-items: flex-end; gap: 6px; height: 150px; margin-top: 12px; padding: 10px 8px 0; border: 1px solid var(--border); border-radius: 12px; background: linear-gradient(180deg, rgba(124,106,247,0.06), rgba(0,200,255,0.02)); }
  .ai-bar-wrap { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 20px; }
  .ai-bar { width: 100%; min-height: 18px; border-radius: 8px 8px 0 0; border: 1px solid rgba(255,255,255,0.06); box-shadow: 0 0 12px rgba(0,200,255,0.15); }
  .ai-bar-label, .scanner-head { font-family: var(--mono); font-size: 9px; color: var(--muted); }
  .focus-toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
  .market-deck { display: grid; grid-template-columns: 1.2fr 1fr; gap: 10px; margin-top: 12px; }
  .market-box, .sparkline-box { padding: 12px; }
  .sparkline-box { min-height: 140px; display: flex; align-items: center; justify-content: center; background: linear-gradient(180deg, rgba(124,106,247,0.06), rgba(0,200,255,0.02)); }
  .metric-row { margin-bottom: 8px; }
  .metric-head { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); margin-bottom: 4px; font-family: var(--mono); }
  .ai-exchange { margin-top: 14px; overflow: hidden; }
  .ai-exchange-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid var(--border); background: rgba(0,200,255,0.02); cursor: pointer; user-select: none; }
  .ai-exchange-body { padding: 0 18px 18px; display: none; }
  .ai-exchange-body.open { display: block; }
  .ai-msg {
    margin-top: 14px;
    padding: 14px 16px;
    border-radius: 12px;
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.7;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 400px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border2) transparent;
  }
  .ai-msg-prompt, .ai-msg.analyst { background: rgba(0,200,255,0.05); border: 1px solid rgba(0,200,255,0.12); }
  .ai-msg-response, .ai-msg.execution { background: rgba(0,255,163,0.05); border: 1px solid rgba(0,255,163,0.12); }
  .ai-msg.risk { background: rgba(255,184,32,0.05); border: 1px solid rgba(255,184,32,0.12); }
  .ai-msg.decision { background: rgba(124,106,247,0.05); border: 1px solid rgba(124,106,247,0.12); }
  .ai-msg-label { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; }
  .ai-msg-label.prompt-label { color: var(--accent2); }
  .ai-msg-label.response-label { color: var(--green); }
  .ai-exchange-meta { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 10px; font-family: var(--mono); font-size: 11px; color: var(--muted); }
  .toggle-arrow { font-size: 11px; color: var(--muted); transition: transform 0.2s; }
  .toggle-arrow.open { transform: rotate(180deg); }
  .scanner-row { display: grid; grid-template-columns: 1.5fr 0.8fr 0.8fr 0.8fr 0.6fr 1.2fr; gap: 4px; padding: 9px 0; border-bottom: 1px solid var(--border); font-family: var(--mono); font-size: 12px; align-items: center; }
  .scanner-row:last-child { border: none; }
  .scanner-row .symbol { font-weight: 600; color: var(--accent); }
  .score-bar { display: flex; gap: 3px; }
  .score-pip { width: 10px; height: 10px; border-radius: 3px; background: var(--border2); }
  .score-pip.filled { background: var(--amber); box-shadow: 0 0 4px var(--amber); }
  .tab-nav { display: flex; gap: 2px; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
  .tab-btn { padding: 10px 16px; background: none; border: none; color: var(--muted); font-family: var(--mono); font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.08em; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
  .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tab-content { display: none; }
  .tab-content.active { display: block; }
  .features-bar { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 18px; border-bottom: 1px solid var(--border); background: rgba(0,200,255,0.015); }
  .perf-grid { display: grid; grid-template-columns: 1.6fr 1fr; gap: 12px; margin-top: 8px; }
  .perf-box { background: var(--bg2); border: 1px solid var(--border); border-radius: 12px; padding: 12px; }
  .perf-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
  .perf-chip { font-family: var(--mono); font-size: 11px; color: var(--muted); padding: 4px 8px; border-radius: 999px; border: 1px solid var(--border2); background: var(--bg3); }
  #perf-cb-badge.active { color: #fff; background: rgba(255,68,102,0.25); border-color: rgba(255,68,102,0.45); }
  #perf-equity-chart { width: 100%; min-height: 170px; display: flex; align-items: center; justify-content: center; border: 1px solid var(--border); border-radius: 10px; background: linear-gradient(180deg, rgba(0,200,255,0.03), rgba(124,106,247,0.03)); }
  #perf-trades-table { width: 100%; border-collapse: collapse; }
  #perf-trades-table th { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; padding: 0 0 8px; text-align: left; border-bottom: 1px solid var(--border); }
  #perf-trades-table td { padding: 8px 0; border-bottom: 1px solid var(--border); font-family: var(--mono); font-size: 12px; }
  .neon-text { text-shadow: 0 0 20px var(--accent), 0 0 40px rgba(0,200,255,0.3); }
  .divider { height: 1px; background: var(--border); margin: 12px 0; }
  ::-webkit-scrollbar { width: 5px; height: 5px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--border3); }
  @media (max-width: 768px) {
    .main-grid, .market-deck { grid-template-columns: 1fr; }
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
    .mini-grid { grid-template-columns: repeat(2, 1fr); }
  }
</style>
</head>
<body>
<div class="wrapper">
  <header>
    <div class="logo">
      <div class="logo-icon">⚡</div>
      <div>
        <div class="logo-text">Agent IA MT5</div>
        <div class="logo-sub" id="header-subtitle">AUTONOME · OLLAMA · MT5</div>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:12px">
      <span id="account-type-badge" style="display:none;padding:3px 10px;border-radius:12px;font-size:0.75em;font-weight:600;letter-spacing:0.05em;color:#fff;"></span>
      <span class="refresh-info">Refresh: <span id="countdown">5</span>s</span>
      <div id="status-badge" class="closed">
        <div class="dot"></div>
        <span id="status-text">Chargement...</span>
      </div>
    </div>
  </header>

  <div class="panel" style="margin-bottom:16px;">
    <div class="panel-header">
      <span class="panel-title">Configuration active</span>
    </div>
    <div class="panel-body" style="display:grid;grid-template-columns:1fr 1fr 2fr 1fr;gap:12px;">
      <div>
        <div class="kpi-label">Filtre actif</div>
        <div class="kpi-value accent" id="symbol-mode" style="font-size:16px;">—</div>
      </div>
      <div>
        <div class="kpi-label">IA</div>
        <div class="kpi-value accent" id="ai-provider" style="font-size:16px;">—</div>
      </div>
      <div>
        <div class="kpi-label">Symboles tradés</div>
        <div class="refresh-info" id="active-symbols" style="white-space:normal;line-height:1.6;">—</div>
      </div>
      <div>
        <div class="kpi-label">Pipeline Agents</div>
        <div class="kpi-value accent" id="agent-pipeline-status" style="font-size:14px;">—</div>
        <div class="kpi-sub" id="agent-pipeline-info">Analyste → Risk → Décideur</div>
      </div>
    </div>
    <div id="features-bar" style="display:flex;gap:6px;flex-wrap:wrap;padding:8px 16px 12px;border-top:1px solid var(--border);"></div>
  </div>

  <div class="panel" style="margin-bottom:16px;">
    <div class="panel-header">
      <span class="panel-title">Paramètres modifiables</span>
      <span class="refresh-info" id="settings-save-status">non sauvegardé</span>
    </div>
    <div class="panel-body">
      <div class="form-grid">

        <div class="field" style="grid-column:1/-1">
          <label>Instrument</label>
          <div style="padding:8px 12px;border-radius:6px;background:rgba(255,215,0,0.08);border:1px solid #f59e0b;color:#f59e0b;font-weight:600;font-size:0.9em;">🪙 XAUUSDm &mdash; spécialisé (fixé)</div>
        </div>
        <div class="field">
          <label>Intervalle minutes</label>
          <input id="setting-check-interval" type="number" min="1" max="120" />
        </div>
        <div class="field">
          <label>Risque max/trade</label>
          <input id="setting-risk" type="number" min="0.001" max="0.1" step="0.001" />
        </div>
        <div class="field">
          <label>Objectif jour</label>
          <input id="setting-daily-target" type="number" min="0" step="0.1" />
        </div>
        <div class="field">
          <label>Limite perte jour</label>
          <input id="setting-daily-loss" type="number" max="0" step="0.1" />
        </div>
        <div class="field">
          <label>Max positions</label>
          <input id="setting-max-positions" type="number" min="1" max="20" step="1" />
        </div>
        <div class="field">
          <label>Modèle local</label>
          <input id="setting-local-model" placeholder="qwen2.5:3b" />
        </div>
        <div class="field">
          <label>Endpoint local</label>
          <input id="setting-local-endpoint" placeholder="http://127.0.0.1:11434/api/generate" />
        </div>
        <div class="field">
          <label>Timeout LLM</label>
          <input id="setting-local-timeout" type="number" min="10" step="5" />
        </div>
        <div class="field">
          <label>Mode analyse</label>
          <select id="setting-analysis-mode">
            <option value="precision">precision</option>
            <option value="strict">strict</option>
            <option value="balanced">balanced</option>
          </select>
        </div>
        <div class="field">
          <label>Seuil confiance IA</label>
          <input id="setting-confidence" type="number" min="0.50" max="0.95" step="0.01" />
        </div>
        <div class="field">
          <label>Appels LLM / jour</label>
          <input id="setting-max-llm-calls" type="number" min="0" step="1" />
        </div>
        <div class="field">
          <label>Notes IA</label>
          <input id="setting-analysis-notes" placeholder="Ex: attendre confirmation multi-signaux" />
        </div>
        <div class="field">
          <label>Trading réel sur démo</label>
          <select id="setting-allow-trade">
            <option value="false">false</option>
            <option value="true">true</option>
          </select>
        </div>
        <div class="field" style="grid-column:1/-1">
          <label>Type de compte détecté</label>
          <div id="account-type-info" style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:6px;background:rgba(255,255,255,0.04);border:1px solid var(--border);">
            <span id="account-type-info-badge" style="padding:2px 10px;border-radius:10px;font-size:0.78em;font-weight:600;color:#fff;background:#3b82f6;">COMPTE STANDARD</span>
            <span id="account-type-info-detail" style="color:var(--muted);font-size:0.85em;">Valeurs monétaires affichées en USD ($)</span>
          </div>
        </div>
      </div>
      <div style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
        <button class="btn" onclick="saveSettings()">Sauvegarder</button>
        <button class="btn" onclick="testAI()">Tester IA</button>
        <button class="btn secondary" id="auto-ai-btn" onclick="toggleAutoAI()">Auto IA: ON</button>
        <span class="refresh-info" id="ai-mode-note">Le cockpit affiche un signal IA en aperçu sur XAUUSDm. Un ordre réel MT5 n'est envoyé que par le cycle automatique quand toutes les validations sont encore confirmées.</span>
      </div>
      <div id="ai-test-result" class="refresh-info" style="margin-top:10px;white-space:normal;line-height:1.6;">Chargement de l'analyse automatique sur XAUUSDm...</div>

      <div class="live-ai-box">
        <div class="panel-title" style="margin-bottom:8px;">Cockpit IA en direct</div>
        <div class="focus-toolbar">
          <span class="refresh-info" id="rotation-label">Focus fixe : XAUUSDm</span>
        </div>
        <div id="ai-live-decision" class="refresh-info" style="white-space:normal;line-height:1.6;">En attente d'une analyse IA...</div>
        <div class="mini-grid">
          <div class="mini-kpi"><div class="label">Instrument</div><div class="value" id="ai-live-symbol">—</div></div>
          <div class="mini-kpi"><div class="label">Décision</div><div class="value" id="ai-live-action">WAIT</div></div>
          <div class="mini-kpi"><div class="label">Confiance</div><div class="value" id="ai-live-confidence">0%</div></div>
          <div class="mini-kpi"><div class="label">Spread</div><div class="value" id="ai-live-spread">—</div></div>
          <div class="mini-kpi"><div class="label">Auto</div><div class="value" id="ai-live-auto">ON · 45s</div></div>
        </div>
        <div class="market-deck">
          <div class="market-box">
            <div class="panel-title" style="margin-bottom:8px;">Marché live</div>
            <div id="pair-sparkline" class="sparkline-box"><span class="refresh-info">Aucune donnée XAUUSDm</span></div>
            <div id="pair-market-note" class="market-note">Le graphique montre uniquement XAUUSDm.</div>
          </div>
          <div class="market-box">
            <div class="panel-title" style="margin-bottom:8px;">Forces de l'analyse</div>
            <div class="metric-row"><div class="metric-head"><span>RSI</span><span id="metric-rsi-value">—</span></div><div class="metric-track"><div id="metric-rsi" class="metric-fill" style="width:0%"></div></div></div>
            <div class="metric-row"><div class="metric-head"><span>Momentum</span><span id="metric-momentum-value">—</span></div><div class="metric-track"><div id="metric-momentum" class="metric-fill" style="width:0%"></div></div></div>
            <div class="metric-row"><div class="metric-head"><span>Tendance</span><span id="metric-trend-value">—</span></div><div class="metric-track"><div id="metric-trend" class="metric-fill" style="width:0%"></div></div></div>
            <div class="metric-row"><div class="metric-head"><span>Risk/Reward</span><span id="metric-rr-value">—</span></div><div class="metric-track"><div id="metric-rr" class="metric-fill" style="width:0%"></div></div></div>
            <div id="pair-flow-note" class="market-note">Spread, support, résistance et régime s'affichent ici en direct.</div>
          </div>
        </div>
        <div id="ai-history-chart" class="ai-bars"></div>
      </div>
    </div>
  </div>

  <!-- TELEGRAM SETTINGS -->
  <div class="panel" style="margin-bottom:16px;">
    <div class="panel-header">
      <span class="panel-title">📱 Telegram Notifications</span>
      <span class="refresh-info" id="tg-status">—</span>
    </div>
    <div class="panel-body">
      <div class="form-grid">
        <div class="field">
          <label>Telegram actif</label>
          <select id="setting-telegram-enabled">
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        </div>
        <div class="field">
          <label>Bot Token</label>
          <input type="password" id="setting-telegram-token" placeholder="123456:ABCdef..." style="font-family:monospace;" oninput="scheduleAutoSave()">
        </div>
        <div class="field">
          <label>Chat ID</label>
          <input type="text" id="setting-telegram-chatid" placeholder="-1001234567890" style="font-family:monospace;" oninput="scheduleAutoSave()">
        </div>
      </div>
      <div style="margin-top:10px;display:flex;gap:10px;align-items:center;">
        <button class="btn" onclick="testTelegram()">Tester Telegram</button>
        <span class="refresh-info" id="tg-test-result"></span>
      </div>
    </div>
  </div>

  <!-- SCALPING SETTINGS -->
  <div class="panel" style="margin-bottom:16px;">
    <div class="panel-header">
      <span class="panel-title">⚡ Scalping — Paramètres</span>
      <span class="refresh-info">EMA 9/21 · Stoch(5,3,3) · ATR SL/TP · Kill Zones London/NY</span>
    </div>
    <div class="panel-body">
      <div class="form-grid">
        <div class="field">
          <label>Moteur de signaux</label>
          <select id="strategy-mode" onchange="updateStrategyModeUI(); scheduleAutoSave()">
            <option value="classic">classic (ancien système)</option>
            <option value="scalping">scalping uniquement</option>
            <option value="hybrid">hybrid (classique + scalping)</option>
          </select>
        </div>
        <div class="field" style="grid-column:1/-1;">
          <label>Résumé du mode</label>
          <div id="strategy-mode-note" style="padding:10px 12px;border-radius:8px;background:rgba(255,255,255,0.04);border:1px solid var(--border);color:var(--muted);font-size:12px;line-height:1.5;">
            `classic` = ancien moteur en M15 avec confirmation M5. `scalping` = moteur court terme M1/M5. `hybrid` = combine les deux.
          </div>
        </div>
        <div id="scalp-settings-fields" style="display:contents;">
        <div class="field">
          <label>Mode scalping</label>
          <select id="scalp-mode" onchange="scheduleAutoSave()">
            <option value="momentum">momentum (breakout)</option>
            <option value="mean_reversion">mean_reversion (rebond)</option>
          </select>
        </div>
        <div class="field">
          <label>Timeframe</label>
          <select id="scalp-timeframe" onchange="scheduleAutoSave()">
            <option value="M5">M5</option>
            <option value="M1">M1</option>
          </select>
        </div>
        <div class="field">
          <label>EMA rapide</label>
          <input id="scalp-ema-fast" type="number" min="3" max="20" oninput="scheduleAutoSave()" />
        </div>
        <div class="field">
          <label>EMA lente</label>
          <input id="scalp-ema-slow" type="number" min="10" max="50" oninput="scheduleAutoSave()" />
        </div>
        <div class="field">
          <label>Stoch K</label>
          <input id="scalp-stoch-k" type="number" min="3" max="14" oninput="scheduleAutoSave()" />
        </div>
        <div class="field">
          <label>Stoch D</label>
          <input id="scalp-stoch-d" type="number" min="2" max="9" oninput="scheduleAutoSave()" />
        </div>
        <div class="field">
          <label>SL × ATR</label>
          <input id="scalp-sl-atr" type="number" min="0.5" max="3.0" step="0.1" oninput="scheduleAutoSave()" />
        </div>
        <div class="field">
          <label>TP × ATR</label>
          <input id="scalp-tp-atr" type="number" min="0.5" max="5.0" step="0.1" oninput="scheduleAutoSave()" />
        </div>
        <div class="field">
          <label>Spread max Gold (p)</label>
          <input id="scalp-spread-gold" type="number" min="5" max="80" step="1" oninput="scheduleAutoSave()" />
        </div>
        <div class="field">
          <label>Score min (0–6)</label>
          <input id="scalp-min-score" type="number" min="1" max="6" oninput="scheduleAutoSave()" />
        </div>
        <div class="field">
          <label>Kill Zones uniquement</label>
          <select id="scalp-kill-zones" onchange="scheduleAutoSave()">
            <option value="true">oui (recommandé)</option>
            <option value="false">non (toujours)</option>
          </select>
        </div>
        <div class="field">
          <label>Max trades / heure</label>
          <input id="scalp-max-per-hour" type="number" min="1" max="20" oninput="scheduleAutoSave()" />
        </div>
        <div class="field">
          <label>ADX min tendance</label>
          <input id="scalp-adx-min" type="number" min="10" max="40" step="1" oninput="scheduleAutoSave()" />
        </div>
        </div>
      </div>
      <div style="margin-top:10px;color:var(--muted);font-family:var(--mono);font-size:11px;">
        Kill Zones actives : London Open 07h–10h UTC · NY Open 12h–15h UTC. Spread filtré avant chaque signal.
      </div>
    </div>
  </div>

  <!-- HUMAN CONFIRMATION GATE -->
  <div class="panel" style="margin-bottom:16px;" id="panel-human-gate">
    <div class="panel-header">
      <span class="panel-title">🔒 Confirmation Humaine</span>
      <span class="refresh-info">Point d'entrée manuel — approuve ou rejette chaque trade avant exécution</span>
    </div>
    <div class="panel-body">
      <div class="form-grid" style="margin-bottom:14px;">
        <div class="field">
          <label>Confirmation humaine requise</label>
          <select id="require-human-confirmation" onchange="scheduleAutoSave()">
            <option value="false">non — exécution automatique</option>
            <option value="true">oui — validation manuelle avant ordre</option>
          </select>
        </div>
        <div class="field" style="grid-column:1/-1;">
          <div id="human-gate-note" style="padding:10px 12px;border-radius:8px;background:rgba(255,200,50,0.07);border:1px solid rgba(255,200,50,0.3);color:#f59e0b;font-size:12px;line-height:1.5;">
            Quand activé, chaque signal validé par les agents est mis <strong>en attente</strong> ici. Tu approuves ou rejettes avant tout envoi à MT5.
          </div>
        </div>
      </div>

      <!-- Pending trades -->
      <div style="color:var(--text);font-weight:600;margin-bottom:8px;font-size:13px;">Trades en attente d'approbation</div>
      <div id="pending-approvals-list">
        <div style="color:var(--muted);font-size:12px;">Aucun trade en attente.</div>
      </div>
    </div>
  </div>
  <div class="ai-exchange" style="margin-bottom:16px;" id="scanner-panel">
    <div class="ai-exchange-header" onclick="toggleScanner()">
      <span class="panel-title">🔍 Scanner XAUUSDm</span>
      <span id="scanner-badge" style="padding:2px 8px;border-radius:4px;font-size:0.75em;margin-left:8px;background:var(--accent);color:#fff;">—</span>
      <span class="toggle-arrow" id="scanner-arrow">▼</span>
    </div>
    <div class="ai-exchange-body" id="scanner-body">
      <div style="display:flex;gap:16px;margin-bottom:10px;">
        <div style="flex:1;">
          <div style="color:var(--green);font-weight:600;margin-bottom:8px;">✅ XAU retenu</div>
          <div id="scan-selected" style="font-size:0.85em;">—</div>
        </div>
        <div style="flex:1;">
          <div style="color:var(--red);font-weight:600;margin-bottom:8px;">❌ XAU rejeté (spread)</div>
          <div id="scan-rejected" style="font-size:0.85em;color:var(--muted);">—</div>
        </div>
      </div>
      <div id="scan-table-wrap" style="max-height:260px;overflow-y:auto;"></div>
    </div>
  </div>

  <!-- TRENDING PAIRS PANEL -->
  <div class="ai-exchange" style="margin-bottom:16px;" id="trending-panel">
    <div class="ai-exchange-header" onclick="toggleTrending()">
      <span class="panel-title">📈 Tendance XAUUSDm</span>
      <span id="trending-badge" style="padding:2px 8px;border-radius:4px;font-size:0.75em;margin-left:8px;background:var(--green);color:#000;">—</span>
      <span class="toggle-arrow" id="trending-arrow">▼</span>
    </div>
    <div class="ai-exchange-body" id="trending-body">
      <div id="trending-table" style="font-size:0.85em;">Chargement...</div>
    </div>
  </div>

  <!-- AGENT STATUS PANEL -->
  <div class="ai-exchange" style="margin-bottom:16px;" id="agents-status-panel">
    <div class="ai-exchange-header" onclick="toggleAgentsStatus()">
      <span class="panel-title">🤖 Statut des Agents</span>
      <span id="agents-status-badge" style="padding:2px 8px;border-radius:4px;font-size:0.75em;margin-left:8px;background:var(--muted);color:#fff;">—</span>
      <span class="toggle-arrow" id="agents-status-arrow">▼</span>
    </div>
    <div class="ai-exchange-body" id="agents-status-body">
      <div id="agents-status-list" style="display:flex;flex-direction:column;gap:8px;font-size:0.88em;"></div>
    </div>
  </div>

  <!-- ECONOMIC CALENDAR -->
  <div class="ai-exchange" style="margin-bottom:16px;" id="calendar-panel">
    <div class="ai-exchange-header" onclick="toggleCalendar()">
      <span class="panel-title">📰 Calendrier Économique</span>
      <span id="news-pause-badge" style="display:none;background:#e74c3c;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.75em;margin-left:8px;">⚠️ PAUSE NEWS</span>
      <span class="toggle-arrow" id="calendar-arrow">▼</span>
    </div>
    <div class="ai-exchange-body" id="calendar-body">
      <div id="calendar-events" style="color:var(--text);font-size:0.85em;">Chargement...</div>
    </div>
  </div>

  <!-- PRO STRATEGIES / LAST SCAN -->
  <div class="ai-exchange" style="margin-bottom:16px;" id="strategies-panel">
    <div class="ai-exchange-header" onclick="toggleStrategies()">
      <span class="panel-title">🎯 Dernière Analyse (Analyste)</span>
      <span id="session-badge" style="padding:2px 8px;border-radius:4px;font-size:0.75em;margin-left:8px;"></span>
      <span class="toggle-arrow" id="strategies-arrow">▼</span>
    </div>
    <div class="ai-exchange-body" id="strategies-body">
      <div id="strat-scan-table" style="font-size:0.85em;">En attente du scan...</div>
      <div style="margin-top:8px;display:flex;gap:16px;font-size:0.82em;">
        <div>Session: <strong id="strat-session-label" style="color:var(--amber);">—</strong></div>
        <div>Candidats: <strong id="strat-count" style="color:var(--green);">—</strong></div>
        <div>Dernière analyse: <strong id="strat-last-ts" style="color:var(--muted);">—</strong></div>
      </div>
    </div>
  </div>

  <!-- CIRCUIT BREAKER / PROTECTIONS -->
  <div class="ai-exchange" style="margin-bottom:16px;" id="protections-panel">
    <div class="ai-exchange-header" onclick="toggleProtections()">
      <span class="panel-title">🛡️ Circuit Breaker &amp; Protections</span>
      <span id="protection-badge" style="padding:2px 8px;border-radius:4px;font-size:0.75em;margin-left:8px;"></span>
      <span class="toggle-arrow" id="protections-arrow">▼</span>
    </div>
    <div class="ai-exchange-body" id="protections-body">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
        <div style="background:rgba(255,255,255,0.03);padding:10px;border-radius:8px;">
          <div style="color:var(--teal);font-weight:600;margin-bottom:6px;">🔌 État du Circuit Breaker</div>
          <div id="prot-cb-state" style="color:var(--text);font-size:0.85em;">—</div>
        </div>
        <div style="background:rgba(255,255,255,0.03);padding:10px;border-radius:8px;">
          <div style="color:var(--teal);font-weight:600;margin-bottom:6px;">📉 Pertes Consécutives</div>
          <div id="prot-losses" style="color:var(--text);font-size:0.85em;">—</div>
        </div>
        <div style="background:rgba(255,255,255,0.03);padding:10px;border-radius:8px;">
          <div style="color:var(--teal);font-weight:600;margin-bottom:6px;">📊 P&L Journalier</div>
          <div id="prot-daily" style="color:var(--text);font-size:0.85em;">—</div>
        </div>
        <div style="background:rgba(255,255,255,0.03);padding:10px;border-radius:8px;">
          <div style="color:var(--teal);font-weight:600;margin-bottom:6px;">📰 Pause News</div>
          <div id="prot-news" style="color:var(--text);font-size:0.85em;">—</div>
        </div>
      </div>
      <div id="prot-alerts" style="margin-top:10px;font-size:0.82em;color:var(--muted);"></div>
    </div>
  </div>

  <!-- XAUUSDM LIVE PANEL -->
  <div class="panel" style="margin-bottom:16px;border-color:rgba(255,184,32,0.35);">
    <div class="panel-header" style="background:rgba(255,184,32,0.05);">
      <span class="panel-title" style="color:var(--amber)">🪵 XAUUSDm Live</span>
      <span id="xau-pnl-badge" class="refresh-info" style="font-size:13px;font-weight:700;">—</span>
    </div>
    <div class="panel-body">
      <!-- Prix et spread -->
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:14px;">
        <div class="mini-kpi" style="text-align:left;padding:10px 14px;">
          <div class="label">Bid</div><div class="value" id="xau-bid" style="color:var(--amber)">—</div>
        </div>
        <div class="mini-kpi" style="text-align:left;padding:10px 14px;">
          <div class="label">Ask</div><div class="value" id="xau-ask" style="color:var(--amber)">—</div>
        </div>
        <div class="mini-kpi" style="text-align:left;padding:10px 14px;">
          <div class="label">Spread</div><div class="value" id="xau-spread">—</div>
        </div>
        <div class="mini-kpi" style="text-align:left;padding:10px 14px;">
          <div class="label">P&amp;L Jour</div><div class="value" id="xau-day-pnl">—</div>
        </div>
        <div class="mini-kpi" style="text-align:left;padding:10px 14px;">
          <div class="label">Trades Jour</div><div class="value" id="xau-day-trades">—</div>
        </div>
      </div>
      <!-- Barre de progression objectif -->
      <div style="margin-bottom:14px;">
        <div style="display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;color:var(--muted);margin-bottom:4px;">
          <span>Progression objectif journalier</span><span id="xau-goal-label">$0.00 / $5.00</span>
        </div>
        <div class="api-bar-track"><div class="api-bar-fill" id="xau-goal-bar" style="width:0%"></div></div>
      </div>
      <!-- Position ouverte XAU -->
      <div id="xau-position-wrap" style="display:none;padding:12px;border-radius:10px;background:rgba(255,184,32,0.06);border:1px solid rgba(255,184,32,0.2);margin-bottom:12px;">
        <div style="font-family:var(--mono);font-size:11px;color:var(--amber);font-weight:600;margin-bottom:8px;">Position ouverte</div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;font-family:var(--mono);font-size:12px;">
          <span>Dir: <strong id="xau-pos-dir">—</strong></span>
          <span>Entrée: <strong id="xau-pos-entry">—</strong></span>
          <span>P&amp;L: <strong id="xau-pos-pnl">—</strong></span>
          <span>SL: <strong id="xau-pos-sl">—</strong></span>
          <span>TP: <strong id="xau-pos-tp">—</strong></span>
          <span>Lot: <strong id="xau-pos-lot">—</strong></span>
        </div>
      </div>
      <!-- Derniers signaux XAU -->
      <div>
        <div style="font-family:var(--mono);font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;">Derniers signaux XAUUSDm</div>
        <div id="xau-signals-list" style="font-family:var(--mono);font-size:12px;color:var(--muted);">En attente de signal...</div>
      </div>
    </div>
  </div>

  <!-- KPIs -->
  <div class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">Balance</div>
      <div class="kpi-value neutral" id="balance">—</div>
      <div class="kpi-sub" id="balance-sub">USD</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">P&L Aujourd'hui</div>
      <div class="kpi-value" id="daily-pnl">—</div>
      <div class="kpi-sub" id="daily-pnl-sub">vs objectif $5.00</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">P&L Total</div>
      <div class="kpi-value" id="total-pnl">—</div>
      <div class="kpi-sub">depuis départ</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Win Rate</div>
      <div class="kpi-value accent" id="win-rate">—</div>
      <div class="kpi-sub" id="total-trades">0 trades</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Positions</div>
      <div class="kpi-value neutral" id="open-positions">0</div>
      <div class="kpi-sub">ouvertes</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Appels LLM</div>
      <div class="kpi-value accent" id="api-calls">0</div>
      <div class="api-bar-track">
        <div class="api-bar-fill" id="api-bar" style="width:0%"></div>
      </div>
    </div>
  </div>

  <!-- MAIN GRID -->
  <div class="main-grid">
    <!-- LOG -->
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">Journal de session</span>
        <span class="refresh-info" id="last-update">—</span>
      </div>
      <div id="log-container">
        <div style="color:var(--muted);font-family:var(--mono);font-size:12px;padding:20px 0;text-align:center">
          Chargement...
        </div>
      </div>
    </div>

    <!-- SIDEBAR -->
    <div style="display:flex;flex-direction:column;gap:16px">

      <!-- POSITIONS OUVERTES -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">Positions ouvertes</span>
          <span id="positions-count" class="refresh-info">0</span>
        </div>
        <div class="panel-body" id="positions-container">
          <div style="color:var(--muted);font-size:12px;text-align:center;padding:12px 0">
            Aucune position
          </div>
        </div>
      </div>

      <!-- PATTERNS -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">Meilleurs patterns</span>
        </div>
        <div class="panel-body" id="patterns-container">
          <div style="color:var(--muted);font-size:12px;text-align:center;padding:12px 0">
            Pas encore de données
          </div>
        </div>
      </div>

    </div>
  </div>

  <!-- RECENT TRADES -->
  <div class="panel">
    <div class="panel-header">
      <span class="panel-title">Trades récents</span>
    </div>
    <div class="panel-body">
      <table class="trades-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Instrument</th>
            <th>Dir</th>
            <th>Entry</th>
            <th>Pattern</th>
            <th>Score</th>
            <th>P&L</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody id="trades-tbody">
          <tr><td colspan="8" style="color:var(--muted);text-align:center;padding:16px">Aucun trade</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="panel" style="margin-top:16px;">
    <div class="panel-header">
      <span class="panel-title">Performance</span>
      <span class="refresh-info" id="perf-last-update">—</span>
    </div>
    <div class="panel-body">
      <div class="perf-meta">
        <span class="perf-chip" id="perf-day-pnl">P&L jour: —</span>
        <span class="perf-chip" id="perf-winrate">Win rate: —</span>
        <span class="perf-chip" id="perf-cb-badge">Circuit Breaker INACTIF</span>
      </div>
      <div class="perf-grid">
        <div class="perf-box">
          <div class="panel-title" style="margin-bottom:8px;">Equity Curve</div>
          <div id="perf-equity-chart">
            <span class="refresh-info">En attente du flux WebSocket...</span>
          </div>
        </div>
        <div class="perf-box">
          <div class="panel-title" style="margin-bottom:8px;">20 derniers trades</div>
          <table id="perf-trades-table">
            <thead>
              <tr>
                <th>Instrument</th>
                <th>Dir</th>
                <th>P&L</th>
                <th>Durée</th>
              </tr>
            </thead>
            <tbody id="perf-trades-body">
              <tr><td colspan="4" style="color:var(--muted);text-align:center;padding:12px 0;">Aucune donnée</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

</div>

<script>
let countdown = 5;
let autoAiCountdown = 30;
let autoSaveTimer = null;
let autoAiEnabled = true;
let aiBusy = false;
let initialAiWarmupDone = false;
let lastAiPayload = null;
let latestStatusPayload = null;
let currentFocusPair = '';
let rotationIndex = 0;
let activeSymbolsList = [];
let trendingPairsList = [];
let performanceSocket = null;

function coalesce() {
  for (let i = 0; i < arguments.length; i++) {
    const value = arguments[i];
    if (value !== null && value !== undefined) {
      return value;
    }
  }
  return null;
}

function updateStrategyModeUI() {
  const strategyEl = document.getElementById('strategy-mode');
  const noteEl = document.getElementById('strategy-mode-note');
  const scalpFieldsEl = document.getElementById('scalp-settings-fields');
  if (!strategyEl || !noteEl || !scalpFieldsEl) return;

  const mode = strategyEl.value || 'hybrid';
  if (mode === 'classic') {
    noteEl.innerHTML = '<strong style="color:var(--text);">classic</strong> : ancien moteur technique. Analyse principale en <strong>M15</strong> avec confirmation <strong>M5</strong>. Les réglages scalping M1/M5 ci-dessous ne s\'appliquent pas.';
    scalpFieldsEl.style.display = 'none';
    return;
  }

  if (mode === 'scalping') {
    noteEl.innerHTML = '<strong style="color:var(--text);">scalping</strong> : moteur court terme. Les paramètres M1/M5, EMA, Stoch, ATR et spread ci-dessous pilotent directement les entrées.';
    scalpFieldsEl.style.display = 'contents';
    return;
  }

  noteEl.innerHTML = '<strong style="color:var(--text);">hybrid</strong> : ancien moteur + scalping. Le classique travaille en <strong>M15/M5</strong> et les réglages ci-dessous ne concernent que la partie scalping.';
  scalpFieldsEl.style.display = 'contents';
}

async function approveOrRejectTrade(tradeId, action) {
  try {
    const res = await fetch('/api/' + action + '-trade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: tradeId })
    });
    const data = await res.json();
    if (data.ok) await fetchStatus();
    else alert('Erreur: ' + (data.error || 'inconnu'));
  } catch(e) { alert('Erreur réseau: ' + e); }
}

function renderPendingApprovals(list) {
  const container = document.getElementById('pending-approvals-list');
  if (!container) return;
  if (!list || list.length === 0) {
    container.innerHTML = '<div style="color:var(--muted);font-size:12px;">Aucun trade en attente.</div>';
    return;
  }
  const rows = list.map(t => {
    const expires = new Date(t.expires_at);
    const minutesLeft = Math.max(0, Math.round((expires - Date.now()) / 60000));
    const confPct = Math.round((t.confidence || 0) * 100);
    const dirColor = t.direction === 'BUY' ? 'var(--green)' : '#ef4444';
    return `
      <div style="display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:8px;border:1px solid var(--border);background:rgba(255,255,255,0.03);margin-bottom:6px;flex-wrap:wrap;">
        <span style="font-family:var(--mono);font-weight:700;color:var(--text);">${t.instrument}</span>
        <span style="font-weight:700;color:${dirColor};font-size:13px;">${t.direction}</span>
        <span style="color:var(--muted);font-size:11px;">conf <strong style="color:var(--text);">${confPct}%</strong></span>
        <span style="color:var(--muted);font-size:11px;">SL <strong>${t.sl_pips}p</strong> TP <strong>${t.tp_pips}p</strong></span>
        <span style="color:var(--muted);font-size:11px;">source: ${t.source || '—'}</span>
        <span style="margin-left:auto;color:var(--muted);font-size:11px;">⏱ ${minutesLeft}min</span>
        <span style="font-family:var(--mono);font-size:10px;color:var(--muted);">#${t.id}</span>
        <button onclick="approveOrRejectTrade('${t.id}','approve')" style="padding:4px 14px;border-radius:6px;border:none;background:var(--green);color:#fff;font-weight:600;cursor:pointer;font-size:12px;">✅ Approuver</button>
        <button onclick="approveOrRejectTrade('${t.id}','reject')" style="padding:4px 14px;border-radius:6px;border:none;background:#ef4444;color:#fff;font-weight:600;cursor:pointer;font-size:12px;">❌ Rejeter</button>
      </div>`;
  });
  container.innerHTML = rows.join('');
}

function fmtPnl(val, currSym) {
  const sym = currSym || window._displayCurrency || '$';
  const v = parseFloat(val) || 0;
  const cls = v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral';
  const sign = v > 0 ? '+' : '';
  return `<span class="${cls}">${sign}${sym}${v.toFixed(2)}</span>`;
}

function perfDurationLabel(seconds) {
  const s = Math.max(0, parseInt(seconds || 0, 10));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, '0')}s`;
  return `${sec}s`;
}

function drawEquitySvg(points) {
  const host = document.getElementById('perf-equity-chart');
  if (!host) return;
  if (!points || !points.length) {
    host.innerHTML = '<span class="refresh-info">Aucune donnée equity.</span>';
    return;
  }

  const width = 640;
  const height = 190;
  const pad = 20;
  const values = points.map(p => parseFloat(p.balance || 0) || 0);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = (max - min) || 1;

  const coords = values.map((v, i) => {
    const x = pad + (i / Math.max(1, values.length - 1)) * (width - pad * 2);
    const y = (height - pad) - ((v - min) / span) * (height - pad * 2);
    return { x, y };
  });

  const line = coords.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const area = `${pad},${height - pad} ${line} ${width - pad},${height - pad}`;
  const up = values[values.length - 1] >= values[0];
  const color = up ? '#00ffa3' : '#ff4466';
  const last = coords[coords.length - 1];

  host.innerHTML = '<svg viewBox="0 0 ' + width + ' ' + height + '" width="100%" height="180" preserveAspectRatio="none">' +
    '<polyline fill="none" stroke="rgba(0,200,255,0.15)" stroke-width="1" points="' + `${pad},${height - pad} ${width - pad},${height - pad}` + '" />' +
    '<polygon fill="' + color + '22" points="' + area + '" />' +
    '<polyline fill="none" stroke="' + color + '" stroke-width="3" points="' + line + '" />' +
    '<circle cx="' + last.x.toFixed(1) + '" cy="' + last.y.toFixed(1) + '" r="4" fill="' + color + '" />' +
    '</svg>';
}

function renderPerformance(data) {
  if (!data) return;

  const dayPnl = parseFloat(data.cumulative_pnl_day || 0) || 0;
  const dayEl = document.getElementById('perf-day-pnl');
  if (dayEl) {
    dayEl.innerHTML = 'P&L jour: ' + fmtPnl(dayPnl);
  }

  const wr = data.win_rate_day || {};
  const wrEl = document.getElementById('perf-winrate');
  if (wrEl) {
    const wins = parseInt(wr.wins || 0, 10);
    const total = parseInt(wr.total || 0, 10);
    const rate = parseFloat(wr.rate || 0) || 0;
    wrEl.textContent = `Win rate: ${wins}/${total} (${rate.toFixed(1)}%)`;
  }

  const cb = data.circuit_breaker || {};
  const cbEl = document.getElementById('perf-cb-badge');
  if (cbEl) {
    const paused = !!cb.is_paused;
    cbEl.classList.toggle('active', paused);
    cbEl.textContent = paused
      ? `Circuit Breaker ACTIF${cb.reason ? ' - ' + cb.reason : ''}`
      : 'Circuit Breaker INACTIF';
  }

  drawEquitySvg(Array.isArray(data.equity_curve) ? data.equity_curve : []);

  const tbody = document.getElementById('perf-trades-body');
  const trades = Array.isArray(data.recent_trades) ? data.recent_trades : [];
  if (tbody) {
    if (!trades.length) {
      tbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted);text-align:center;padding:12px 0;">Aucune donnée</td></tr>';
    } else {
      tbody.innerHTML = trades.map((t) => {
        const pnl = parseFloat(t.pnl || 0) || 0;
        const pnlCls = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : 'neutral';
        const currSym = window._displayCurrency || '$';
        let pnlTxt;
        if (window._isCents) {
          const pnlUsd = pnl / 100;
          pnlTxt = (pnl > 0 ? '+' : '') + '\u00a2' + pnl.toFixed(2) + ' <span style="color:var(--muted);font-size:0.85em;">($' + (pnl > 0 ? '+' : '') + pnlUsd.toFixed(2) + ')</span>';
        } else {
          pnlTxt = (pnl > 0 ? '+' : '') + '$' + pnl.toFixed(2);
        }
        const dir = String(t.direction || '?').toUpperCase();
        const dirClass = dir === 'BUY' ? 'buy' : dir === 'SELL' ? 'sell' : 'wait';
        return '<tr>' +
          '<td>' + (t.instrument || '?') + '</td>' +
          '<td><span class="pos-dir ' + dirClass + '">' + dir + '</span></td>' +
          '<td><span class="' + pnlCls + '">' + pnlTxt + '</span></td>' +
          '<td>' + (t.duration || perfDurationLabel(t.duration_seconds)) + '</td>' +
        '</tr>';
      }).join('');
    }
  }

  const tsEl = document.getElementById('perf-last-update');
  if (tsEl) {
    tsEl.textContent = new Date().toLocaleTimeString('fr-FR');
  }
}

function connectPerformanceWs() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${window.location.host}/ws`;
  try {
    if (performanceSocket && (performanceSocket.readyState === WebSocket.OPEN || performanceSocket.readyState === WebSocket.CONNECTING)) {
      return;
    }
    performanceSocket = new WebSocket(url);
    performanceSocket.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data || '{}');
        if (msg.type === 'performance') {
          renderPerformance(msg.data || {});
        }
      } catch (_) {}
    };
    performanceSocket.onclose = () => {
      setTimeout(connectPerformanceWs, 3000);
    };
    performanceSocket.onerror = () => {
      try { performanceSocket.close(); } catch (_) {}
    };
  } catch (_) {
    setTimeout(connectPerformanceWs, 5000);
  }
}

function colorVal(el, val) {
  el.className = 'kpi-value ' + (val > 0 ? 'positive' : val < 0 ? 'negative' : 'neutral');
}

function populateSettings(data) {
  const settings = data.settings || {};
  document.getElementById('setting-check-interval').value = settings.check_interval_minutes || 15;
  document.getElementById('setting-risk').value = settings.max_risk_per_trade || 0.015;
  document.getElementById('setting-daily-target').value = coalesce(settings.daily_target, 5.0);
  document.getElementById('setting-daily-loss').value = coalesce(settings.daily_loss_limit, -10.0);
  document.getElementById('setting-max-positions').value = settings.max_open_positions || 1;
  document.getElementById('setting-local-model').value = settings.local_llm_model || 'qwen2.5:3b';
  document.getElementById('setting-local-endpoint').value = settings.local_llm_endpoint || 'http://127.0.0.1:11434/api/generate';
  document.getElementById('setting-local-timeout').value = coalesce(settings.local_llm_timeout, 300);
  document.getElementById('setting-analysis-mode').value = settings.llm_analysis_mode || 'precision';
  document.getElementById('setting-confidence').value = settings.llm_min_confidence || 0.60;
  document.getElementById('setting-max-llm-calls').value = coalesce(settings.max_llm_calls_per_day, 0);
  document.getElementById('setting-analysis-notes').value = settings.llm_analysis_notes || '';
  document.getElementById('setting-allow-trade').value = String(settings.allow_trade_execution || false);

  // Telegram + dynamic pairs
  document.getElementById('setting-telegram-enabled').value = String(coalesce(settings.telegram_enabled, true));
  document.getElementById('tg-status').textContent = coalesce(settings.telegram_enabled, true) ? 'actif' : 'désactivé';
  if (settings.telegram_bot_token) document.getElementById('setting-telegram-token').value = settings.telegram_bot_token;
  if (settings.telegram_chat_id) document.getElementById('setting-telegram-chatid').value = settings.telegram_chat_id;

  // Scalping settings
  document.getElementById('strategy-mode').value = settings.strategy_mode || 'hybrid';
  document.getElementById('scalp-mode').value = settings.scalp_mode || 'momentum';
  document.getElementById('scalp-timeframe').value = settings.scalp_timeframe || 'M5';
  document.getElementById('scalp-ema-fast').value = coalesce(settings.scalp_ema_fast, 9);
  document.getElementById('scalp-ema-slow').value = coalesce(settings.scalp_ema_slow, 21);
  document.getElementById('scalp-stoch-k').value = coalesce(settings.scalp_stoch_k, 5);
  document.getElementById('scalp-stoch-d').value = coalesce(settings.scalp_stoch_d, 3);
  document.getElementById('scalp-sl-atr').value = coalesce(settings.scalp_sl_atr_mult, 1.5);
  document.getElementById('scalp-tp-atr').value = coalesce(settings.scalp_tp_atr_mult, 3.0);
  document.getElementById('scalp-spread-gold').value = coalesce(settings.scalp_max_spread_gold, 6.0);
  document.getElementById('scalp-min-score').value = coalesce(settings.scalp_min_score, 5);
  document.getElementById('scalp-kill-zones').value = String(coalesce(settings.scalp_only_kill_zones, true));
  document.getElementById('scalp-max-per-hour').value = coalesce(settings.scalp_max_trades_per_hour, 2);
  document.getElementById('scalp-adx-min').value = coalesce(settings.scalp_adx_min_trend, 30);
  document.getElementById('require-human-confirmation').value = String(coalesce(settings.require_human_confirmation, false));
  updateStrategyModeUI();

  // Agent pipeline status: show from heartbeat data
  const agentData = data.agents || [];
  if (agentData.length > 0) {
    const running = agentData.filter(a => a.status === 'running').map(a => a.name.replace('Agent', '') + ' ✅');
    const stopped = agentData.filter(a => a.status !== 'running').map(a => a.name.replace('Agent', '') + ' 🔴');
    const all = [...running, ...stopped];
    document.getElementById('agent-pipeline-status').textContent = all.join(' → ') || '—';
  }

  // Account type info in settings panel
  const adSettings = data.account_display || {};
  const infoBadge = document.getElementById('account-type-info-badge');
  const infoDetail = document.getElementById('account-type-info-detail');
  if (infoBadge && adSettings.account_type_label) {
    infoBadge.textContent = adSettings.account_type_label;
    infoBadge.style.background = adSettings.account_type_color || '#3b82f6';
  }
  if (infoDetail) {
    if (adSettings.is_cents) {
      infoDetail.textContent = 'Valeurs en centimes (\u00a2). 100\u00a2 = 1$ USD réel.';
    } else {
      infoDetail.textContent = 'Valeurs monétaires affichées en USD ($)';
    }
  }
}

function scheduleAutoSave() {
  clearTimeout(autoSaveTimer);
  document.getElementById('settings-save-status').textContent = 'modification en attente';
  autoSaveTimer = setTimeout(() => saveSettings(true), 350);
}


async function saveSettings(silent = false) {
  const payload = {
    symbol_source_mode: 'fixed',
    symbol_selection_mode: 'fixed',
    preferred_symbols: 'XAUUSDm',
    max_symbols_per_cycle: 1,
    ai_provider_requested: 'ollama',
    check_interval_minutes: parseInt(document.getElementById('setting-check-interval').value || '5', 10),
    max_risk_per_trade: parseFloat(document.getElementById('setting-risk').value || '0.015'),
    daily_target: parseFloat(document.getElementById('setting-daily-target').value || '5'),
    daily_loss_limit: parseFloat(document.getElementById('setting-daily-loss').value || '-10'),
    max_open_positions: parseInt(document.getElementById('setting-max-positions').value || '1', 10),
    local_llm_model: document.getElementById('setting-local-model').value,
    local_llm_endpoint: document.getElementById('setting-local-endpoint').value,
    local_llm_timeout: parseInt(document.getElementById('setting-local-timeout').value || '300', 10),
    llm_analysis_mode: document.getElementById('setting-analysis-mode').value,
    llm_min_confidence: parseFloat(document.getElementById('setting-confidence').value || '0.60'),
    max_llm_calls_per_day: parseInt(document.getElementById('setting-max-llm-calls').value || '0', 10),
    llm_analysis_notes: document.getElementById('setting-analysis-notes').value,
    allow_trade_execution: document.getElementById('setting-allow-trade').value === 'true',
    telegram_enabled: document.getElementById('setting-telegram-enabled').value === 'true',
    telegram_bot_token: document.getElementById('setting-telegram-token').value.trim(),
    telegram_chat_id: document.getElementById('setting-telegram-chatid').value.trim(),
    strategy_mode: document.getElementById('strategy-mode').value,
    scalp_mode: document.getElementById('scalp-mode').value,
    scalp_timeframe: document.getElementById('scalp-timeframe').value,
    scalp_ema_fast: parseInt(document.getElementById('scalp-ema-fast').value || '9', 10),
    scalp_ema_slow: parseInt(document.getElementById('scalp-ema-slow').value || '21', 10),
    scalp_stoch_k: parseInt(document.getElementById('scalp-stoch-k').value || '5', 10),
    scalp_stoch_d: parseInt(document.getElementById('scalp-stoch-d').value || '3', 10),
    scalp_sl_atr_mult: parseFloat(document.getElementById('scalp-sl-atr').value || '1.5'),
    scalp_tp_atr_mult: parseFloat(document.getElementById('scalp-tp-atr').value || '3.0'),
    scalp_max_spread_gold: parseFloat(document.getElementById('scalp-spread-gold').value || '6.0'),
    scalp_min_score: parseInt(document.getElementById('scalp-min-score').value || '5', 10),
    scalp_only_kill_zones: document.getElementById('scalp-kill-zones').value === 'true',
    scalp_max_trades_per_hour: parseInt(document.getElementById('scalp-max-per-hour').value || '2', 10),
    scalp_adx_min_trend: parseFloat(document.getElementById('scalp-adx-min').value || '30'),
    require_human_confirmation: document.getElementById('require-human-confirmation').value === 'true',
  };

  const res = await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  document.getElementById('settings-save-status').textContent = data.ok ? 'sauvegardé instantanément' : 'erreur';
  if (!silent) {
    await fetchStatus();
  }
}

function getFocusedPair() {
  return currentFocusPair || (activeSymbolsList[0] || '');
}

function getNextRotationPair() {
  // Prioritize trending pairs (those with trending_score > 0)
  const trending = trendingPairsList.filter(p => p.trending_score > 0).map(p => p.symbol);
  const pool = trending.length ? trending : activeSymbolsList;
  if (!pool.length) return '';
  rotationIndex = (rotationIndex + 1) % pool.length;
  currentFocusPair = pool[rotationIndex];
  return currentFocusPair;
}

function syncFocusPairs(symbols, trending) {
  const visible = (symbols || []).filter(Boolean);
  if (visible.length) activeSymbolsList = visible;
  trendingPairsList = trending || [];
  const label = document.getElementById('rotation-label');
  const trendingSyms = trendingPairsList.filter(p => p.trending_score > 0);
  if (label) {
    if (trendingSyms.length) {
      label.textContent = '📈 Tendance : ' + trendingSyms.map(p => p.symbol + ' (' + (p.direction || '—') + ')').join(', ');
    } else {
      label.textContent = 'Focus XAU : ' + visible.join(', ');
    }
  }
}

function renderPairSnapshot(result) {
  if (!result) return;
  const snap = result.market_snapshot || {};
  const signal = result.signal || {};
  const details = signal.details || {};
  const action = String((result.decision && result.decision.decision) || 'WAIT').toUpperCase();
  const rr = action === 'SELL' ? coalesce(snap.rr_sell, details.rr_sell, 0) : coalesce(snap.rr_buy, details.rr_buy, 0);
  const closes = Array.isArray(snap.closes) ? snap.closes : [];
  const box = document.getElementById('pair-sparkline');

  if (closes.length >= 2) {
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const span = (max - min) || 1;
    const coords = closes.map((v, i) => {
      const x = (i / Math.max(1, closes.length - 1)) * 280;
      const y = 100 - (((v - min) / span) * 80 + 10);
      return { x, y };
    });
    const points = coords.map(p => p.x.toFixed(1) + ',' + p.y.toFixed(1)).join(' ');
    const area = '0,100 ' + points + ' 280,100';
    const last = coords[coords.length - 1] || { x: 280, y: 50 };
    const color = action === 'BUY' ? '#3dffa0' : action === 'SELL' ? '#ff5757' : '#ffb847';
    box.innerHTML = '<svg viewBox="0 0 280 100" width="100%" height="120" preserveAspectRatio="none">' +
      '<polygon fill="' + color + '22" points="' + area + '" />' +
      '<polyline fill="none" stroke="' + color + '" stroke-width="3.5" points="' + points + '" />' +
      '<circle cx="' + last.x.toFixed(1) + '" cy="' + last.y.toFixed(1) + '" r="4" fill="' + color + '" />' +
      '</svg>';
  } else {
    box.innerHTML = '<span class="refresh-info">Données marché insuffisantes</span>';
  }

  const rsi = Math.max(0, Math.min(100, parseFloat(snap.rsi || details.rsi || 0) || 0));
  const liveMove = parseFloat(coalesce(snap.price_change_pct, snap.momentum_5, 0)) || 0;
  const momentum = Math.max(0, Math.min(100, 50 + liveMove * 180));
  const trend = Math.max(0, Math.min(100, (parseFloat(snap.trend_strength || 0) || 0) * 240));
  const rrPct = Math.max(0, Math.min(100, (parseFloat(rr || 0) || 0) * 35));

  document.getElementById('metric-rsi').style.width = rsi + '%';
  document.getElementById('metric-rsi-value').textContent = rsi.toFixed(1);
  document.getElementById('metric-momentum').style.width = momentum + '%';
  document.getElementById('metric-momentum-value').textContent = liveMove.toFixed(3) + '%';
  document.getElementById('metric-trend').style.width = trend + '%';
  document.getElementById('metric-trend-value').textContent = (parseFloat(snap.trend_strength || 0) || 0).toFixed(3);
  document.getElementById('metric-rr').style.width = rrPct + '%';
  document.getElementById('metric-rr-value').textContent = (parseFloat(rr || 0) || 0).toFixed(2);

  document.getElementById('pair-market-note').textContent =
    'Prix ' + (parseFloat(snap.price || 0) || 0).toFixed(5) +
    ' · Δ live ' + (parseFloat(snap.price_change_pct || 0) || 0).toFixed(3) + '% · spread ' +
    (parseFloat(snap.spread || 0) || 0).toFixed(1) + ' pips · support ' +
    (parseFloat(snap.support || 0) || 0).toFixed(5) + ' · résistance ' +
    (parseFloat(snap.resistance || 0) || 0).toFixed(5);

  document.getElementById('pair-flow-note').textContent =
    'Régime ' + (snap.regime || details.market_regime || '—') +
    ' · pattern ' + (snap.candle_pattern || details.candle_pattern || '—') +
    ' · ATR ' + ((parseFloat(snap.atr_pips || signal.atr_pips || 0) || 0).toFixed(1)) + ' pips';
}

function renderAiDecision(result) {
  if (!result) return;
  const d = result.decision || {};
  const signal = result.signal || {};
  const details = signal.details || {};
  const snap = result.market_snapshot || {};
  const action = (d.decision || 'WAIT').toUpperCase();
  const klass = action === 'BUY' ? 'buy' : action === 'SELL' ? 'sell' : 'wait';
  const confidence = Math.round((parseFloat(d.confidence || 0) || 0) * 100);
  const spreadVal = parseFloat(coalesce(result.spread, snap.spread, 0)) || 0;
  const humanSummary = snap.human_summary || details.human_summary || '';
  const reasoning = d.reasoning || '';
  const displayText = reasoning && humanSummary && reasoning.includes(humanSummary.slice(0, 30))
    ? reasoning
    : [reasoning, humanSummary].filter(Boolean).join(' · ') || 'Analyse en attente.';

  document.getElementById('ai-live-symbol').textContent = result.instrument || '—';
  document.getElementById('ai-live-action').innerHTML = '<span class="ai-pill ' + klass + '">' + action + '</span>';
  document.getElementById('ai-live-confidence').textContent = confidence + '%';
  document.getElementById('ai-live-spread').textContent = spreadVal.toFixed(1) + 'p';
  const rr = action === 'SELL' ? coalesce(details.rr_sell, snap.rr_sell, 0) : coalesce(details.rr_buy, snap.rr_buy, 0);
  document.getElementById('ai-live-decision').innerHTML =
    '<strong>' + (result.instrument || '—') + '</strong> · ' +
    '<span class="ai-pill ' + klass + '">' + action + '</span>' +
    ' Score ' + (signal.score || 0) + '/5 · Régime ' + (details.market_regime || snap.regime || '—') +
    ' · RR ' + (parseFloat(rr) || 0).toFixed(2) +
    ' · Spread ' + spreadVal.toFixed(1) + 'p' +
    '<br>' + displayText;
  renderPairSnapshot(result);
}

function renderAiChart(data) {
  const rowsAll = (data.ml_history || []).slice(-40);
  const rows = rowsAll.slice(-20);
  const el = document.getElementById('ai-history-chart');
  if (!rows.length) {
    el.innerHTML = '<div class="refresh-info">Pas encore d\'historique IA.</div>';
    return;
  }
  el.innerHTML = rows.map((row) => {
    const decision = String(row.decision || 'WAIT').toUpperCase();
    const confPct = Math.round((parseFloat(row.confidence || 0) || 0) * 100);
    const scorePct = Math.round(((parseFloat(row.score || 0) || 0) / 5) * 100);
    const strength = Math.max(18, confPct, scorePct);
    const color = decision === 'BUY' ? 'var(--green)' : decision === 'SELL' ? 'var(--red)' : 'var(--amber)';
    const label = String(row.timestamp || '').slice(11, 16) || (row.instrument || '—').slice(0, 3);
    return '<div class="ai-bar-wrap" title="' + (row.instrument || '—') + ' | ' + decision + ' | score ' + (row.score || 0) + '/5 | conf ' + confPct + '%">' +
      '<div class="ai-bar" style="height:' + strength + '%;background:' + color + '"></div>' +
      '<div class="ai-bar-label">' + label + '</div>' +
    '</div>';
  }).join('');
}

function renderTrending(pairs) {
  const badge = document.getElementById('trending-badge');
  const tableDiv = document.getElementById('trending-table');
  if (!pairs || !pairs.length) {
    badge.textContent = '0 en tendance / 0 total';
    badge.style.background = 'var(--muted)';
    badge.style.color = '#fff';
    tableDiv.innerHTML = '<span style="color:var(--muted);">Aucune donnée de tendance pour le moment</span>';
    return;
  }
  const trending = pairs.filter(p => Number(coalesce(p.trending_score, 0)) > 0);
  const neutral = pairs.filter(p => Number(coalesce(p.trending_score, 0)) <= 0);

  badge.textContent = trending.length + ' en tendance / ' + pairs.length + ' total';
  badge.style.background = trending.length > 0 ? 'var(--green)' : 'var(--muted)';
  badge.style.color = '#000';

  if (pairs.length === 0) {
    tableDiv.innerHTML = '<span style="color:var(--muted);">Aucune donnée</span>';
    return;
  }

  let rows = pairs.map((p, i) => {
    const trendingScore = Number(coalesce(p.trending_score, 0));
    const isTrending = trendingScore > 0;
    const dirColor = p.direction === 'BUY' ? 'var(--green)' : p.direction === 'SELL' ? 'var(--red)' : 'var(--muted)';
    const dirIcon = p.direction === 'BUY' ? '🟢' : p.direction === 'SELL' ? '🔴' : '⚪';
    const regimeColor = (p.regime || '').includes('bullish') ? 'var(--green)' : (p.regime || '').includes('bearish') ? 'var(--red)' : 'var(--muted)';
    const trendBar = Math.min(100, Math.round(trendingScore * 10));
    const rsiVal = Number(coalesce(p.rsi, 50));
    const qualityVal = Number(coalesce(p.quality, 0));
    const bg = isTrending ? 'rgba(61,255,160,0.06)' : '';
    return '<tr style="background:' + bg + ';">' +
      '<td style="padding:4px 8px;color:var(--text);">' + (i + 1) + '</td>' +
      '<td style="padding:4px 8px;font-weight:600;">' + p.symbol + (isTrending ? ' 🔥' : '') + '</td>' +
      '<td style="padding:4px 8px;color:' + dirColor + ';">' + dirIcon + ' ' + (p.direction || '—') + '</td>' +
      '<td style="padding:4px 8px;">' +
        '<div style="display:flex;align-items:center;gap:4px;">' +
          '<div style="width:60px;height:6px;background:var(--border);border-radius:3px;overflow:hidden;">' +
            '<div style="width:' + trendBar + '%;height:100%;background:' + (isTrending ? 'var(--green)' : 'var(--muted)') + ';border-radius:3px;"></div>' +
          '</div>' +
          '<span style="font-size:0.8em;color:' + (isTrending ? 'var(--green)' : 'var(--muted)') + ';">' + trendingScore.toFixed(1) + '</span>' +
        '</div>' +
      '</td>' +
      '<td style="padding:4px 8px;color:' + regimeColor + ';font-size:0.82em;">' + (p.regime || '—') + '</td>' +
      '<td style="padding:4px 8px;font-size:0.82em;">RSI ' + rsiVal.toFixed(0) + '</td>' +
      '<td style="padding:4px 8px;font-size:0.82em;color:var(--accent);">' + qualityVal.toFixed(2) + '</td></tr>';
  }).join('');

  tableDiv.innerHTML = '<table style="width:100%;border-collapse:collapse;font-size:0.82em;">' +
    '<thead><tr style="border-bottom:1px solid var(--border2);color:var(--muted);">' +
    '<th style="padding:4px 8px;text-align:left;">#</th>' +
    '<th style="padding:4px 8px;text-align:left;">Paire</th>' +
    '<th style="padding:4px 8px;text-align:left;">Direction</th>' +
    '<th style="padding:4px 8px;text-align:left;">Score Tendance</th>' +
    '<th style="padding:4px 8px;text-align:left;">Régime</th>' +
    '<th style="padding:4px 8px;text-align:left;">RSI</th>' +
    '<th style="padding:4px 8px;text-align:left;">Qualité</th></tr></thead><tbody>' + rows + '</tbody></table>';
}

function renderScanner(scan) {
  if (!scan) return;
  const badge = document.getElementById('scanner-badge');
  const mode = scan.mode || 'smart';
  const candidates = scan.candidates || [];
  const rejected = scan.rejected || [];
  const selected = (scan.selected && scan.selected.length)
    ? scan.selected
    : candidates.map(c => c.symbol).filter(Boolean);

  // Badge
  if (mode === 'smart') {
    badge.style.background = 'var(--accent)';
    badge.textContent = 'XAU · ' + selected.length + ' actif';
  } else if (mode === 'preferred') {
    badge.style.background = '#f39c12'; badge.style.color = '#000';
    badge.textContent = 'FIXE · ' + selected.length + ' actif';
  } else {
    badge.textContent = mode;
  }

  // Selected pairs
  const selDiv = document.getElementById('scan-selected');
  if (candidates.length > 0) {
    const selCandidates = candidates.filter(c => selected.includes(c.symbol));
    selDiv.innerHTML = selCandidates.map(c => {
      const tags = (c.tags || []).map(t =>
        '<span style="padding:1px 5px;border-radius:3px;font-size:0.7em;' +
        (t === 'major' ? 'background:#2a5d96;color:#8fc' : 'background:#5d2a96;color:#c8f') + ';">' + t + '</span>'
      ).join(' ');
      const spreadVal = Number(coalesce(c.spread, 0));
      const maxSpreadVal = Number(coalesce(c.max_spread, 0));
      const spreadPct = c.spread_pct !== undefined ? Number(c.spread_pct) : (maxSpreadVal > 0 ? (spreadVal / maxSpreadVal) * 100 : 0);
      const priorityVal = Number(coalesce(c.priority, c.score, 0));
      const pctColor = spreadPct < 30 ? 'var(--green)' : spreadPct < 60 ? 'var(--amber)' : 'var(--red)';
      return '<div style="display:flex;align-items:center;gap:8px;padding:3px 0;border-bottom:1px solid var(--border);">' +
        '<strong style="min-width:90px;">' + c.symbol + '</strong>' +
        '<span style="color:' + pctColor + ';">' + spreadVal.toFixed(1) + 'p</span>' +
        '<span style="color:var(--muted);font-size:0.8em;">(' + spreadPct.toFixed(0) + '% du max)</span>' +
        '<span style="color:var(--accent);font-size:0.8em;">★ ' + priorityVal.toFixed(2) + '</span>' +
        tags + '</div>';
    }).join('');
  } else {
    selDiv.innerHTML = selected.length > 0
      ? selected.map(s => '<span style="margin-right:6px;">' + s + '</span>').join('')
      : '<span style="color:var(--muted);">Aucun XAU retenu</span>';
  }

  // Rejected pairs
  const rejDiv = document.getElementById('scan-rejected');
  if (rejected.length > 0) {
    rejDiv.innerHTML = rejected.map(r =>
      '<div style="padding:2px 0;font-size:0.82em;">' +
      '<span style="min-width:90px;display:inline-block;">' + r.symbol + '</span> ' +
      '<span style="color:var(--red);">' + coalesce(r.spread, '—') + 'p > ' + coalesce(r.max_spread, '—') + 'p</span></div>'
    ).join('');
  } else {
    rejDiv.innerHTML = '<span style="color:var(--green);">Aucun rejet XAU</span>';
  }

  // Full table
  const tableWrap = document.getElementById('scan-table-wrap');
  if (candidates.length > 0) {
    let rows = candidates.map((c, i) => {
      const isSel = selected.includes(c.symbol);
      const bg = isSel ? 'rgba(0,166,166,0.10)' : '';
      const spreadVal = Number(coalesce(c.spread, 0));
      const maxSpreadVal = Number(coalesce(c.max_spread, 0));
      const spreadPct = c.spread_pct !== undefined ? Number(c.spread_pct) : (maxSpreadVal > 0 ? (spreadVal / maxSpreadVal) * 100 : 0);
      const priorityVal = Number(coalesce(c.priority, c.score, 0));
      const pctColor = spreadPct < 30 ? 'var(--green)' : spreadPct < 60 ? 'var(--amber)' : 'var(--red)';
      return '<tr style="background:' + bg + ';">' +
        '<td style="padding:4px 8px;color:var(--text);">' + (i + 1) + '</td>' +
        '<td style="padding:4px 8px;font-weight:600;">' + c.symbol + (isSel ? ' ✅' : '') + '</td>' +
        '<td style="padding:4px 8px;color:' + pctColor + ';">' + spreadVal.toFixed(1) + '</td>' +
        '<td style="padding:4px 8px;color:var(--muted);">' + (maxSpreadVal ? maxSpreadVal.toFixed(1) : '—') + '</td>' +
        '<td style="padding:4px 8px;color:var(--accent);">' + priorityVal.toFixed(3) + '</td>' +
        '<td style="padding:4px 8px;color:' + pctColor + ';">' + spreadPct.toFixed(0) + '%</td>' +
        '<td style="padding:4px 8px;">' + (c.tags || []).join(', ') + '</td></tr>';
    }).join('');
    tableWrap.innerHTML = '<table style="width:100%;border-collapse:collapse;font-size:0.82em;">' +
      '<thead><tr style="border-bottom:1px solid var(--border2);color:var(--muted);">' +
      '<th style="padding:4px 8px;text-align:left;">#</th>' +
      '<th style="padding:4px 8px;text-align:left;">Paire</th>' +
      '<th style="padding:4px 8px;text-align:left;">Spread</th>' +
      '<th style="padding:4px 8px;text-align:left;">Max</th>' +
      '<th style="padding:4px 8px;text-align:left;">Priorité</th>' +
      '<th style="padding:4px 8px;text-align:left;">Spread %</th>' +
      '<th style="padding:4px 8px;text-align:left;">Tags</th></tr></thead><tbody>' + rows + '</tbody></table>';
  } else {
    tableWrap.innerHTML = '';
  }
}

function toggleProtections() {
  const body = document.getElementById('protections-body');
  const arrow = document.getElementById('protections-arrow');
  const isClosed = getComputedStyle(body).display === 'none';
  body.style.display = isClosed ? 'block' : 'none';
  arrow.textContent = isClosed ? '▼' : '▶';
}

function toggleCalendar() {
  const body = document.getElementById('calendar-body');
  const arrow = document.getElementById('calendar-arrow');
  const isClosed = getComputedStyle(body).display === 'none';
  body.style.display = isClosed ? 'block' : 'none';
  arrow.textContent = isClosed ? '▼' : '▶';
}

function toggleStrategies() {
  const body = document.getElementById('strategies-body');
  const arrow = document.getElementById('strategies-arrow');
  const isClosed = getComputedStyle(body).display === 'none';
  body.style.display = isClosed ? 'block' : 'none';
  arrow.textContent = isClosed ? '▼' : '▶';
}

function renderCalendar(calendar) {
  const newsPause = (calendar && calendar.news_pause) || {};
  const upcoming = (calendar && calendar.upcoming) || [];
  const badge = document.getElementById('news-pause-badge');
  const container = document.getElementById('calendar-events');

  if (badge) {
    badge.style.display = newsPause.pause ? 'inline-block' : 'none';
  }

  if (!container) {
    return;
  }

  if (!upcoming.length) {
    container.innerHTML = newsPause.pause
      ? '<div style="color:var(--amber);">Pause active: ' + (newsPause.reason || 'news importante') + '</div>'
      : '<div style="color:var(--muted);">Aucun événement économique imminent</div>';
    return;
  }

  container.innerHTML = upcoming.map((event) => {
    const impact = String(event.impact || event.importance || 'medium').toLowerCase();
    const color = impact === 'high' ? 'var(--red)' : impact === 'medium' ? 'var(--amber)' : 'var(--green)';
    const when = event.time || event.datetime || event.date || '—';
    const title = event.title || event.event || event.name || 'Événement';
    const currency = event.currency || event.country || '—';
    return '<div style="padding:8px 0;border-bottom:1px solid var(--border);">' +
      '<div style="display:flex;justify-content:space-between;gap:12px;">' +
        '<strong style="color:' + color + ';">' + title + '</strong>' +
        '<span style="color:var(--muted);font-family:var(--mono);">' + when + '</span>' +
      '</div>' +
      '<div style="font-size:0.82em;color:var(--muted);margin-top:3px;">' + currency + ' · impact ' + impact + '</div>' +
    '</div>';
  }).join('');
}

function renderStrategies(strategies) {
  const table = document.getElementById('strat-scan-table');
  const sessionLabel = document.getElementById('strat-session-label');
  const countLabel = document.getElementById('strat-count');
  const tsLabel = document.getElementById('strat-last-ts');
  const sessionBadge = document.getElementById('session-badge');
  const candidates = (strategies && strategies.candidates) || [];
  const session = (strategies && strategies.session) || '—';
  const timestamp = (strategies && strategies.timestamp) || '';

  if (sessionLabel) sessionLabel.textContent = session;
  if (countLabel) countLabel.textContent = String(candidates.length);
  if (tsLabel) tsLabel.textContent = timestamp ? String(timestamp).replace('T', ' ').slice(0, 19) : '—';
  if (sessionBadge) {
    sessionBadge.textContent = session;
    sessionBadge.style.background = candidates.length > 0 ? 'var(--green)' : 'var(--muted)';
    sessionBadge.style.color = candidates.length > 0 ? '#000' : '#fff';
  }

  if (!table) {
    return;
  }

  if (!candidates.length) {
    table.innerHTML = '<div style="color:var(--muted);">Aucune analyse récente disponible</div>';
    return;
  }

  table.innerHTML = candidates.map((item, index) => {
    const direction = item.signal_direction || item.direction || 'WAIT';
    const dirColor = direction === 'BUY' ? 'var(--green)' : direction === 'SELL' ? 'var(--red)' : 'var(--amber)';
    const score = Number(item.score || item.trending_score || 0);
    const spread = coalesce(item.spread, '—');
    return '<div style="display:grid;grid-template-columns:36px 1fr auto auto;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);">' +
      '<div style="color:var(--muted);font-family:var(--mono);">' + (index + 1) + '</div>' +
      '<div>' +
        '<div style="font-weight:600;">' + (item.symbol || '—') + '</div>' +
        '<div style="font-size:0.82em;color:var(--muted);">' + (item.regime || 'régime inconnu') + ' · spread ' + spread + '</div>' +
      '</div>' +
      '<div style="color:' + dirColor + ';font-family:var(--mono);">' + direction + '</div>' +
      '<div style="color:var(--accent);font-family:var(--mono);">' + score.toFixed(1) + '</div>' +
    '</div>';
  }).join('');
}

function renderProtections(prot) {
  if (!prot) return;
  const badge = document.getElementById('protection-badge');
  const cb = prot.circuit_breaker || {};
  const isActive = cb.is_active || false;
  const consLoss = cb.consecutive_losses || 0;
  const maxLoss = cb.daily_max_loss !== undefined ? cb.daily_max_loss : -5.0;
  const threshold = cb.consecutive_loss_threshold || 3;

  // Badge
  if (isActive) {
    badge.style.background = '#e74c3c'; badge.style.color = '#fff';
    badge.textContent = '🔴 PAUSE ACTIVE';
  } else {
    badge.style.background = '#00e676'; badge.style.color = '#000';
    badge.textContent = '✅ Trading Actif';
  }

  // État CB
  const cbDiv = document.getElementById('prot-cb-state');
  if (isActive) {
    const reason = cb.pause_reason || '—';
    const until = cb.pause_until ? cb.pause_until.replace('T', ' ').slice(0, 19) : '';
    cbDiv.innerHTML = '<strong style="color:#e74c3c;">⛔ BLOQUÉ</strong><br>' +
      '<span style="opacity:0.8;">' + reason + '</span>' +
      (until ? '<br>Jusqu\'à: <strong>' + until + '</strong>' : '');
  } else {
    cbDiv.innerHTML = '<strong style="color:#00e676;">✅ Actif</strong><br>' +
      '<span style="opacity:0.7;">Prêt à trader</span>';
  }

  // Pertes consécutives
  const lossDiv = document.getElementById('prot-losses');
  const lossColor = consLoss >= threshold ? '#e74c3c' : consLoss >= threshold - 1 ? '#f39c12' : '#00e676';
  const lossBar = Math.min(100, Math.round((consLoss / threshold) * 100));
  lossDiv.innerHTML = '<strong style="color:' + lossColor + '">' + consLoss + ' / ' + threshold + '</strong>' +
    '<div style="width:100%;height:5px;background:var(--border);border-radius:3px;margin-top:4px;overflow:hidden;">' +
      '<div style="width:' + lossBar + '%;height:100%;background:' + lossColor + ';border-radius:3px;"></div></div>';

  // P&L journalier
  const dailyDiv = document.getElementById('prot-daily');
  const dailyPnl = prot.daily_pnl || 0;
  const pnlColor = dailyPnl >= 0 ? '#00e676' : '#e74c3c';
  dailyDiv.innerHTML = 'P&L: <strong style="color:' + pnlColor + '">' + (dailyPnl >= 0 ? '+' : '') + dailyPnl.toFixed(2) + '$</strong>' +
    '<br>Seuil: <strong>' + maxLoss.toFixed(2) + '$</strong>';

  // News pause
  const newsDiv = document.getElementById('prot-news');
  const newsPause = prot.news_pause || {};
  if (newsPause.pause) {
    newsDiv.innerHTML = '<strong style="color:#f39c12;">⚠️ PAUSE NEWS</strong><br>' +
      '<span style="opacity:0.8;font-size:0.85em;">' + (newsPause.reason || '') + '</span>';
  } else {
    newsDiv.innerHTML = '<strong style="color:#00e676;">✅ Aucune news imminente</strong>';
  }

  // Alerts
  const alertsDiv = document.getElementById('prot-alerts');
  const alerts = prot.alerts || [];
  alertsDiv.innerHTML = alerts.length > 0
    ? alerts.map(a => '<div style="color:#f39c12;">⚠️ ' + a + '</div>').join('')
    : '<span style="color:#00e676;">Aucune alerte active</span>';
}

function toggleAgentsStatus() {
  const body = document.getElementById('agents-status-body');
  const arrow = document.getElementById('agents-status-arrow');
  const isClosed = getComputedStyle(body).display === 'none';
  body.style.display = isClosed ? 'block' : 'none';
  arrow.textContent = isClosed ? '▼' : '▶';
}

function initPanelsOpen() {
  [
    ['scanner-body', 'scanner-arrow'],
    ['trending-body', 'trending-arrow'],
    ['agents-status-body', 'agents-status-arrow'],
    ['calendar-body', 'calendar-arrow'],
    ['strategies-body', 'strategies-arrow'],
    ['protections-body', 'protections-arrow'],
  ].forEach(([bodyId, arrowId]) => {
    const body = document.getElementById(bodyId);
    const arrow = document.getElementById(arrowId);
    if (body) body.style.display = 'block';
    if (arrow) arrow.textContent = '▼';
  });
}

function renderAgentsStatus(agents) {
  const badge = document.getElementById('agents-status-badge');
  const list = document.getElementById('agents-status-list');
  if (!agents || agents.length === 0) {
    badge.textContent = 'Aucun agent'; badge.style.background = 'var(--muted)';
    list.innerHTML = '<span style="color:var(--muted);">Aucune donnée de heartbeat</span>';
    return;
  }
  const running = agents.filter(a => a.status === 'running').length;
  badge.textContent = running + '/' + agents.length + ' actifs';
  badge.style.background = running === agents.length ? 'var(--green)' : running > 0 ? '#f39c12' : '#e74c3c';
  badge.style.color = running === agents.length ? '#000' : '#fff';

  list.innerHTML = agents.map(a => {
    const statusColor = a.status === 'running' ? '#00e676' : a.status === 'stale' ? '#f39c12' : '#e74c3c';
    const statusIcon = a.status === 'running' ? '🟢' : a.status === 'stale' ? '🟡' : '🔴';
    const extra = a.extra && Object.keys(a.extra).length
      ? Object.entries(a.extra).map(([k, v]) => k + '=' + v).join(' · ') : '';
    const ts = a.last_seen ? a.last_seen.replace('T', ' ').slice(0, 19) : '—';
    return '<div style="display:flex;align-items:center;gap:10px;padding:7px 10px;background:rgba(255,255,255,0.03);border-radius:8px;">' +
      '<span style="font-size:1em;">' + statusIcon + '</span>' +
      '<div style="flex:1;">' +
        '<strong style="color:var(--text);">' + (a.name || a.agent) + '</strong>' +
        (extra ? '<span style="color:var(--muted);font-size:0.8em;margin-left:8px;">' + extra + '</span>' : '') +
        '<div style="color:var(--muted);font-size:0.78em;margin-top:2px;">Vu: ' + ts + '</div>' +
      '</div>' +
      '<span style="color:' + statusColor + ';font-size:0.8em;font-weight:600;">' + (a.status || '—').toUpperCase() + '</span>' +
    '</div>';
  }).join('');
}


async function testAI() {
  if (aiBusy) return;
  aiBusy = true;
  const symbol = 'XAUUSDm';
  document.getElementById('ai-test-result').textContent = 'Analyse IA XAUUSDm...';
  try {
    const res = await fetch('/api/test-ai', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instrument: symbol })
    });
    const data = await res.json();
    if (data.ok) {
      const d = (data.result && data.result.decision) || {};
      lastAiPayload = data.result || null;
      renderAiDecision(data.result || {});
      const liveMode = document.getElementById('setting-allow-trade').value === 'true'
        ? 'mode réel démo actif'
        : 'mode aperçu actif';
      document.getElementById('ai-test-result').textContent =
        'Signal IA aperçu · ' + ((data.result && data.result.instrument) || '—') + ' · ' +
        (d.decision || 'WAIT') + ' · confiance ' + Math.round((parseFloat(d.confidence || 0) || 0) * 100) + '% · ' + liveMode + ' · ordre réel uniquement si le cycle d\'exécution confirme encore le setup.';
    } else {
      document.getElementById('ai-test-result').textContent = 'Erreur test IA: ' + (data.error || 'inconnue');
    }
  } finally {
    aiBusy = false;
    autoAiCountdown = 30;
    await fetchStatus();
  }
}

async function testTelegram() {
  const el = document.getElementById('tg-test-result');
  el.textContent = 'Envoi en cours...';
  try {
    // Assure que les champs token/chat_id modifiés sont bien persistés avant test.
    await saveSettings(true);
    const res = await fetch('/api/test-telegram', { method: 'POST' });
    const data = await res.json();
    el.textContent = data.ok
      ? ('✅ ' + (data.message || 'Message test envoyé'))
      : ('❌ ' + (data.error || data.message || 'Échec'));
  } catch (e) {
    el.textContent = '❌ Erreur: ' + e.message;
  }
}

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    latestStatusPayload = data;

    // Market status
    const badge = document.getElementById('status-badge');
    const statusText = document.getElementById('status-text');
    if (data.market_open) {
      badge.className = 'open';
      statusText.textContent = (data.market_status && data.market_status.reason) || 'MARCHÉ OUVERT';
    } else {
      badge.className = 'closed';
      statusText.textContent = (data.market_status && data.market_status.reason) || 'MARCHÉ FERMÉ';
    }

    // Config active
    document.getElementById('symbol-mode').textContent = '🪙 XAUUSDm';
    document.getElementById('ai-provider').textContent = data.ai_provider || '—';
    document.getElementById('active-symbols').textContent = 'XAUUSDm';
    populateSettings(data);
    renderPendingApprovals(data.pending_approvals || []);
    const allowTrade = String((data.settings && data.settings.allow_trade_execution) || false) === 'true';
    const modeNote = document.getElementById('ai-mode-note');
    if (modeNote) {
      modeNote.textContent = allowTrade
        ? 'Le cockpit affiche un signal IA en aperçu sur XAUUSDm. Un ordre réel MT5 n\'est envoyé que par le cycle automatique quand toutes les validations sont encore confirmées.'
        : 'L\'agent autonome analyse XAUUSDm en continu. Active le trading réel démo pour autoriser les ouvertures et fermetures automatiques.';
    }
    syncFocusPairs(data.active_symbols || [], data.trending_pairs || []);

    // Features bar
    const fb = document.getElementById('features-bar');
    if (fb) {
      const agentsList = data.agents || [];
      const agentsOk = agentsList.length > 0 && agentsList.filter(a => a.status === 'running').length === agentsList.length;
      const cbOk = !(((data.market_protections && data.market_protections.circuit_breaker) || {}).is_active);
      const features = [
        {label: '🔍 Smart Scan', on: !!(data.smart_scan && (data.smart_scan.candidates || []).length >= 0)},
        {label: '📱 Telegram', on: String(coalesce(data.settings && data.settings.telegram_enabled, true)) === 'true'},
        {label: '🤖 Agents (' + agentsList.filter(a => a.status === 'running').length + '/' + agentsList.length + ')', on: agentsOk},
        {label: '🛡️ Circuit Breaker', on: cbOk},
        {label: '📰 Calendrier', on: true},
        {label: allowTrade ? '✅ Trading Actif' : '⏸️ Paper Mode', on: allowTrade},
      ];
      fb.innerHTML = features.map(f =>
        '<span style="padding:2px 8px;border-radius:4px;font-size:0.72em;font-weight:500;' +
        (f.on ? 'background:rgba(61,255,160,0.12);color:var(--green);border:1px solid rgba(61,255,160,0.2);'
              : 'background:rgba(255,255,255,0.04);color:var(--muted);border:1px solid var(--border);') +
        '">' + f.label + '</span>'
      ).join('');
    }

    renderAiChart(data);
    if (data.economic_calendar) renderCalendar(data.economic_calendar);
    if (data.pro_strategies) renderStrategies(data.pro_strategies);
    if (data.market_protections) renderProtections(data.market_protections);
    if (data.smart_scan) renderScanner(data.smart_scan);
    if (data.trending_pairs) renderTrending(data.trending_pairs);
    if (data.agents) renderAgentsStatus(data.agents);

    // Live snapshot rotation: show chart even before first AI call
    if (data.live_snapshot && data.live_snapshot.closes) {
      const liveInst = data.live_snapshot.instrument || '—';
      const aiMatch = lastAiPayload && lastAiPayload.instrument === liveInst;
      const livePayload = aiMatch ? Object.assign({}, lastAiPayload, { market_snapshot: data.live_snapshot }) : {
        instrument: liveInst,
        market_snapshot: data.live_snapshot,
        signal: {},
        decision: { decision: 'WAIT', confidence: 0, reasoning: "En attente d'analyse IA\u2026" },
      };
      renderAiDecision(livePayload);
    } else if (lastAiPayload) {
      renderAiDecision(lastAiPayload);
    }
    if (!initialAiWarmupDone && !aiBusy && activeSymbolsList.length) {
      initialAiWarmupDone = true;
      setTimeout(() => testAI(), 300);
    }

    // Account type detection + adaptive display
    const ad = data.account_display || {};
    const isCents = !!ad.is_cents;
    const displayCurrency = ad.display_currency || '$';
    window._displayCurrency = displayCurrency;
    window._isCents = isCents;
    const accentColor = ad.accent_color || '#3b82f6';
    document.documentElement.style.setProperty('--accent', accentColor);

    // Header subtitle
    const subtitleEl = document.getElementById('header-subtitle');
    if (subtitleEl && ad.header_subtitle) subtitleEl.textContent = ad.header_subtitle;

    // Account type badge
    const badgeEl = document.getElementById('account-type-badge');
    if (badgeEl && ad.account_type_label) {
      badgeEl.style.display = 'inline';
      badgeEl.textContent = ad.account_type_label;
      badgeEl.style.background = ad.account_type_color || '#3b82f6';
    }

    // KPIs
    const balance = (data.account && data.account.balance) || 0;
    if (isCents && ad.balance_real_usd != null) {
      document.getElementById('balance').textContent = '\u00a2' + balance.toFixed(2);
      document.getElementById('balance-sub').textContent = '= $' + ad.balance_real_usd.toFixed(2) + ' USD réel';
    } else {
      document.getElementById('balance').textContent = '$' + balance.toFixed(2);
      document.getElementById('balance-sub').textContent = 'USD';
    }

    const dpnl = data.daily_pnl || 0;
    const dpnlEl = document.getElementById('daily-pnl');
    dpnlEl.innerHTML = fmtPnl(dpnl);
    const target = parseFloat(coalesce(data.settings && data.settings.daily_target, 0));
    document.getElementById('daily-pnl-sub').textContent = target > 0 ? ('vs objectif ' + displayCurrency + target.toFixed(2)) : 'objectif désactivé';

    const tpnl = data.total_pnl || 0;
    document.getElementById('total-pnl').innerHTML = fmtPnl(tpnl);

    const wr = data.win_rate || 0;
    document.getElementById('win-rate').textContent = wr.toFixed(1) + '%';
    document.getElementById('total-trades').textContent = (data.total_trades || 0) + ' trades';

    document.getElementById('open-positions').textContent = (data.open_positions && data.open_positions.length) || 0;

    const apiCalls = data.llm_calls_today || data.api_calls_today || 0;
    const maxApiDay = parseInt(coalesce(data.settings && data.settings.max_llm_calls_per_day, 0), 10);
    document.getElementById('api-calls').textContent = maxApiDay > 0 ? (apiCalls + ' / ' + maxApiDay) : (apiCalls + ' / illimité');
    document.getElementById('api-bar').style.width = maxApiDay > 0 ? ((apiCalls / maxApiDay) * 100) + '%' : '100%';

    document.getElementById('last-update').textContent =
      new Date().toLocaleTimeString('fr-FR');

    // ── XAUUSDm Live panel ──────────────────────────────────────────────
    updateXauLivePanel(data);
    // ────────────────────────────────────────────────────────────────────

    // Log
    const logs = data.session_log || [];
    const logEl = document.getElementById('log-container');
    if (logs.length > 0) {
      logEl.innerHTML = logs.slice().reverse().map(line => {
        const icon = line.includes('✅') ? '✅' :
                     line.includes('❌') ? '❌' :
                     line.includes('📈') ? '📈' :
                     line.includes('⚠️') ? '⚠️' :
                     line.includes('🤖') ? '🤖' :
                     line.includes('🔔') ? '🔔' : '·';
        const timeMatch = line.match(/\[(\d{2}:\d{2}:\d{2})\]/);
        const time = timeMatch ? timeMatch[1] : '';
        const msg = line.replace(/\[[\d:]+\]\s*/, '');
        return `<div class="log-line">
          <span class="log-time">${time}</span>${msg}
        </div>`;
      }).join('');
    }

    // Positions
    const positions = data.open_positions || [];
    document.getElementById('positions-count').textContent = positions.length;
    const posEl = document.getElementById('positions-container');
    if (positions.length === 0) {
      posEl.innerHTML = '<div style="color:var(--muted);font-size:12px;text-align:center;padding:12px 0">Aucune position</div>';
    } else {
      posEl.innerHTML = positions.map(p => {
        const sl = p.sl ? p.sl.toFixed(2) : '—';
        const tp = p.tp ? p.tp.toFixed(2) : '—';
        const cur = p.price_current ? p.price_current.toFixed(2) : '—';
        return `
        <div class="position-item" style="flex-direction:column;align-items:stretch;gap:6px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <div class="pos-instrument">${p.instrument}</div>
              <div style="margin-top:2px"><span class="pos-dir ${p.direction.toLowerCase()}">${p.direction}</span> <span style="color:var(--muted);font-size:11px;font-family:var(--mono)">@ ${(p.avg_price||0).toFixed(2)}</span></div>
            </div>
            <div class="pos-pnl">${fmtPnl(p.unrealized_pnl)}</div>
          </div>
          <div style="display:flex;gap:12px;font-family:var(--mono);font-size:11px;color:var(--muted)">
            <span>Prix: <span style="color:var(--text)">${cur}</span></span>
            <span>SL: <span style="color:var(--red)">${sl}</span></span>
            <span>TP: <span style="color:var(--green)">${tp}</span></span>
          </div>
        </div>`;
      }).join('');
    }

    // Patterns
    const patterns = data.best_patterns || [];
    const patEl = document.getElementById('patterns-container');
    if (patterns.length === 0) {
      patEl.innerHTML = '<div style="color:var(--muted);font-size:12px;text-align:center;padding:12px 0">Pas encore de données</div>';
    } else {
      patEl.innerHTML = patterns.map(p => `
        <div class="pattern-row">
          <div class="pattern-name">${p.pattern.replace(/_/g,' ')}</div>
          <div class="pattern-bar-track"><div class="pattern-bar-fill" style="width:${p.win_rate}%"></div></div>
          <div class="pattern-wr">${p.win_rate.toFixed(0)}%</div>
        </div>
      `).join('');
    }

    // Recent trades
    const trades = data.recent_trades || [];
    const tbody = document.getElementById('trades-tbody');
    if (trades.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="color:var(--muted);text-align:center;padding:16px">Aucun trade</td></tr>';
    } else {
      tbody.innerHTML = trades.slice().reverse().map(t => {
        const tradeStatus = String(t.status || 'open').toLowerCase();
        const pnl = t.pnl != null
          ? fmtPnl(t.pnl)
          : (tradeStatus === 'open'
              ? '<span style="color:var(--amber)">ouvert</span>'
              : '<span style="color:var(--muted)">—</span>');
        const dir = `<span class="pos-dir ${((t.direction || '').toLowerCase())}">${t.direction}</span>`;
        return `<tr>
          <td>${t.id}</td>
          <td>${t.instrument}</td>
          <td>${dir}</td>
          <td>${(t.entry_price || 0).toFixed(5)}</td>
          <td style="color:var(--muted);font-size:11px">${(t.pattern || '').replace(/_/g,' ')}</td>
          <td>${t.signal_score || 0}/5</td>
          <td>${pnl}</td>
          <td style="color:var(--muted);font-size:11px">${t.status || 'open'}</td>
        </tr>`;
      }).join('');
    }

  } catch(e) {
    console.error('Fetch error:', e);
    const badge = document.getElementById('status-badge');
    const statusText = document.getElementById('status-text');
    badge.className = 'closed';
    statusText.textContent = 'BACKEND INDISPONIBLE';
    const logEl = document.getElementById('log-container');
    if (logEl) {
      logEl.innerHTML = '<div style="color:var(--red);font-family:var(--mono);font-size:12px;padding:20px 0;text-align:center">' +
        'Impossible de joindre /api/status. Vérifie que launch.py tourne.' +
        '</div>';
    }
  }
}

// Countdown & auto-refresh
// ── XAUUSDm Live panel update ────────────────────────────────────────────
function updateXauLivePanel(data) {
  const sym = '$';
  // Prix bid/ask depuis live_snapshot ou open_positions
  const snap = data.live_snapshot || {};
  const xauPos = (data.open_positions || []).find(p => String(p.instrument||'').toUpperCase() === 'XAUUSDM');

  // Bid/Ask
  const bid = snap.bid || snap.close || 0;
  const ask = snap.ask || (bid > 0 ? bid + (snap.spread_pips || 0) * 0.1 : 0);
  document.getElementById('xau-bid').textContent = bid > 0 ? bid.toFixed(2) : '—';
  document.getElementById('xau-ask').textContent = ask > 0 ? ask.toFixed(2) : '—';

  // Spread
  const spreadVal = snap.spread_pips || 0;
  const spreadEl = document.getElementById('xau-spread');
  spreadEl.textContent = spreadVal > 0 ? spreadVal.toFixed(1) + 'p' : '—';
  spreadEl.style.color = spreadVal > 0 && spreadVal > 6 ? 'var(--red)' : 'var(--green)';

  // P&L jour
  const dpnl = parseFloat(data.daily_pnl || 0);
  const dayPnlEl = document.getElementById('xau-day-pnl');
  let pnlIcon = dpnl >= 5.0 ? '🏆' : dpnl <= -10.0 ? '⛔' : dpnl > 0 ? '🟢' : dpnl < 0 ? '🔴' : '⚪';
  dayPnlEl.innerHTML = pnlIcon + ' <span style="color:' + (dpnl >= 0 ? 'var(--green)' : 'var(--red)') + ';font-weight:700;">' + (dpnl >= 0 ? '+' : '') + sym + dpnl.toFixed(2) + '</span>';

  // Trades jour
  const todayTrades = (data.recent_trades_today || 0);
  document.getElementById('xau-day-trades').textContent = todayTrades + ' / 5';

  // Badge de titre
  const badgeEl = document.getElementById('xau-pnl-badge');
  if (dpnl >= 5.0) {
    badgeEl.innerHTML = '🏆 Objectif atteint ! +' + sym + dpnl.toFixed(2);
    badgeEl.style.color = 'var(--green)';
  } else if (dpnl <= -10.0) {
    badgeEl.innerHTML = '⛔ Limite perte atteinte ' + sym + dpnl.toFixed(2);
    badgeEl.style.color = 'var(--red)';
  } else {
    badgeEl.innerHTML = (dpnl >= 0 ? '🟢 +' : '🔴 ') + sym + dpnl.toFixed(2) + ' jour';
    badgeEl.style.color = dpnl >= 0 ? 'var(--green)' : 'var(--red)';
  }

  // Barre de progression objectif $5
  const goalPct = Math.min(100, Math.max(0, (dpnl / 5.0) * 100));
  document.getElementById('xau-goal-bar').style.width = goalPct + '%';
  document.getElementById('xau-goal-label').textContent = (dpnl >= 0 ? '+' : '') + sym + dpnl.toFixed(2) + ' / ' + sym + '5.00';

  // Position ouverte XAU
  const posWrap = document.getElementById('xau-position-wrap');
  if (xauPos) {
    posWrap.style.display = 'block';
    const pnlPos = parseFloat(xauPos.unrealized_pnl || xauPos.pnl || 0);
    document.getElementById('xau-pos-dir').innerHTML = '<span style="color:' + (xauPos.direction === 'BUY' ? 'var(--green)' : 'var(--red)') + ';">' + xauPos.direction + '</span>';
    document.getElementById('xau-pos-entry').textContent = (xauPos.avg_price || xauPos.entry_price || 0).toFixed(2);
    document.getElementById('xau-pos-pnl').innerHTML = '<span style="color:' + (pnlPos >= 0 ? 'var(--green)' : 'var(--red)') + ';">' + (pnlPos >= 0 ? '+' : '') + sym + pnlPos.toFixed(2) + '</span>';
    document.getElementById('xau-pos-sl').textContent = xauPos.sl ? xauPos.sl.toFixed(2) : '—';
    document.getElementById('xau-pos-tp').textContent = xauPos.tp ? xauPos.tp.toFixed(2) : '—';
    document.getElementById('xau-pos-lot').textContent = xauPos.volume || xauPos.lot || '—';
  } else {
    posWrap.style.display = 'none';
  }

  // Derniers signaux XAU depuis scan_results
  const scan = data.smart_scan || {};
  const xauCandidate = (scan.candidates || []).find(c => String(c.symbol||'').toUpperCase() === 'XAUUSDM');
  const sigList = document.getElementById('xau-signals-list');
  if (xauCandidate) {
    const dir = xauCandidate.signal_direction || '—';
    const score = xauCandidate.score || 0;
    const src = xauCandidate.source || '—';
    const ts = xauCandidate.scanned_at ? new Date(xauCandidate.scanned_at).toLocaleTimeString('fr-FR') : '—';
    const regime = xauCandidate.regime || '';
    const dirColor = dir === 'BUY' ? 'var(--green)' : dir === 'SELL' ? 'var(--red)' : 'var(--muted)';
    const scorePips = Array.from({length: 5}, (_, i) =>
      '<span style="display:inline-block;width:8px;height:8px;border-radius:2px;margin:0 1px;background:' + (i < score ? 'var(--amber)' : 'var(--border2)') + ';"></span>'
    ).join('');
    sigList.innerHTML =
      '<span style="color:' + dirColor + ';font-weight:700;">' + dir + '</span>' +
      ' &nbsp;Score: ' + scorePips +
      ' &nbsp;<span style="color:var(--accent);">[' + src + ']</span>' +
      (regime ? ' &nbsp;<span style="color:var(--muted);">' + regime + '</span>' : '') +
      ' &nbsp;<span style="color:var(--muted2);">' + ts + '</span>';
  } else if (scan.updated_at) {
    sigList.textContent = 'Pas de signal XAU actif — dernier scan ' + new Date(scan.updated_at).toLocaleTimeString('fr-FR');
  }
}
// ─────────────────────────────────────────────────────────────────────────

function tick() {
  countdown--;
  autoAiCountdown--;
  document.getElementById('countdown').textContent = countdown;
  if (autoAiEnabled) {
    document.getElementById('ai-live-auto').textContent = 'ON · ' + Math.max(0, autoAiCountdown) + 's';
  }
  if (countdown <= 0) {
    countdown = 5;
    fetchStatus();
  }
  if (autoAiEnabled && autoAiCountdown <= 0 && !aiBusy) {
    testAI();
  }
}

function initAutoSave() {
  [
    'setting-check-interval',
    'setting-risk',
    'setting-daily-target',
    'setting-daily-loss',
    'setting-max-positions',
    'setting-local-model',
    'setting-local-endpoint',
    'setting-local-timeout',
    'setting-analysis-mode',
    'setting-confidence',
    'setting-max-llm-calls',
    'setting-analysis-notes',
    'setting-allow-trade', 'strategy-mode',
    'scalp-mode', 'scalp-timeframe', 'scalp-ema-fast', 'scalp-ema-slow',
    'scalp-stoch-k', 'scalp-stoch-d', 'scalp-sl-atr', 'scalp-tp-atr',
    'scalp-spread-gold', 'scalp-min-score',
    'scalp-kill-zones', 'scalp-max-per-hour', 'scalp-adx-min',
    'require-human-confirmation'
  ].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', scheduleAutoSave);
      el.addEventListener('input', scheduleAutoSave);
    }
  });
}

fetchStatus().finally(() => {
  initPanelsOpen();
  if (!initialAiWarmupDone) {
    setTimeout(() => testAI(), 700);
  }
});
connectPerformanceWs();
initAutoSave();
setInterval(tick, 1000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Silence les logs HTTP

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, default=str, ensure_ascii=False).encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, OSError):
            # Client disconnected before response could be sent.
            # Ignore this error to keep the dashboard server stable.
            pass

    def _send_ws_text(self, text: str):
        payload = text.encode("utf-8")
        header = bytearray([0x81])  # FIN + text frame
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length <= 65535:
            header.append(126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(127)
            header.extend(length.to_bytes(8, "big"))
        self.wfile.write(header + payload)
        self.wfile.flush()

    def _serve_websocket(self):
        upgrade = str(self.headers.get("Upgrade", "")).lower()
        key = self.headers.get("Sec-WebSocket-Key")
        if upgrade != "websocket" or not key:
            self._send_json({"error": "upgrade websocket requis"}, status=400)
            return

        accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("utf-8")).digest()).decode("ascii")
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()

        try:
            while True:
                perf = _build_performance_payload()
                self._send_ws_text(json.dumps({"type": "performance", "data": perf}, ensure_ascii=False))
                time.sleep(5)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return

    def do_GET(self):
        if self.path.startswith('/ws'):
            self._serve_websocket()
        elif self.path.startswith('/api/status'):
            try:
                from urllib.parse import urlparse, parse_qs
                from datetime import datetime, timezone
                from mt5_bridge import build_broker
                from learning_store import AgentMemory
                from circuit_breaker import CircuitBreaker
                from runtime_db import RuntimeStore
                from economic_calendar import EconomicCalendar
                import settings as cfg

                qs = parse_qs(urlparse(self.path).query)
                focus = (qs.get('focus', [''])[0] or '').strip()

                broker = build_broker()
                memory = AgentMemory()
                cb = CircuitBreaker()
                store = RuntimeStore()
                calendar = EconomicCalendar()

                # Calendar pause check
                try:
                    cal_pause = calendar.should_pause_trading("XAUUSDm")
                    cal_status = {
                        "news_pause": cal_pause,
                        "upcoming": [],
                    }
                except Exception:
                    cal_status = {}
                positions = broker.get_open_positions()
                recent_trades = memory.get_recent_trades(20)
                # Reconcile stale local 'open' trades against live broker positions.
                # If no matching live position exists, expose the trade as closed in the dashboard payload.
                try:
                  open_tickets = set()
                  open_symbols = set()
                  for p in positions or []:
                    ticket = p.get("ticket") or p.get("position_ticket") or p.get("broker_id")
                    symbol = p.get("instrument") or p.get("symbol")
                    if ticket is not None:
                      open_tickets.add(str(ticket))
                    if symbol:
                      open_symbols.add(str(symbol))

                  reconciled = []
                  for trade in recent_trades or []:
                    t = dict(trade)
                    if str(t.get("status", "")).lower() == "open":
                      trade_ticket = t.get("position_ticket") or t.get("broker_id") or t.get("ticket")
                      trade_symbol = t.get("instrument") or t.get("symbol")
                      ticket_is_open = trade_ticket is not None and str(trade_ticket) in open_tickets
                      symbol_is_open = bool(trade_symbol) and str(trade_symbol) in open_symbols
                      if not ticket_is_open and not symbol_is_open:
                        t["status"] = "closed"
                        if not t.get("closed_at"):
                          t["closed_at"] = datetime.now(timezone.utc).isoformat()
                        if not t.get("close_reason"):
                          t["close_reason"] = "SYNC_CLOSE"
                    reconciled.append(t)
                  recent_trades = reconciled
                except Exception:
                  pass
                cb_status = cb.get_status()
                # Normalize circuit breaker status for frontend
                cb_status = {
                  "is_active": cb_status.get("is_paused", False),
                  "pause_reason": cb_status.get("reason", ""),
                  "pause_until": cb_status.get("pause_until"),
                  "consecutive_losses": cb_status.get("consecutive_losses", cb.consecutive_losses),
                  "daily_max_loss": cb.daily_max_loss,
                  "consecutive_loss_threshold": cb.consecutive_loss_threshold,
                  "remaining_minutes": cb_status.get("remaining_minutes", 0),
                }
                runtime_settings = store.get_settings()

                # P&L stats from memory
                daily_pnl = memory.get_daily_pnl()
                win_rate = memory.get_win_rate()  # already in %
                all_trades = memory.get_recent_trades(1000)
                total_trades = len(all_trades)
                total_pnl = sum(t.get("pnl", 0) or 0 for t in all_trades if t.get("status") == "closed")
                llm_calls_today = memory.get_llm_calls_today()

                # Session log from audit_logger
                try:
                    from audit_logger import get_audit_logger
                    session_log = get_audit_logger().get_session_log(50)
                    llm_calls_today = get_audit_logger().get_daily_stats().get("llm_calls", 0)
                except Exception:
                    session_log = []
                    llm_calls_today = memory.get_llm_calls_today()

                # Market open check (weekday + hour)
                now = datetime.now(timezone.utc)
                weekday = now.weekday()  # 0=Mon, 6=Sun
                hour = now.hour
                market_open = weekday < 5 and not (weekday == 4 and hour >= 22) and not (weekday == 6 and hour < 22)
                market_status = {"reason": "MARCHÉ OUVERT" if market_open else "MARCHÉ FERMÉ (week-end)"}

                account = broker.get_account_summary()
                active_symbols = ["XAUUSDm"]

                # Live snapshot XAU
                live_snapshot = {}
                try:
                    sym = "XAUUSDm"
                    candles = broker.get_candles(sym, "H1", 60)
                    if len(candles) >= 2:
                        closes = [float(c["close"]) for c in candles[-30:]]
                        last = candles[-1]
                        prev = candles[-2]
                        price_change_pct = ((last["close"] - prev["close"]) / prev["close"] * 100) if prev["close"] else 0
                        live_snapshot = {
                            "instrument": sym,
                            "closes": closes,
                            "price": last["close"],
                            "price_change_pct": round(price_change_pct, 4),
                            "spread": broker.get_spread_pips(sym) if hasattr(broker, "get_spread_pips") else 0,
                        }
                except Exception:
                    pass

                # Best patterns from memory
                best_patterns = memory.get_best_patterns() if hasattr(memory, "get_best_patterns") else []

                # Scan results from AnalystAgent
                import time as _time
                scan_file = Path("data/scan_results.json")
                smart_scan = {"candidates": [], "rejected": []}
                trending_pairs = []
                scan_data = {}
                if scan_file.exists():
                    try:
                        scan_data = json.loads(scan_file.read_text(encoding="utf-8"))
                        smart_scan = {
                            "candidates": scan_data.get("candidates", []),
                            "rejected": scan_data.get("rejected", []),
                        }
                        trending_pairs = scan_data.get("trending", [])
                    except Exception:
                        pass

                # Agents heartbeat
                hb_file = Path("data/agents_heartbeat.json")
                agents_status = []
                if hb_file.exists():
                    try:
                        hb_data = json.loads(hb_file.read_text(encoding="utf-8"))
                        now_ts = datetime.now(timezone.utc).timestamp()
                        for agent_name, info in hb_data.items():
                            last_seen_str = info.get("last_seen", "")
                            try:
                                last_ts = datetime.fromisoformat(last_seen_str).timestamp()
                                age_sec = now_ts - last_ts
                                status = "running" if age_sec < 120 else "stale"
                            except Exception:
                                status = "unknown"
                            agents_status.append({"name": agent_name, "status": status, "last_seen": last_seen_str})
                    except Exception:
                        pass
                if not agents_status:
                    for name in ["AnalystAgent", "RiskAgent", "DecisionAgent", "ExecutionAgent", "GuardianAgent"]:
                        agents_status.append({"name": name, "status": "stopped"})

                # Account type detection
                _is_cents = bool(account.get("is_cents", False))
                account_display = {
                    "is_cents": _is_cents,
                    "display_currency": account.get("display_currency", "$"),
                    "cents_ratio": int(account.get("cents_ratio", 1)),
                    "account_type_label": "COMPTE CENTS" if _is_cents else "COMPTE STANDARD",
                    "account_type_color": "#f59e0b" if _is_cents else "#3b82f6",
                    "accent_color": "#f59e0b" if _is_cents else "#3b82f6",
                    "header_subtitle": "AUTONOME · OLLAMA · MT5 · CENTS" if _is_cents else "AUTONOME · OLLAMA · MT5",
                    "balance_real_usd": round(account.get("balance", 0.0) / 100.0, 2) if _is_cents else None,
                    "nav_real_usd": round(account.get("nav", 0.0) / 100.0, 2) if _is_cents else None,
                }

                status = {
                    # Market state
                    "market_open": market_open,
                    "market_status": market_status,
                    # Account
                    "account": account,
                    "account_display": account_display,
                    "open_positions": positions,
                    "recent_trades": recent_trades,
                    # Stats
                    "daily_pnl": daily_pnl,
                    "total_pnl": total_pnl,
                    "win_rate": win_rate,
                    "total_trades": total_trades,
                    # Config
                    "settings": runtime_settings,
                    "ai_provider": f"Ollama {runtime_settings.get('local_llm_model', 'qwen2.5:3b')}",
                    "active_symbols": active_symbols,
                    "llm_calls_today": llm_calls_today,
                    # Live data
                    "live_snapshot": live_snapshot,
                    "best_patterns": best_patterns,
                    "session_log": session_log,
                    # Modules
                    "economic_calendar": cal_status,
                    "circuit_breaker": cb_status,
                    "smart_scan": smart_scan,
                    "trending_pairs": trending_pairs,
                    "market_protections": {
                        "circuit_breaker": cb_status,
                        "daily_pnl": daily_pnl,
                        "news_pause": cal_status.get("news_pause", {"pause": False, "reason": ""}),
                        "alerts": cb_status.get("alerts", []),
                    },
                    "pro_strategies": {
                        "candidates": smart_scan.get("candidates", []),
                        "session": scan_data.get("session", "—"),
                        "timestamp": scan_data.get("timestamp", ""),
                    },
                    # Agents status
                    "agents": agents_status,
                }
                # Human pending approvals
                try:
                    from runtime_db import RuntimeStore as _RS
                    _store = _RS()
                    _store.expire_old_approvals()
                    status["pending_approvals"] = _store.get_pending_approvals()
                except Exception:
                    status["pending_approvals"] = []
                if focus:
                    status["focus"] = focus
                self._send_json(status)
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
        else:
            body = HTML_PAGE.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        if self.path == '/api/settings':
            try:
                from runtime_db import RuntimeStore
                length = int(self.headers.get('Content-Length', '0'))
                raw = self.rfile.read(length).decode('utf-8') if length else '{}'
                payload = json.loads(raw)
                settings = RuntimeStore().update_settings(payload)
                self._send_json({"ok": True, "settings": settings})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=500)
        elif self.path == '/api/test-ai':
            try:
                from mt5_bridge import build_broker
                from signal_engine import calculate_signal_score
                from smart_strategies import build_strategies_context
                length = int(self.headers.get('Content-Length', '0'))
                raw = self.rfile.read(length).decode('utf-8') if length else '{}'
                payload = json.loads(raw)
                instrument = payload.get('instrument', 'XAUUSDm')
                broker = build_broker()
                candles = broker.get_candles(instrument, 'H1', 100)
                if len(candles) < 20:
                    self._send_json({"ok": False, "error": "Pas assez de données"})
                    return
                signal = calculate_signal_score(candles, instrument)
                strategies = build_strategies_context(
                    instrument, candles, [], [],
                    signal_direction=signal.get('direction'),
                    signal_score=signal.get('score', 0),
                    open_positions=[]
                )
                direction = str(signal.get('direction', 'WAIT') or 'WAIT').upper()
                score = int(signal.get('score', 0) or 0)
                confidence = max(0.0, min(1.0, score / 5.0))
                decision = {
                  "decision": direction if direction in ("BUY", "SELL") else "WAIT",
                  "confidence": confidence,
                  "reasoning": f"Signal technique {direction} score {score}/5",
                }
                result = {
                    "instrument": instrument,
                    "signal": signal,
                  "decision": decision,
                    "strategies_summary": strategies.get('summary', '') if isinstance(strategies, dict) else str(strategies)[:200],
                    "spread": broker.get_spread_pips(instrument),
                }
                self._send_json({"ok": True, "result": result})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=500)
        elif self.path == '/api/test-telegram':
            try:
                from telegram_notifier import TelegramNotifier
                tg = TelegramNotifier()
                result = tg.test_connection()
                self._send_json(result)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=500)
        elif self.path in ('/api/approve-trade', '/api/reject-trade'):
            try:
                from runtime_db import RuntimeStore
                length = int(self.headers.get('Content-Length', '0'))
                raw = self.rfile.read(length).decode('utf-8') if length else '{}'
                payload = json.loads(raw)
                trade_id = str(payload.get('id', '')).strip()
                if not trade_id:
                    self._send_json({"ok": False, "error": "id manquant"}, status=400)
                    return
                new_status = 'approved' if self.path == '/api/approve-trade' else 'rejected'
                updated = RuntimeStore().update_approval_status(trade_id, new_status)
                self._send_json({"ok": updated, "id": trade_id, "status": new_status})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=500)
        else:
            self._send_json({"ok": False, "error": "route inconnue"}, status=404)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"🌐 Dashboard: http://localhost:{port}")
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()
