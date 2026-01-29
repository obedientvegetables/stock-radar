"""
Paper Trading Engine

Simulates trades with virtual money for validation.
Tracks positions, calculates P&L, manages stops/targets.

Key features:
- Position entry with risk-based sizing
- Stop loss management (fixed, breakeven, trailing)
- Target hit detection
- Portfolio snapshots for equity curve tracking
- Performance metrics calculation
"""

import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Dict

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_db
from utils.config import config


@dataclass
class Position:
    """Represents an open position."""
    id: int
    ticker: str
    entry_date: date
    entry_price: float
    shares: int
    entry_value: float
    initial_stop: float
    current_stop: float
    stop_type: str  # FIXED, BREAKEVEN, TRAILING
    target_price: float
    highest_price: float
    current_price: float
    current_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    days_held: int
    status: str


@dataclass
class ClosedTrade:
    """Represents a closed trade."""
    id: int
    ticker: str
    entry_date: date
    entry_price: float
    shares: int
    exit_date: date
    exit_price: float
    exit_reason: str
    return_pct: float
    return_dollars: float
    days_held: int
    r_multiple: float


@dataclass
class PortfolioStatus:
    """Current portfolio status."""
    cash: float
    positions_value: float
    total_value: float
    total_pnl: float
    total_pnl_pct: float
    open_positions: List[Position]
    num_positions: int
    available_slots: int


@dataclass
class PerformanceMetrics:
    """Trading performance metrics."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    avg_r_multiple: float
    total_return: float
    total_return_pct: float
    max_drawdown_pct: float
    best_trade: Optional[ClosedTrade]
    worst_trade: Optional[ClosedTrade]


class PaperTradingEngine:
    """
    Manages paper trading portfolio.
    """

    def __init__(self, starting_capital: float = None):
        """
        Initialize paper trading engine.

        Args:
            starting_capital: Starting cash (defaults to config)
        """
        self.starting_capital = starting_capital or config.V2_PAPER_PORTFOLIO_SIZE
        self._ensure_initialized()

    def _ensure_initialized(self):
        """Ensure portfolio is initialized in database."""
        with get_db() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots")
            if cursor.fetchone()[0] == 0:
                # Initialize with starting capital
                conn.execute("""
                    INSERT INTO portfolio_snapshots
                    (date, cash_balance, positions_value, total_value,
                     open_positions, daily_pnl, daily_pnl_pct, total_return_pct,
                     max_drawdown_pct, peak_value)
                    VALUES (?, ?, 0, ?, 0, 0, 0, 0, 0, ?)
                """, (
                    date.today().isoformat(),
                    self.starting_capital,
                    self.starting_capital,
                    self.starting_capital
                ))

    def get_cash_balance(self) -> float:
        """Get current cash balance."""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT cash_balance FROM portfolio_snapshots
                ORDER BY date DESC LIMIT 1
            """)
            row = cursor.fetchone()
            return row['cash_balance'] if row else self.starting_capital

    def enter_trade(
        self,
        ticker: str,
        entry_price: float,
        shares: int,
        stop_price: float,
        target_price: float,
        signal_source: str = 'V2_MANUAL',
        notes: str = ""
    ) -> int:
        """
        Enter a new paper trade.

        Args:
            ticker: Stock symbol
            entry_price: Entry price per share
            shares: Number of shares
            stop_price: Initial stop loss price
            target_price: Profit target price
            signal_source: Source of signal (V2_TREND, V2_VCP, V2_BREAKOUT)
            notes: Optional notes

        Returns:
            Trade ID
        """
        entry_value = entry_price * shares
        cash = self.get_cash_balance()

        if entry_value > cash:
            raise ValueError(f"Insufficient cash: need ${entry_value:.2f}, have ${cash:.2f}")

        # Check position limits
        open_count = len(self.get_open_positions())
        if open_count >= config.V2_MAX_POSITIONS:
            raise ValueError(f"Position limit reached: {open_count}/{config.V2_MAX_POSITIONS}")

        # Calculate risk metrics
        risk_per_share = entry_price - stop_price
        risk_dollars = risk_per_share * shares
        risk_pct = (risk_dollars / self.starting_capital) * 100
        reward_per_share = target_price - entry_price
        rr_ratio = reward_per_share / risk_per_share if risk_per_share > 0 else 0
        target_pct = ((target_price - entry_price) / entry_price) * 100

        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO paper_trades_v2
                (ticker, entry_date, entry_price, shares, entry_value,
                 initial_stop, current_stop, stop_type, target_price, target_pct,
                 risk_per_share, risk_dollars, risk_pct, risk_reward_ratio,
                 highest_price, lowest_price_since_entry, days_held,
                 status, signal_source, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'FIXED', ?, ?, ?, ?, ?, ?, ?, ?, 0, 'OPEN', ?, ?)
            """, (
                ticker.upper(),
                date.today().isoformat(),
                entry_price,
                shares,
                entry_value,
                stop_price,
                stop_price,
                target_price,
                target_pct,
                risk_per_share,
                risk_dollars,
                risk_pct,
                rr_ratio,
                entry_price,
                entry_price,
                signal_source,
                notes
            ))
            trade_id = cursor.lastrowid

            # Update cash balance
            self._update_cash(-entry_value)

        return trade_id

    def exit_trade(
        self,
        trade_id: int,
        exit_price: float,
        reason: str = "MANUAL"
    ) -> Dict:
        """
        Exit an existing trade.

        Args:
            trade_id: ID of trade to exit
            exit_price: Exit price per share
            reason: Exit reason (TARGET, STOP, TRAILING_STOP, TIME, MANUAL)

        Returns:
            Dict with trade results
        """
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM paper_trades_v2 WHERE id = ?", (trade_id,)
            )
            trade = cursor.fetchone()

            if not trade:
                raise ValueError(f"Trade {trade_id} not found")
            if trade['status'] != 'OPEN':
                raise ValueError(f"Trade {trade_id} is not open (status: {trade['status']})")

            entry_price = trade['entry_price']
            shares = trade['shares']
            entry_date = date.fromisoformat(trade['entry_date'])
            exit_value = exit_price * shares

            # Calculate returns
            return_pct = ((exit_price - entry_price) / entry_price) * 100
            return_dollars = (exit_price - entry_price) * shares
            days_held = (date.today() - entry_date).days

            # Calculate R-multiple (return relative to initial risk)
            risk_per_share = trade['risk_per_share']
            r_multiple = (exit_price - entry_price) / risk_per_share if risk_per_share > 0 else 0

            # Update trade record
            conn.execute("""
                UPDATE paper_trades_v2
                SET exit_date = ?, exit_price = ?, exit_value = ?,
                    exit_reason = ?, return_pct = ?, return_dollars = ?,
                    days_held = ?, r_multiple = ?, status = 'CLOSED',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                date.today().isoformat(),
                exit_price,
                exit_value,
                reason,
                return_pct,
                return_dollars,
                days_held,
                r_multiple,
                trade_id
            ))

            # Return cash to portfolio
            self._update_cash(exit_value)

        return {
            'trade_id': trade_id,
            'ticker': trade['ticker'],
            'entry_price': entry_price,
            'exit_price': exit_price,
            'shares': shares,
            'return_pct': round(return_pct, 2),
            'return_dollars': round(return_dollars, 2),
            'r_multiple': round(r_multiple, 2),
            'days_held': days_held,
            'reason': reason
        }

    def check_stops_and_targets(self, current_prices: Dict[str, float] = None) -> List[Dict]:
        """
        Check all open positions for stop/target hits.

        Args:
            current_prices: Dict of {ticker: price}, fetches if not provided

        Returns:
            List of triggered exits
        """
        positions = self.get_open_positions()

        if not positions:
            return []

        # Get current prices if not provided
        if current_prices is None:
            current_prices = self._get_current_prices([p.ticker for p in positions])

        triggered = []

        for pos in positions:
            ticker = pos.ticker
            if ticker not in current_prices:
                continue

            price = current_prices[ticker]

            # Check stop hit
            if price <= pos.current_stop:
                result = self.exit_trade(pos.id, price, 'STOP')
                triggered.append(result)
                continue

            # Check target hit
            if price >= pos.target_price:
                result = self.exit_trade(pos.id, price, 'TARGET')
                triggered.append(result)
                continue

            # Update trailing stop if price made new high
            if price > pos.highest_price:
                new_stop = self._calculate_trailing_stop(
                    pos.entry_price, price, pos.current_stop
                )
                self._update_position_tracking(pos.id, price, new_stop)

    def _calculate_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        current_stop: float
    ) -> float:
        """
        Calculate new trailing stop based on rules.

        Rules:
        - After +5%: Move stop to breakeven
        - After +10%: Trail at highest - 10%
        - Never lower the stop
        """
        gain_pct = ((current_price - entry_price) / entry_price) * 100

        if gain_pct >= config.TRAILING_TRIGGER_PCT * 100:
            # Trail at 10% below highest
            new_stop = current_price * (1 - config.TRAILING_STOP_PCT)
        elif gain_pct >= config.BREAKEVEN_TRIGGER_PCT * 100:
            # Move to breakeven
            new_stop = entry_price
        else:
            new_stop = current_stop

        # Never lower the stop
        return max(new_stop, current_stop)

    def _update_position_tracking(self, trade_id: int, highest_price: float, new_stop: float):
        """Update position tracking fields."""
        with get_db() as conn:
            # Determine stop type
            cursor = conn.execute(
                "SELECT entry_price, initial_stop FROM paper_trades_v2 WHERE id = ?",
                (trade_id,)
            )
            trade = cursor.fetchone()

            if new_stop > trade['initial_stop']:
                if new_stop >= trade['entry_price']:
                    stop_type = 'TRAILING' if new_stop > trade['entry_price'] else 'BREAKEVEN'
                else:
                    stop_type = 'FIXED'
            else:
                stop_type = 'FIXED'

            conn.execute("""
                UPDATE paper_trades_v2
                SET highest_price = ?, current_stop = ?, stop_type = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (highest_price, new_stop, stop_type, trade_id))

    def get_open_positions(self) -> List[Position]:
        """Get all open positions with current values."""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM paper_trades_v2
                WHERE status = 'OPEN'
                ORDER BY entry_date
            """)
            rows = cursor.fetchall()

        if not rows:
            return []

        # Get current prices
        tickers = [row['ticker'] for row in rows]
        prices = self._get_current_prices(tickers)

        positions = []
        for row in rows:
            ticker = row['ticker']
            current_price = prices.get(ticker, row['entry_price'])
            current_value = current_price * row['shares']
            entry_value = row['entry_value']
            unrealized_pnl = current_value - entry_value
            unrealized_pnl_pct = (unrealized_pnl / entry_value) * 100 if entry_value > 0 else 0
            entry_date = date.fromisoformat(row['entry_date'])
            days_held = (date.today() - entry_date).days

            positions.append(Position(
                id=row['id'],
                ticker=ticker,
                entry_date=entry_date,
                entry_price=row['entry_price'],
                shares=row['shares'],
                entry_value=entry_value,
                initial_stop=row['initial_stop'],
                current_stop=row['current_stop'],
                stop_type=row['stop_type'],
                target_price=row['target_price'],
                highest_price=row['highest_price'],
                current_price=round(current_price, 2),
                current_value=round(current_value, 2),
                unrealized_pnl=round(unrealized_pnl, 2),
                unrealized_pnl_pct=round(unrealized_pnl_pct, 2),
                days_held=days_held,
                status=row['status']
            ))

        return positions

    def get_portfolio_status(self) -> PortfolioStatus:
        """Get current portfolio status."""
        cash = self.get_cash_balance()
        positions = self.get_open_positions()

        positions_value = sum(p.current_value for p in positions)
        total_value = cash + positions_value
        total_pnl = total_value - self.starting_capital
        total_pnl_pct = (total_pnl / self.starting_capital) * 100

        return PortfolioStatus(
            cash=round(cash, 2),
            positions_value=round(positions_value, 2),
            total_value=round(total_value, 2),
            total_pnl=round(total_pnl, 2),
            total_pnl_pct=round(total_pnl_pct, 2),
            open_positions=positions,
            num_positions=len(positions),
            available_slots=config.V2_MAX_POSITIONS - len(positions)
        )

    def get_closed_trades(self, limit: int = 50) -> List[ClosedTrade]:
        """Get recently closed trades."""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM paper_trades_v2
                WHERE status = 'CLOSED'
                ORDER BY exit_date DESC
                LIMIT ?
            """, (limit,))

            trades = []
            for row in cursor.fetchall():
                trades.append(ClosedTrade(
                    id=row['id'],
                    ticker=row['ticker'],
                    entry_date=date.fromisoformat(row['entry_date']),
                    entry_price=row['entry_price'],
                    shares=row['shares'],
                    exit_date=date.fromisoformat(row['exit_date']),
                    exit_price=row['exit_price'],
                    exit_reason=row['exit_reason'],
                    return_pct=row['return_pct'],
                    return_dollars=row['return_dollars'],
                    days_held=row['days_held'],
                    r_multiple=row['r_multiple'] or 0
                ))

            return trades

    def get_performance_metrics(self) -> PerformanceMetrics:
        """Calculate trading performance metrics."""
        trades = self.get_closed_trades(limit=1000)

        if not trades:
            return PerformanceMetrics(
                total_trades=0, winning_trades=0, losing_trades=0,
                win_rate=0, avg_win=0, avg_loss=0, profit_factor=0,
                avg_r_multiple=0, total_return=0, total_return_pct=0,
                max_drawdown_pct=0, best_trade=None, worst_trade=None
            )

        winners = [t for t in trades if t.return_pct > 0]
        losers = [t for t in trades if t.return_pct <= 0]

        total_wins = sum(t.return_dollars for t in winners)
        total_losses = abs(sum(t.return_dollars for t in losers))

        avg_win = total_wins / len(winners) if winners else 0
        avg_loss = total_losses / len(losers) if losers else 0
        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')

        avg_r = sum(t.r_multiple for t in trades) / len(trades) if trades else 0
        total_return = sum(t.return_dollars for t in trades)
        total_return_pct = (total_return / self.starting_capital) * 100

        # Find best and worst trades
        best_trade = max(trades, key=lambda t: t.return_pct) if trades else None
        worst_trade = min(trades, key=lambda t: t.return_pct) if trades else None

        return PerformanceMetrics(
            total_trades=len(trades),
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=len(winners) / len(trades) * 100 if trades else 0,
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            profit_factor=round(profit_factor, 2),
            avg_r_multiple=round(avg_r, 2),
            total_return=round(total_return, 2),
            total_return_pct=round(total_return_pct, 2),
            max_drawdown_pct=0,  # Would need equity curve to calculate
            best_trade=best_trade,
            worst_trade=worst_trade
        )

    def calculate_position_size(
        self,
        entry_price: float,
        stop_price: float,
        portfolio_value: float = None
    ) -> int:
        """
        Calculate position size based on risk.

        Risk per trade = 2% of portfolio (configurable)

        Args:
            entry_price: Planned entry price
            stop_price: Stop loss price
            portfolio_value: Portfolio value (defaults to current)

        Returns:
            Number of shares
        """
        if portfolio_value is None:
            status = self.get_portfolio_status()
            portfolio_value = status.total_value

        risk_per_share = entry_price - stop_price
        if risk_per_share <= 0:
            return 0

        max_risk_dollars = portfolio_value * config.V2_MAX_RISK_PER_TRADE
        shares = int(max_risk_dollars / risk_per_share)

        # Cap at max position percentage
        max_shares = int((portfolio_value * config.V2_MAX_POSITION_PCT) / entry_price)

        return min(shares, max_shares)

    def take_snapshot(self):
        """Take a portfolio snapshot for equity curve tracking."""
        status = self.get_portfolio_status()

        # Get SPY price for benchmark
        try:
            spy = yf.Ticker('SPY')
            spy_hist = spy.history(period='1d')
            spy_close = float(spy_hist['Close'].iloc[-1]) if len(spy_hist) > 0 else None
        except Exception:
            spy_close = None

        with get_db() as conn:
            # Get previous snapshot for calculating drawdown
            cursor = conn.execute("""
                SELECT peak_value, total_value FROM portfolio_snapshots
                ORDER BY date DESC LIMIT 1
            """)
            prev = cursor.fetchone()

            peak_value = max(prev['peak_value'] or self.starting_capital, status.total_value) if prev else status.total_value
            max_dd = ((peak_value - status.total_value) / peak_value) * 100 if peak_value > 0 else 0

            # Calculate daily P&L
            prev_value = prev['total_value'] if prev else self.starting_capital
            daily_pnl = status.total_value - prev_value
            daily_pnl_pct = (daily_pnl / prev_value) * 100 if prev_value > 0 else 0

            conn.execute("""
                INSERT INTO portfolio_snapshots
                (date, cash_balance, positions_value, total_value, open_positions,
                 daily_pnl, daily_pnl_pct, total_return_pct, max_drawdown_pct,
                 peak_value, spy_close)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    cash_balance = excluded.cash_balance,
                    positions_value = excluded.positions_value,
                    total_value = excluded.total_value,
                    open_positions = excluded.open_positions,
                    daily_pnl = excluded.daily_pnl,
                    daily_pnl_pct = excluded.daily_pnl_pct,
                    total_return_pct = excluded.total_return_pct,
                    max_drawdown_pct = excluded.max_drawdown_pct,
                    peak_value = excluded.peak_value,
                    spy_close = excluded.spy_close
            """, (
                date.today().isoformat(),
                status.cash,
                status.positions_value,
                status.total_value,
                status.num_positions,
                daily_pnl,
                daily_pnl_pct,
                status.total_pnl_pct,
                max_dd,
                peak_value,
                spy_close
            ))

    def _update_cash(self, amount: float):
        """Update cash balance in latest snapshot."""
        with get_db() as conn:
            conn.execute("""
                UPDATE portfolio_snapshots
                SET cash_balance = cash_balance + ?
                WHERE date = (SELECT MAX(date) FROM portfolio_snapshots)
            """, (amount,))

    def _get_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        """Get current prices for multiple tickers."""
        prices = {}
        for ticker in tickers:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='1d')
                if len(hist) > 0:
                    prices[ticker] = float(hist['Close'].iloc[-1])
            except Exception:
                pass
        return prices


if __name__ == "__main__":
    # Test the paper trading engine
    print("Testing Paper Trading Engine")
    print("=" * 50)

    engine = PaperTradingEngine()
    status = engine.get_portfolio_status()

    print(f"\nPortfolio Status:")
    print(f"  Cash: ${status.cash:,.2f}")
    print(f"  Positions: ${status.positions_value:,.2f}")
    print(f"  Total: ${status.total_value:,.2f}")
    print(f"  P&L: ${status.total_pnl:+,.2f} ({status.total_pnl_pct:+.2f}%)")
    print(f"  Open positions: {status.num_positions}/{config.V2_MAX_POSITIONS}")

    if status.open_positions:
        print(f"\nOpen Positions:")
        for pos in status.open_positions:
            print(f"  {pos.ticker}: {pos.shares} sh @ ${pos.entry_price:.2f}")
            print(f"    Current: ${pos.current_price:.2f} ({pos.unrealized_pnl_pct:+.1f}%)")
            print(f"    Stop: ${pos.current_stop:.2f} ({pos.stop_type})")
            print(f"    Days held: {pos.days_held}")

    metrics = engine.get_performance_metrics()
    if metrics.total_trades > 0:
        print(f"\nPerformance Metrics:")
        print(f"  Total trades: {metrics.total_trades}")
        print(f"  Win rate: {metrics.win_rate:.1f}%")
        print(f"  Profit factor: {metrics.profit_factor:.2f}")
        print(f"  Avg R-multiple: {metrics.avg_r_multiple:.2f}")
