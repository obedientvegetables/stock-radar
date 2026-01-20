#!/usr/bin/env python3
"""
Stock Radar - Flask Web Dashboard

Comprehensive dashboard for monitoring the stock radar trading system.
"""

from flask import Flask, render_template, jsonify, request
import sqlite3
from pathlib import Path
import json
from datetime import datetime, date, timedelta
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from utils.config import config
from collectors.market import get_current_price

app = Flask(__name__)

DB_PATH = Path(__file__).parent / "data" / "radar.db"
OUTPUT_PATH = Path(__file__).parent / "output"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def is_market_open():
    """Check if US stock market is currently open."""
    now = datetime.now()
    # Market hours: 9:30 AM - 4:00 PM ET, Mon-Fri
    # Simplified check (doesn't account for holidays)
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


# ============================================================================
# DASHBOARD ROUTES
# ============================================================================

@app.route("/")
def dashboard():
    """Serve the main dashboard."""
    return render_template("dashboard.html")


@app.route("/validation")
def validation():
    """Serve the old validation dashboard."""
    return render_template("index.html")


# ============================================================================
# API ENDPOINTS - HEALTH & STATUS
# ============================================================================

@app.route("/api/health")
def api_health():
    """Get system health status."""
    conn = get_db()
    cur = conn.cursor()

    # Get last collection timestamps
    cur.execute("""
        SELECT MAX(created_at) FROM insider_trades
    """)
    last_insider = cur.fetchone()[0]

    cur.execute("""
        SELECT MAX(date) FROM signals
    """)
    last_signal = cur.fetchone()[0]

    # Check for errors (placeholder - could check logs)
    errors = []

    conn.close()

    # Calculate next update time (8:30 AM ET next trading day)
    now = datetime.now()
    next_update = now.replace(hour=8, minute=30, second=0, microsecond=0)

    # If we're past 8:30 AM today, next update is tomorrow
    if now.hour >= 8 and now.minute >= 30:
        next_update += timedelta(days=1)

    # Skip weekends
    while next_update.weekday() >= 5:  # Saturday = 5, Sunday = 6
        next_update += timedelta(days=1)

    return jsonify({
        "status": "healthy" if not errors else "warning",
        "last_collection": last_insider,
        "last_signal_date": last_signal,
        "market_open": is_market_open(),
        "next_update": next_update.strftime("%I:%M %p"),
        "next_update_full": next_update.isoformat(),
        "errors": errors,
        "timestamp": datetime.now().isoformat()
    })


# ============================================================================
# API ENDPOINTS - SIGNALS
# ============================================================================

# Stock of the Day selection thresholds
STOCK_OF_DAY_MIN_SCORE = 25  # Minimum total score to qualify
STOCK_OF_DAY_STOP_PCT = 0.10  # 10% stop loss
STOCK_OF_DAY_TARGET_PCT = 0.20  # 20% target


@app.route("/api/stock-of-the-day")
def api_stock_of_the_day():
    """
    Get the Stock of the Day - a single high-confidence pick.

    Selection criteria:
    - Must have insider buying activity (insider_score > 0)
    - Must have total_score >= 25
    - Highest scoring signal that meets criteria

    Returns either a confident pick or "no pick today" state.
    """
    conn = get_db()
    cur = conn.cursor()

    today = date.today().isoformat()

    # Get the best candidate that meets our criteria
    # Priority: highest total score, must have insider activity, score >= 25
    cur.execute("""
        SELECT id, date, ticker, total_score, tier, action,
               insider_score, options_score, social_score,
               entry_price, stop_price, target_price,
               position_size, notes
        FROM signals
        WHERE date = ?
          AND insider_score > 0
          AND total_score >= ?
        ORDER BY total_score DESC
        LIMIT 1
    """, (today, STOCK_OF_DAY_MIN_SCORE))

    pick = cur.fetchone()

    # If no pick today, get the most recent day's best candidate
    if not pick:
        cur.execute("""
            SELECT id, date, ticker, total_score, tier, action,
                   insider_score, options_score, social_score,
                   entry_price, stop_price, target_price,
                   position_size, notes
            FROM signals
            WHERE insider_score > 0 AND total_score >= ?
            ORDER BY date DESC, total_score DESC
            LIMIT 1
        """, (STOCK_OF_DAY_MIN_SCORE,))
        pick = cur.fetchone()

    if pick:
        pick = dict(pick)
        ticker = pick['ticker']

        # Get fresh price and calculate Entry/Stop/Target
        current_price = get_current_price(ticker)
        if current_price:
            pick['entry_price'] = round(current_price, 2)
            pick['stop_price'] = round(current_price * (1 - STOCK_OF_DAY_STOP_PCT), 2)
            pick['target_price'] = round(current_price * (1 + STOCK_OF_DAY_TARGET_PCT), 2)

        # Determine confidence level
        if pick['total_score'] >= 45 and pick['insider_score'] >= 15:
            pick['confidence'] = 'High'
        else:
            pick['confidence'] = 'Medium'

        # Generate explanation
        explanations = []
        if pick['insider_score'] >= 15:
            explanations.append("Strong insider buying")
        elif pick['insider_score'] > 0:
            explanations.append("Insider buying detected")
        if pick['options_score'] >= 15:
            explanations.append("bullish options flow")
        if pick['social_score'] >= 10:
            explanations.append("social confirmation")

        pick['explanation'] = " + ".join(explanations) if explanations else pick.get('notes', '')
        pick['has_pick'] = True

        conn.close()
        return jsonify(pick)

    # No qualified pick - find best candidate and show what's missing
    cur.execute("""
        SELECT id, date, ticker, total_score, tier, action,
               insider_score, options_score, social_score, notes
        FROM signals
        WHERE date = ?
        ORDER BY total_score DESC
        LIMIT 1
    """, (today,))

    best_candidate = cur.fetchone()

    # If no signals today at all, try recent
    if not best_candidate:
        cur.execute("""
            SELECT id, date, ticker, total_score, tier, action,
                   insider_score, options_score, social_score, notes
            FROM signals
            ORDER BY date DESC, total_score DESC
            LIMIT 1
        """)
        best_candidate = cur.fetchone()

    conn.close()

    if best_candidate:
        best_candidate = dict(best_candidate)

        # Determine what's missing
        missing = []
        if best_candidate['insider_score'] == 0:
            missing.append("needs insider activity")
        if best_candidate['total_score'] < STOCK_OF_DAY_MIN_SCORE:
            missing.append(f"score below {STOCK_OF_DAY_MIN_SCORE}")
        if best_candidate['social_score'] == 0:
            missing.append("needs social confirmation")

        return jsonify({
            "has_pick": False,
            "best_candidate": best_candidate,
            "missing": " — ".join(missing) if missing else "Below threshold"
        })

    return jsonify({
        "has_pick": False,
        "best_candidate": None,
        "missing": "No signals detected"
    })


@app.route("/api/signals/today")
def api_signals_today():
    """Get today's trading signals (for watchlist, excludes Stock of the Day)."""
    conn = get_db()
    cur = conn.cursor()

    # Get today's date (or most recent signal date)
    today = date.today().isoformat()

    # Get all signals with some activity (score > 15 to exclude pure noise)
    cur.execute("""
        SELECT id, date, ticker, total_score, tier, action,
               insider_score, options_score, social_score, technical_score,
               entry_price, stop_price, target_price,
               position_size, market_regime, notes
        FROM signals
        WHERE date = ? AND total_score > 15
        ORDER BY total_score DESC
    """, (today,))

    signals = [dict(row) for row in cur.fetchall()]

    # If no signals today, get the most recent
    if not signals:
        cur.execute("""
            SELECT id, date, ticker, total_score, tier, action,
                   insider_score, options_score, social_score, technical_score,
                   entry_price, stop_price, target_price,
                   position_size, market_regime, notes
            FROM signals
            WHERE total_score > 15
            ORDER BY date DESC, total_score DESC
            LIMIT 10
        """)
        signals = [dict(row) for row in cur.fetchall()]

    conn.close()
    return jsonify({"signals": signals, "date": today, "threshold": STOCK_OF_DAY_MIN_SCORE})


# ============================================================================
# API ENDPOINTS - POSITIONS
# ============================================================================

@app.route("/api/positions")
def api_positions():
    """Get open positions with live prices."""
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
    total_value = config.PAPER_PORTFOLIO_SIZE
    total_cost = 0
    total_current = 0

    for row in cur.fetchall():
        pos = dict(row)
        ticker = pos['ticker']

        # Get current price
        current_price = get_current_price(ticker)
        if current_price is None:
            current_price = pos['entry_price']  # Fallback to entry

        pos['current_price'] = current_price

        # Calculate P&L
        cost = pos['entry_price'] * pos['shares']
        current = current_price * pos['shares']
        pos['unrealized_pnl'] = round(current - cost, 2)
        pos['unrealized_pnl_pct'] = round((current / cost - 1) * 100, 2) if cost > 0 else 0

        # Days held
        entry_date = datetime.strptime(pos['entry_date'], '%Y-%m-%d').date()
        pos['days_held'] = (date.today() - entry_date).days

        # Progress to target (as percentage of distance from entry to target)
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

    # Calculate portfolio totals
    cash = total_value - total_cost
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


# ============================================================================
# API ENDPOINTS - PERFORMANCE
# ============================================================================

@app.route("/api/performance")
def api_performance():
    """Get performance summary statistics."""
    conn = get_db()
    cur = conn.cursor()

    # Get closed trades stats
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

    # Get performance by score tier
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

    # Build equity curve from closed trades
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

    # Get SPY comparison (simplified - just use 0 baseline)
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


# ============================================================================
# API ENDPOINTS - RECENT TRADES
# ============================================================================

@app.route("/api/trades/recent")
def api_trades_recent():
    """Get recent closed trades."""
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


# ============================================================================
# API ENDPOINTS - INSIDER ACTIVITY
# ============================================================================

@app.route("/api/insider/recent")
def api_insider_recent():
    """Get recent insider buys detected."""
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


# ============================================================================
# API ENDPOINTS - TRADE ENTRY/EXIT
# ============================================================================

@app.route("/api/trade/enter", methods=["POST"])
def api_trade_enter():
    """Enter a new paper trade."""
    data = request.get_json()

    ticker = data.get('ticker', '').upper().strip()
    price = data.get('price')
    size = data.get('size', 'QUARTER')
    signal_id = data.get('signal_id')

    if not ticker:
        return jsonify({"success": False, "error": "Ticker is required"})

    # Get current price if not provided
    if not price:
        price = get_current_price(ticker)
        if not price:
            return jsonify({"success": False, "error": f"Could not get price for {ticker}"})

    # Calculate position size
    portfolio_size = config.PAPER_PORTFOLIO_SIZE
    position_pct = {
        'FULL': config.MAX_POSITION_PCT,
        'HALF': config.MAX_POSITION_PCT / 2,
        'QUARTER': config.MAX_POSITION_PCT / 4
    }.get(size, config.MAX_POSITION_PCT / 4)

    position_value = portfolio_size * position_pct
    shares = int(position_value / price)

    if shares < 1:
        return jsonify({"success": False, "error": "Position size too small"})

    # Calculate stop and target
    stop_price = round(price * (1 - config.DEFAULT_STOP_PCT), 2)
    target_price = round(price * (1 + config.DEFAULT_TARGET_PCT), 2)

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
    """Exit an existing paper trade."""
    data = request.get_json()

    trade_id = data.get('trade_id')
    price = data.get('price')
    reason = data.get('reason', 'MANUAL')

    if not trade_id:
        return jsonify({"success": False, "error": "Trade ID is required"})

    conn = get_db()
    cur = conn.cursor()

    # Get the trade
    cur.execute("""
        SELECT id, ticker, entry_price, shares, status
        FROM trades
        WHERE id = ?
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

    # Get exit price if not provided
    if not price:
        price = get_current_price(ticker)
        if not price:
            conn.close()
            return jsonify({"success": False, "error": f"Could not get price for {ticker}"})

    # Calculate returns
    return_pct = round((price / entry_price - 1) * 100, 2)
    return_dollars = round((price - entry_price) * shares, 2)

    # Get entry date for days held
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


# ============================================================================
# LEGACY API ENDPOINTS (kept for validation dashboard)
# ============================================================================

@app.route("/api/stats")
def api_stats():
    """Get overall database statistics."""
    conn = get_db()
    cur = conn.cursor()

    stats = {}

    # Insider trades
    cur.execute("SELECT COUNT(*) FROM insider_trades")
    stats["insider_trades"] = cur.fetchone()[0]

    # Validation events
    cur.execute("SELECT COUNT(*) FROM validation_insider")
    stats["validation_events"] = cur.fetchone()[0]

    # Signals
    cur.execute("SELECT COUNT(*) FROM signals")
    stats["signals"] = cur.fetchone()[0]

    # Date range
    cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM insider_trades")
    row = cur.fetchone()
    stats["date_range"] = {"min": row[0], "max": row[1]}

    conn.close()
    return jsonify(stats)


@app.route("/api/recent-trades")
def api_recent_insider_trades():
    """Get recent insider trades (legacy endpoint)."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT ticker, insider_name, insider_title, trade_type,
               shares, price_per_share, total_value, trade_date, filed_date
        FROM insider_trades
        ORDER BY filed_date DESC, trade_date DESC
        LIMIT 50
    """)

    trades = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify(trades)


@app.route("/api/validation-results")
def api_validation_results():
    """Get validation analysis results."""
    # Find most recent validation results file
    result_files = sorted(OUTPUT_PATH.glob("validation_results_*.json"), reverse=True)

    if not result_files:
        return jsonify({"error": "No validation results found"})

    with open(result_files[0]) as f:
        results = json.load(f)

    return jsonify(results)


@app.route("/api/top-signals")
def api_top_signals():
    """Get top insider buying signals by excess return."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT ticker, signal_date, insider_type, buy_value,
               return_5d, spy_return_5d, excess_5d,
               return_10d, spy_return_10d, excess_10d
        FROM validation_insider
        WHERE excess_5d IS NOT NULL
        ORDER BY excess_5d DESC
        LIMIT 30
    """)

    signals = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify(signals)


@app.route("/api/worst-signals")
def api_worst_signals():
    """Get worst insider buying signals by excess return."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT ticker, signal_date, insider_type, buy_value,
               return_5d, spy_return_5d, excess_5d,
               return_10d, spy_return_10d, excess_10d
        FROM validation_insider
        WHERE excess_5d IS NOT NULL
        ORDER BY excess_5d ASC
        LIMIT 30
    """)

    signals = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify(signals)


@app.route("/api/by-insider-type")
def api_by_insider_type():
    """Get performance breakdown by insider type."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT insider_type,
               COUNT(*) as count,
               AVG(excess_5d) as avg_excess_5d,
               AVG(excess_10d) as avg_excess_10d,
               SUM(CASE WHEN excess_5d > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate_5d
        FROM validation_insider
        WHERE excess_5d IS NOT NULL
        GROUP BY insider_type
        ORDER BY avg_excess_5d DESC
    """)

    data = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify(data)


@app.route("/api/by-buy-size")
def api_by_buy_size():
    """Get performance breakdown by buy size."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            CASE
                WHEN buy_value < 100000 THEN '<$100k'
                WHEN buy_value < 500000 THEN '$100k-$500k'
                WHEN buy_value < 1000000 THEN '$500k-$1M'
                ELSE '>$1M'
            END as size_bucket,
            COUNT(*) as count,
            AVG(excess_5d) as avg_excess_5d,
            AVG(excess_10d) as avg_excess_10d,
            SUM(CASE WHEN excess_5d > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate_5d
        FROM validation_insider
        WHERE excess_5d IS NOT NULL AND buy_value > 0
        GROUP BY size_bucket
        ORDER BY MIN(buy_value)
    """)

    data = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify(data)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, port=port, host="0.0.0.0")
