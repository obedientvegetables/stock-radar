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


@app.route("/v2")
def dashboard_v2():
    """Serve the V2 momentum trading dashboard."""
    return render_template("dashboard_v2.html")


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

    return jsonify({
        "status": "healthy" if not errors else "warning",
        "last_collection": last_insider,
        "last_signal_date": last_signal,
        "market_open": is_market_open(),
        "errors": errors,
        "timestamp": datetime.now().isoformat()
    })


# ============================================================================
# API ENDPOINTS - SIGNALS
# ============================================================================

@app.route("/api/signals/today")
def api_signals_today():
    """Get today's trading signals."""
    conn = get_db()
    cur = conn.cursor()

    # Get today's date (or most recent signal date)
    today = date.today().isoformat()

    cur.execute("""
        SELECT id, date, ticker, total_score, tier, action,
               insider_score, options_score, social_score, technical_score,
               entry_price, stop_price, target_price,
               position_size, market_regime, notes
        FROM signals
        WHERE date = ? AND action IN ('TRADE', 'WATCH')
        ORDER BY
            CASE action WHEN 'TRADE' THEN 1 WHEN 'WATCH' THEN 2 END,
            total_score DESC
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
            WHERE action IN ('TRADE', 'WATCH')
            ORDER BY date DESC, total_score DESC
            LIMIT 10
        """)
        signals = [dict(row) for row in cur.fetchall()]

    conn.close()
    return jsonify({"signals": signals, "date": today})


@app.route("/api/stock-of-day")
def api_stock_of_day():
    """Get the Stock of the Day - highest confidence pick."""
    conn = get_db()
    cur = conn.cursor()

    # Get today's date (or most recent signal date)
    today = date.today().isoformat()

    # Find the best candidate: highest score where insider_score > 0 AND total_score >= threshold
    cur.execute("""
        SELECT id, date, ticker, total_score, tier, action,
               insider_score, options_score, social_score, technical_score,
               entry_price, stop_price, target_price,
               position_size, market_regime, notes
        FROM signals
        WHERE date = ? AND insider_score > 0 AND total_score >= ?
        ORDER BY total_score DESC
        LIMIT 1
    """, (today, config.STOCK_OF_DAY_MIN_SCORE))

    pick = cur.fetchone()

    # If no pick today, check most recent date
    if not pick:
        cur.execute("""
            SELECT id, date, ticker, total_score, tier, action,
                   insider_score, options_score, social_score, technical_score,
                   entry_price, stop_price, target_price,
                   position_size, market_regime, notes
            FROM signals
            WHERE insider_score > 0 AND total_score >= ?
            ORDER BY date DESC, total_score DESC
            LIMIT 1
        """, (config.STOCK_OF_DAY_MIN_SCORE,))
        pick = cur.fetchone()

    if not pick:
        # No qualifying pick - find best candidate to show what's missing
        cur.execute("""
            SELECT ticker, total_score, insider_score, options_score, social_score
            FROM signals
            WHERE date = ?
            ORDER BY total_score DESC
            LIMIT 1
        """, (today,))
        best_candidate = cur.fetchone()
        conn.close()

        if best_candidate:
            missing = []
            if not best_candidate['insider_score'] or best_candidate['insider_score'] == 0:
                missing.append("Insider activity")
            if not best_candidate['social_score'] or best_candidate['social_score'] == 0:
                missing.append("Social confirmation")
            if best_candidate['total_score'] < config.STOCK_OF_DAY_MIN_SCORE:
                missing.append(f"Score below {config.STOCK_OF_DAY_MIN_SCORE}")

            return jsonify({
                "has_pick": False,
                "best_candidate": {
                    "ticker": best_candidate['ticker'],
                    "score": best_candidate['total_score']
                },
                "missing": ", ".join(missing) if missing else "Unknown"
            })
        else:
            return jsonify({"has_pick": False, "best_candidate": None, "missing": "No signals today"})

    # We have a pick - get current price
    pick_dict = dict(pick)
    ticker = pick_dict['ticker']

    current_price = get_current_price(ticker)
    if current_price is None:
        current_price = pick_dict['entry_price'] or 0

    # Calculate entry, stop, target based on current price
    entry = round(current_price, 2)
    stop = round(entry * (1 - config.DEFAULT_STOP_PCT), 2)
    target = round(entry * (1 + config.DEFAULT_TARGET_PCT), 2)

    # Determine confidence level
    score = pick_dict['total_score']
    if score >= 50:
        confidence = "VERY HIGH"
    elif score >= 40:
        confidence = "HIGH"
    elif score >= 30:
        confidence = "MODERATE"
    else:
        confidence = "LOW"

    # Build summary from available signals
    summary_parts = []
    if pick_dict['insider_score'] and pick_dict['insider_score'] > 15:
        summary_parts.append("Insider buying")
    if pick_dict['options_score'] and pick_dict['options_score'] > 10:
        summary_parts.append("bullish options flow")
    if pick_dict['social_score'] and pick_dict['social_score'] > 5:
        summary_parts.append("social momentum")

    summary = " + ".join(summary_parts) if summary_parts else pick_dict.get('notes', '')

    conn.close()

    return jsonify({
        "has_pick": True,
        "ticker": ticker,
        "entry": entry,
        "stop": stop,
        "target": target,
        "score": score,
        "confidence": confidence,
        "summary": summary,
        "insider_score": pick_dict['insider_score'],
        "options_score": pick_dict['options_score'],
        "social_score": pick_dict['social_score'],
        "signal_id": pick_dict['id'],
        "date": pick_dict['date']
    })


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


# ============================================================================
# V2 API ENDPOINTS: Momentum Trading System
# ============================================================================

@app.route("/api/v2/portfolio")
def api_v2_portfolio():
    """Get V2 paper trading portfolio status."""
    from utils.paper_trading import PaperTradingEngine
    
    engine = PaperTradingEngine()
    status = engine.get_portfolio_status()
    
    return jsonify({
        "cash": status.cash,
        "positions_value": status.positions_value,
        "total_value": status.total_value,
        "total_pnl": status.total_pnl,
        "total_pnl_pct": status.total_pnl_pct,
        "positions": [
            {
                "id": p.id,
                "ticker": p.ticker,
                "shares": p.shares,
                "entry_date": p.entry_date.isoformat(),
                "entry_price": p.entry_price,
                "stop": p.current_stop,
                "target": p.target_price,
            }
            for p in status.open_positions
        ]
    })


@app.route("/api/v2/watchlist")
def api_v2_watchlist():
    """Get V2 watchlist - stocks passing trend template."""
    from signals.trend_template import get_compliant_stocks
    from datetime import date
    
    stocks = get_compliant_stocks(date.today())
    
    return jsonify({
        "date": date.today().isoformat(),
        "count": len(stocks),
        "stocks": stocks[:50],  # Limit response size
    })


@app.route("/api/v2/screening")
def api_v2_screening():
    """Get today's V2 screening results."""
    from datetime import date
    
    conn = get_db()
    cur = conn.cursor()
    
    today = date.today().isoformat()
    
    cur.execute("""
        SELECT t.*, f.fundamental_score, v.pattern_score, v.pivot_price
        FROM trend_template t
        LEFT JOIN fundamentals f ON t.ticker = f.ticker AND f.date = ?
        LEFT JOIN vcp_patterns v ON t.ticker = v.ticker AND v.date = ?
        WHERE t.date = ? AND t.template_compliant = 1
        ORDER BY t.rs_rating DESC NULLS LAST
        LIMIT 50
    """, (today, today, today))
    
    results = [dict(row) for row in cur.fetchall()]
    conn.close()
    
    return jsonify({
        "date": today,
        "count": len(results),
        "results": results,
    })


@app.route("/api/v2/performance")
def api_v2_performance():
    """Get V2 paper trading performance stats."""
    from utils.paper_trading import PaperTradingEngine
    
    engine = PaperTradingEngine()
    stats = engine.get_performance_stats()
    
    return jsonify(stats)


@app.route("/api/v2/trades")
def api_v2_trades():
    """Get V2 trade history."""
    from utils.paper_trading import PaperTradingEngine
    
    limit = request.args.get('limit', 50, type=int)
    
    engine = PaperTradingEngine()
    trades = engine.get_trade_history(days=limit)
    
    return jsonify({
        "count": len(trades),
        "trades": trades,
    })


@app.route("/api/v2/alerts")
def api_v2_alerts():
    """Get recent V2 alerts."""
    from output.alerts import get_recent_alerts
    
    limit = request.args.get('limit', 20, type=int)
    alert_type = request.args.get('type', None)
    
    alerts = get_recent_alerts(limit=limit, alert_type=alert_type)
    
    return jsonify({
        "count": len(alerts),
        "alerts": alerts,
    })


@app.route("/api/v2/enter-trade", methods=["POST"])
def api_v2_enter_trade():
    """Enter a new V2 paper trade."""
    from utils.paper_trading import PaperTradingEngine
    
    data = request.get_json()
    
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400
    
    required = ['ticker', 'price', 'shares', 'stop', 'target']
    for field in required:
        if field not in data:
            return jsonify({"success": False, "error": f"Missing field: {field}"}), 400
    
    engine = PaperTradingEngine()
    
    try:
        trade_id = engine.enter_trade(
            ticker=data['ticker'].upper(),
            entry_price=float(data['price']),
            shares=int(data['shares']),
            stop_price=float(data['stop']),
            target_price=float(data['target']),
            notes=data.get('notes', '')
        )
        
        return jsonify({"success": True, "trade_id": trade_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/v2/exit-trade", methods=["POST"])
def api_v2_exit_trade():
    """Exit a V2 paper trade."""
    from utils.paper_trading import PaperTradingEngine
    
    data = request.get_json()
    
    if not data or 'trade_id' not in data or 'price' not in data:
        return jsonify({"success": False, "error": "Missing trade_id or price"}), 400
    
    engine = PaperTradingEngine()
    
    try:
        result = engine.exit_trade(
            trade_id=int(data['trade_id']),
            exit_price=float(data['price']),
            reason=data.get('reason', 'MANUAL')
        )
        
        return jsonify({
            "success": True,
            "ticker": result.ticker,
            "return_pct": result.return_pct,
            "return_dollars": result.return_dollars,
            "days_held": result.days_held,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/v2/analyze/<ticker>")
def api_v2_analyze(ticker):
    """Get full V2 analysis for a single stock."""
    from signals.trend_template import check_trend_template
    from signals.vcp_detector import detect_vcp
    from collectors.earnings import is_earnings_safe
    
    ticker = ticker.upper()
    
    try:
        # Trend template
        trend = check_trend_template(ticker)
        
        # VCP pattern
        vcp = detect_vcp(ticker)
        
        # Earnings check
        earnings_safe, earnings_date = is_earnings_safe(ticker)
        
        return jsonify({
            "ticker": ticker,
            "trend_template": {
                "passes": trend.passes_template,
                "criteria_passed": trend.criteria_passed,
                "price": trend.price,
                "ma_50": trend.ma_50,
                "ma_150": trend.ma_150,
                "ma_200": trend.ma_200,
                "rs_rating": trend.rs_rating,
                "distance_from_high_pct": trend.distance_from_high_pct,
            },
            "vcp_pattern": {
                "is_valid": vcp.is_valid,
                "pattern_score": vcp.pattern_score,
                "num_contractions": vcp.num_contractions,
                "pivot_price": vcp.pivot_price,
                "volume_declining": vcp.volume_declining,
                "notes": vcp.notes,
            },
            "earnings": {
                "is_safe": earnings_safe,
                "next_date": earnings_date.isoformat() if earnings_date else None,
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ============================================================================
# MEAN REVERSION API ENDPOINTS
# ============================================================================

@app.route("/api/v2/mr/positions")
def api_v2_mr_positions():
    """Get open mean reversion positions."""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT * FROM mean_reversion_trades 
        WHERE status = 'OPEN'
        ORDER BY entry_date DESC
    """)
    
    positions = []
    for row in cur.fetchall():
        positions.append({
            "id": row["id"],
            "ticker": row["ticker"],
            "entry_date": row["entry_date"],
            "entry_price": row["entry_price"],
            "shares": row["shares"],
            "position_value": row["position_value"],
            "stop_price": row["stop_price"],
            "target_price": row["target_price"],
            "status": row["status"],
        })
    
    conn.close()
    return jsonify({"positions": positions, "count": len(positions)})


@app.route("/api/v2/mr/signals")
def api_v2_mr_signals():
    """Get recent mean reversion signals."""
    conn = get_db()
    cur = conn.cursor()
    
    limit = request.args.get('limit', 20, type=int)
    
    cur.execute("""
        SELECT * FROM mean_reversion_signals 
        WHERE is_signal = 1
        ORDER BY date DESC, signal_strength DESC
        LIMIT ?
    """, (limit,))
    
    signals = []
    for row in cur.fetchall():
        signals.append({
            "ticker": row["ticker"],
            "date": row["date"],
            "rsi_14": row["rsi_14"],
            "drop_pct": row["drop_pct"],
            "current_price": row["current_price"],
            "suggested_entry": row["suggested_entry"],
            "suggested_stop": row["suggested_stop"],
            "suggested_target": row["suggested_target"],
            "signal_strength": row["signal_strength"],
            "notes": row["notes"],
        })
    
    conn.close()
    return jsonify({"signals": signals, "count": len(signals)})


@app.route("/api/v2/mr/trades")
def api_v2_mr_trades():
    """Get mean reversion trade history."""
    conn = get_db()
    cur = conn.cursor()
    
    limit = request.args.get('limit', 20, type=int)
    
    cur.execute("""
        SELECT * FROM mean_reversion_trades 
        WHERE status = 'CLOSED'
        ORDER BY exit_date DESC
        LIMIT ?
    """, (limit,))
    
    trades = []
    for row in cur.fetchall():
        trades.append({
            "id": row["id"],
            "ticker": row["ticker"],
            "entry_date": row["entry_date"],
            "entry_price": row["entry_price"],
            "exit_date": row["exit_date"],
            "exit_price": row["exit_price"],
            "return_pct": row["return_pct"],
            "return_dollars": row["return_dollars"],
            "days_held": row["days_held"],
            "exit_reason": row["exit_reason"],
        })
    
    conn.close()
    return jsonify({"trades": trades, "count": len(trades)})


@app.route("/api/v2/mr/performance")
def api_v2_mr_performance():
    """Get mean reversion strategy performance stats."""
    conn = get_db()
    cur = conn.cursor()
    
    # Total trades
    cur.execute("SELECT COUNT(*) as cnt FROM mean_reversion_trades WHERE status = 'CLOSED'")
    total_trades = cur.fetchone()["cnt"]
    
    # Win rate
    cur.execute("SELECT COUNT(*) as cnt FROM mean_reversion_trades WHERE status = 'CLOSED' AND return_pct > 0")
    wins = cur.fetchone()["cnt"]
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    # Avg return
    cur.execute("SELECT AVG(return_pct) as avg_ret, AVG(days_held) as avg_days FROM mean_reversion_trades WHERE status = 'CLOSED'")
    row = cur.fetchone()
    avg_return = row["avg_ret"] or 0
    avg_days = row["avg_days"] or 0
    
    # Total P&L
    cur.execute("SELECT SUM(return_dollars) as total FROM mean_reversion_trades WHERE status = 'CLOSED'")
    total_pnl = cur.fetchone()["total"] or 0
    
    conn.close()
    
    return jsonify({
        "total_trades": total_trades,
        "wins": wins,
        "losses": total_trades - wins,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "avg_days_held": avg_days,
        "total_pnl": total_pnl,
    })


@app.route("/api/v2/combined/portfolio")
def api_v2_combined_portfolio():
    """Get combined portfolio view with both strategies."""
    from utils.paper_trading import PaperTradingEngine
    
    conn = get_db()
    cur = conn.cursor()
    engine = PaperTradingEngine()
    
    # Get momentum positions
    momentum_status = engine.get_portfolio_status({})
    
    # Get mean reversion positions
    cur.execute("""
        SELECT * FROM mean_reversion_trades 
        WHERE status = 'OPEN'
    """)
    mr_positions = cur.fetchall()
    mr_value = sum(row["position_value"] for row in mr_positions)
    
    # Get cash from portfolio snapshot
    cur.execute("SELECT cash FROM portfolio_snapshots ORDER BY date DESC LIMIT 1")
    cash_row = cur.fetchone()
    cash = cash_row["cash"] if cash_row else 50000
    
    total_value = cash + momentum_status.positions_value + mr_value
    
    conn.close()
    
    return jsonify({
        "total_value": total_value,
        "cash": cash,
        "momentum": {
            "positions_value": momentum_status.positions_value,
            "positions_count": len(momentum_status.open_positions),
            "max_positions": 4,
            "allocation_pct": 70,
        },
        "mean_reversion": {
            "positions_value": mr_value,
            "positions_count": len(mr_positions),
            "max_positions": 2,
            "allocation_pct": 30,
        },
        "total_positions": len(momentum_status.open_positions) + len(mr_positions),
        "max_total_positions": 6,
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, port=port, host="0.0.0.0")
