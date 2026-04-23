import json
import os
from flask import Flask, jsonify, render_template_string, request
import subprocess

app = Flask(__name__)

BASE   = "/root/Trading-bot"
STATUS = os.path.join(BASE, "status.json")
LOG    = os.path.join(BASE, "bot.log")


def read_status():
    try:
        with open(STATUS) as f:
            return json.load(f)
    except Exception:
        return {
            "bot_active":  False,
            "last_update": "unavailable",
            "market_open": False,
        }


def read_logs(n=60):
    try:
        with open(LOG) as f:
            return [line.strip() for line in f.readlines()[-n:]]
    except Exception:
        return []


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
<h1>&#x1F916; Bot HUD <button class="theme-toggle" onclick="toggleTheme()" id="themeBtn">☀ Light</button></h1>
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

  // equity chart
  if(s.equity) {
    equityHistory.push(parseFloat(s.equity));
    if(equityHistory.length > 50) equityHistory.shift();
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

  const tradesPct = s.max_trades ? (s.trades_today / s.max_trades * 100) : 0;

  document.getElementById('app').innerHTML = `
    <div class="card ${cb ? 'cb-tripped' : ''}">
      <div class="card-title">Bot Status</div>
      <div class="status-row">
        <span class="status-dot ${active ? 'dot-green' : 'dot-red'}"></span>
        ${active ? '<span class="green">ACTIVE</span>' : '<span class="red">OFFLINE</span>'}
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
def index():
    return render_template_string(TEMPLATE)


@app.route("/api/data")
def api_data():
    return jsonify({"status": read_status(), "logs": read_logs(60)})


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    try:
        subprocess.Popen(["sudo", "systemctl", "stop", "tradingbot.service"])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
