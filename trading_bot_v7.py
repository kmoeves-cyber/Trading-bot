import asyncio
import logging
import os
import time
import math
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_ta as ta
import httpx
import yfinance as yf
from dotenv import load_dotenv
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from transformers import pipeline

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, OrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

# ---------------------------------------------------------------------------
# 0. LOGGING
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger().addHandler(logging.FileHandler("bot.log"))
log = logging.getLogger("TradingBot_v7")

# ---------------------------------------------------------------------------
# 1. CONFIG — LOADED FROM ENVIRONMENT VARIABLES (.env file or system env)
# ---------------------------------------------------------------------------
load_dotenv()

API_KEY         = os.getenv("ALPACA_API_KEY", "YOUR_API_KEY_HERE")
SECRET_KEY      = os.getenv("ALPACA_SECRET_KEY", "YOUR_SECRET_KEY_HERE")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")  # None if not set

WATCHLIST = ["NVDA", "TSLA", "AMD", "AAPL", "META"]

RISK_CONFIG = {
    "account_risk_pct":      0.01,
    "atr_stop_mult":         2.0,
    "min_score_to_buy":      12.0,
    "max_open_positions":    3,
    "max_position_notional": 50_000,
    "limit_slippage_pct":    0.0005,
}

CIRCUIT_BREAKER_CONFIG = {
    "daily_drawdown_limit_pct": 0.02,
    "daily_max_trades":         10,
}

ORDER_FILL_TIMEOUT_SECONDS = 120
ORDER_POLL_SECONDS         = 15
BAR_BUFFER_SIZE            = 390
MIN_BARS_FOR_SIGNAL        = 30
SENTIMENT_CACHE_MINUTES    = 10
WATCHDOG_TIMEOUT_SECONDS   = 180
WATCHDOG_POLL_SECONDS      = 60
DATA_FEED                  = DataFeed.IEX
ET                         = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# 2. CLIENT INITIALIZATION
# ---------------------------------------------------------------------------
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client    = StockHistoricalDataClient(API_KEY, SECRET_KEY)
stream_client: StockDataStream = StockDataStream(API_KEY, SECRET_KEY, feed=DATA_FEED)

log.info("Loading FinBERT sentiment model... (~30 s)")
sentiment_analyzer = pipeline(
    "sentiment-analysis", model="ProsusAI/finbert",
    truncation=True, max_length=512,
)
log.info("FinBERT loaded.")

_sentiment_cache: dict = {}
_bar_buffers: dict[str, deque] = {
    ticker: deque(maxlen=BAR_BUFFER_SIZE) for ticker in WATCHLIST
}
_pending_orders: dict[str, asyncio.Task] = {}
_last_bar_time: float             = time.monotonic()
_stream_task: asyncio.Task | None = None

# ---------------------------------------------------------------------------
# CIRCUIT BREAKER STATE
# ---------------------------------------------------------------------------
_cb_state = {
    "session_date":         None,
    "session_start_equity": None,
    "trades_today":         0,
    "is_tripped":           False,
}


def _clear_buffers_for_new_day():
    for ticker in WATCHLIST:
        _bar_buffers[ticker].clear()
    log.info("Bar buffers cleared for new trading session.")


def _reset_circuit_breaker_if_new_day():
    today = datetime.now(ET).date()
    if _cb_state["session_date"] != today:
        _cb_state["session_date"]         = today
        _cb_state["session_start_equity"] = None
        _cb_state["trades_today"]         = 0
        _cb_state["is_tripped"]           = False
        _clear_buffers_for_new_day()
        log.info(f"Circuit breaker reset for new session: {today}")


async def check_circuit_breaker(current_equity: float) -> bool:
    if _cb_state["is_tripped"]:
        return True
    if _cb_state["session_start_equity"] is None:
        _cb_state["session_start_equity"] = current_equity
        log.info(f"Session start equity snapshot: ${current_equity:,.2f}")
        return False
    start_equity = _cb_state["session_start_equity"]
    drawdown_pct = (start_equity - current_equity) / start_equity
    limit_pct    = CIRCUIT_BREAKER_CONFIG["daily_drawdown_limit_pct"]
    if drawdown_pct >= limit_pct:
        _cb_state["is_tripped"] = True
        msg = (
            f"CIRCUIT BREAKER TRIPPED - DRAWDOWN\n"
            f"Session start: ${start_equity:,.2f} | Current: ${current_equity:,.2f}\n"
            f"Loss: {drawdown_pct*100:.2f}% >= limit {limit_pct*100:.1f}%"
        )
        log.critical(msg)
        await send_alert(msg)
        return True
    if _cb_state["trades_today"] >= CIRCUIT_BREAKER_CONFIG["daily_max_trades"]:
        _cb_state["is_tripped"] = True
        msg = (
            f"CIRCUIT BREAKER TRIPPED - MAX TRADES\n"
            f"Executed {_cb_state['trades_today']} trades today."
        )
        log.critical(msg)
        await send_alert(msg)
        return True
    return False


# ---------------------------------------------------------------------------
# 3. RETRY HELPERS
# ---------------------------------------------------------------------------
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(Exception))
def fetch_account_safe():
    return trading_client.get_account()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(Exception))
def fetch_positions_safe():
    return trading_client.get_all_positions()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(Exception))
def fetch_order_safe(order_id: str):
    return trading_client.get_order_by_id(order_id)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(Exception))
def cancel_order_safe(order_id: str):
    return trading_client.cancel_order_by_id(order_id)


# ---------------------------------------------------------------------------
# 4. DISCORD ALERTS
# ---------------------------------------------------------------------------
async def send_alert(message: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                DISCORD_WEBHOOK,
                json={"content": f"🤖 **Algo-Bot v7:**\n{message}"},
            )
    except Exception as exc:
        log.warning(f"Discord webhook failed: {exc}")


# ---------------------------------------------------------------------------
# 5. MARKET HOURS GUARD
# ---------------------------------------------------------------------------
def is_market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    open_t  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= now < close_t


# ---------------------------------------------------------------------------
# 6. BUFFER BOOTSTRAP
# ---------------------------------------------------------------------------
async def bootstrap_buffers():
    log.info("Bootstrapping bar buffers with today's historical data...")
    today_open = datetime.now(ET).replace(hour=9, minute=30, second=0, microsecond=0)
    for ticker in WATCHLIST:
        try:
            request = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame.Minute,
                start=today_open,
            )
            bars = await asyncio.to_thread(data_client.get_stock_bars, request)
            df   = bars.df
            if df.empty:
                continue
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(ticker, level=0)
            df.index = pd.to_datetime(df.index, utc=True).tz_convert(ET)
            df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                                "close": "Close", "volume": "Volume"}, inplace=True)
            for ts, row in df.iterrows():
                _bar_buffers[ticker].append({
                    "timestamp": ts,
                    "Open": row["Open"], "High": row["High"],
                    "Low":  row["Low"],  "Close": row["Close"],
                    "Volume": row["Volume"],
                })
            log.info(f"Bootstrap: {ticker} seeded {len(_bar_buffers[ticker])} bars.")
        except Exception as exc:
            log.error(f"Bootstrap failed for {ticker}: {exc}")


# ---------------------------------------------------------------------------
# 7. INDICATORS
# ---------------------------------------------------------------------------
def buffer_to_df(ticker: str) -> pd.DataFrame | None:
    buf = _bar_buffers.get(ticker)
    if not buf or len(buf) < MIN_BARS_FOR_SIGNAL:
        return None
    df = pd.DataFrame(list(buf))
    df.set_index("timestamp", inplace=True)
    return df


def compute_indicators(df: pd.DataFrame):
    try:
        df.ta.vwap(append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.macd(append=True)
        df.ta.atr(length=14, append=True)
        return df.iloc[-1]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 8. NEWS SENTIMENT
# ---------------------------------------------------------------------------
async def get_cached_sentiment(ticker: str) -> float:
    now = datetime.now(ET)
    if ticker in _sentiment_cache:
        score, ts = _sentiment_cache[ticker]
        if (now - ts).total_seconds() < SENTIMENT_CACHE_MINUTES * 60:
            return score
    score = await asyncio.to_thread(_compute_sentiment_blocking, ticker)
    _sentiment_cache[ticker] = (score, now)
    return score


def _compute_sentiment_blocking(ticker: str) -> float:
    try:
        news_items = yf.Ticker(ticker).news or []
        headlines  = [
            item["content"]["title"]
            for item in news_items
            if "content" in item and "title" in item["content"]
        ][:5]
        if not headlines:
            return 0.0
        scores = []
        for h in headlines:
            res = sentiment_analyzer(h)[0]
            if   res["label"] == "positive": scores.append( res["score"])
            elif res["label"] == "negative": scores.append(-res["score"])
            else:                            scores.append(0.0)
        return sum(scores) / len(scores)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 9. TRADE SCORING
# ---------------------------------------------------------------------------
def compute_trade_score(last, sentiment: float):
    breakdown = {}
    sentiment_score = max(-10.0, min(10.0, sentiment * 10.0))
    breakdown["sentiment"] = round(sentiment_score, 2)
    macd_hist  = last.get("MACDh_12_26_9", 0.0)
    macd_score = (
        max(-10.0, min(10.0, (macd_hist / 0.5) * 10.0))
        if not pd.isna(macd_hist) else 0.0
    )
    breakdown["macd"] = round(macd_score, 2)
    rsi = last.get("RSI_14", 50.0)
    if pd.isna(rsi): rsi = 50.0
    if   rsi < 30:  rsi_score =  8.0
    elif rsi < 40:  rsi_score =  5.0
    elif rsi <= 60: rsi_score =  2.0
    elif rsi <= 70: rsi_score = -3.0
    else:           rsi_score = -8.0
    breakdown["rsi"] = round(rsi_score, 2)
    price = last.get("Close", 0.0)
    vwap  = last.get("VWAP_D", price)
    if pd.isna(vwap) or vwap == 0:
        vwap = price
    vwap_pct   = (price - vwap) / vwap
    vwap_score = max(-10.0, min(10.0, (vwap_pct / 0.01) * 10.0))
    breakdown["vwap"] = round(vwap_score, 2)
    total = sentiment_score + macd_score + rsi_score + vwap_score
    breakdown["total"] = round(total, 2)
    return total, breakdown


# ---------------------------------------------------------------------------
# 10. ORDER FILL TRACKER
# ---------------------------------------------------------------------------
async def track_order_fill(
    ticker: str, order_id: str, qty: int,
    limit_price: float, sl_price: float, tp_price: float,
):
    deadline = time.monotonic() + ORDER_FILL_TIMEOUT_SECONDS
    dead_statuses = {
        OrderStatus.CANCELED, OrderStatus.EXPIRED,
        OrderStatus.REPLACED, OrderStatus.REJECTED,
        OrderStatus.DONE_FOR_DAY,
    }
    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(ORDER_POLL_SECONDS)
            try:
                order = await asyncio.to_thread(fetch_order_safe, order_id)
            except Exception as exc:
                log.error(f"[{ticker}] Poll failed: {exc}")
                continue
            status = order.status
            if status == OrderStatus.FILLED:
                filled_price = float(order.filled_avg_price or limit_price)
                _cb_state["trades_today"] += 1
                log.info(f"[{ticker}] FILLED at ${filled_price:.2f} | trades today: {_cb_state['trades_today']}")
                await send_alert(
                    f"ORDER FILLED: {qty}x {ticker} @ ${filled_price:.2f}\n"
                    f"SL: ${sl_price:.2f}  TP: ${tp_price:.2f}\n"
                    f"Trades today: {_cb_state['trades_today']} / {CIRCUIT_BREAKER_CONFIG['daily_max_trades']}"
                )
                return
            if status in dead_statuses:
                log.warning(f"[{ticker}] Order terminal status: {status}")
                await send_alert(f"ORDER {status.value.upper()}: {qty}x {ticker} - not filled.")
                return
        try:
            await asyncio.to_thread(cancel_order_safe, order_id)
            log.info(f"[{ticker}] Stale order cancelled after timeout.")
            await send_alert(f"ORDER TIMEOUT - CANCELLED: {qty}x {ticker} limit ${limit_price:.2f}")
        except Exception as exc:
            log.error(f"[{ticker}] Cancel failed: {exc}")
    except asyncio.CancelledError:
        try:
            await asyncio.to_thread(cancel_order_safe, order_id)
        except Exception:
            pass
        raise
    except Exception as exc:
        log.error(f"[{ticker}] Unexpected error in track_order_fill: {exc}")
    finally:
        _pending_orders.pop(ticker, None)


# ---------------------------------------------------------------------------
# 11. EXECUTION
# ---------------------------------------------------------------------------
async def maybe_execute(ticker: str, score: float, price: float, atr: float):
    if score < RISK_CONFIG["min_score_to_buy"]:
        return
    if ticker in _pending_orders and not _pending_orders[ticker].done():
        return
    account        = fetch_account_safe()
    current_equity = float(account.equity)
    _reset_circuit_breaker_if_new_day()
    if await check_circuit_breaker(current_equity):
        return
    open_positions = fetch_positions_safe()
    open_symbols   = {p.symbol for p in open_positions}
    if ticker in open_symbols:
        return
    if len(open_symbols) >= RISK_CONFIG["max_open_positions"]:
        return
    stop_distance       = max(atr * RISK_CONFIG["atr_stop_mult"], 0.01)
    risk_dollar_amount  = current_equity * RISK_CONFIG["account_risk_pct"]
    qty                 = max(1, math.floor(risk_dollar_amount / stop_distance))
    max_qty_by_notional = max(1, math.floor(RISK_CONFIG["max_position_notional"] / price))
    if qty > max_qty_by_notional:
        qty = max_qty_by_notional
    limit_price = round(price * (1 + RISK_CONFIG["limit_slippage_pct"]), 2)
    sl_price    = round(price - stop_distance,       2)
    tp_price    = round(price + (stop_distance * 2), 2)
    try:
        bracket_order = LimitOrderRequest(
            symbol=ticker, qty=qty, side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY, order_class=OrderClass.BRACKET,
            limit_price=limit_price,
            take_profit=TakeProfitRequest(limit_price=tp_price),
            stop_loss=StopLossRequest(stop_price=sl_price),
        )
        submitted = await asyncio.to_thread(trading_client.submit_order, bracket_order)
        order_id  = str(submitted.id)
        log.info(
            f"[{ticker}] Limit bracket submitted | qty={qty} "
            f"entry<=${limit_price:.2f} SL=${sl_price:.2f} TP=${tp_price:.2f}"
        )
        await send_alert(
            f"LIMIT ORDER SUBMITTED: {qty}x {ticker}\n"
            f"Entry <= ${limit_price:.2f} | SL: ${sl_price:.2f} TP: ${tp_price:.2f}"
        )
        task = asyncio.create_task(
            track_order_fill(ticker, order_id, qty, limit_price, sl_price, tp_price)
        )
        _pending_orders[ticker] = task
    except Exception as exc:
        log.error(f"[{ticker}] Order submission failed: {exc}")


# ---------------------------------------------------------------------------
# 12. WEBSOCKET BAR HANDLER
# ---------------------------------------------------------------------------
async def bar_handler(bar):
    global _last_bar_time
    if not is_market_open():
        return
    _last_bar_time = time.monotonic()
    ticker = bar.symbol
    _bar_buffers[ticker].append({
        "timestamp": bar.timestamp,
        "Open":   float(bar.open),  "High": float(bar.high),
        "Low":    float(bar.low),   "Close": float(bar.close),
        "Volume": float(bar.volume),
    })
    df = buffer_to_df(ticker)
    if df is None:
        return
    last = compute_indicators(df)
    if last is None:
        return
    sentiment        = await get_cached_sentiment(ticker)
    score, breakdown = compute_trade_score(last, sentiment)
    atr = last.get("ATRr_14", 1.0)
    if pd.isna(atr) or atr <= 0:
        atr = 1.0
    price = round(float(last["Close"]), 2)
    log.info(
        f"[{ticker}] close=${price:.2f}  score={score:.2f}  "
        f"rsi={breakdown.get('rsi', 0):.1f}  "
        f"macd={breakdown.get('macd', 0):.2f}  "
        f"vwap={breakdown.get('vwap', 0):.2f}  "
        f"sentiment={breakdown.get('sentiment', 0):.2f}"
    )
    await maybe_execute(ticker, score, price, atr)


# ---------------------------------------------------------------------------
# 13. STREAM RESTART
# ---------------------------------------------------------------------------
async def restart_stream():
    global stream_client, _stream_task, _last_bar_time
    log.warning("Restarting WebSocket stream...")
    if _stream_task and not _stream_task.done():
        _stream_task.cancel()
        try:
            await _stream_task
        except (asyncio.CancelledError, Exception):
            pass
    await bootstrap_buffers()
    stream_client = StockDataStream(API_KEY, SECRET_KEY, feed=DATA_FEED)
    stream_client.subscribe_bars(bar_handler, *WATCHLIST)
    _last_bar_time = time.monotonic()
    _stream_task   = asyncio.create_task(stream_client.run())
    log.info("Stream restarted.")
    await send_alert("Stream restarted - WebSocket reconnected.")


# ---------------------------------------------------------------------------
# 14. WATCHDOG
# ---------------------------------------------------------------------------
async def watchdog_loop():
    log.info(f"Watchdog armed - timeout: {WATCHDOG_TIMEOUT_SECONDS}s")
    while True:
        await asyncio.sleep(WATCHDOG_POLL_SECONDS)
        if not is_market_open():
            global _last_bar_time
            _last_bar_time = time.monotonic()
            continue
        silence = time.monotonic() - _last_bar_time
        if silence > WATCHDOG_TIMEOUT_SECONDS:
            msg = f"WATCHDOG TRIGGERED - No bars for {silence:.0f}s. Restarting stream..."
            log.critical(msg)
            await send_alert(msg)
            await restart_stream()
        else:
            log.debug(f"Watchdog OK - last bar {silence:.0f}s ago.")


# ---------------------------------------------------------------------------
# 15. MAIN
# ---------------------------------------------------------------------------
async def main_loop():
    global _stream_task, _last_bar_time
    log.info("=== Trading Bot v7 Starting (VPS) ===")
    await send_alert("Bot v7 booted - paper trading active.")
    _reset_circuit_breaker_if_new_day()
    await bootstrap_buffers()
    log.info("Pre-warming sentiment cache...")
    await asyncio.gather(*[get_cached_sentiment(t) for t in WATCHLIST])
    log.info("Sentiment cache ready.")
    stream_client.subscribe_bars(bar_handler, *WATCHLIST)
    log.info(f"Subscribed to live bars: {WATCHLIST}")
    _last_bar_time = time.monotonic()
    _stream_task   = asyncio.create_task(stream_client.run())
    await asyncio.gather(
        _stream_task,
        asyncio.create_task(watchdog_loop()),
    )


# ---------------------------------------------------------------------------
# ENTRY POINT — VPS / Linux (no nest_asyncio needed)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        log.info("Bot stopped by user.")
