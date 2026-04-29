import html
import json
import os
import sqlite3
import threading
from datetime import date, datetime
from functools import wraps
from flask import Flask, jsonify, render_template_string, request, Response
import subprocess
from backtest import (
    BacktestEngine, init_backtest_db, create_run,
    get_runs, get_run_details, DEFAULT_RISK, DEFAULT_CB,
)
from chess_module import chess_manager

app = Flask(__name__)
app.static_folder = 'static'
init_backtest_db()

DASHBOARD_USER = os.getenv("DASHBOARD_USER", "")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "")


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not DASHBOARD_USER or not DASHBOARD_PASS:
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or auth.username != DASHBOARD_USER or auth.password != DASHBOARD_PASS:
            return Response(
                "Authentication required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Trading Bot"'},
            )
        return f(*args, **kwargs)
    return decorated

BASE   = "/root/Trading-bot"
STATUS = os.path.join(BASE, "status.json")
LOG    = os.path.join(BASE, "bot.log")


def read_status():
    try:
        with open(STATUS) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "bot_active":  False,
            "last_update": "unavailable",
            "market_open": False,
        }


def read_logs(n=60):
    try:
        with open(LOG) as f:
            return [html.escape(line.strip()) for line in f.readlines()[-n:]]
    except Exception:
        return []


def read_performance() -> dict:
    try:
        db_file = os.path.join(BASE, "trades.db")
        with sqlite3.connect(db_file) as conn:
            total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            today = datetime.now().strftime("%Y-%m-%d")
            by_status = conn.execute(
                "SELECT status, COUNT(*) FROM trades GROUP BY status"
            ).fetchall()
            today_rows = conn.execute(
                "SELECT status, COUNT(*) FROM trades WHERE date=? GROUP BY status",
                (today,)
            ).fetchall()
            equity_hist = conn.execute(
                "SELECT equity FROM equity_snapshots ORDER BY id DESC LIMIT 100"
            ).fetchall()
        return {
            "all_time_trades": total,
            "all_time_by_status": {s: c for s, c in by_status},
            "today_by_status":    {s: c for s, c in today_rows},
            "equity_history":     [row[0] for row in reversed(equity_hist)],
        }
    except Exception:
        return {}


TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0d1117">
<title>Trading Bot HUD</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',monospace;padding:12px;max-width:600px;margin:0 auto}
h1{font-size:18px;font-weight:700;margin-bottom:6px;color:#58a6ff;letter-spacing:1px;text-transform:uppercase;display:flex;align-items:center;gap:8px}
.market-banner{padding:8px 14px;border-radius:8px;font-size:13px;font-weight:700;text-align:center;margin-bottom:14px;letter-spacing:1px}
.market-open{background:#0f2d1a;border:1px solid #3fb950;color:#3fb950}
.market-closed{background:#2d1b1b;border:1px solid #f85149;color:#f85149}
.card{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:14px;margin-bottom:12px}
.card-title{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#8b949e;margin-bottom:10px}
.row{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.label{font-size:13px;color:#8b949e}
.value{font-size:14px;font-weight:600}
.green{color:#3fb950}
.red{color:#f85149}
.yellow{color:#d29922}
.blue{color:#58a6ff}
.status-dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:8px}
.dot-green{background:#3fb950;box-shadow:0 0 8px #3fb950;animation:pulse 2s infinite}
.dot-red{background:#f85149;box-shadow:0 0 8px #f85149}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.status-row{display:flex;align-items:center;font-size:15px;font-weight:700}
.ticker-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.ticker-card{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px}
.ticker-name{font-size:13px;font-weight:700;color:#58a6ff;margin-bottom:6px}
.ticker-row{display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px}
.score-bar{height:4px;border-radius:2px;background:#21262d;margin-top:6px;overflow:hidden}
.score-fill{height:100%;border-radius:2px;transition:width 0.5s}
.log-box{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px;max-height:220px;overflow-y:auto;font-size:11px;line-height:1.6;font-family:monospace}
.log-line{color:#8b949e;border-bottom:1px solid #161b22;padding:2px 0}
.log-line.info{color:#e6edf3}
.log-line.error{color:#f85149}
.log-line.critical{color:#d29922}
.position-card{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px;margin-bottom:8px}
.pos-symbol{font-size:15px;font-weight:700;color:#58a6ff}
.pos-pl{font-size:18px;font-weight:700}
.refresh-bar{font-size:11px;color:#8b949e;text-align:center;margin-top:12px;padding-bottom:20px}
.progress{height:2px;background:#21262d;border-radius:2px;margin-top:6px}
.progress-fill{height:100%;background:#58a6ff;border-radius:2px;transition:width 1s linear}
.cb-tripped{background:#2d1b1b;border-color:#f85149}
.equity-big{font-size:26px;font-weight:700;color:#e6edf3}
.change{font-size:13px;margin-top:4px}
.stop-btn{width:100%;padding:14px;background:#2d1b1b;border:2px solid #f85149;color:#f85149;font-size:15px;font-weight:700;border-radius:10px;cursor:pointer;letter-spacing:1px;text-transform:uppercase;margin-bottom:12px;transition:background 0.2s}
.stop-btn:active{background:#f85149;color:#fff}
.stop-confirm{display:none;background:#161b22;border:1px solid #f85149;border-radius:10px;padding:14px;margin-bottom:12px;text-align:center}
.stop-confirm p{font-size:14px;margin-bottom:12px;color:#e6edf3}
.confirm-yes{background:#f85149;color:#fff;border:none;padding:10px 24px;border-radius:8px;font-weight:700;font-size:14px;cursor:pointer;margin-right:10px}
.confirm-no{background:#21262d;color:#e6edf3;border:none;padding:10px 24px;border-radius:8px;font-weight:700;font-size:14px;cursor:pointer}
.history-table{width:100%;border-collapse:collapse;font-size:12px}
.history-table th{color:#8b949e;text-align:left;padding:4px 6px;border-bottom:1px solid #21262d;font-weight:600;font-size:11px;text-transform:uppercase}
.history-table td{padding:5px 6px;border-bottom:1px solid #161b22;color:#e6edf3}
.chart-wrap{width:100%;height:120px;background:#0d1117;border:1px solid #21262d;border-radius:8px;overflow:hidden}
canvas{width:100%;height:100%}
.theme-toggle{margin-left:auto;background:none;border:1px solid #21262d;color:#8b949e;padding:4px 10px;border-radius:6px;font-size:11px;cursor:pointer}
body.light{background:#f6f8fa;color:#1f2328}
body.light .card{background:#fff;border-color:#d0d7de}
body.light .ticker-card,.body.light .position-card,.body.light .log-box,.body.light .chart-wrap{background:#f6f8fa;border-color:#d0d7de}
body.light .label{color:#57606a}
body.light .log-line{color:#57606a}
body.light .log-line.info{color:#1f2328}
body.light h1{color:#0969da}
body.light .blue{color:#0969da}
body.light .market-open{background:#dafbe1;color:#1a7f37;border-color:#1a7f37}
body.light .market-closed{background:#fff0ee;color:#cf222e;border-color:#cf222e}
</style>
</head>
<body>
<h1>&#x1F916; Bot HUD <a href="/backtest" style="font-size:12px;color:#58a6ff;margin-left:8px;text-decoration:none;font-weight:400">&#x1F4CA; Backtest</a><a href="/chess" style="font-size:12px;color:#58a6ff;margin-left:8px;text-decoration:none;font-weight:400">&#x265F; Chess</a><button class="theme-toggle" onclick="toggleTheme()" id="themeBtn">☀ Light</button></h1>
<div id="market-banner" class="market-banner market-closed">&#x23F0; Checking market...</div>
<div id="stop-confirm" class="stop-confirm">
  <p>&#x26A0; Are you sure you want to stop the bot?<br>All open orders will remain open.</p>
  <button class="confirm-yes" onclick="confirmStop()">Yes, Stop Bot</button>
  <button class="confirm-no" onclick="cancelStop()">Cancel</button>
</div>
<button class="stop-btn" onclick="showStopConfirm()">&#x23F9; Emergency Stop Bot</button>
<div id="app">Loading...</div>
<div class="refresh-bar">
  Auto-refreshing every 15s
  <div class="progress"><div class="progress-fill" id="prog" style="width:100%"></div></div>
</div>
<script>
let countdown = 15;
let equityHistory = [];

function toggleTheme() {
  document.body.classList.toggle('light');
  const btn = document.getElementById('themeBtn');
  btn.textContent = document.body.classList.contains('light') ? '🌙 Dark' : '☀ Light';
}

function showStopConfirm() {
  document.getElementById('stop-confirm').style.display = 'block';
}

function cancelStop() {
  document.getElementById('stop-confirm').style.display = 'none';
}

async function confirmStop() {
  cancelStop();
  try {
    await fetch('/api/stop', {method:'POST'});
    alert('Stop signal sent. Bot will shut down shortly.');
  } catch(e) {
    alert('Failed to send stop signal.');
  }
}

async function refresh() {
  try {
    const r = await fetch('/api/data');
    const d = await r.json();
    render(d);
  } catch(e) {
    document.getElementById('app').innerHTML = '<div class="card"><p style="color:#8b949e;text-align:center;padding:10px">Connection error - retrying...</p></div>';
  }
}

function fmt(n, decimals=2) {
  if(n===null||n===undefined) return 'N/A';
  return parseFloat(n).toFixed(decimals);
}

function drawChart(equity) {
  const canvas = document.getElementById('equityCanvas');
  if(!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.offsetWidth;
  const h = canvas.height = canvas.offsetHeight;
  if(equity.length < 2) {
    ctx.fillStyle = '#8b949e';
    ctx.font = '12px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Waiting for data...', w/2, h/2);
    return;
  }
  const min = Math.min(...equity);
  const max = Math.max(...equity);
  const range = max - min || 1;
  ctx.clearRect(0, 0, w, h);
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  const isUp = equity[equity.length-1] >= equity[0];
  grad.addColorStop(0, isUp ? 'rgba(63,185,80,0.3)' : 'rgba(248,81,73,0.3)');
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.beginPath();
  equity.forEach((v, i) => {
    const x = (i / (equity.length-1)) * w;
    const y = h - ((v - min) / range) * (h - 10) - 5;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.strokeStyle = isUp ? '#3fb950' : '#f85149';
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.lineTo(w, h);
  ctx.lineTo(0, h);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();
}

function render(d) {
  const s = d.status;
  const logs = d.logs;
  const active = s.bot_active;
  const cb = s.circuit_breaker;
  const marketOpen = s.market_open;

  // market banner
  const banner = document.getElementById('market-banner');
  if(marketOpen) {
    banner.className = 'market-banner market-open';
    banner.innerHTML = '&#x26AB; MARKET OPEN &nbsp;|&nbsp; Live Trading Active';
  } else {
    banner.className = 'market-banner market-closed';
    banner.innerHTML = '&#x23F8; MARKET CLOSED &nbsp;|&nbsp; Next open 9:30 AM ET';
  }

  // equity change
  let changeHtml = '';
  if(s.session_start && s.equity) {
    const diff = parseFloat(s.equity) - parseFloat(s.session_start);
    const pct  = ((diff / parseFloat(s.session_start)) * 100).toFixed(2);
    const cls  = diff >= 0 ? 'green' : 'red';
    const sign = diff >= 0 ? '+' : '';
    changeHtml = `<div class="change"><span class="${cls}">${sign}$${fmt(Math.abs(diff))} (${sign}${pct}%) today</span></div>`;
  }

  // positions
  let posHtml = '';
  if(s.open_positions && s.open_positions.length > 0) {
    s.open_positions.forEach(p => {
      const plCls  = p.pl_dollar >= 0 ? 'green' : 'red';
      const sign   = p.pl_dollar >= 0 ? '+' : '';
      posHtml += `
        <div class="position-card">
          <div class="row"><span class="pos-symbol">${p.symbol}</span><span class="pos-pl ${plCls}">${sign}$${fmt(p.pl_dollar)}</span></div>
          <div class="row"><span class="label">Qty</span><span class="value">${p.qty}</span></div>
          <div class="row"><span class="label">Entry</span><span class="value">$${fmt(p.entry)}</span></div>
          <div class="row"><span class="label">Current</span><span class="value">$${fmt(p.current)}</span></div>
          <div class="row"><span class="label">Return</span><span class="value ${plCls}">${sign}${fmt(p.pl_pct)}%</span></div>
        </div>`;
    });
  } else {
    posHtml = '<p style="color:#8b949e;font-size:13px;text-align:center;padding:8px">No open positions</p>';
  }

  // ticker scores
  let tickerHtml = '';
  if(s.ticker_scores && Object.keys(s.ticker_scores).length > 0) {
    Object.entries(s.ticker_scores).forEach(([sym, t]) => {
      const scoreNorm = Math.min(100, Math.max(0, ((t.score + 40) / 80) * 100));
      const scoreCls  = t.score >= 12 ? 'green' : t.score >= 5 ? 'yellow' : 'red';
      const barColor  = t.score >= 12 ? '#3fb950' : t.score >= 5 ? '#d29922' : '#f85149';
      tickerHtml += `
        <div class="ticker-card">
          <div class="ticker-name">${sym} <span style="font-size:11px;color:#8b949e">$${fmt(t.price)}</span></div>
          <div class="ticker-row"><span class="label">Score</span><span class="${scoreCls}">${fmt(t.score)}</span></div>
          <div class="ticker-row"><span class="label">RSI</span><span>${fmt(t.rsi)}</span></div>
          <div class="ticker-row"><span class="label">MACD</span><span>${fmt(t.macd)}</span></div>
          <div class="ticker-row"><span class="label">VWAP</span><span>${fmt(t.vwap)}</span></div>
          <div class="ticker-row"><span class="label">Sent.</span><span>${fmt(t.sentiment)}</span></div>
          <div class="score-bar"><div class="score-fill" style="width:${scoreNorm}%;background:${barColor}"></div></div>
        </div>`;
    });
  } else {
    tickerHtml = '<p style="color:#8b949e;font-size:13px;text-align:center;padding:8px">Waiting for market data...</p>';
  }

  // trade history
  let historyHtml = '';
  if(s.trade_history && s.trade_history.length > 0) {
    let rows = '';
    s.trade_history.slice().reverse().forEach(t => {
      rows += `<tr>
        <td>${t.time}</td>
        <td class="blue">${t.symbol}</td>
        <td>${t.qty}</td>
        <td>$${fmt(t.entry)}</td>
        <td>$${fmt(t.tp)}</td>
        <td>$${fmt(t.sl)}</td>
      </tr>`;
    });
    historyHtml = `<table class="history-table">
      <thead><tr><th>Time</th><th>Sym</th><th>Qty</th><th>Entry</th><th>TP</th><th>SL</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  } else {
    historyHtml = '<p style="color:#8b949e;font-size:13px;text-align:center;padding:8px">No trades yet today</p>';
  }

  // logs
  let logHtml = '';
  logs.slice().reverse().forEach(line => {
    let cls = 'log-line';
    if(line.includes('INFO'))     cls += ' info';
    if(line.includes('ERROR') || line.includes('failed')) cls += ' error';
    if(line.includes('CRITICAL') || line.includes('TRIPPED')) cls += ' critical';
    logHtml += `<div class="${cls}">${line}</div>`;
  });

  // performance stats
  const perf = d.performance || {};
  const allTime = perf.all_time_by_status || {};
  const todaySt = perf.today_by_status   || {};
  const perfHtml = perf.all_time_trades !== undefined ? `
    <div class="row"><span class="label">All-time Trades</span><span class="value">${perf.all_time_trades}</span></div>
    <div class="row"><span class="label">Filled (all)</span><span class="value green">${allTime.filled || 0}</span></div>
    <div class="row"><span class="label">EOD Closed (all)</span><span class="value yellow">${allTime.eod_closed || 0}</span></div>
    <div class="row"><span class="label">Gap Closed (all)</span><span class="value red">${allTime.gap_closed || 0}</span></div>
    <div style="border-top:1px solid #21262d;margin:8px 0"></div>
    <div class="row"><span class="label">Today Filled</span><span class="value green">${todaySt.filled || 0}</span></div>
    <div class="row"><span class="label">Today EOD Closed</span><span class="value yellow">${todaySt.eod_closed || 0}</span></div>
    <div class="row"><span class="label">Today Gap Closed</span><span class="value red">${todaySt.gap_closed || 0}</span></div>
  ` : '<p style="color:#8b949e;font-size:13px;text-align:center;padding:8px">No trade data yet</p>';

  // use DB equity history when available, otherwise fallback to in-memory
  if(perf.equity_history && perf.equity_history.length > equityHistory.length) {
    equityHistory = perf.equity_history.slice();
  } else if(s.equity) {
    equityHistory.push(parseFloat(s.equity));
    if(equityHistory.length > 100) equityHistory.shift();
  }

  const tradesPct = s.max_trades ? (s.trades_today / s.max_trades * 100) : 0;
  const modeTag   = s.paper_mode ? '<span style="font-size:11px;color:#d29922;border:1px solid #d29922;border-radius:4px;padding:1px 6px;margin-left:8px">PAPER</span>'
                                 : '<span style="font-size:11px;color:#f85149;border:1px solid #f85149;border-radius:4px;padding:1px 6px;margin-left:8px">LIVE</span>';

  document.getElementById('app').innerHTML = `
    <div class="card ${cb ? 'cb-tripped' : ''}">
      <div class="card-title">Bot Status</div>
      <div class="status-row">
        <span class="status-dot ${active ? 'dot-green' : 'dot-red'}"></span>
        ${active ? '<span class="green">ACTIVE</span>' : '<span class="red">OFFLINE</span>'}
        ${modeTag}
        ${cb ? '<span class="red" style="margin-left:auto;font-size:12px">&#x26A0; CIRCUIT BREAKER TRIPPED</span>' : ''}
      </div>
      <div class="row" style="margin-top:10px">
        <span class="label">Last Update</span>
        <span class="value blue" style="font-size:12px">${s.last_update || 'N/A'}</span>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Account Equity</div>
      <div class="equity-big">$${s.equity ? parseFloat(s.equity).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}) : 'N/A'}</div>
      ${changeHtml}
      <div class="row" style="margin-top:10px">
        <span class="label">Cash Available</span>
        <span class="value">$${s.cash ? parseFloat(s.cash).toLocaleString('en-US',{minimumFractionDigits:2}) : 'N/A'}</span>
      </div>
      <div class="row">
        <span class="label">Trades Today</span>
        <span class="value ${tradesPct >= 80 ? 'red' : 'green'}">${s.trades_today || 0} / ${s.max_trades || 10}</span>
      </div>
      <div class="score-bar" style="margin-top:6px"><div class="score-fill" style="width:${tradesPct}%;background:${tradesPct>=80?'#f85149':'#3fb950'}"></div></div>
      <div class="card-title" style="margin-top:12px">Equity Curve</div>
      <div class="chart-wrap"><canvas id="equityCanvas"></canvas></div>
    </div>

    <div class="card">
      <div class="card-title">Open Positions (${s.open_positions ? s.open_positions.length : 0})</div>
      ${posHtml}
    </div>

    <div class="card">
      <div class="card-title">Ticker Scores</div>
      <div class="ticker-grid">${tickerHtml}</div>
    </div>

    <div class="card">
      <div class="card-title">Trade History</div>
      ${historyHtml}
    </div>

    <div class="card">
      <div class="card-title">Performance Stats</div>
      ${perfHtml}
    </div>

    <div class="card">
      <div class="card-title">Live Log</div>
      <div class="log-box">${logHtml}</div>
    </div>
  `;

  setTimeout(() => drawChart(equityHistory), 50);
}

function tick() {
  countdown--;
  document.getElementById('prog').style.width = ((countdown/15)*100) + '%';
  if(countdown <= 0) { countdown = 15; refresh(); }
}

refresh();
setInterval(tick, 1000);
</script>
</body>
</html>
"""


@app.route("/")
@require_auth
def index():
    return render_template_string(TEMPLATE)


@app.route("/api/data")
@require_auth
def api_data():
    return jsonify({
        "status":      read_status(),
        "logs":        read_logs(60),
        "performance": read_performance(),
    })


@app.route("/api/stop", methods=["POST"])
@require_auth
def stop_bot():
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "stop", "tradingbot.service"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return jsonify({"success": False, "error": result.stderr.strip()})
        return jsonify({"success": True})
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "systemctl command timed out"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ---------------------------------------------------------------------------
# BACKTEST PAGE
# ---------------------------------------------------------------------------
BACKTEST_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backtest</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',monospace;padding:12px;max-width:720px;margin:0 auto}
h1{font-size:18px;font-weight:700;margin-bottom:6px;color:#58a6ff;letter-spacing:1px;text-transform:uppercase}
.nav{margin-bottom:14px;font-size:13px}.nav a{color:#58a6ff;text-decoration:none}
.card{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:14px;margin-bottom:12px}
.card-title{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#8b949e;margin-bottom:10px}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}
.form-group{margin-bottom:10px}
.form-group label{display:block;font-size:11px;color:#8b949e;margin-bottom:4px;text-transform:uppercase;letter-spacing:1px}
.form-group input{width:100%;background:#0d1117;border:1px solid #21262d;border-radius:6px;padding:8px;color:#e6edf3;font-size:13px}
.run-btn{width:100%;padding:12px;background:#0d2540;border:1px solid #58a6ff;color:#58a6ff;font-size:14px;font-weight:700;border-radius:8px;cursor:pointer;letter-spacing:1px;margin-top:4px}
.run-btn:disabled{opacity:0.4;cursor:not-allowed}
.metric-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}
.metric-box{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px;text-align:center}
.metric-val{font-size:20px;font-weight:700;margin-bottom:4px}
.metric-lbl{font-size:10px;color:#8b949e;text-transform:uppercase;letter-spacing:1px}
.green{color:#3fb950}.red{color:#f85149}.yellow{color:#d29922}.blue{color:#58a6ff}
.runs-table,.trades-table{width:100%;border-collapse:collapse;font-size:12px}
.runs-table th,.trades-table th{color:#8b949e;text-align:left;padding:5px 7px;border-bottom:1px solid #21262d;font-size:11px;text-transform:uppercase}
.runs-table td{padding:7px 7px;border-bottom:1px solid #161b22;cursor:pointer}
.trades-table td{padding:5px 7px;border-bottom:1px solid #161b22}
.runs-table tr:hover td{background:#21262d}
.status-running{color:#d29922}.status-completed{color:#3fb950}.status-failed{color:#f85149}
.chart-wrap{width:100%;height:140px;background:#0d1117;border:1px solid #21262d;border-radius:8px;overflow:hidden;margin-bottom:12px}
canvas{width:100%;height:100%}
.badge{display:inline-block;padding:1px 5px;border-radius:4px;font-size:10px;font-weight:700}
.badge-tp{background:#0f2d1a;color:#3fb950;border:1px solid #3fb950}
.badge-sl{background:#2d1b1b;color:#f85149;border:1px solid #f85149}
.badge-eod{background:#2d2519;color:#d29922;border:1px solid #d29922}
#results{display:none}
#run-msg{margin-top:10px;font-size:13px;color:#8b949e;text-align:center;min-height:18px}
</style>
</head>
<body>
<div class="nav"><a href="/">&#x2190; Live Monitor</a></div>
<h1>&#x1F4CA; Backtest</h1>

<div class="card">
  <div class="card-title">Configure Backtest</div>
  <div class="form-row">
    <div class="form-group">
      <label>Start Date</label>
      <input type="date" id="bt-start">
    </div>
    <div class="form-group">
      <label>End Date</label>
      <input type="date" id="bt-end">
    </div>
  </div>
  <div class="form-row">
    <div class="form-group">
      <label>Initial Equity ($)</label>
      <input type="number" id="bt-equity" value="100000" min="1000" step="1000">
    </div>
    <div class="form-group">
      <label>Min Score to Buy</label>
      <input type="number" id="bt-score" value="12" step="0.5" min="0" max="40">
    </div>
  </div>
  <div class="form-group">
    <label>Tickers (comma-separated)</label>
    <input type="text" id="bt-tickers" value="NVDA,TSLA,AMD,AAPL,META,MSFT,SPY,QQQ">
  </div>
  <button class="run-btn" id="run-btn" onclick="startBacktest()">&#x25B6; Run Backtest</button>
  <div id="run-msg"></div>
</div>

<div class="card">
  <div class="card-title">Past Runs</div>
  <div id="runs-list"><p style="color:#8b949e;font-size:13px;text-align:center;padding:8px">Loading...</p></div>
</div>

<div id="results">
  <div class="card">
    <div class="card-title" id="res-title">Results</div>
    <div class="metric-grid" id="res-metrics"></div>
    <div class="card-title">Equity Curve</div>
    <div class="chart-wrap"><canvas id="bt-canvas"></canvas></div>
  </div>
  <div class="card">
    <div class="card-title" id="res-trades-title">Trades</div>
    <div style="overflow-x:auto">
      <table class="trades-table">
        <thead><tr>
          <th>Date</th><th>Sym</th><th>Qty</th>
          <th>Entry</th><th>Exit</th><th>Reason</th><th>P&amp;L</th><th>P&amp;L%</th>
        </tr></thead>
        <tbody id="res-trades"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
const today = new Date();
const ago30 = new Date(); ago30.setDate(ago30.getDate()-30);
document.getElementById('bt-end').value   = today.toISOString().slice(0,10);
document.getElementById('bt-start').value = ago30.toISOString().slice(0,10);

function fmt(n,d=2){return(n==null||n===undefined)?'N/A':parseFloat(n).toFixed(d);}

async function startBacktest(){
  const btn=document.getElementById('run-btn');
  const msg=document.getElementById('run-msg');
  btn.disabled=true; msg.style.color='#8b949e'; msg.textContent='Starting...';
  try{
    const r=await fetch('/api/backtest/start',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        start:  document.getElementById('bt-start').value,
        end:    document.getElementById('bt-end').value,
        equity: parseFloat(document.getElementById('bt-equity').value),
        tickers:document.getElementById('bt-tickers').value,
        min_score: parseFloat(document.getElementById('bt-score').value),
      }),
    });
    const d=await r.json();
    if(d.run_id){
      msg.textContent=`Run #${d.run_id} started — fetching data & simulating (may take a few minutes)...`;
      loadRuns(); pollRun(d.run_id);
    }else{
      msg.style.color='#f85149'; msg.textContent=d.error||'Failed to start.'; btn.disabled=false;
    }
  }catch(e){msg.style.color='#f85149';msg.textContent='Request failed.';btn.disabled=false;}
}

async function pollRun(id){
  const r=await fetch(`/api/backtest/run/${id}`);
  const d=await r.json();
  const msg=document.getElementById('run-msg');
  if(d.status==='running'){setTimeout(()=>pollRun(id),5000);return;}
  document.getElementById('run-btn').disabled=false;
  if(d.status==='completed'){
    msg.style.color='#3fb950'; msg.textContent=`Run #${id} complete!`;
    loadRuns(); showResults(id);
  }else{
    msg.style.color='#f85149'; msg.textContent=`Run #${id} failed: ${d.error||'unknown error'}`;
    loadRuns();
  }
}

async function loadRuns(){
  const r=await fetch('/api/backtest/runs');
  const runs=await r.json();
  const el=document.getElementById('runs-list');
  if(!runs.length){
    el.innerHTML='<p style="color:#8b949e;font-size:13px;text-align:center;padding:8px">No runs yet.</p>';
    return;
  }
  let html='<table class="runs-table"><thead><tr><th>#</th><th>Period</th><th>Tickers</th><th>Return</th><th>Sharpe</th><th>Win%</th><th>Status</th></tr></thead><tbody>';
  runs.forEach(r=>{
    const m=r.metrics||{};
    const ret=m.total_return_pct!=null?`<span class="${m.total_return_pct>=0?'green':'red'}">${m.total_return_pct>=0?'+':''}${fmt(m.total_return_pct)}%</span>`:'—';
    html+=`<tr onclick="showResults(${r.id})">
      <td class="blue">#${r.id}</td>
      <td style="font-size:11px">${r.start_date}<br>${r.end_date}</td>
      <td style="font-size:10px;color:#8b949e">${r.tickers.join(', ')}</td>
      <td>${ret}</td>
      <td>${m.sharpe_ratio!=null?fmt(m.sharpe_ratio):'—'}</td>
      <td>${m.win_rate_pct!=null?fmt(m.win_rate_pct,1)+'%':'—'}</td>
      <td class="status-${r.status}">${r.status}</td>
    </tr>`;
  });
  el.innerHTML=html+'</tbody></table>';
}

async function showResults(id){
  const r=await fetch(`/api/backtest/run/${id}`);
  const d=await r.json();
  document.getElementById('results').style.display='block';
  document.getElementById('res-title').textContent=`Run #${d.id} — ${d.start_date} to ${d.end_date}`;
  const m=d.metrics||{};
  const metrics=[
    {l:'Total Return', v:`${m.total_return_pct>=0?'+':''}${fmt(m.total_return_pct)}%`, c:m.total_return_pct>=0?'green':'red'},
    {l:'Sharpe Ratio', v:fmt(m.sharpe_ratio),   c:m.sharpe_ratio>=1?'green':m.sharpe_ratio>=0?'yellow':'red'},
    {l:'Win Rate',     v:`${fmt(m.win_rate_pct,1)}%`, c:'blue'},
    {l:'Max Drawdown', v:`${fmt(m.max_drawdown_pct)}%`,c:'red'},
    {l:'Profit Factor',v:fmt(m.profit_factor),  c:m.profit_factor>=1.5?'green':'yellow'},
    {l:'Total Trades', v:m.total_trades||0,      c:''},
  ];
  document.getElementById('res-metrics').innerHTML=metrics.map(x=>
    `<div class="metric-box"><div class="metric-val ${x.c}">${x.v}</div><div class="metric-lbl">${x.l}</div></div>`
  ).join('');
  drawChart(d.equity_curve, d.initial_equity);
  const wins=d.trades.filter(t=>t.pnl>0).length;
  document.getElementById('res-trades-title').textContent=
    `Trades (${d.trades.length} total, ${wins} wins, ${d.trades.length-wins} losses)`;
  let rows='';
  d.trades.slice().reverse().forEach(t=>{
    const pc=t.pnl>=0?'green':'red';
    const sign=t.pnl>=0?'+':'';
    const bc=t.exit_reason==='tp_hit'?'badge-tp':t.exit_reason.includes('eod')?'badge-eod':'badge-sl';
    const bl=t.exit_reason==='tp_hit'?'TP':t.exit_reason.includes('eod')?'EOD':'SL';
    rows+=`<tr>
      <td>${t.date}</td><td class="blue">${t.symbol}</td><td>${t.qty}</td>
      <td>$${fmt(t.entry)}</td><td>$${fmt(t.exit_price)}</td>
      <td><span class="badge ${bc}">${bl}</span></td>
      <td class="${pc}">${sign}$${fmt(Math.abs(t.pnl))}</td>
      <td class="${pc}">${sign}${fmt(t.pnl_pct)}%</td>
    </tr>`;
  });
  document.getElementById('res-trades').innerHTML=rows||
    '<tr><td colspan="8" style="text-align:center;color:#8b949e;padding:12px">No trades in this run.</td></tr>';
  document.getElementById('results').scrollIntoView({behavior:'smooth'});
}

function drawChart(curve, initEq){
  const canvas=document.getElementById('bt-canvas');
  const ctx=canvas.getContext('2d');
  const w=canvas.width=canvas.offsetWidth;
  const h=canvas.height=canvas.offsetHeight;
  const data=curve.map(p=>p.equity);
  if(data.length<2){
    ctx.fillStyle='#8b949e';ctx.font='12px monospace';ctx.textAlign='center';
    ctx.fillText('No data',w/2,h/2);return;
  }
  const mn=Math.min(initEq,...data), mx=Math.max(initEq,...data), rng=mx-mn||1;
  ctx.clearRect(0,0,w,h);
  const isUp=data[data.length-1]>=initEq;
  const col=isUp?'#3fb950':'#f85149';
  const grad=ctx.createLinearGradient(0,0,0,h);
  grad.addColorStop(0,isUp?'rgba(63,185,80,0.3)':'rgba(248,81,73,0.3)');
  grad.addColorStop(1,'rgba(0,0,0,0)');
  ctx.beginPath();
  data.forEach((v,i)=>{
    const x=(i/(data.length-1))*w;
    const y=h-((v-mn)/rng)*(h-10)-5;
    i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
  });
  ctx.strokeStyle=col;ctx.lineWidth=2;ctx.stroke();
  ctx.lineTo(w,h);ctx.lineTo(0,h);ctx.closePath();
  ctx.fillStyle=grad;ctx.fill();
  // baseline
  const by=h-((initEq-mn)/rng)*(h-10)-5;
  ctx.beginPath();ctx.moveTo(0,by);ctx.lineTo(w,by);
  ctx.strokeStyle='rgba(139,148,158,0.4)';ctx.lineWidth=1;ctx.setLineDash([4,4]);
  ctx.stroke();ctx.setLineDash([]);
}

loadRuns();
</script>
</body>
</html>
"""


@app.route("/backtest")
@require_auth
def backtest_page():
    return render_template_string(BACKTEST_TEMPLATE)


@app.route("/api/backtest/runs")
@require_auth
def api_backtest_runs():
    return jsonify(get_runs())


@app.route("/api/backtest/run/<int:run_id>")
@require_auth
def api_backtest_run(run_id):
    d = get_run_details(run_id)
    if not d:
        return jsonify({"error": "Not found"}), 404
    return jsonify(d)


@app.route("/api/backtest/start", methods=["POST"])
@require_auth
def api_backtest_start():
    data = request.get_json(force=True)
    try:
        start     = date.fromisoformat(data["start"])
        end       = date.fromisoformat(data["end"])
        equity    = float(data.get("equity", 100_000))
        tickers   = [t.strip().upper() for t in data.get("tickers", "").split(",") if t.strip()]
        min_score = float(data.get("min_score", DEFAULT_RISK["min_score_to_buy"]))
        if not tickers:
            return jsonify({"error": "No tickers provided"}), 400
        if start >= end:
            return jsonify({"error": "start must be before end"}), 400
        risk = {**DEFAULT_RISK, "min_score_to_buy": min_score}
        engine = BacktestEngine(risk=risk, cb=DEFAULT_CB)
        run_id = create_run(start, end, tickers, engine.risk, equity)
        threading.Thread(
            target=engine.run,
            args=(run_id, tickers, start, end, equity),
            daemon=True,
        ).start()
        return jsonify({"run_id": run_id})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


CHESS_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <title>Chess &#x265F;</title>
  <link rel="stylesheet" href="/static/chess/chess.css">
</head>
<body>

<!-- Rule announcement banner -->
<div id="rule-banner">
  <div class="rule-banner-emoji">&#x26A1;</div>
  <div class="rule-banner-name">Rule Change!</div>
  <div class="rule-banner-desc">A new rule has been activated.</div>
  <button id="rule-ok">Got it!</button>
</div>

<div id="chess-app">
  <!-- Header -->
  <div id="chess-header">
    <div id="chess-title">&#x265F; Chaos Chess</div>
    <div style="display:flex;gap:8px;align-items:center">
      <button id="resign-btn">Resign</button>
      <button id="new-game-btn">New Game</button>
    </div>
  </div>

  <!-- Status bar (check warning) -->
  <div id="status-bar"></div>

  <!-- Turn indicator -->
  <div id="turn-indicator">
    <span class="turn-dot white" id="turn-dot"></span>
    <span id="turn-label">White's Turn</span>
    <span id="turn-counter">Rule changes in 4 moves</span>
  </div>

  <!-- Active rules pill bar -->
  <div id="active-rules-bar"></div>

  <!-- Board -->
  <div id="board-wrapper">
    <div id="chess-board"></div>
  </div>

  <!-- Move log -->
  <div id="move-log-section">
    <div id="move-log-header">Move History</div>
    <div id="move-log"></div>
  </div>

  <!-- Back link -->
  <a href="/" style="font-size:12px;color:#8b949e;text-decoration:none;margin-top:4px">&#x2190; Back to Dashboard</a>
</div>

<!-- Promotion modal -->
<div class="modal-overlay hidden" id="promotion-modal">
  <div class="modal-box">
    <h2>Promote Pawn</h2>
    <p>Choose a piece to promote to:</p>
    <div id="promo-choices"></div>
  </div>
</div>

<!-- Game over modal -->
<div class="modal-overlay hidden" id="game-over-modal">
  <div class="modal-box">
    <div class="winner-banner">&#x265A;</div>
    <div class="outcome-text">Game Over</div>
    <div class="outcome-sub"></div>
    <button id="play-again-btn">Play Again</button>
  </div>
</div>

<script src="/static/chess/chess.js"></script>
</body>
</html>"""


@app.route("/chess")
def chess_page():
    return render_template_string(CHESS_TEMPLATE)


@app.route("/api/chess/new", methods=["POST"])
def api_chess_new():
    session = chess_manager.new_game()
    return jsonify(session.to_dict())


@app.route("/api/chess/state")
def api_chess_state():
    game_id = request.args.get("game_id")
    session = chess_manager.get_game(game_id)
    if not session:
        return jsonify({"error": "Game not found"}), 404
    return jsonify(session.to_dict())


@app.route("/api/chess/moves")
def api_chess_moves():
    game_id = request.args.get("game_id")
    row = int(request.args.get("row", 0))
    col = int(request.args.get("col", 0))
    moves = chess_manager.get_legal_moves_for_square(game_id, row, col)
    return jsonify({"moves": moves})


@app.route("/api/chess/move", methods=["POST"])
def api_chess_move():
    data = request.get_json(force=True)
    result = chess_manager.make_move(
        data.get("game_id"),
        int(data.get("from_row", 0)), int(data.get("from_col", 0)),
        int(data.get("to_row", 0)),  int(data.get("to_col", 0)),
        data.get("promotion"),
    )
    return jsonify(result)


@app.route("/api/chess/resign", methods=["POST"])
def api_chess_resign():
    data = request.get_json(force=True)
    result = chess_manager.resign(data.get("game_id"), data.get("color"))
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
