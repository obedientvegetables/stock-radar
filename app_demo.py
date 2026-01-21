#!/usr/bin/env python3
"""
Stock Radar - Demo Dashboard (no yfinance dependency)
Run this to preview the dashboard locally.
"""

from flask import Flask, render_template, jsonify, request
import sqlite3
from pathlib import Path
import json
from datetime import datetime, date, timedelta
import random

app = Flask(__name__)

DB_PATH = Path(__file__).parent / "data" / "radar.db"

# Config values
PAPER_PORTFOLIO_SIZE = 10000
DEFAULT_STOP_PCT = 0.10
DEFAULT_TARGET_PCT = 0.20
MAX_POSITION_PCT = 0.10
STOCK_OF_DAY_MIN_SCORE = 25


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_current_price(ticker):
    """Mock price function - returns a random price for demo."""
    # Return a plausible price based on ticker
    base_prices = {
        'AAPL': 185, 'MSFT': 420, 'GOOGL': 175, 'AMZN': 185,
        'NVDA': 880, 'META': 520, 'TSLA': 175, 'AMD': 165,
    }
    base = base_prices.get(ticker, 50 + hash(ticker) % 200)
    # Add small random variation
    return round(base * (1 + (random.random() - 0.5) * 0.02), 2)


def is_market_open():
    """Check if US stock market is currently open."""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def get_next_update_time():
    """Calculate the next scheduled update time."""
    now = datetime.now()
    today_830 = now.replace(hour=8, minute=30, second=0, microsecond=0)
    if now < today_830 and now.weekday() < 5:
        return today_830
    next_day = now + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day.replace(hour=8, minute=30, second=0, microsecond=0)


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/health")
def api_health():
    next_update = get_next_update_time()
    return jsonify({
        "status": "healthy",
        "last_collection": datetime.now().isoformat(),
        "last_signal_date": date.today().isoformat(),
        "market_open": is_market_open(),
        "next_update": next_update.strftime("%I:%M %p"),
        "next_update_iso": next_update.isoformat(),
        "errors": [],
        "timestamp": datetime.now().isoformat()
    })


@app.route("/api/stock-of-day")
def api_stock_of_day():
    conn = get_db()
    cur = conn.cursor()
    today = date.today().isoformat()

    cur.execute("""
        SELECT id, date, ticker, total_score, tier, action,
               insider_score, options_score, social_score, technical_score,
               entry_price, stop_price, target_price,
               position_size, market_regime, notes
        FROM signals
        WHERE action IN ('TRADE', 'WATCH')
        ORDER BY date DESC, total_score DESC
        LIMIT 20
    """)
    signals = [dict(row) for row in cur.fetchall()]
    conn.close()

    stock_of_day = None
    best_candidate = None
    missing_criteria = []

    for s in signals:
        has_insider = (s.get('insider_score') or 0) > 0
        meets_threshold = (s.get('total_score') or 0) >= STOCK_OF_DAY_MIN_SCORE

        if best_candidate is None or s['total_score'] > best_candidate['total_score']:
            best_candidate = s
            missing_criteria = []
            if not has_insider:
                missing_criteria.append("needs insider activity")
            if not meets_threshold:
                missing_criteria.append(f"score below {STOCK_OF_DAY_MIN_SCORE}")

        if has_insider and meets_threshold:
            if stock_of_day is None or s['total_score'] > stock_of_day['total_score']:
                stock_of_day = s

    result = {
        "date": today,
        "min_score_threshold": STOCK_OF_DAY_MIN_SCORE,
        "has_pick": stock_of_day is not None
    }

    if stock_of_day:
        current_price = get_current_price(stock_of_day['ticker'])
        entry_price = current_price or stock_of_day.get('entry_price') or 100
        stop_price = round(entry_price * (1 - DEFAULT_STOP_PCT), 2)
        target_price = round(entry_price * (1 + DEFAULT_TARGET_PCT), 2)

        total = stock_of_day.get('total_score') or 0
        confidence = "High" if total >= 45 else "Medium"

        explanation_parts = []
        insider_score = stock_of_day.get('insider_score') or 0
        options_score = stock_of_day.get('options_score') or 0
        social_score = stock_of_day.get('social_score') or 0

        if insider_score >= 12:
            explanation_parts.append("CEO/CFO purchase")
        elif insider_score >= 6:
            explanation_parts.append("C-Suite buying")
        elif insider_score > 0:
            explanation_parts.append("Insider buying")

        if options_score >= 12:
            explanation_parts.append("strong options flow")
        elif options_score >= 8:
            explanation_parts.append("bullish options activity")

        if social_score >= 10:
            explanation_parts.append("social momentum")

        explanation = " + ".join(explanation_parts) if explanation_parts else "Multiple signals aligned"

        result["pick"] = {
            "id": stock_of_day['id'],
            "ticker": stock_of_day['ticker'],
            "total_score": stock_of_day['total_score'],
            "insider_score": insider_score,
            "options_score": options_score,
            "social_score": social_score,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "confidence": confidence,
            "explanation": explanation,
            "position_size": stock_of_day.get('position_size') or 'QUARTER'
        }
    else:
        if best_candidate:
            result["best_candidate"] = {
                "ticker": best_candidate['ticker'],
                "total_score": best_candidate['total_score'],
                "missing": missing_criteria[0] if missing_criteria else "below threshold"
            }

    return jsonify(result)


@app.route("/api/watchlist")
def api_watchlist():
    conn = get_db()
    cur = conn.cursor()
    today = date.today().isoformat()

    cur.execute("""
        SELECT id, date, ticker, total_score, tier, action,
               insider_score, options_score, social_score, technical_score,
               entry_price, stop_price, target_price,
               position_size, market_regime, notes
        FROM signals
        WHERE action IN ('TRADE', 'WATCH')
        ORDER BY date DESC, total_score DESC
        LIMIT 20
    """)
    signals = [dict(row) for row in cur.fetchall()]
    conn.close()

    # Find stock of day to exclude
    stock_of_day_ticker = None
    for s in signals:
        has_insider = (s.get('insider_score') or 0) > 0
        meets_threshold = (s.get('total_score') or 0) >= STOCK_OF_DAY_MIN_SCORE
        if has_insider and meets_threshold:
            stock_of_day_ticker = s['ticker']
            break

    watchlist = []
    for s in signals:
        if s['ticker'] == stock_of_day_ticker:
            continue
        insider = s.get('insider_score') or 0
        social = s.get('social_score') or 0
        total = s.get('total_score') or 0
        if insider == 0 and social == 0 and total <= 15:
            continue
        watchlist.append(s)

    return jsonify({
        "watchlist": watchlist,
        "date": today,
        "stock_of_day_threshold": STOCK_OF_DAY_MIN_SCORE
    })


@app.route("/api/signals/today")
def api_signals_today():
    conn = get_db()
    cur = conn.cursor()
    today = date.today().isoformat()

    cur.execute("""
        SELECT id, date, ticker, total_score, tier, action,
               insider_score, options_score, social_score, technical_score,
               entry_price, stop_price, target_price,
               position_size, market_regime, notes
        FROM signals
        WHERE action IN ('TRADE', 'WATCH')
        ORDER BY date DESC, total_score DESC
        LIMIT 10
    """)
    signals = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify({"signals": signals, "date": today})


@app.route("/api/positions")
def api_positions():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, ticker, entry_date, entry_price, shares,
               stop_price, target_price, notes
        FROM trades
        WHERE status = 'OPEN'
        ORDER BY entry_date DESC
    """)

    positions = []
    total_cost = 0
    total_current = 0

    for row in cur.fetchall():
        pos = dict(row)
        ticker = pos['ticker']
        current_price = get_current_price(ticker)
        if current_price is None:
            current_price = pos['entry_price']

        pos['current_price'] = current_price
        cost = pos['entry_price'] * pos['shares']
        current = current_price * pos['shares']
        pos['unrealized_pnl'] = round(current - cost, 2)
        pos['unrealized_pnl_pct'] = round((current / cost - 1) * 100, 2) if cost > 0 else 0

        entry_date = datetime.strptime(pos['entry_date'], '%Y-%m-%d').date()
        pos['days_held'] = (date.today() - entry_date).days

        if pos['target_price'] and pos['entry_price']:
            target_distance = pos['target_price'] - pos['entry_price']
            if target_distance != 0:
                current_distance = current_price - pos['entry_price']
                pos['target_progress'] = round((current_distance / target_distance) * 100, 1)
            else:
                pos['target_progress'] = 0
        else:
            pos['target_progress'] = 0

        positions.append(pos)
        total_cost += cost
        total_current += current

    conn.close()

    cash = PAPER_PORTFOLIO_SIZE - total_cost
    portfolio_value = cash + total_current
    total_unrealized_pnl = total_current - total_cost
    total_unrealized_pnl_pct = (total_current / total_cost - 1) * 100 if total_cost > 0 else 0

    return jsonify({
        "positions": positions,
        "portfolio_value": round(portfolio_value, 2),
        "cash": round(cash, 2),
        "total_invested": round(total_cost, 2),
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_unrealized_pnl_pct": round(total_unrealized_pnl_pct, 2)
    })


@app.route("/api/performance")
def api_performance():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) as winners,
            AVG(CASE WHEN return_pct > 0 THEN return_pct END) as avg_win,
            AVG(CASE WHEN return_pct <= 0 THEN return_pct END) as avg_loss,
            AVG(return_pct) as avg_return,
            SUM(return_dollars) as total_pnl
        FROM trades
        WHERE status = 'CLOSED'
    """)

    row = cur.fetchone()
    total_trades = row['total_trades'] or 0
    winners = row['winners'] or 0
    win_rate = (winners / total_trades * 100) if total_trades > 0 else None

    cur.execute("""
        SELECT
            CASE
                WHEN s.total_score >= 60 THEN '60+'
                WHEN s.total_score >= 45 THEN '45-59'
                WHEN s.total_score >= 30 THEN '30-44'
                ELSE '<30'
            END as tier,
            COUNT(*) as count,
            AVG(t.return_pct) as avg_return,
            SUM(CASE WHEN t.return_pct > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate
        FROM trades t
        LEFT JOIN signals s ON t.signal_id = s.id
        WHERE t.status = 'CLOSED'
        GROUP BY tier
        ORDER BY MIN(s.total_score) DESC
    """)
    by_score_tier = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT exit_date, return_pct, return_dollars
        FROM trades
        WHERE status = 'CLOSED'
        ORDER BY exit_date
    """)

    equity_curve = []
    cumulative_return = 0
    for trade in cur.fetchall():
        cumulative_return += trade['return_pct'] or 0
        equity_curve.append({
            "date": trade['exit_date'],
            "value": round(cumulative_return, 2)
        })

    spy_curve = [{"date": p["date"], "value": 0} for p in equity_curve]
    conn.close()

    return jsonify({
        "total_trades": total_trades,
        "winners": winners,
        "win_rate": win_rate,
        "avg_win": row['avg_win'],
        "avg_loss": row['avg_loss'],
        "avg_return": row['avg_return'],
        "total_pnl": row['total_pnl'],
        "by_score_tier": by_score_tier,
        "equity_curve": equity_curve,
        "spy_curve": spy_curve
    })


@app.route("/api/trades/recent")
def api_trades_recent():
    limit = request.args.get('limit', 10, type=int)
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT ticker, entry_date, entry_price, exit_date, exit_price,
               return_pct, return_dollars, days_held, exit_reason
        FROM trades
        WHERE status = 'CLOSED'
        ORDER BY exit_date DESC
        LIMIT ?
    """, (limit,))

    trades = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify({"trades": trades})


@app.route("/api/insider/recent")
def api_insider_recent():
    limit = request.args.get('limit', 5, type=int)
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT ticker, insider_name, insider_title, total_value, trade_date
        FROM insider_trades
        WHERE trade_type = 'P'
        ORDER BY filed_date DESC, trade_date DESC
        LIMIT ?
    """, (limit,))

    insider_buys = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify({"insider_buys": insider_buys})


@app.route("/api/trade/enter", methods=["POST"])
def api_trade_enter():
    data = request.get_json()
    ticker = data.get('ticker', '').upper().strip()
    price = data.get('price')
    size = data.get('size', 'QUARTER')
    signal_id = data.get('signal_id')

    if not ticker:
        return jsonify({"success": False, "error": "Ticker is required"})

    if not price:
        price = get_current_price(ticker)
        if not price:
            return jsonify({"success": False, "error": f"Could not get price for {ticker}"})

    position_pct = {
        'FULL': MAX_POSITION_PCT,
        'HALF': MAX_POSITION_PCT / 2,
        'QUARTER': MAX_POSITION_PCT / 4
    }.get(size, MAX_POSITION_PCT / 4)

    position_value = PAPER_PORTFOLIO_SIZE * position_pct
    shares = int(position_value / price)

    if shares < 1:
        return jsonify({"success": False, "error": "Position size too small"})

    stop_price = round(price * (1 - DEFAULT_STOP_PCT), 2)
    target_price = round(price * (1 + DEFAULT_TARGET_PCT), 2)

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO trades (signal_id, ticker, entry_date, entry_price, shares,
                              stop_price, target_price, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """, (signal_id, ticker, date.today().isoformat(), price, shares,
              stop_price, target_price))

        conn.commit()
        trade_id = cur.lastrowid
        conn.close()

        return jsonify({
            "success": True,
            "trade_id": trade_id,
            "ticker": ticker,
            "entry_price": price,
            "shares": shares,
            "stop_price": stop_price,
            "target_price": target_price
        })
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/trade/exit", methods=["POST"])
def api_trade_exit():
    data = request.get_json()
    trade_id = data.get('trade_id')
    price = data.get('price')
    reason = data.get('reason', 'MANUAL')

    if not trade_id:
        return jsonify({"success": False, "error": "Trade ID is required"})

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, ticker, entry_price, shares, status
        FROM trades WHERE id = ?
    """, (trade_id,))

    trade = cur.fetchone()
    if not trade:
        conn.close()
        return jsonify({"success": False, "error": "Trade not found"})

    if trade['status'] != 'OPEN':
        conn.close()
        return jsonify({"success": False, "error": "Trade is not open"})

    ticker = trade['ticker']
    entry_price = trade['entry_price']
    shares = trade['shares']

    if not price:
        price = get_current_price(ticker)
        if not price:
            conn.close()
            return jsonify({"success": False, "error": f"Could not get price for {ticker}"})

    return_pct = round((price / entry_price - 1) * 100, 2)
    return_dollars = round((price - entry_price) * shares, 2)

    cur.execute("SELECT entry_date FROM trades WHERE id = ?", (trade_id,))
    entry_date = datetime.strptime(cur.fetchone()['entry_date'], '%Y-%m-%d').date()
    days_held = (date.today() - entry_date).days

    try:
        cur.execute("""
            UPDATE trades
            SET exit_date = ?, exit_price = ?, exit_reason = ?,
                return_pct = ?, return_dollars = ?, days_held = ?,
                status = 'CLOSED'
            WHERE id = ?
        """, (date.today().isoformat(), price, reason,
              return_pct, return_dollars, days_held, trade_id))

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "trade_id": trade_id,
            "ticker": ticker,
            "exit_price": price,
            "return_pct": return_pct,
            "return_dollars": return_dollars,
            "days_held": days_held
        })
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    print(f"\n  Dashboard available at: http://localhost:{port}\n")
    app.run(debug=True, port=port, host="0.0.0.0")
