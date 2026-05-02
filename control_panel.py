#!/usr/bin/env python3
"""
Dashboard web léger pour monitorer l'agent
Lance avec: python web/dashboard.py
Accès: http://localhost:8080
"""

import json
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent IA MT5 · Trading Autonome</title>
<style>
  :root {
    --bg: #071018;
    --bg2: #0d1823;
    --bg3: #132334;
    --border: rgba(255,255,255,0.06);
    --border2: rgba(255,255,255,0.12);
    --text: #e7f0f8;
    --muted: #7f96aa;
    --accent: #00a6a6;
    --accent2: #5eead4;
    --green: #3dffa0;
    --green2: #1a7a4a;
    --red: #ff5757;
    --red2: #7a1a1a;
    --amber: #ffc857;
    --teal: #3dd9ff;
    --mono: Consolas, 'Courier New', monospace;
    --sans: 'Bahnschrift', 'Trebuchet MS', 'Segoe UI', sans-serif;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    min-height: 100vh;
    font-size: 14px;
  }

  /* GRID BACKGROUND */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      linear-gradient(rgba(61,217,255,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,166,166,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }

  .wrapper { position: relative; z-index: 1; max-width: 1200px; margin: 0 auto; padding: 24px 20px; }

  /* HEADER */
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 28px;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--border);
  }
  .logo {
    display: flex; align-items: center; gap: 12px;
  }
  .logo-icon {
    width: 36px; height: 36px;
    background: linear-gradient(135deg, var(--accent), var(--teal));
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px;
  }
  .logo-text { font-size: 18px; font-weight: 600; letter-spacing: -0.02em; }
  .logo-sub { font-size: 11px; color: var(--muted); font-family: var(--mono); letter-spacing: 0.05em; }
  #status-badge {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 14px;
    border-radius: 20px;
    font-family: var(--mono); font-size: 12px;
    border: 1px solid var(--border2);
  }
  #status-badge.open { background: rgba(61,255,160,0.08); border-color: rgba(61,255,160,0.2); color: var(--green); }
  #status-badge.closed { background: rgba(107,107,128,0.1); border-color: var(--border); color: var(--muted); }
  .dot { width: 6px; height: 6px; border-radius: 50%; }
  .open .dot { background: var(--green); box-shadow: 0 0 6px var(--green); animation: pulse 2s infinite; }
  .closed .dot { background: var(--muted); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

  /* KPI CARDS */
  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
  }
  .kpi {
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    transition: border-color 0.2s;
  }
  .kpi:hover { border-color: var(--border2); }
  .kpi-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }
  .kpi-value { font-family: var(--mono); font-size: 22px; font-weight: 500; line-height: 1; }
  .kpi-sub { font-size: 11px; color: var(--muted); margin-top: 4px; font-family: var(--mono); }
  .positive { color: var(--green); }
  .negative { color: var(--red); }
  .neutral { color: var(--text); }
  .accent { color: var(--accent2); }

  /* MAIN GRID */
  .main-grid {
    display: grid;
    grid-template-columns: 1fr 340px;
    gap: 16px;
    margin-bottom: 16px;
  }

  /* PANELS */
  .panel {
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
  }
  .panel-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 18px;
    border-bottom: 1px solid var(--border);
  }
  .panel-title { font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
  .panel-body { padding: 16px 18px; }

  /* LOG */
  #log-container {
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.8;
    height: 320px;
    overflow-y: auto;
    padding: 14px 18px;
    scrollbar-width: thin;
    scrollbar-color: var(--border2) transparent;
  }
  .log-line { padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.02); }
  .log-line:last-child { border: none; }
  .log-time { color: var(--muted); margin-right: 8px; }
  .log-icon { margin-right: 6px; }

  /* POSITIONS */
  .position-item {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
  }
  .position-item:last-child { border: none; }
  .pos-instrument { font-family: var(--mono); font-weight: 500; font-size: 13px; }
  .pos-dir {
    font-size: 10px; font-weight: 500; padding: 2px 8px; border-radius: 4px;
    font-family: var(--mono); letter-spacing: 0.05em;
  }
  .pos-dir.buy { background: rgba(61,255,160,0.12); color: var(--green); }
  .pos-dir.sell { background: rgba(255,87,87,0.12); color: var(--red); }
  .pos-pnl { font-family: var(--mono); font-size: 13px; }

  /* TRADES TABLE */
  .trades-table { width: 100%; border-collapse: collapse; }
  .trades-table th {
    font-size: 10px; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.08em; padding: 0 0 10px; text-align: left;
    border-bottom: 1px solid var(--border);
  }
  .trades-table td {
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
    font-family: var(--mono); font-size: 12px;
  }
  .trades-table tr:last-child td { border: none; }

  /* API USAGE BAR */
  .api-bar-track {
    height: 6px; background: var(--bg3); border-radius: 3px; overflow: hidden;
    margin-top: 8px;
  }
  .api-bar-fill {
    height: 100%; border-radius: 3px;
    background: linear-gradient(90deg, var(--accent), var(--teal));
    transition: width 0.5s ease;
  }

  /* REFRESH */
  .refresh-info { font-family: var(--mono); font-size: 11px; color: var(--muted); }

  /* PATTERNS */
  .pattern-row {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 0; border-bottom: 1px solid var(--border);
  }
  .pattern-row:last-child { border: none; }
  .pattern-name { font-family: var(--mono); font-size: 12px; flex: 1; }
  .pattern-wr { font-family: var(--mono); font-size: 12px; color: var(--accent2); }
  .pattern-bar-track { width: 80px; height: 4px; background: var(--bg3); border-radius: 2px; }
  .pattern-bar-fill { height: 100%; border-radius: 2px; background: var(--accent); }

  .form-grid {
    display:grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 10px;
  }
  .field label {
    display:block;
    font-size:11px;
    color: var(--muted);
    margin-bottom:6px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .field input, .field select {
    width:100%;
    background: var(--bg3);
    color: var(--text);
    border:1px solid var(--border2);
    border-radius:8px;
    padding:10px 12px;
    font-family: var(--mono);
    font-size:12px;
  }
  .btn {
    background: linear-gradient(90deg, var(--accent), var(--teal));
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    font-family: var(--mono);
    font-size: 12px;
    cursor: pointer;
  }
  .btn.secondary {
    background: var(--bg3);
    border: 1px solid var(--border2);
    color: var(--text);
  }
  .live-ai-box {
    border: 1px solid var(--border);
    background: var(--bg3);
    border-radius: 12px;
    padding: 12px;
    margin-top: 12px;
  }
  .mini-grid {
    display:grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 8px;
    margin-top: 10px;
  }
  .mini-kpi {
    background: rgba(255,255,255,0.02);
    border:1px solid var(--border);
    border-radius: 10px;
    padding: 8px;
  }
  .mini-kpi .label {
    font-size: 10px;
    color: var(--muted);
    text-transform: uppercase;
  }
  .mini-kpi .value {
    font-family: var(--mono);
    font-size: 13px;
    margin-top: 4px;
  }
  .ai-bars {
    display:flex;
    align-items:flex-end;
    gap:6px;
    height:150px;
    margin-top:12px;
    padding:10px 8px 0;
    border:1px solid var(--border);
    border-radius:12px;
    background: linear-gradient(180deg, rgba(124,106,247,0.08), rgba(61,217,255,0.02));
  }
  .ai-bar-wrap {
    flex:1;
    display:flex;
    flex-direction:column;
    align-items:center;
    gap:4px;
    min-width: 20px;
  }
  .ai-bar {
    width:100%;
    border-radius: 8px 8px 0 0;
    min-height: 18px;
    opacity: 0.98;
    box-shadow: 0 0 10px rgba(124,106,247,0.18);
    border: 1px solid rgba(255,255,255,0.08);
  }
  .ai-bar-label {
    font-size:9px;
    color: var(--muted);
    font-family: var(--mono);
  }
  .ai-pill {
    display:inline-block;
    padding: 3px 8px;
    border-radius: 999px;
    font-size:11px;
    font-family: var(--mono);
    margin-right:6px;
  }
  .ai-pill.buy { background: rgba(61,255,160,0.12); color: var(--green); }
  .ai-pill.sell { background: rgba(255,87,87,0.12); color: var(--red); }
  .ai-pill.wait { background: rgba(255,184,71,0.12); color: var(--amber); }
  .focus-toolbar {
    display:flex;
    gap:8px;
    align-items:center;
    flex-wrap:wrap;
    margin-bottom:10px;
  }
  .focus-toolbar select {
    background: var(--bg2);
    color: var(--text);
    border:1px solid var(--border2);
    border-radius:8px;
    padding:8px 10px;
    font-family: var(--mono);
    font-size:12px;
  }
  .market-deck {
    display:grid;
    grid-template-columns: 1.2fr 1fr;
    gap:10px;
    margin-top:12px;
  }
  .market-box {
    border:1px solid var(--border);
    border-radius:10px;
    padding:10px;
    background: rgba(255,255,255,0.02);
  }
  .sparkline-box {
    height:140px;
    display:flex;
    align-items:center;
    justify-content:center;
    border:1px solid var(--border);
    border-radius:10px;
    background: linear-gradient(180deg, rgba(124,106,247,0.08), rgba(61,217,255,0.02));
  }
  .metric-row {
    margin-bottom:8px;
  }
  .metric-head {
    display:flex;
    justify-content:space-between;
    font-size:11px;
    color: var(--muted);
    margin-bottom:4px;
    font-family: var(--mono);
  }
  .metric-track {
    height:8px;
    background: var(--bg);
    border-radius:999px;
    overflow:hidden;
  }
  .metric-fill {
    height:100%;
    border-radius:999px;
    background: linear-gradient(90deg, var(--accent), var(--teal));
  }
  .market-note {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    line-height: 1.6;
    margin-top: 8px;
  }

  /* AI EXCHANGE VIEWER */
  .ai-exchange {
    margin-top: 16px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: var(--bg2);
    overflow: hidden;
  }
  .ai-exchange-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 18px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    user-select: none;
  }
  .ai-exchange-header:hover { background: rgba(255,255,255,0.02); }
  .ai-exchange-body { padding: 0 18px 18px; display: none; }
  .ai-exchange-body.open { display: block; }
  .ai-msg {
    margin-top: 14px;
    border-radius: 12px;
    padding: 14px 16px;
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
  .ai-msg-prompt {
    background: linear-gradient(135deg, rgba(124,106,247,0.08), rgba(61,217,255,0.04));
    border: 1px solid rgba(124,106,247,0.15);
    border-left: 3px solid var(--accent);
  }
  .ai-msg-response {
    background: linear-gradient(135deg, rgba(61,255,160,0.06), rgba(61,217,255,0.04));
    border: 1px solid rgba(61,255,160,0.12);
    border-left: 3px solid var(--green);
  }
  .ai-msg-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .ai-msg-label.prompt-label { color: var(--accent2); }
  .ai-msg-label.response-label { color: var(--green); }
  .ai-exchange-meta {
    display: flex;
    gap: 16px;
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .toggle-arrow {
    transition: transform 0.2s;
    font-size: 14px;
    color: var(--muted);
  }
  .toggle-arrow.open { transform: rotate(180deg); }

  /* Responsive */
  @media (max-width: 768px) {
    .main-grid { grid-template-columns: 1fr; }
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
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
        <div class="logo-sub">AUTONOME · OLLAMA · MT5</div>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:12px">
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

        <div class="field">
          <label>Filtre symboles (vide = tous)</label>
          <input id="setting-preferred-symbols" placeholder="vide = tous les symboles MT5 visibles" />
        </div>
        <div class="field">
          <label>Max symboles</label>
          <input id="setting-max-symbols" type="number" min="1" max="20" />
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
      </div>
      <div style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
        <button class="btn" onclick="saveSettings()">Sauvegarder</button>
        <button class="btn" onclick="testAI()">Tester IA</button>
        <button class="btn secondary" id="auto-ai-btn" onclick="toggleAutoAI()">Auto IA: ON</button>
        <span class="refresh-info" id="ai-mode-note">Le cockpit affiche un signal IA en aperçu sur la paire active. Un ordre réel MT5 n'est envoyé que par le cycle automatique quand toutes les validations sont encore confirmées.</span>
      </div>
      <div id="ai-test-result" class="refresh-info" style="margin-top:10px;white-space:normal;line-height:1.6;">Chargement de l'analyse automatique sur la paire active...</div>

      <div class="live-ai-box">
        <div class="panel-title" style="margin-bottom:8px;">Cockpit IA en direct</div>
        <div class="focus-toolbar">
          <span class="refresh-info" id="rotation-label">Rotation auto sur toutes les paires</span>
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
            <div id="pair-sparkline" class="sparkline-box"><span class="refresh-info">Aucune paire analysée</span></div>
            <div id="pair-market-note" class="market-note">Le graphique montrera uniquement la paire sélectionnée.</div>
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

  <!-- SMART PAIR SCANNER -->
  <div class="ai-exchange" style="margin-bottom:16px;" id="scanner-panel">
    <div class="ai-exchange-header" onclick="toggleScanner()">
      <span class="panel-title">🔍 Scanner de Paires Dynamique</span>
      <span id="scanner-badge" style="padding:2px 8px;border-radius:4px;font-size:0.75em;margin-left:8px;background:var(--accent);color:#fff;">—</span>
      <span class="toggle-arrow" id="scanner-arrow">▼</span>
    </div>
    <div class="ai-exchange-body" id="scanner-body">
      <div style="display:flex;gap:16px;margin-bottom:10px;">
        <div style="flex:1;">
          <div style="color:var(--green);font-weight:600;margin-bottom:8px;">✅ Paires Sélectionnées</div>
          <div id="scan-selected" style="font-size:0.85em;">—</div>
        </div>
        <div style="flex:1;">
          <div style="color:var(--red);font-weight:600;margin-bottom:8px;">❌ Paires Rejetées (spread)</div>
          <div id="scan-rejected" style="font-size:0.85em;color:var(--muted);">—</div>
        </div>
      </div>
      <div id="scan-table-wrap" style="max-height:260px;overflow-y:auto;"></div>
    </div>
  </div>

  <!-- TRENDING PAIRS PANEL -->
  <div class="ai-exchange" style="margin-bottom:16px;" id="trending-panel">
    <div class="ai-exchange-header" onclick="toggleTrending()">
      <span class="panel-title">📈 Paires en Tendance (Analyse Silencieuse)</span>
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

  <!-- KPIs -->
  <div class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">Balance</div>
      <div class="kpi-value neutral" id="balance">—</div>
      <div class="kpi-sub">USD</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">P&L Aujourd'hui</div>
      <div class="kpi-value" id="daily-pnl">—</div>
      <div class="kpi-sub" id="daily-pnl-sub">vs objectif $2.00</div>
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

</div>

<script>
let countdown = 3;
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

function fmtPnl(val) {
  const v = parseFloat(val) || 0;
  const cls = v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral';
  const sign = v > 0 ? '+' : '';
  return `<span class="${cls}">${sign}$${v.toFixed(2)}</span>`;
}

function colorVal(el, val) {
  el.className = 'kpi-value ' + (val > 0 ? 'positive' : val < 0 ? 'negative' : 'neutral');
}

function populateSettings(data) {
  const settings = data.settings || {};
  const preferredSymbols = Array.isArray(settings.preferred_symbols)
    ? settings.preferred_symbols.join(',')
    : String(settings.preferred_symbols || '');
  document.getElementById('setting-preferred-symbols').value = preferredSymbols;
  document.getElementById('setting-max-symbols').value = settings.max_symbols_per_cycle || 3;
  document.getElementById('setting-check-interval').value = settings.check_interval_minutes || 15;
  document.getElementById('setting-risk').value = settings.max_risk_per_trade || 0.02;
  document.getElementById('setting-daily-target').value = settings.daily_target ?? 2.0;
  document.getElementById('setting-daily-loss').value = settings.daily_loss_limit ?? -5.0;
  document.getElementById('setting-max-positions').value = settings.max_open_positions || 2;
  document.getElementById('setting-local-model').value = settings.local_llm_model || 'qwen2.5:3b';
  document.getElementById('setting-local-endpoint').value = settings.local_llm_endpoint || 'http://127.0.0.1:11434/api/generate';
  document.getElementById('setting-local-timeout').value = settings.local_llm_timeout ?? 120;
  document.getElementById('setting-analysis-mode').value = settings.llm_analysis_mode || 'precision';
  document.getElementById('setting-confidence').value = settings.llm_min_confidence || 0.60;
  document.getElementById('setting-max-llm-calls').value = settings.max_llm_calls_per_day ?? 0;
  document.getElementById('setting-analysis-notes').value = settings.llm_analysis_notes || '';
  document.getElementById('setting-allow-trade').value = String(settings.allow_trade_execution || false);

  // Telegram + dynamic pairs
  document.getElementById('setting-telegram-enabled').value = String(settings.telegram_enabled ?? true);
  document.getElementById('tg-status').textContent = (settings.telegram_enabled ?? true) ? 'actif' : 'désactivé';
  if (settings.telegram_bot_token) document.getElementById('setting-telegram-token').value = settings.telegram_bot_token;
  if (settings.telegram_chat_id) document.getElementById('setting-telegram-chatid').value = settings.telegram_chat_id;

  // Agent pipeline status: show from heartbeat data
  const agentData = data.agents || [];
  if (agentData.length > 0) {
    const running = agentData.filter(a => a.status === 'running').map(a => a.name.replace('Agent', '') + ' ✅');
    const stopped = agentData.filter(a => a.status !== 'running').map(a => a.name.replace('Agent', '') + ' 🔴');
    const all = [...running, ...stopped];
    document.getElementById('agent-pipeline-status').textContent = all.join(' → ') || '—';
  }
}

function scheduleAutoSave() {
  clearTimeout(autoSaveTimer);
  document.getElementById('settings-save-status').textContent = 'modification en attente';
  autoSaveTimer = setTimeout(() => saveSettings(true), 350);
}


async function saveSettings(silent = false) {
  const payload = {
    symbol_source_mode: 'visible',
    ai_provider_requested: 'ollama',
    preferred_symbols: document.getElementById('setting-preferred-symbols').value,
    max_symbols_per_cycle: parseInt(document.getElementById('setting-max-symbols').value || '3', 10),
    check_interval_minutes: parseInt(document.getElementById('setting-check-interval').value || '15', 10),
    max_risk_per_trade: parseFloat(document.getElementById('setting-risk').value || '0.02'),
    daily_target: parseFloat(document.getElementById('setting-daily-target').value || '0'),
    daily_loss_limit: parseFloat(document.getElementById('setting-daily-loss').value || '-5'),
    max_open_positions: parseInt(document.getElementById('setting-max-positions').value || '2', 10),
    local_llm_model: document.getElementById('setting-local-model').value,
    local_llm_endpoint: document.getElementById('setting-local-endpoint').value,
    local_llm_timeout: parseInt(document.getElementById('setting-local-timeout').value || '120', 10),
    llm_analysis_mode: document.getElementById('setting-analysis-mode').value,
    llm_min_confidence: parseFloat(document.getElementById('setting-confidence').value || '0.60'),
    max_llm_calls_per_day: parseInt(document.getElementById('setting-max-llm-calls').value || '0', 10),
    llm_analysis_notes: document.getElementById('setting-analysis-notes').value,
    allow_trade_execution: document.getElementById('setting-allow-trade').value === 'true',
    telegram_enabled: document.getElementById('setting-telegram-enabled').value === 'true',
    telegram_bot_token: document.getElementById('setting-telegram-token').value.trim(),
    telegram_chat_id: document.getElementById('setting-telegram-chatid').value.trim(),
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
      label.textContent = 'Rotation auto : ' + visible.join(', ');
    }
  }
}

function renderPairSnapshot(result) {
  if (!result) return;
  const snap = result.market_snapshot || {};
  const signal = result.signal || {};
  const details = signal.details || {};
  const action = String(result.decision?.decision || 'WAIT').toUpperCase();
  const rr = action === 'SELL' ? (snap.rr_sell ?? details.rr_sell ?? 0) : (snap.rr_buy ?? details.rr_buy ?? 0);
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
  const liveMove = parseFloat(snap.price_change_pct ?? snap.momentum_5 ?? 0) || 0;
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
  const spreadVal = parseFloat(result.spread ?? snap.spread ?? 0) || 0;
  const humanSummary = snap.human_summary || details.human_summary || '';
  const reasoning = d.reasoning || '';
  const displayText = reasoning && humanSummary && reasoning.includes(humanSummary.slice(0, 30))
    ? reasoning
    : [reasoning, humanSummary].filter(Boolean).join(' · ') || 'Analyse en attente.';

  document.getElementById('ai-live-symbol').textContent = result.instrument || '—';
  document.getElementById('ai-live-action').innerHTML = '<span class="ai-pill ' + klass + '">' + action + '</span>';
  document.getElementById('ai-live-confidence').textContent = confidence + '%';
  document.getElementById('ai-live-spread').textContent = spreadVal.toFixed(1) + 'p';
  const rr = action === 'SELL' ? (details.rr_sell ?? snap.rr_sell ?? 0) : (details.rr_buy ?? snap.rr_buy ?? 0);
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



function toggleAutoAI() {
  autoAiEnabled = !autoAiEnabled;
  autoAiCountdown = 30;
  document.getElementById('auto-ai-btn').textContent = 'Auto IA: ' + (autoAiEnabled ? 'ON' : 'OFF');
  document.getElementById('ai-live-auto').textContent = autoAiEnabled ? 'ON · 30s' : 'OFF';
}

function toggleAiExchange() {
  const body = document.getElementById('ai-exchange-body');
  const arrow = document.getElementById('ai-exchange-arrow');
  const isOpen = body.classList.toggle('open');
  arrow.classList.toggle('open', isOpen);
}

function toggleCalendar() {
  const body = document.getElementById('calendar-body');
  const arrow = document.getElementById('calendar-arrow');
  const isClosed = getComputedStyle(body).display === 'none';
  body.style.display = isClosed ? 'block' : 'none';
  arrow.textContent = isClosed ? '▼' : '▶';
}

function renderCalendar(cal) {
  if (!cal) return;
  const container = document.getElementById('calendar-events');
  const badge = document.getElementById('news-pause-badge');
  if (cal.news_pause && cal.news_pause.pause) {
    badge.style.display = 'inline';
    badge.textContent = '⚠️ ' + (cal.news_pause.reason || 'PAUSE NEWS');
  } else {
    badge.style.display = 'none';
  }
  const events = cal.upcoming || [];
  if (events.length === 0) {
    container.innerHTML = '<div style="padding:8px;opacity:0.6;">Aucun événement majeur à venir.</div>';
    return;
  }
  let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82em;">';
  html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.1);"><th style="text-align:left;padding:4px 6px;">Heure</th><th style="text-align:left;padding:4px 6px;">Impact</th><th style="text-align:left;padding:4px 6px;">Devise</th><th style="text-align:left;padding:4px 6px;">Événement</th><th style="text-align:right;padding:4px 6px;">Dans</th></tr>';
  events.forEach(ev => {
    const impactColor = ev.impact === 'High' ? '#e74c3c' : ev.impact === 'Medium' ? '#f39c12' : '#7f8c8d';
    const impactDot = '<span style="color:' + impactColor + ';font-weight:bold;">●</span>';
    const mins = ev.minutes_to || 0;
    const timeStr = mins > 60 ? Math.floor(mins/60) + 'h' + (mins%60 < 10 ? '0' : '') + (mins%60) + 'm' : mins + 'min';
    const sign = mins < 0 ? '(passé)' : timeStr;
    html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05);">';
    html += '<td style="padding:3px 6px;">' + (ev.time_utc || '') + '</td>';
    html += '<td style="padding:3px 6px;">' + impactDot + ' ' + ev.impact + '</td>';
    html += '<td style="padding:3px 6px;font-weight:bold;">' + (ev.country || '') + '</td>';
    html += '<td style="padding:3px 6px;">' + (ev.title || '') + '</td>';
    html += '<td style="padding:3px 6px;text-align:right;opacity:0.7;">' + sign + '</td>';
    html += '</tr>';
  });
  html += '</table>';
  container.innerHTML = html;
}

function toggleStrategies() {
  const body = document.getElementById('strategies-body');
  const arrow = document.getElementById('strategies-arrow');
  const isClosed = getComputedStyle(body).display === 'none';
  body.style.display = isClosed ? 'block' : 'none';
  arrow.textContent = isClosed ? '▼' : '▶';
}

function renderStrategies(strat) {
  if (!strat) return;
  const badge = document.getElementById('session-badge');
  const candidates = strat.candidates || [];
  const session = strat.session || '—';
  const ts = strat.timestamp || '';

  // Badge
  const n = candidates.length;
  badge.style.background = n > 0 ? 'var(--green)' : 'var(--muted)';
  badge.style.color = n > 0 ? '#000' : '#fff';
  badge.textContent = n + ' signal' + (n > 1 ? 's' : '');

  document.getElementById('strat-session-label').textContent = session;
  document.getElementById('strat-count').textContent = n;
  document.getElementById('strat-last-ts').textContent = ts ? ts.replace('T', ' ').slice(0, 19) : '—';

  const wrap = document.getElementById('strat-scan-table');
  if (candidates.length === 0) {
    wrap.innerHTML = '<span style="color:var(--muted);">Aucun signal en attente</span>';
    return;
  }
  const rows = candidates.map(c => {
    const dirColor = c.signal_direction === 'BUY' ? 'var(--green)' : 'var(--red)';
    const scoreVal = Number(c.score ?? 0);
    const spreadVal = Number(c.spread ?? 0);
    const scoreBar = Math.min(100, Math.round(scoreVal * 100));
    return '<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">' +
      '<td style="padding:4px 8px;font-weight:600;">' + (c.symbol || '—') + '</td>' +
      '<td style="padding:4px 8px;color:' + dirColor + ';font-weight:600;">' + (c.signal_direction || '—') + '</td>' +
      '<td style="padding:4px 8px;">' +
        '<div style="display:flex;align-items:center;gap:4px;">' +
          '<div style="width:50px;height:5px;background:var(--border);border-radius:3px;overflow:hidden;">' +
            '<div style="width:' + scoreBar + '%;height:100%;background:var(--green);border-radius:3px;"></div></div>' +
          '<span style="font-size:0.8em;color:var(--green);">' + scoreVal.toFixed(2) + '</span></div>' +
      '</td>' +
      '<td style="padding:4px 8px;font-size:0.82em;color:var(--muted);">' + (c.regime || '—') + '</td>' +
        '<td style="padding:4px 8px;font-size:0.82em;color:var(--amber);">' +
      ((c.spread !== undefined && c.spread !== null) ? spreadVal.toFixed(1) + 'p' : '—') + '</td></tr>';
  }).join('');
  wrap.innerHTML = '<table style="width:100%;border-collapse:collapse;font-size:0.82em;">' +
    '<thead><tr style="color:var(--muted);"><th style="padding:4px 8px;text-align:left;">Paire</th>' +
    '<th style="padding:4px 8px;text-align:left;">Signal</th>' +
    '<th style="padding:4px 8px;text-align:left;">Score</th>' +
    '<th style="padding:4px 8px;text-align:left;">Régime</th>' +
    '<th style="padding:4px 8px;text-align:left;">Spread</th></tr></thead><tbody>' + rows + '</tbody></table>';
}

function toggleScanner() {
  const body = document.getElementById('scanner-body');
  const arrow = document.getElementById('scanner-arrow');
  const isClosed = getComputedStyle(body).display === 'none';
  body.style.display = isClosed ? 'block' : 'none';
  arrow.textContent = isClosed ? '▼' : '▶';
}

function toggleTrending() {
  const body = document.getElementById('trending-body');
  const arrow = document.getElementById('trending-arrow');
  const isClosed = getComputedStyle(body).display === 'none';
  body.style.display = isClosed ? 'block' : 'none';
  arrow.textContent = isClosed ? '▼' : '▶';
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
  const trending = pairs.filter(p => Number(p.trending_score ?? 0) > 0);
  const neutral = pairs.filter(p => Number(p.trending_score ?? 0) <= 0);

  badge.textContent = trending.length + ' en tendance / ' + pairs.length + ' total';
  badge.style.background = trending.length > 0 ? 'var(--green)' : 'var(--muted)';
  badge.style.color = '#000';

  if (pairs.length === 0) {
    tableDiv.innerHTML = '<span style="color:var(--muted);">Aucune donnée</span>';
    return;
  }

  let rows = pairs.map((p, i) => {
    const trendingScore = Number(p.trending_score ?? 0);
    const isTrending = trendingScore > 0;
    const dirColor = p.direction === 'BUY' ? 'var(--green)' : p.direction === 'SELL' ? 'var(--red)' : 'var(--muted)';
    const dirIcon = p.direction === 'BUY' ? '🟢' : p.direction === 'SELL' ? '🔴' : '⚪';
    const regimeColor = (p.regime || '').includes('bullish') ? 'var(--green)' : (p.regime || '').includes('bearish') ? 'var(--red)' : 'var(--muted)';
    const trendBar = Math.min(100, Math.round(trendingScore * 10));
    const rsiVal = Number(p.rsi ?? 50);
    const qualityVal = Number(p.quality ?? 0);
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
    badge.textContent = 'SMART · ' + selected.length + ' paires';
  } else if (mode === 'preferred') {
    badge.style.background = '#f39c12'; badge.style.color = '#000';
    badge.textContent = 'STATIQUE · ' + selected.length + ' paires';
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
      const spreadVal = Number(c.spread ?? 0);
      const maxSpreadVal = Number(c.max_spread ?? 0);
      const spreadPct = c.spread_pct !== undefined ? Number(c.spread_pct) : (maxSpreadVal > 0 ? (spreadVal / maxSpreadVal) * 100 : 0);
      const priorityVal = Number(c.priority ?? c.score ?? 0);
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
      : '<span style="color:var(--muted);">Aucune paire sélectionnée</span>';
  }

  // Rejected pairs
  const rejDiv = document.getElementById('scan-rejected');
  if (rejected.length > 0) {
    rejDiv.innerHTML = rejected.map(r =>
      '<div style="padding:2px 0;font-size:0.82em;">' +
      '<span style="min-width:90px;display:inline-block;">' + r.symbol + '</span> ' +
      '<span style="color:var(--red);">' + (r.spread ?? '—') + 'p > ' + (r.max_spread ?? '—') + 'p</span></div>'
    ).join('');
  } else {
    rejDiv.innerHTML = '<span style="color:var(--green);">Aucune paire rejetée</span>';
  }

  // Full table
  const tableWrap = document.getElementById('scan-table-wrap');
  if (candidates.length > 0) {
    let rows = candidates.map((c, i) => {
      const isSel = selected.includes(c.symbol);
      const bg = isSel ? 'rgba(0,166,166,0.10)' : '';
      const spreadVal = Number(c.spread ?? 0);
      const maxSpreadVal = Number(c.max_spread ?? 0);
      const spreadPct = c.spread_pct !== undefined ? Number(c.spread_pct) : (maxSpreadVal > 0 ? (spreadVal / maxSpreadVal) * 100 : 0);
      const priorityVal = Number(c.priority ?? c.score ?? 0);
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
  const symbol = getNextRotationPair() || (document.getElementById('setting-preferred-symbols').value || '').split(',')[0]?.trim() || '';
  document.getElementById('ai-test-result').textContent = 'Analyse IA de ' + symbol + '...';
  try {
    const res = await fetch('/api/test-ai', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instrument: symbol })
    });
    const data = await res.json();
    if (data.ok) {
      const d = data.result?.decision || {};
      lastAiPayload = data.result || null;
      renderAiDecision(data.result || {});
      const liveMode = document.getElementById('setting-allow-trade').value === 'true'
        ? 'mode réel démo actif'
        : 'mode aperçu actif';
      document.getElementById('ai-test-result').textContent =
        'Signal IA aperçu · ' + (data.result?.instrument || '—') + ' · ' +
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
    const res = await fetch('/api/test-telegram', { method: 'POST' });
    const data = await res.json();
    el.textContent = data.ok ? '✅ ' + data.message : '❌ ' + (data.error || data.message || 'Échec');
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
      statusText.textContent = data.market_status?.reason || 'MARCHÉ OUVERT';
    } else {
      badge.className = 'closed';
      statusText.textContent = data.market_status?.reason || 'MARCHÉ FERMÉ';
    }

    // Config active
    const rawPref = data.settings?.preferred_symbols || '';
    const prefFilter = Array.isArray(rawPref) ? rawPref.join(', ') : String(rawPref).trim();
    const filterLabel = prefFilter ? '🎯 ' + prefFilter : '🔍 toutes les paires';
    document.getElementById('symbol-mode').textContent = filterLabel;
    document.getElementById('ai-provider').textContent = data.ai_provider || '—';
    const symList = data.active_symbols || [];
    const scanInfo = data.smart_scan || {};
    const rejCount = (scanInfo.rejected || []).length;
    const candCount = (scanInfo.candidates || []).length;
    let symText = symList.join(', ') || '—';
    if (candCount || rejCount) {
      symText += ' (' + candCount + ' analysées, ' + rejCount + ' rejetées)';
    }
    document.getElementById('active-symbols').textContent = symText;
    populateSettings(data);
    const allowTrade = String(data.settings?.allow_trade_execution || false) === 'true';
    const modeNote = document.getElementById('ai-mode-note');
    if (modeNote) {
      modeNote.textContent = allowTrade
        ? 'Le cockpit affiche un signal IA en aperçu sur la paire active. Un ordre réel MT5 n\'est envoyé que par le cycle automatique quand toutes les validations sont encore confirmées.'
        : 'L\'agent autonome analyse la paire active en continu. Active le trading réel démo pour autoriser les ouvertures et fermetures automatiques.';
    }
    syncFocusPairs(data.active_symbols || [], data.trending_pairs || []);

    // Features bar
    const fb = document.getElementById('features-bar');
    if (fb) {
      const agentsList = data.agents || [];
      const agentsOk = agentsList.length > 0 && agentsList.filter(a => a.status === 'running').length === agentsList.length;
      const cbOk = !(data.market_protections?.circuit_breaker?.is_active);
      const features = [
        {label: '🔍 Smart Scan', on: !!(data.smart_scan && (data.smart_scan.candidates || []).length >= 0)},
        {label: '📱 Telegram', on: String(data.settings?.telegram_enabled ?? true) === 'true'},
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

    // KPIs
    const balance = data.account?.balance || 0;
    document.getElementById('balance').textContent = '$' + balance.toFixed(2);

    const dpnl = data.daily_pnl || 0;
    const dpnlEl = document.getElementById('daily-pnl');
    dpnlEl.innerHTML = fmtPnl(dpnl);
    const target = parseFloat(data.settings?.daily_target ?? 0);
    document.getElementById('daily-pnl-sub').textContent = target > 0 ? ('vs objectif $' + target.toFixed(2)) : 'objectif désactivé';

    const tpnl = data.total_pnl || 0;
    document.getElementById('total-pnl').innerHTML = fmtPnl(tpnl);

    const wr = data.win_rate || 0;
    document.getElementById('win-rate').textContent = wr.toFixed(1) + '%';
    document.getElementById('total-trades').textContent = (data.total_trades || 0) + ' trades';

    document.getElementById('open-positions').textContent = data.open_positions?.length || 0;

    const apiCalls = data.llm_calls_today || data.api_calls_today || 0;
    const maxApiDay = parseInt(data.settings?.max_llm_calls_per_day ?? 0, 10);
    document.getElementById('api-calls').textContent = maxApiDay > 0 ? (apiCalls + ' / ' + maxApiDay) : (apiCalls + ' / illimité');
    document.getElementById('api-bar').style.width = maxApiDay > 0 ? ((apiCalls / maxApiDay) * 100) + '%' : '100%';

    document.getElementById('last-update').textContent =
      new Date().toLocaleTimeString('fr-FR');

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
        const pnl = t.pnl != null ? fmtPnl(t.pnl) : '<span style="color:var(--amber)">ouvert</span>';
        const dir = `<span class="pos-dir ${t.direction?.toLowerCase()}">${t.direction}</span>`;
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
function tick() {
  countdown--;
  autoAiCountdown--;
  document.getElementById('countdown').textContent = countdown;
  if (autoAiEnabled) {
    document.getElementById('ai-live-auto').textContent = 'ON · ' + Math.max(0, autoAiCountdown) + 's';
  }
  if (countdown <= 0) {
    countdown = 3;
    fetchStatus();
  }
  if (autoAiEnabled && autoAiCountdown <= 0 && !aiBusy) {
    testAI();
  }
}

function initAutoSave() {
  [
    'setting-preferred-symbols',
    'setting-max-symbols',
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
    'setting-allow-trade'
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

    def do_GET(self):
        if self.path.startswith('/api/status'):
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
                    cal_pause = calendar.should_pause_trading("EURUSDm")
                    cal_status = {
                        "news_pause": cal_pause,
                        "upcoming": [],
                    }
                except Exception:
                    cal_status = {}
                positions = broker.get_open_positions()
                recent_trades = memory.get_recent_trades(20)
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
                pref_raw = runtime_settings.get("preferred_symbols", "")
                if pref_raw:
                    raw_str = str(pref_raw).strip().strip("[]").replace("'", "").replace('"', "")
                    active_symbols = [s.strip() for s in raw_str.split(",") if s.strip()]
                else:
                    active_symbols = list(getattr(cfg, "INSTRUMENTS", []))

                # Live snapshot for first symbol
                live_snapshot = {}
                try:
                    sym = focus or (active_symbols[0] if active_symbols else "EURUSDm")
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

                status = {
                    # Market state
                    "market_open": market_open,
                    "market_status": market_status,
                    # Account
                    "account": account,
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
                instrument = payload.get('instrument', 'EURUSDm')
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
                result = {
                    "instrument": instrument,
                    "signal": signal,
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
        else:
            self._send_json({"ok": False, "error": "route inconnue"}, status=404)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"🌐 Dashboard: http://localhost:{port}")
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()
