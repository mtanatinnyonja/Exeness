#!/usr/bin/env python3
"""
Dashboard web léger pour monitorer l'agent
Lance avec: python web/dashboard.py
Accès: http://localhost:8080
"""

import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trading Agent · Monitor</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Space+Grotesk:wght@300;400;500;600&display=swap" rel="stylesheet">
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
    --mono: 'JetBrains Mono', monospace;
    --sans: 'Space Grotesk', sans-serif;
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
        <div class="logo-text">TradingAgent</div>
        <div class="logo-sub">AI-POWERED · FOREX</div>
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
            <option value="preferred">preferred</option>
            <option value="visible">visible</option>
            <option value="hybrid">hybrid</option>
          </select>
        </div>
        <div class="field">
          <label>IA demandée</label>
          <select id="setting-ai-provider">
            <option value="auto">auto</option>
            <option value="gemini">gemini</option>
            <option value="claude">claude</option>
          </select>
        </div>
        <div class="field">
          <label>Paires préférées</label>
          <input id="setting-preferred-symbols" placeholder="EURUSDm,XAUUSDm" />
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
          <label>Clé Gemini</label>
          <input id="setting-gemini-key" type="password" placeholder="AIza..." />
        </div>
        <div class="field">
          <label>Clé Claude</label>
          <input id="setting-anthropic-key" type="password" placeholder="sk-ant-..." />
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
        <span class="refresh-info">Les changements sont repris automatiquement par le dashboard, et par le bot au prochain cycle.</span>
      </div>
      <div id="ai-test-result" class="refresh-info" style="margin-top:10px;white-space:normal;line-height:1.6;">Aucun test IA lancé.</div>
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
      <div class="kpi-label">API Claude</div>
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
let autoSaveTimer = null;

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
  document.getElementById('setting-symbol-mode').value = settings.symbol_source_mode || 'preferred';
  document.getElementById('setting-ai-provider').value = ['auto','gemini','claude'].includes(settings.ai_provider_requested) ? settings.ai_provider_requested : 'auto';
  document.getElementById('setting-preferred-symbols').value = (settings.preferred_symbols || []).join(',');
  document.getElementById('setting-max-symbols').value = settings.max_symbols_per_cycle || 3;
  document.getElementById('setting-check-interval').value = settings.check_interval_minutes || 15;
  document.getElementById('setting-risk').value = settings.max_risk_per_trade || 0.02;
  document.getElementById('setting-gemini-key').value = settings.gemini_api_key || '';
  document.getElementById('setting-anthropic-key').value = settings.anthropic_api_key || '';
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

function forcePreferredModeIfNeeded() {
  const text = document.getElementById('setting-preferred-symbols').value || '';
  if (text.trim()) {
    document.getElementById('setting-symbol-mode').value = 'preferred';
  }
}

async function saveSettings(silent = false) {
  const payload = {
    symbol_source_mode: document.getElementById('setting-symbol-mode').value,
    ai_provider_requested: document.getElementById('setting-ai-provider').value,
    preferred_symbols: document.getElementById('setting-preferred-symbols').value,
    max_symbols_per_cycle: parseInt(document.getElementById('setting-max-symbols').value || '3', 10),
    check_interval_minutes: parseInt(document.getElementById('setting-check-interval').value || '15', 10),
    max_risk_per_trade: parseFloat(document.getElementById('setting-risk').value || '0.02'),
    gemini_api_key: document.getElementById('setting-gemini-key').value,
    anthropic_api_key: document.getElementById('setting-anthropic-key').value,
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

async function testAI() {
  document.getElementById('ai-test-result').textContent = 'Test IA en cours...';
  const symbol = (document.getElementById('setting-preferred-symbols').value || '').split(',')[0]?.trim() || 'EURUSDm';
  const res = await fetch('/api/test-ai', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instrument: symbol })
  });
  const data = await res.json();
  if (data.ok) {
    const d = data.result?.decision || {};
    document.getElementById('ai-test-result').textContent =
      'Provider: ' + (data.result?.provider || '—') + ' | Instrument: ' + (data.result?.instrument || '—') +
      ' | Decision: ' + (d.decision || 'WAIT') + ' | Confidence: ' + (d.confidence ?? 0);
  } else {
    document.getElementById('ai-test-result').textContent = 'Erreur test IA: ' + (data.error || 'inconnue');
  }
  await fetchStatus();
}

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();

    // Market status
    const badge = document.getElementById('status-badge');
    const statusText = document.getElementById('status-text');
    if (data.market_open) {
      badge.className = 'open';
      statusText.textContent = 'MARCHÉ OUVERT';
    } else {
      badge.className = 'closed';
      statusText.textContent = 'MARCHÉ FERMÉ';
    }

    // Config active
    document.getElementById('symbol-mode').textContent = data.settings?.symbol_source_mode || '—';
    document.getElementById('ai-provider').textContent = data.ai_provider || '—';
    document.getElementById('active-symbols').textContent = (data.active_symbols || []).join(', ') || '—';
    populateSettings(data);

    // KPIs
    const balance = data.account?.balance || 0;
    document.getElementById('balance').textContent = '$' + balance.toFixed(2);

    const dpnl = data.daily_pnl || 0;
    const dpnlEl = document.getElementById('daily-pnl');
    dpnlEl.innerHTML = fmtPnl(dpnl);

    const tpnl = data.total_pnl || 0;
    document.getElementById('total-pnl').innerHTML = fmtPnl(tpnl);

    const wr = data.win_rate || 0;
    document.getElementById('win-rate').textContent = wr.toFixed(1) + '%';
    document.getElementById('total-trades').textContent = (data.total_trades || 0) + ' trades';

    document.getElementById('open-positions').textContent = data.open_positions?.length || 0;

    const apiCalls = data.api_calls_today || 0;
    const maxApiDay = data.settings?.max_api_calls_per_day || 20;
    document.getElementById('api-calls').textContent = apiCalls + ' / ' + maxApiDay;
    document.getElementById('api-bar').style.width = (apiCalls / maxApiDay * 100) + '%';

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
  document.getElementById('countdown').textContent = countdown;
  if (countdown <= 0) {
    countdown = 5;
    fetchStatus();
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
    'setting-gemini-key',
    'setting-anthropic-key',
    'setting-allow-trade'
  ].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', scheduleAutoSave);
      el.addEventListener('input', scheduleAutoSave);
      if (id === 'setting-preferred-symbols') {
        el.addEventListener('input', forcePreferredModeIfNeeded);
      }
    }
  });
}

fetchStatus();
initAutoSave();
setInterval(tick, 1000);
</script>
</body>
</html>"""


from control_panel import Handler


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"🌐 Dashboard: http://localhost:{port}")
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()
