"""
V2 Paper Trading Engine

Simulates trades with virtual money for validation.
Tracks positions, calculates P&L, manages stops/targets.

Key features:
- Position sizing based on risk (2% max per trade)
- Automatic trailing stop management
- Daily portfolio snapshots
- Performance tracking
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Dict, Tuple
import yfinance as yf
import sys
from pathlib import Path

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
    position_value: float
    stop_price: float
    target_price: float
    current_stop: float
    highest_price: float
    status: str
    notes: str = ""


@dataclass
class PortfolioStatus:
    """Current portfolio state."""
    cash: float
    positions_value: float
    total_value: float
    open_positions: List[Position]
    daily_pnl: float
    daily_pnl_pct: float
    total_pnl: float
    total_pnl_pct: float


@dataclass
class TradeResult:
    """Result of a closed trade."""
    trade_id: int
    ticker: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    shares: int
    return_pct: float
    return_dollars: float
    days_held: int
    exit_reason: str


class PaperTradingEngine:
    """
    Manages V2 paper trading portfolio.
    
    Features:
    - Track positions with entry/stop/target
    - Calculate P&L daily
    - Auto-execute stops and targets
    - Trailing stop management
    - Portfolio snapshots
    """
    
    def __init__(self, starting_capital: Optional[float] = None):
        self.starting_capital = starting_capital or config.V2_PORTFOLIO_SIZE
        self._ensure_initialized()
    
    def _ensure_initialized(self):
        """Ensure portfolio is initialized in database."""
        with get_db() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots")
            if cursor.fetchone()[0] == 0:
                # Initialize with starting capital
                today = date.today().isoformat()
                conn.execute("""
                    INSERT INTO portfolio_snapshots 
                    (date, cash, positions_value, total_value, daily_pnl, daily_pnl_pct, open_positions)
                    VALUES (?, ?, 0, ?, 0, 0, 0)
                """, (today, self.starting_capital, self.starting_capital))
    
    def get_cash(self) -> float:
        """Get current cash balance."""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT cash FROM portfolio_snapshots ORDER BY date DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row['cash'] if row else self.starting_capital
    
    def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT * FROM paper_trades_v2 WHERE status = 'OPEN'"
            )
            positions = []
            for row in cursor.fetchall():
                positions.append(Position(
                    id=row['id'],
                    ticker=row['ticker'],
                    entry_date=date.fromisoformat(row['entry_date']),
                    entry_price=row['entry_price'],
                    shares=row['shares'],
                    position_value=row['position_value'],
                    stop_price=row['stop_price'],
                    target_price=row['target_price'],
                    current_stop=row['current_stop'] or row['stop_price'],
                    highest_price=row['highest_price'] or row['entry_price'],
                    status=row['status'],
                    notes=row['notes'] or "",
                ))
            return positions
    
    def enter_trade(
        self,
        ticker: str,
        entry_price: float,
        shares: int,
        stop_price: float,
        target_price: float,
        notes: str = ""
    ) -> int:
        """
        Enter a new paper trade.
        
        Args:
            ticker: Stock symbol
            entry_price: Entry price
            shares: Number of shares
            stop_price: Initial stop loss price
            target_price: Target price for profit taking
            notes: Optional notes
        
        Returns:
            trade_id
        """
        position_value = entry_price * shares
        cash = self.get_cash()
        
        if position_value > cash:
            raise ValueError(f"Insufficient cash: need ${position_value:.2f}, have ${cash:.2f}")
        
        # Check max positions
        open_positions = self.get_open_positions()
        if len(open_positions) >= config.V2_MAX_POSITIONS:
            raise ValueError(f"Max positions reached ({config.V2_MAX_POSITIONS})")
        
        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO paper_trades_v2
                (ticker, entry_date, entry_price, shares, position_value,
                 stop_price, target_price, current_stop, highest_price, notes, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
            """, (
                ticker,
                date.today().isoformat(),
                entry_price,
                shares,
                position_value,
                stop_price,
                target_price,
                stop_price,  # current_stop starts at initial stop
                entry_price,  # highest_price starts at entry
                notes,
            ))
            
            trade_id = cursor.lastrowid
            
            # Update cash
            self._update_cash(-position_value)
        
        return trade_id
    
    def exit_trade(
        self,
        trade_id: int,
        exit_price: float,
        reason: str = "MANUAL"
    ) -> TradeResult:
        """
        Exit an existing trade.
        
        Args:
            trade_id: ID of the trade to exit
            exit_price: Exit price
            reason: Exit reason (STOP, TARGET, MANUAL, TIME)
        
        Returns:
            TradeResult with trade details
        """
        with get_db() as conn:
            # Get trade details
            cursor = conn.execute(
                "SELECT * FROM paper_trades_v2 WHERE id = ?", (trade_id,)
            )
            trade = cursor.fetchone()
            
            if not trade:
                raise ValueError(f"Trade {trade_id} not found")
            if trade['status'] != 'OPEN':
                raise ValueError(f"Trade {trade_id} is not open")
            
            # Calculate returns
            entry_price = trade['entry_price']
            shares = trade['shares']
            entry_date = date.fromisoformat(trade['entry_date'])
            exit_date = date.today()
            
            return_pct = ((exit_price - entry_price) / entry_price) * 100
            return_dollars = (exit_price - entry_price) * shares
            days_held = (exit_date - entry_date).days
            
            # Update trade
            conn.execute("""
                UPDATE paper_trades_v2
                SET exit_date = ?, exit_price = ?, exit_reason = ?,
                    return_pct = ?, return_dollars = ?, days_held = ?,
                    status = 'CLOSED'
                WHERE id = ?
            """, (
                exit_date.isoformat(),
                exit_price,
                reason,
                return_pct,
                return_dollars,
                days_held,
                trade_id,
            ))
            
            # Return cash
            exit_value = exit_price * shares
            self._update_cash(exit_value)
        
        return TradeResult(
            trade_id=trade_id,
            ticker=trade['ticker'],
            entry_date=entry_date,
            exit_date=exit_date,
            entry_price=entry_price,
            exit_price=exit_price,
            shares=shares,
            return_pct=round(return_pct, 2),
            return_dollars=round(return_dollars, 2),
            days_held=days_held,
            exit_reason=reason,
        )
    
    def check_stops_and_targets(self, current_prices: Optional[Dict[str, float]] = None) -> List[TradeResult]:
        """
        Check all open positions for stop/target hits.
        
        Args:
            current_prices: Dict of ticker -> current price (fetched if not provided)
        
        Returns:
            List of triggered exits
        """
        positions = self.get_open_positions()
        if not positions:
            return []
        
        # Fetch prices if not provided
        if current_prices is None:
            current_prices = self._get_current_prices([p.ticker for p in positions])
        
        triggered = []
        
        for pos in positions:
            ticker = pos.ticker
            if ticker not in current_prices:
                continue
            
            price = current_prices[ticker]
            
            # Check stop
            if price <= pos.current_stop:
                result = self.exit_trade(pos.id, price, 'STOP')
                triggered.append(result)
                continue
            
            # Check target
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
        
        return triggered
    
    def _calculate_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        current_stop: float
    ) -> float:
        """
        Calculate new trailing stop.
        
        Rules:
        - After +5%: Move to breakeven
        - After +10%: Trail at highest - 10%
        - Never move stop down
        """
        gain_pct = ((current_price - entry_price) / entry_price) * 100
        
        if gain_pct >= 10:
            # Trail at 10% below highest
            new_stop = current_price * 0.90
        elif gain_pct >= 5:
            # Move to breakeven
            new_stop = entry_price
        else:
            new_stop = current_stop
        
        # Never lower the stop
        return max(new_stop, current_stop)
    
    def _update_position_tracking(self, trade_id: int, highest_price: float, current_stop: float):
        """Update highest price and current stop for a position."""
        with get_db() as conn:
            conn.execute("""
                UPDATE paper_trades_v2
                SET highest_price = ?, current_stop = ?
                WHERE id = ?
            """, (highest_price, current_stop, trade_id))
    
    def get_portfolio_status(self, current_prices: Optional[Dict[str, float]] = None) -> PortfolioStatus:
        """
        Get current portfolio status.
        
        Args:
            current_prices: Dict of ticker -> current price
        
        Returns:
            PortfolioStatus with full details
        """
        cash = self.get_cash()
        positions = self.get_open_positions()
        
        # Fetch prices if not provided
        if positions and current_prices is None:
            current_prices = self._get_current_prices([p.ticker for p in positions])
        
        # Calculate positions value
        positions_value = 0
        for pos in positions:
            price = current_prices.get(pos.ticker, pos.entry_price) if current_prices else pos.entry_price
            positions_value += price * pos.shares
        
        total_value = cash + positions_value
        total_pnl = total_value - self.starting_capital
        total_pnl_pct = (total_pnl / self.starting_capital) * 100
        
        return PortfolioStatus(
            cash=round(cash, 2),
            positions_value=round(positions_value, 2),
            total_value=round(total_value, 2),
            open_positions=positions,
            daily_pnl=0,  # Would need yesterday's snapshot to calculate
            daily_pnl_pct=0,
            total_pnl=round(total_pnl, 2),
            total_pnl_pct=round(total_pnl_pct, 2),
        )
    
    def calculate_position_size(
        self,
        entry_price: float,
        stop_price: float,
        portfolio_value: Optional[float] = None
    ) -> int:
        """
        Calculate position size based on risk.
        
        Risk per trade = V2_MAX_RISK_PER_TRADE (default 2%) of portfolio
        
        Args:
            entry_price: Planned entry price
            stop_price: Planned stop price
            portfolio_value: Portfolio value (fetched if not provided)
        
        Returns:
            Number of shares to buy
        """
        if portfolio_value is None:
            status = self.get_portfolio_status()
            portfolio_value = status.total_value
        
        risk_per_share = entry_price - stop_price
        if risk_per_share <= 0:
            raise ValueError("Stop price must be below entry price")
        
        max_risk = portfolio_value * config.V2_MAX_RISK_PER_TRADE
        shares = int(max_risk / risk_per_share)
        
        # Cap at max position %
        max_position_value = portfolio_value * config.V2_MAX_POSITION_PCT
        max_shares = int(max_position_value / entry_price)
        
        return min(shares, max_shares)
    
    def _update_cash(self, amount: float):
        """Update cash balance (positive = add, negative = subtract)."""
        with get_db() as conn:
            # Get latest snapshot date
            cursor = conn.execute(
                "SELECT date, cash FROM portfolio_snapshots ORDER BY date DESC LIMIT 1"
            )
            row = cursor.fetchone()
            
            if row:
                today = date.today().isoformat()
                if row['date'] == today:
                    # Update today's snapshot
                    conn.execute("""
                        UPDATE portfolio_snapshots
                        SET cash = cash + ?
                        WHERE date = ?
                    """, (amount, today))
                else:
                    # Create new snapshot for today
                    new_cash = row['cash'] + amount
                    conn.execute("""
                        INSERT INTO portfolio_snapshots
                        (date, cash, positions_value, total_value, daily_pnl, daily_pnl_pct, open_positions)
                        VALUES (?, ?, 0, ?, 0, 0, 0)
                    """, (today, new_cash, new_cash))
    
    def _get_current_prices(self, tickers: List[str]) -> Dict[str, float]:
        """Fetch current prices for a list of tickers."""
        prices = {}
        for ticker in tickers:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="1d")
                if not hist.empty:
                    prices[ticker] = float(hist['Close'].iloc[-1])
            except Exception:
                continue
        return prices
    
    def take_daily_snapshot(self) -> None:
        """Take end-of-day portfolio snapshot."""
        status = self.get_portfolio_status()
        today = date.today().isoformat()
        
        with get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO portfolio_snapshots
                (date, cash, positions_value, total_value, daily_pnl, daily_pnl_pct, open_positions)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                today,
                status.cash,
                status.positions_value,
                status.total_value,
                status.daily_pnl,
                status.daily_pnl_pct,
                len(status.open_positions),
            ))
    
    def get_trade_history(self, days: int = 30) -> List[Dict]:
        """Get recent trade history."""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM paper_trades_v2
                WHERE status = 'CLOSED'
                ORDER BY exit_date DESC
                LIMIT ?
            """, (days,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_performance_stats(self) -> Dict:
        """Calculate performance statistics."""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT * FROM paper_trades_v2 WHERE status = 'CLOSED'
            """)
            trades = cursor.fetchall()
        
        if not trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'profit_factor': 0,
                'avg_days_held': 0,
            }
        
        wins = [t for t in trades if t['return_pct'] > 0]
        losses = [t for t in trades if t['return_pct'] <= 0]
        
        total_wins = sum(t['return_dollars'] for t in wins) if wins else 0
        total_losses = abs(sum(t['return_dollars'] for t in losses)) if losses else 0
        
        return {
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(len(wins) / len(trades) * 100, 1) if trades else 0,
            'avg_win': round(sum(t['return_pct'] for t in wins) / len(wins), 2) if wins else 0,
            'avg_loss': round(sum(t['return_pct'] for t in losses) / len(losses), 2) if losses else 0,
            'profit_factor': round(total_wins / total_losses, 2) if total_losses > 0 else float('inf'),
            'avg_days_held': round(sum(t['days_held'] for t in trades) / len(trades), 1) if trades else 0,
            'total_pnl': round(sum(t['return_dollars'] for t in trades), 2),
        }


def format_portfolio_status(status: PortfolioStatus) -> str:
    """Format portfolio status for display."""
    lines = [
        "=" * 50,
        "V2 PAPER TRADING PORTFOLIO",
        "=" * 50,
        "",
        f"Cash:            ${status.cash:>12,.2f}",
        f"Positions:       ${status.positions_value:>12,.2f}",
        f"Total Value:     ${status.total_value:>12,.2f}",
        "",
        f"Total P&L:       ${status.total_pnl:>+12,.2f} ({status.total_pnl_pct:+.2f}%)",
        "",
    ]
    
    if status.open_positions:
        lines.append("Open Positions:")
        lines.append("-" * 50)
        for pos in status.open_positions:
            lines.append(
                f"  {pos.ticker:<6} {pos.shares:>5} sh @ ${pos.entry_price:.2f}  "
                f"Stop: ${pos.current_stop:.2f}"
            )
    else:
        lines.append("No open positions")
    
    return "\n".join(lines)


# Quick test
if __name__ == "__main__":
    print("Testing V2 Paper Trading Engine")
    print("=" * 50)
    
    engine = PaperTradingEngine()
    status = engine.get_portfolio_status()
    print(format_portfolio_status(status))
    
    print("\n\nPosition Sizing Example:")
    print("-" * 50)
    entry = 100.0
    stop = 93.0  # 7% stop
    shares = engine.calculate_position_size(entry, stop)
    risk_per_share = entry - stop
    total_risk = risk_per_share * shares
    print(f"Entry: ${entry:.2f}, Stop: ${stop:.2f}")
    print(f"Recommended shares: {shares}")
    print(f"Position value: ${entry * shares:,.2f}")
    print(f"Risk per share: ${risk_per_share:.2f}")
    print(f"Total risk: ${total_risk:.2f} ({total_risk / status.total_value * 100:.1f}% of portfolio)")
