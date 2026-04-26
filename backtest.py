"""
Backtesting engine — simulates the live trading strategy on historical Alpaca data.

Sentiment is fixed at 0.0 (neutral) since historical news is unavailable.
All indicator and scoring logic mirrors trading_bot_v7.py exactly.

CLI usage:
    python backtest.py --start 2026-03-01 --end 2026-04-25
    python backtest.py --start 2026-03-01 --end 2026-04-25 --equity 50000 --tickers NVDA,TSLA,AMD
"""

import argparse
import json
import logging
import math
import os
import sqlite3
from collections import deque
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_ta  # noqa — registers .ta accessor on DataFrames
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

load_dotenv()

ET           = ZoneInfo("America/New_York")
BACKTEST_DB  = "backtest_results.db"
MIN_BARS     = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backtest")


# ---------------------------------------------------------------------------
# INDICATORS + SCORING
# Self-contained copy to avoid importing trading_bot_v7 (side effects there).
# ---------------------------------------------------------------------------
def _compute_indicators(df: pd.DataFrame):
    try:
        df.ta.vwap(append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(append=True)
        df.ta.atr(length=14, append=True)
        return df.iloc[-1]
    except Exception:
        return None


def _compute_score(last) -> tuple[float, dict]:
    macd_hist  = last.get("MACDh_12_26_9", 0.0)
    macd_score = (
        max(-10.0, min(10.0, (macd_hist / 0.5) * 10.0))
        if not pd.isna(macd_hist) else 0.0
    )
    rsi = last.get("RSI_14", 50.0)
    if pd.isna(rsi): rsi = 50.0
    if   rsi < 30:  rsi_score =  8.0
    elif rsi < 40:  rsi_score =  5.0
    elif rsi <= 60: rsi_score =  2.0
    elif rsi <= 70: rsi_score = -3.0
    else:           rsi_score = -8.0
    price = float(last.get("Close", 0.0))
    vwap  = float(last.get("VWAP_D", price) or price)
    if pd.isna(vwap) or vwap == 0:
        vwap = price
    vwap_score = max(-10.0, min(10.0, ((price - vwap) / vwap / 0.01) * 10.0))
    total = macd_score + rsi_score + vwap_score  # sentiment fixed at 0
    return total, {"macd": macd_score, "rsi": rsi_score, "vwap": vwap_score, "total": total}


# ---------------------------------------------------------------------------
# DEFAULT RISK / CB CONFIG
# ---------------------------------------------------------------------------
DEFAULT_RISK: dict = {
    "account_risk_pct":        0.01,
    "atr_stop_mult":           2.0,
    "min_score_to_buy":        12.0,
    "max_open_positions":      3,
    "max_position_notional":   50_000,
    "limit_slippage_pct":      0.0005,
}
DEFAULT_CB: dict = {
    "daily_drawdown_limit_pct": 0.02,
    "daily_max_trades":         10,
}


# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------
def init_backtest_db():
    with sqlite3.connect(BACKTEST_DB) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at     TEXT NOT NULL,
                start_date     TEXT NOT NULL,
                end_date       TEXT NOT NULL,
                tickers        TEXT NOT NULL,
                config         TEXT NOT NULL,
                initial_equity REAL NOT NULL,
                status         TEXT NOT NULL DEFAULT 'pending',
                error          TEXT,
                metrics        TEXT
            );
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      INTEGER NOT NULL,
                date        TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                qty         REAL NOT NULL,
                entry       REAL NOT NULL,
                exit_price  REAL NOT NULL,
                tp          REAL NOT NULL,
                sl          REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                pnl         REAL NOT NULL,
                pnl_pct     REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS backtest_equity (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id  INTEGER NOT NULL,
                date    TEXT NOT NULL,
                equity  REAL NOT NULL
            );
        """)


def create_run(start: date, end: date, tickers: list, config: dict, initial_equity: float) -> int:
    with sqlite3.connect(BACKTEST_DB) as conn:
        cur = conn.execute(
            "INSERT INTO backtest_runs "
            "(created_at,start_date,end_date,tickers,config,initial_equity,status) "
            "VALUES (?,?,?,?,?,?,'running')",
            (
                datetime.now(ET).isoformat(),
                str(start), str(end),
                json.dumps(tickers),
                json.dumps(config),
                initial_equity,
            ),
        )
        return cur.lastrowid


def _update_run(run_id: int, status: str, metrics: dict = None, error: str = None):
    with sqlite3.connect(BACKTEST_DB) as conn:
        conn.execute(
            "UPDATE backtest_runs SET status=?, metrics=?, error=? WHERE id=?",
            (status, json.dumps(metrics) if metrics else None, error, run_id),
        )


def _save_trade(run_id: int, t: dict):
    with sqlite3.connect(BACKTEST_DB) as conn:
        conn.execute(
            "INSERT INTO backtest_trades "
            "(run_id,date,symbol,qty,entry,exit_price,tp,sl,exit_reason,pnl,pnl_pct) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, t["date"], t["symbol"], t["qty"],
                t["entry"], t["exit_price"], t["tp"], t["sl"],
                t["exit_reason"], t["pnl"], t["pnl_pct"],
            ),
        )


def _save_equity(run_id: int, date_str: str, equity: float):
    with sqlite3.connect(BACKTEST_DB) as conn:
        conn.execute(
            "INSERT INTO backtest_equity (run_id,date,equity) VALUES (?,?,?)",
            (run_id, date_str, equity),
        )


def get_runs() -> list:
    try:
        with sqlite3.connect(BACKTEST_DB) as conn:
            rows = conn.execute(
                "SELECT id,created_at,start_date,end_date,tickers,"
                "initial_equity,status,metrics FROM backtest_runs ORDER BY id DESC"
            ).fetchall()
        return [
            {
                "id": r[0], "created_at": r[1], "start_date": r[2], "end_date": r[3],
                "tickers": json.loads(r[4]), "initial_equity": r[5],
                "status": r[6], "metrics": json.loads(r[7]) if r[7] else {},
            }
            for r in rows
        ]
    except Exception:
        return []


def get_run_details(run_id: int) -> dict | None:
    try:
        with sqlite3.connect(BACKTEST_DB) as conn:
            run = conn.execute(
                "SELECT id,created_at,start_date,end_date,tickers,config,"
                "initial_equity,status,error,metrics FROM backtest_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if not run:
                return None
            trades = conn.execute(
                "SELECT date,symbol,qty,entry,exit_price,tp,sl,exit_reason,pnl,pnl_pct "
                "FROM backtest_trades WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
            equity = conn.execute(
                "SELECT date,equity FROM backtest_equity WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        return {
            "id": run[0], "created_at": run[1], "start_date": run[2], "end_date": run[3],
            "tickers": json.loads(run[4]), "config": json.loads(run[5]),
            "initial_equity": run[6], "status": run[7], "error": run[8],
            "metrics": json.loads(run[9]) if run[9] else {},
            "trades": [
                {
                    "date": t[0], "symbol": t[1], "qty": t[2], "entry": t[3],
                    "exit_price": t[4], "tp": t[5], "sl": t[6],
                    "exit_reason": t[7], "pnl": t[8], "pnl_pct": t[9],
                }
                for t in trades
            ],
            "equity_curve": [{"date": e[0], "equity": e[1]} for e in equity],
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# METRICS
# ---------------------------------------------------------------------------
def _calculate_metrics(trades: list, equity_curve: list, initial_equity: float) -> dict:
    if not trades:
        return {
            "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
            "win_rate_pct": 0, "profit_factor": 0,
            "total_return_pct": 0, "max_drawdown_pct": 0,
            "sharpe_ratio": 0, "final_equity": round(initial_equity, 2),
        }
    rets   = [t["pnl_pct"] for t in trades]
    wins   = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_profit = sum(wins)
    gross_loss   = abs(sum(losses))
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999.0
    final_eq  = equity_curve[-1]["equity"] if equity_curve else initial_equity
    total_ret = (final_eq - initial_equity) / initial_equity
    # Max drawdown
    peak = max_dd = 0.0
    for pt in equity_curve:
        eq = pt["equity"]
        if eq > peak: peak = eq
        if peak > 0: max_dd = max(max_dd, (peak - eq) / peak)
    # Sharpe (annualised from daily equity returns)
    sharpe = 0.0
    if len(equity_curve) > 1:
        dr   = [
            (equity_curve[i]["equity"] - equity_curve[i-1]["equity"]) / equity_curve[i-1]["equity"]
            for i in range(1, len(equity_curve))
        ]
        mean = sum(dr) / len(dr)
        std  = (sum((r - mean) ** 2 for r in dr) / len(dr)) ** 0.5
        sharpe = round((mean / std) * math.sqrt(252), 2) if std > 0 else 0.0
    return {
        "total_trades":     len(trades),
        "winning_trades":   len(wins),
        "losing_trades":    len(losses),
        "win_rate_pct":     round(len(wins) / len(trades) * 100, 1),
        "profit_factor":    pf,
        "total_return_pct": round(total_ret * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_ratio":     sharpe,
        "final_equity":     round(final_eq, 2),
    }


# ---------------------------------------------------------------------------
# BACKTEST ENGINE
# ---------------------------------------------------------------------------
class BacktestEngine:
    def __init__(self, risk: dict = None, cb: dict = None):
        api_key = os.getenv("ALPACA_API_KEY", "")
        secret  = os.getenv("ALPACA_SECRET_KEY", "")
        if not api_key or not secret:
            raise EnvironmentError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set.")
        self.data_client = StockHistoricalDataClient(api_key, secret)
        self.risk = {**DEFAULT_RISK, **(risk or {})}
        self.cb   = {**DEFAULT_CB,   **(cb   or {})}

    def _fetch(self, tickers: list, start: date, end: date) -> dict[str, pd.DataFrame]:
        result = {}
        for ticker in tickers:
            try:
                log.info(f"Fetching {ticker}  {start} → {end}...")
                req = StockBarsRequest(
                    symbol_or_symbols=ticker,
                    timeframe=TimeFrame.Minute,
                    start=datetime.combine(start, datetime.min.time()),
                    end=datetime.combine(end, datetime.max.time()),
                    feed=DataFeed.IEX,
                )
                bars = self.data_client.get_stock_bars(req)
                df   = bars.df
                if df.empty:
                    log.warning(f"{ticker}: no data returned")
                    continue
                if isinstance(df.index, pd.MultiIndex):
                    df = df.xs(ticker, level=0)
                df.index = pd.to_datetime(df.index, utc=True).tz_convert(ET)
                df.rename(columns={
                    "open": "Open", "high": "High",
                    "low":  "Low",  "close": "Close", "volume": "Volume",
                }, inplace=True)
                df = df.between_time("09:30", "15:59")
                result[ticker] = df
                log.info(f"  {ticker}: {len(df)} bars")
            except Exception as exc:
                log.error(f"Fetch failed for {ticker}: {exc}")
        return result

    def run(self, run_id: int, tickers: list, start: date, end: date, initial_equity: float):
        try:
            bar_data = self._fetch(tickers, start, end)
            if not bar_data:
                _update_run(run_id, "failed", error="No data returned for any ticker.")
                return

            equity          = initial_equity
            equity_curve: list[dict]       = []
            all_trades: list[dict]         = []
            buffers         = {t: deque(maxlen=390) for t in tickers}
            open_positions: dict[str, dict] = {}

            all_dates = sorted({ts.date() for df in bar_data.values() for ts in df.index})

            for trading_date in all_dates:
                log.info(f"Simulating {trading_date}  equity=${equity:,.2f}")
                for t in tickers:
                    buffers[t].clear()

                day_start_eq = equity
                trades_today = 0
                cb_tripped   = False

                # Index all bars for this day by timestamp
                day_map: dict[pd.Timestamp, dict[str, pd.Series]] = {}
                for ticker, df in bar_data.items():
                    for ts, row in df[df.index.date == trading_date].iterrows():
                        day_map.setdefault(ts, {})[ticker] = row

                for ts in sorted(day_map):
                    if cb_tripped:
                        break
                    near_close = ts.hour == 15 and ts.minute >= 45

                    for ticker, bar in day_map[ts].items():
                        buffers[ticker].append({
                            "timestamp": ts,
                            "Open":   float(bar["Open"]),  "High": float(bar["High"]),
                            "Low":    float(bar["Low"]),    "Close": float(bar["Close"]),
                            "Volume": float(bar["Volume"]),
                        })

                        # ── Manage open position ───────────────────────────
                        if ticker in open_positions:
                            pos = open_positions[ticker]
                            hi, lo = float(bar["High"]), float(bar["Low"])
                            if hi >= pos["tp"]:
                                ep, reason = pos["tp"], "tp_hit"
                            elif lo <= pos["sl"]:
                                ep, reason = pos["sl"], "sl_hit"
                            elif near_close:
                                ep, reason = float(bar["Close"]), "eod_close"
                            else:
                                continue
                            pnl     = (ep - pos["entry"]) * pos["qty"]
                            pnl_pct = (ep - pos["entry"]) / pos["entry"] * 100
                            equity += pnl
                            rec = {
                                "date":        str(trading_date),
                                "symbol":      ticker,
                                "qty":         pos["qty"],
                                "entry":       pos["entry"],
                                "exit_price":  ep,
                                "tp":          pos["tp"],
                                "sl":          pos["sl"],
                                "exit_reason": reason,
                                "pnl":         round(pnl, 2),
                                "pnl_pct":     round(pnl_pct, 4),
                            }
                            all_trades.append(rec)
                            _save_trade(run_id, rec)
                            del open_positions[ticker]
                            trades_today += 1
                            continue

                        # ── Entry logic ────────────────────────────────────
                        if near_close:
                            continue
                        if len(buffers[ticker]) < MIN_BARS:
                            continue
                        if len(open_positions) >= self.risk["max_open_positions"]:
                            continue
                        if trades_today >= self.cb["daily_max_trades"]:
                            cb_tripped = True
                            break
                        if day_start_eq > 0:
                            dd = (day_start_eq - equity) / day_start_eq
                            if dd >= self.cb["daily_drawdown_limit_pct"]:
                                cb_tripped = True
                                break

                        df_buf = pd.DataFrame(list(buffers[ticker])).set_index("timestamp")
                        last   = _compute_indicators(df_buf)
                        if last is None:
                            continue
                        score, _ = _compute_score(last)
                        if score < self.risk["min_score_to_buy"]:
                            continue

                        price = float(last["Close"])
                        atr   = float(last.get("ATRr_14", price * 0.01) or price * 0.01)
                        if pd.isna(atr) or atr <= 0:
                            atr = price * 0.01
                        stop_d = max(atr * self.risk["atr_stop_mult"], 0.01)
                        qty    = max(1, math.floor(equity * self.risk["account_risk_pct"] / stop_d))
                        qty    = min(qty, max(1, math.floor(self.risk["max_position_notional"] / price)))
                        entry  = round(price * (1 + self.risk["limit_slippage_pct"]), 2)
                        sl     = round(entry - stop_d, 2)
                        tp     = round(entry + stop_d * 2, 2)
                        if entry * qty > equity:
                            continue

                        open_positions[ticker] = {"entry": entry, "sl": sl, "tp": tp, "qty": qty}
                        log.debug(f"  ENTER {ticker} @ {entry:.2f}  sl={sl:.2f}  tp={tp:.2f}  qty={qty}")

                # EOD force-close any positions that never hit TP/SL
                for ticker, pos in list(open_positions.items()):
                    day_df   = bar_data.get(ticker)
                    day_rows = day_df[day_df.index.date == trading_date] if day_df is not None else None
                    ep       = float(day_rows.iloc[-1]["Close"]) if day_rows is not None and not day_rows.empty else pos["entry"]
                    pnl      = (ep - pos["entry"]) * pos["qty"]
                    pnl_pct  = (ep - pos["entry"]) / pos["entry"] * 100
                    equity  += pnl
                    rec = {
                        "date": str(trading_date), "symbol": ticker,
                        "qty": pos["qty"], "entry": pos["entry"],
                        "exit_price": ep, "tp": pos["tp"], "sl": pos["sl"],
                        "exit_reason": "eod_force",
                        "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 4),
                    }
                    all_trades.append(rec)
                    _save_trade(run_id, rec)
                open_positions.clear()

                equity_curve.append({"date": str(trading_date), "equity": round(equity, 2)})
                _save_equity(run_id, str(trading_date), round(equity, 2))

            metrics = _calculate_metrics(all_trades, equity_curve, initial_equity)
            _update_run(run_id, "completed", metrics=metrics)
            log.info(f"Backtest #{run_id} complete: {metrics}")

        except Exception as exc:
            log.error(f"Backtest #{run_id} failed: {exc}", exc_info=True)
            _update_run(run_id, "failed", error=str(exc))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a backtest of the trading strategy")
    parser.add_argument("--start",   required=True,  help="Start date YYYY-MM-DD")
    parser.add_argument("--end",     required=True,  help="End date YYYY-MM-DD")
    parser.add_argument("--equity",  type=float, default=100_000, help="Initial equity (default 100000)")
    parser.add_argument("--tickers", default="NVDA,TSLA,AMD,AAPL,META,MSFT,SPY,QQQ",
                        help="Comma-separated tickers")
    args = parser.parse_args()

    init_backtest_db()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    engine  = BacktestEngine()
    run_id  = create_run(
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        tickers, engine.risk, args.equity,
    )
    log.info(f"Run #{run_id} started.")
    engine.run(
        run_id, tickers,
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        args.equity,
    )
