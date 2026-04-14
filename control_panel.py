#!/usr/bin/env python3
"""
Dashboard web léger pour monitorer l'agent
Lance avec: python web/dashboard.py
Accès: http://localhost:8080
"""

import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Robot MT5 · Local Monitor</title>
<style>
  :root {
    --bg: #0a0a0f;
    --bg2: #111118;
    --bg3: #18181f;
    --border: rgba(255,255,255,0.06);
    --border2: rgba(255,255,255,0.12);
    --text: #e8e8f0;
    --muted: #6b6b80;
    --accent: #7c6af7;
    --accent2: #a89cf7;
    --green: #3dffa0;
    --green2: #1a7a4a;
    --red: #ff5757;
    --red2: #7a1a1a;
    --amber: #ffb847;
    --teal: #3dd9ff;
    --mono: Consolas, 'Courier New', monospace;
    --sans: 'Segoe UI', Arial, sans-serif;
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
      linear-gradient(rgba(124,106,247,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(124,106,247,0.03) 1px, transparent 1px);
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
    border-radius: 14px;
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
    grid-template-columns: repeat(4, 1fr);
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
    gap:4px;
    height:120px;
    margin-top:12px;
    padding-top:8px;
  }
  .ai-bar-wrap {
    flex:1;
    display:flex;
    flex-direction:column;
    align-items:center;
    gap:4px;
  }
  .ai-bar {
    width:100%;
    border-radius: 6px 6px 0 0;
    min-height: 6px;
    opacity: 0.95;
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
        <div class="logo-text">Robot MT5 Local</div>
        <div class="logo-sub">LOCAL · MT5 · SQLITE</div>
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
        <div class="kpi-label">Mode symboles</div>
        <div class="kpi-value accent" id="symbol-mode" style="font-size:16px;">—</div>
      </div>
      <div>
        <div class="kpi-label">IA</div>
        <div class="kpi-value accent" id="ai-provider" style="font-size:16px;">—</div>
      </div>
      <div>
        <div class="kpi-label">Paires suivies</div>
        <div class="refresh-info" id="active-symbols" style="white-space:normal;line-height:1.6;">—</div>
      </div>
      <div>
        <div class="kpi-label">ML / BDD</div>
        <div class="kpi-value accent" id="ml-samples" style="font-size:16px;">0</div>
        <div class="kpi-sub" id="ml-info">samples</div>
      </div>
    </div>
  </div>

  <div class="panel" style="margin-bottom:16px;">
    <div class="panel-header">
      <span class="panel-title">Paramètres modifiables</span>
      <span class="refresh-info" id="settings-save-status">non sauvegardé</span>
    </div>
    <div class="panel-body">
      <div class="form-grid">
        <div class="field">
          <label>Source symboles</label>
          <select id="setting-symbol-mode">
            <option value="visible">visible · MT5 only</option>
          </select>
        </div>
        <div class="field">
          <label>Moteur IA</label>
          <select id="setting-ai-provider">
            <option value="ollama">ollama · LLM local</option>
          </select>
        </div>
        <div class="field">
          <label>Symbole test IA</label>
          <input id="setting-preferred-symbols" placeholder="laisser vide = 1er symbole visible MT5" />
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
          <input id="setting-local-model" placeholder="llama3.2:3b" />
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
        <span class="refresh-info" id="ai-mode-note">Le bot autonome peut ouvrir et fermer des ordres réels sur le compte démo si le trading réel est activé. Ce bouton montre instantanément la décision sur la paire active.</span>
      </div>
      <div id="ai-test-result" class="refresh-info" style="margin-top:10px;white-space:normal;line-height:1.6;">Chargement de l'analyse automatique sur la paire active...</div>

      <div class="live-ai-box">
        <div class="panel-title" style="margin-bottom:8px;">Cockpit IA en direct</div>
        <div class="focus-toolbar">
          <span class="refresh-info">Paire focus :</span>
          <select id="focus-pair-select" onchange="onFocusPairChanged()"></select>
          <span class="refresh-info">Vue uniquement sur la paire analysée.</span>
        </div>
        <div id="ai-live-decision" class="refresh-info" style="white-space:normal;line-height:1.6;">En attente d'une analyse IA...</div>
        <div class="mini-grid">
          <div class="mini-kpi"><div class="label">Instrument</div><div class="value" id="ai-live-symbol">—</div></div>
          <div class="mini-kpi"><div class="label">Décision</div><div class="value" id="ai-live-action">WAIT</div></div>
          <div class="mini-kpi"><div class="label">Confiance</div><div class="value" id="ai-live-confidence">0%</div></div>
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
let countdown = 5;
let autoAiCountdown = 45;
let autoSaveTimer = null;
let autoAiEnabled = true;
let aiBusy = false;
let initialAiWarmupDone = false;
let lastAiPayload = null;
let latestStatusPayload = null;
let currentFocusPair = '';

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
  document.getElementById('setting-symbol-mode').value = 'visible';
  document.getElementById('setting-ai-provider').value = 'ollama';
  document.getElementById('setting-preferred-symbols').value = (settings.preferred_symbols || []).join(',');
  document.getElementById('setting-max-symbols').value = settings.max_symbols_per_cycle || 3;
  document.getElementById('setting-check-interval').value = settings.check_interval_minutes || 15;
  document.getElementById('setting-risk').value = settings.max_risk_per_trade || 0.02;
  document.getElementById('setting-daily-target').value = settings.daily_target ?? 2.0;
  document.getElementById('setting-daily-loss').value = settings.daily_loss_limit ?? -5.0;
  document.getElementById('setting-max-positions').value = settings.max_open_positions || 2;
  document.getElementById('setting-local-model').value = settings.local_llm_model || 'llama3.2:3b';
  document.getElementById('setting-local-endpoint').value = settings.local_llm_endpoint || 'http://127.0.0.1:11434/api/generate';
  document.getElementById('setting-local-timeout').value = settings.local_llm_timeout ?? 120;
  document.getElementById('setting-analysis-mode').value = settings.llm_analysis_mode || 'precision';
  document.getElementById('setting-confidence').value = settings.llm_min_confidence || 0.60;
  document.getElementById('setting-max-llm-calls').value = settings.max_llm_calls_per_day ?? 0;
  document.getElementById('setting-analysis-notes').value = settings.llm_analysis_notes || '';
  document.getElementById('setting-allow-trade').value = String(settings.allow_trade_execution || false);

  const ml = data.ml_stats || {};
  document.getElementById('ml-samples').textContent = ml.samples || 0;
  document.getElementById('ml-info').textContent = 'avg score ' + ((ml.avg_score || 0).toFixed ? ml.avg_score.toFixed(2) : ml.avg_score || 0);
}

function scheduleAutoSave() {
  clearTimeout(autoSaveTimer);
  document.getElementById('settings-save-status').textContent = 'modification en attente';
  autoSaveTimer = setTimeout(() => saveSettings(true), 350);
}

function keepLockedModes() {
  document.getElementById('setting-symbol-mode').value = 'visible';
  document.getElementById('setting-ai-provider').value = 'ollama';
}

async function saveSettings(silent = false) {
  keepLockedModes();
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
    allow_trade_execution: document.getElementById('setting-allow-trade').value === 'true'
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
  const sel = document.getElementById('focus-pair-select');
  return (sel?.value || currentFocusPair || '').trim();
}

function syncFocusPairs(symbols, preferredList = []) {
  const sel = document.getElementById('focus-pair-select');
  if (!sel) return;

  const fromField = ((document.getElementById('setting-preferred-symbols')?.value || '').split(',')[0] || '').trim();
  const fromSettings = Array.isArray(preferredList) && preferredList.length ? String(preferredList[0] || '').trim() : '';
  const rawPreferred = fromField || fromSettings;
  const normalizedPreferred = rawPreferred ? rawPreferred.replace(/\s+/g, '').toUpperCase() : '';
  const visible = (symbols || []).filter(Boolean);
  const matchedPreferred = visible.find(s => String(s).toUpperCase() === normalizedPreferred) || rawPreferred;

  const unique = new Map();
  if (matchedPreferred) unique.set(String(matchedPreferred).toUpperCase(), matchedPreferred);
  visible.forEach(s => {
    const key = String(s).toUpperCase();
    if (!unique.has(key)) unique.set(key, s);
  });

  const list = Array.from(unique.values());
  const forceSingle = true;
  const finalList = forceSingle && list.length ? [list[0]] : list;
  const wanted = currentFocusPair || matchedPreferred || finalList[0] || '';

  sel.innerHTML = finalList.map(s => '<option value="' + s + '">' + s + '</option>').join('');
  sel.value = finalList.includes(wanted) ? wanted : (finalList[0] || '');
  currentFocusPair = sel.value || matchedPreferred || '';
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
    const points = closes.map((v, i) => {
      const x = (i / Math.max(1, closes.length - 1)) * 280;
      const y = 100 - (((v - min) / span) * 80 + 10);
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    const color = action === 'BUY' ? '#3dffa0' : action === 'SELL' ? '#ff5757' : '#ffb847';
    box.innerHTML = '<svg viewBox="0 0 280 100" width="100%" height="120" preserveAspectRatio="none">' +
      '<polyline fill="none" stroke="' + color + '" stroke-width="3" points="' + points + '" />' +
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
  const reasoningParts = [d.reasoning, snap.human_summary || details.human_summary].filter(Boolean);

  currentFocusPair = result.instrument || currentFocusPair;
  document.getElementById('ai-live-symbol').textContent = result.instrument || '—';
  document.getElementById('ai-live-action').innerHTML = '<span class="ai-pill ' + klass + '">' + action + '</span>';
  document.getElementById('ai-live-confidence').textContent = confidence + '%';
  document.getElementById('ai-live-decision').innerHTML =
    '<strong>' + (result.instrument || '—') + '</strong> · ' +
    '<span class="ai-pill ' + klass + '">' + action + '</span>' +
    ' Score ' + (signal.score || 0) + '/5 · Régime ' + (details.market_regime || snap.regime || '—') +
    ' · RR ' + ((action === 'SELL' ? (details.rr_sell ?? snap.rr_sell) : (details.rr_buy ?? snap.rr_buy)) ?? 0) +
    '<br>' + (reasoningParts.join(' · ') || 'Analyse en attente.');
  renderPairSnapshot(result);
}

function renderAiChart(data) {
  const focus = getFocusedPair();
  const rowsAll = (data.ml_history || []).slice(-40);
  const rows = focus ? rowsAll.filter(row => String(row.instrument || '').toUpperCase() === focus.toUpperCase()).slice(-20) : rowsAll.slice(-20);
  const el = document.getElementById('ai-history-chart');
  if (!rows.length) {
    el.innerHTML = '<div class="refresh-info">Pas encore d\'historique IA sur cette paire.</div>';
    return;
  }
  el.innerHTML = rows.map((row) => {
    const decision = String(row.decision || 'WAIT').toUpperCase();
    const conf = Math.max(6, Math.round((parseFloat(row.confidence || 0) || 0) * 100));
    const color = decision === 'BUY' ? 'var(--green)' : decision === 'SELL' ? 'var(--red)' : 'var(--amber)';
    const label = String(row.timestamp || '').slice(11, 16) || (row.instrument || '—').slice(0, 3);
    return '<div class="ai-bar-wrap" title="' + (row.instrument || '—') + ' | ' + decision + ' | conf ' + conf + '%">' +
      '<div class="ai-bar" style="height:' + conf + '%;background:' + color + '"></div>' +
      '<div class="ai-bar-label">' + label + '</div>' +
    '</div>';
  }).join('');
}

function onFocusPairChanged() {
  currentFocusPair = getFocusedPair();
  if (latestStatusPayload) {
    renderAiChart(latestStatusPayload);
  }
  testAI();
}

function toggleAutoAI() {
  autoAiEnabled = !autoAiEnabled;
  autoAiCountdown = 45;
  document.getElementById('auto-ai-btn').textContent = 'Auto IA: ' + (autoAiEnabled ? 'ON' : 'OFF');
  document.getElementById('ai-live-auto').textContent = autoAiEnabled ? 'ON · 45s' : 'OFF';
}

async function testAI() {
  if (aiBusy) return;
  aiBusy = true;
  document.getElementById('ai-test-result').textContent = 'Test IA en cours...';
  const focused = getFocusedPair();
  const typed = (document.getElementById('setting-preferred-symbols').value || '').split(',')[0]?.trim();
  const visible = (document.getElementById('active-symbols').textContent || '').split(',')[0]?.trim();
  const symbol = focused || typed || visible || 'XAUUSDm';
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
        'Décision live paire active · ' + (data.result?.instrument || '—') + ' · ' +
        (d.decision || 'WAIT') + ' · confiance ' + Math.round((parseFloat(d.confidence || 0) || 0) * 100) + '% · ' + liveMode;
    } else {
      document.getElementById('ai-test-result').textContent = 'Erreur test IA: ' + (data.error || 'inconnue');
    }
  } finally {
    aiBusy = false;
    autoAiCountdown = 45;
    await fetchStatus();
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
    document.getElementById('symbol-mode').textContent = data.settings?.symbol_source_mode || '—';
    document.getElementById('ai-provider').textContent = data.ai_provider || '—';
    document.getElementById('active-symbols').textContent = (data.active_symbols || []).join(', ') || '—';
    populateSettings(data);
    const allowTrade = String(data.settings?.allow_trade_execution || false) === 'true';
    const modeNote = document.getElementById('ai-mode-note');
    if (modeNote) {
      modeNote.textContent = allowTrade
        ? 'Le bot autonome peut ouvrir et fermer des ordres réels sur le compte démo si le trading réel est activé. Ce bouton montre instantanément la décision sur la paire active.'
        : 'Le bot autonome analyse la paire active en continu. Active le trading réel démo pour autoriser les ouvertures et fermetures automatiques.';
    }
    syncFocusPairs(data.active_symbols || [], data.settings?.preferred_symbols || []);
    renderAiChart(data);
    if (data.live_snapshot) {
      const livePayload = {
        instrument: data.live_snapshot.instrument || currentFocusPair || (data.active_symbols || [])[0] || '—',
        signal: { score: lastAiPayload?.signal?.score || 0, details: data.live_snapshot, atr_pips: data.live_snapshot.atr_pips || 0 },
        decision: lastAiPayload?.decision || { decision: 'WAIT', confidence: 0, reasoning: data.live_snapshot.human_summary || 'Lecture technique live.' },
        market_snapshot: data.live_snapshot
      };
      renderAiDecision(livePayload);
    } else if (lastAiPayload) {
      renderAiDecision(lastAiPayload);
    }
    if (!initialAiWarmupDone && !aiBusy && currentFocusPair) {
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
      posEl.innerHTML = positions.map(p => `
        <div class="position-item">
          <div>
            <div class="pos-instrument">${p.instrument}</div>
            <div style="margin-top:2px"><span class="pos-dir ${p.direction.toLowerCase()}">${p.direction}</span></div>
          </div>
          <div class="pos-pnl">${fmtPnl(p.unrealized_pnl)}</div>
        </div>
      `).join('');
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
    countdown = 5;
    fetchStatus();
  }
  if (autoAiEnabled && autoAiCountdown <= 0 && !aiBusy) {
    testAI();
  }
}

function initAutoSave() {
  [
    'setting-symbol-mode',
    'setting-ai-provider',
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
      if (id === 'setting-preferred-symbols' || id === 'setting-symbol-mode' || id === 'setting-ai-provider') {
        el.addEventListener('input', keepLockedModes);
      }
    }
  });
}

keepLockedModes();
fetchStatus().finally(() => {
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
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/api/status':
            try:
                from trade_orchestrator import TradeOrchestrator
                agent = TradeOrchestrator(quiet=True)
                status = agent.get_status()
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
                from trade_orchestrator import TradeOrchestrator
                length = int(self.headers.get('Content-Length', '0'))
                raw = self.rfile.read(length).decode('utf-8') if length else '{}'
                payload = json.loads(raw)
                agent = TradeOrchestrator(quiet=True)
                result = agent.preview_ai_decision(payload.get('instrument'))
                self._send_json({"ok": True, "result": result})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=500)
        else:
            self._send_json({"ok": False, "error": "route inconnue"}, status=404)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"🌐 Dashboard: http://localhost:{port}")
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()
