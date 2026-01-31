"""
Auto Trader - Automated Paper Trading Execution

Automatically enters and manages paper trades based on:
1. Breakout signals with volume confirmation
2. Risk management rules (position sizing, max positions)
3. Stop/target management

This is the "brain" that makes trading decisions without manual intervention.
"""

from datetime import date, datetime
from typing import List, Dict, Optional, Tuple
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.db import get_db
from utils.config import config
from utils.paper_trading import PaperTradingEngine
from signals.trend_template import get_compliant_stocks, check_trend_template
from signals.vcp_detector import detect_vcp
from signals.breakout import check_breakout
from collectors.earnings import is_earnings_safe
from output.alerts import (
    send_alert, 
    format_breakout_alert, 
    format_stop_hit_alert,
    format_target_hit_alert,
    format_watchlist_alert,
)


class AutoTrader:
    """
    Automated paper trading system.
    
    Runs on schedule to:
    1. Scan for new setups
    2. Monitor for breakouts
    3. Enter trades automatically
    4. Manage stops and targets
    """
    
    def __init__(self):
        self.engine = PaperTradingEngine()
        self.today = date.today()
    
    def run_morning_routine(self, send_emails: bool = True) -> Dict:
        """
        Morning routine (run at 6:30 AM ET before market open).
        
        1. Update trend template scan
        2. Identify stocks near breakout
        3. Check earnings calendar
        4. Prepare watchlist for the day
        """
        results = {
            'scan_date': self.today.isoformat(),
            'stocks_scanned': 0,
            'passing_template': 0,
            'near_breakout': [],
            'watchlist': [],
            'errors': [],
        }
        
        print("=" * 50)
        print("AUTO TRADER - MORNING ROUTINE")
        print(f"{datetime.now()}")
        print("=" * 50)
        
        # 1. Get compliant stocks from database (from last scan)
        compliant = get_compliant_stocks(self.today)
        
        if not compliant:
            print("No stocks in watchlist. Running fresh scan...")
            # Run a quick scan if nothing in DB
            from collectors.universe import get_sp500_tickers
            tickers = get_sp500_tickers()[:100]
            
            for ticker in tickers:
                try:
                    result = check_trend_template(ticker)
                    if result.passes_template:
                        compliant.append({
                            'ticker': result.ticker,
                            'price': result.price,
                            'rs_rating': result.rs_rating or 50,
                        })
                except:
                    continue
        
        results['stocks_scanned'] = len(compliant)
        results['passing_template'] = len(compliant)
        
        print(f"Found {len(compliant)} stocks passing trend template")
        
        # 2. Check each for VCP and proximity to breakout
        watchlist = []
        near_breakout = []
        
        for stock in compliant[:30]:  # Limit to top 30
            ticker = stock['ticker']
            
            try:
                # Check earnings
                earnings_safe, earnings_date = is_earnings_safe(ticker)
                if not earnings_safe:
                    print(f"  {ticker}: Skipping - earnings soon ({earnings_date})")
                    continue
                
                # Check VCP pattern
                vcp = detect_vcp(ticker)
                
                if vcp.pattern_score >= 40 and vcp.pivot_price > 0:
                    # Calculate distance to pivot
                    current_price = vcp.current_price
                    pivot = vcp.pivot_price
                    distance_pct = ((pivot - current_price) / current_price) * 100
                    
                    entry = {
                        'ticker': ticker,
                        'price': current_price,
                        'pivot': pivot,
                        'distance_pct': distance_pct,
                        'vcp_score': vcp.pattern_score,
                        'rs_rating': stock.get('rs_rating', 50),
                        'contractions': vcp.contractions,
                    }
                    
                    watchlist.append(entry)
                    
                    # Near breakout = within 3% of pivot
                    if -1 <= distance_pct <= 3:
                        near_breakout.append(entry)
                        print(f"  {ticker}: NEAR BREAKOUT - {distance_pct:.1f}% from pivot ${pivot:.2f}")
                    else:
                        print(f"  {ticker}: Watching - {distance_pct:.1f}% from pivot")
                        
            except Exception as e:
                results['errors'].append(f"{ticker}: {str(e)[:50]}")
        
        results['watchlist'] = watchlist
        results['near_breakout'] = near_breakout
        
        # 3. Send morning alert
        if send_emails and (watchlist or near_breakout):
            self._send_morning_alert(watchlist, near_breakout)
        
        print()
        print(f"Watchlist: {len(watchlist)} stocks")
        print(f"Near breakout: {len(near_breakout)} stocks")
        
        return results
    
    def run_breakout_check(self, send_emails: bool = True) -> Dict:
        """
        Check for breakouts and auto-enter trades.
        
        Run every 30 min during market hours.
        """
        results = {
            'check_time': datetime.now().isoformat(),
            'breakouts_found': [],
            'trades_entered': [],
            'skipped': [],
            'errors': [],
        }
        
        print("=" * 50)
        print("AUTO TRADER - BREAKOUT CHECK")
        print(f"{datetime.now()}")
        print("=" * 50)
        
        # Get current portfolio status
        status = self.engine.get_portfolio_status()
        open_positions = len(status.open_positions)
        open_tickers = [p.ticker for p in status.open_positions]
        
        print(f"Open positions: {open_positions}/{config.V2_MAX_POSITIONS}")
        print(f"Available cash: ${status.cash:,.2f}")
        
        if open_positions >= config.V2_MAX_POSITIONS:
            print("Max positions reached - skipping new entries")
            return results
        
        # Get watchlist stocks
        compliant = get_compliant_stocks(self.today)
        
        for stock in compliant[:20]:
            ticker = stock['ticker']
            
            # Skip if already in position
            if ticker in open_tickers:
                continue
            
            try:
                # Get VCP for pivot price
                vcp = detect_vcp(ticker)
                
                if vcp.pivot_price <= 0 or vcp.pattern_score < 40:
                    continue
                
                # Check for breakout
                signal = check_breakout(ticker, vcp.pivot_price)
                
                if signal.is_breakout and signal.breakout_quality in ['A', 'B']:
                    print(f"  🚀 BREAKOUT: {ticker} - Grade {signal.breakout_quality}")
                    
                    results['breakouts_found'].append({
                        'ticker': ticker,
                        'price': signal.current_price,
                        'pivot': signal.pivot_price,
                        'volume_ratio': signal.volume_ratio,
                        'quality': signal.breakout_quality,
                    })
                    
                    # Check if we should enter
                    should_enter, reason = self._should_enter_trade(ticker, signal, status)
                    
                    if should_enter:
                        trade_result = self._enter_trade(ticker, signal, send_emails)
                        if trade_result:
                            results['trades_entered'].append(trade_result)
                    else:
                        results['skipped'].append({
                            'ticker': ticker,
                            'reason': reason,
                        })
                        print(f"    Skipped: {reason}")
                        
            except Exception as e:
                results['errors'].append(f"{ticker}: {str(e)[:50]}")
        
        print()
        print(f"Breakouts: {len(results['breakouts_found'])}")
        print(f"Trades entered: {len(results['trades_entered'])}")
        
        return results
    
    def run_evening_routine(self, send_emails: bool = True) -> Dict:
        """
        Evening routine (run at 6 PM ET after market close).
        
        1. Check stops and targets
        2. Update trailing stops
        3. Take daily snapshot
        4. Send daily report
        """
        results = {
            'date': self.today.isoformat(),
            'stops_triggered': [],
            'targets_triggered': [],
            'portfolio_value': 0,
            'daily_pnl': 0,
        }
        
        print("=" * 50)
        print("AUTO TRADER - EVENING ROUTINE")
        print(f"{datetime.now()}")
        print("=" * 50)
        
        # 1. Check stops and targets
        print("Checking stops and targets...")
        triggered = self.engine.check_stops_and_targets()
        
        for t in triggered:
            if t.exit_reason == 'STOP':
                results['stops_triggered'].append(t)
                print(f"  🛑 STOP: {t.ticker} at ${t.exit_price:.2f} ({t.return_pct:+.1f}%)")
                
                if send_emails:
                    msg = format_stop_hit_alert(
                        t.ticker, t.entry_price, t.exit_price,
                        t.return_pct, t.return_dollars, t.days_held
                    )
                    send_alert("STOP_HIT", t.ticker, msg)
                    
            elif t.exit_reason == 'TARGET':
                results['targets_triggered'].append(t)
                print(f"  🎯 TARGET: {t.ticker} at ${t.exit_price:.2f} ({t.return_pct:+.1f}%)")
                
                if send_emails:
                    msg = format_target_hit_alert(
                        t.ticker, t.entry_price, t.exit_price,
                        t.return_pct, t.return_dollars, t.days_held
                    )
                    send_alert("TARGET_HIT", t.ticker, msg)
        
        # 2. Take daily snapshot
        print("Taking daily snapshot...")
        self.engine.take_daily_snapshot()
        
        # 3. Get final portfolio status
        status = self.engine.get_portfolio_status()
        results['portfolio_value'] = status.total_value
        results['daily_pnl'] = status.daily_pnl
        
        print()
        print(f"Portfolio Value: ${status.total_value:,.2f}")
        print(f"Daily P&L: ${status.daily_pnl:+,.2f}")
        print(f"Total P&L: ${status.total_pnl:+,.2f} ({status.total_pnl_pct:+.2f}%)")
        print(f"Open positions: {len(status.open_positions)}")
        
        # 4. Send daily report
        if send_emails:
            self._send_daily_report(status, triggered)
        
        return results
    
    def _should_enter_trade(
        self, 
        ticker: str, 
        signal, 
        status
    ) -> Tuple[bool, str]:
        """
        Decide if we should enter a trade.
        
        Returns (should_enter, reason)
        """
        # Check max positions
        if len(status.open_positions) >= config.V2_MAX_POSITIONS:
            return False, "Max positions reached"
        
        # Check available cash
        min_position = 1000  # Minimum $1000 position
        if status.cash < min_position:
            return False, "Insufficient cash"
        
        # Check if extended (too far above pivot)
        if signal.breakout_pct > 5:
            return False, f"Extended {signal.breakout_pct:.1f}%"
        
        # Check earnings
        earnings_safe, _ = is_earnings_safe(ticker)
        if not earnings_safe:
            return False, "Near earnings"
        
        # Check breakout quality
        if signal.breakout_quality not in ['A', 'B']:
            return False, f"Low quality ({signal.breakout_quality})"
        
        return True, "OK"
    
    def _enter_trade(self, ticker: str, signal, send_emails: bool) -> Optional[Dict]:
        """
        Execute a paper trade entry.
        """
        try:
            entry_price = signal.current_price
            stop_price = signal.suggested_stop
            target_price = signal.suggested_target
            
            # Calculate position size
            shares = self.engine.calculate_position_size(entry_price, stop_price)
            
            if shares <= 0:
                print(f"    Position size too small for {ticker}")
                return None
            
            # Enter the trade
            trade_id = self.engine.enter_trade(
                ticker=ticker,
                entry_price=entry_price,
                shares=shares,
                stop_price=stop_price,
                target_price=target_price,
                notes=f"Auto-entry on breakout. Quality: {signal.breakout_quality}"
            )
            
            print(f"    ✅ ENTERED: {ticker} - {shares} shares @ ${entry_price:.2f}")
            print(f"       Stop: ${stop_price:.2f} | Target: ${target_price:.2f}")
            
            # Send alert
            if send_emails:
                msg = format_breakout_alert(
                    ticker, signal.pivot_price, entry_price,
                    signal.volume_ratio, signal.breakout_quality
                )
                send_alert("TRADE_ENTRY", ticker, msg)
            
            return {
                'trade_id': trade_id,
                'ticker': ticker,
                'shares': shares,
                'entry_price': entry_price,
                'stop': stop_price,
                'target': target_price,
            }
            
        except Exception as e:
            print(f"    ❌ Error entering {ticker}: {e}")
            return None
    
    def _send_morning_alert(self, watchlist: List, near_breakout: List):
        """Send morning scan alert."""
        lines = [
            "☀️ MORNING SCAN RESULTS",
            "=" * 50,
            "",
            f"Date: {self.today}",
            f"Stocks on watchlist: {len(watchlist)}",
            "",
        ]
        
        if near_breakout:
            lines.append("⚡ NEAR BREAKOUT (within 3% of pivot):")
            lines.append("-" * 40)
            for s in near_breakout[:5]:
                lines.append(
                    f"  {s['ticker']:<6} "
                    f"Price: ${s['price']:.2f}  "
                    f"Pivot: ${s['pivot']:.2f}  "
                    f"({s['distance_pct']:+.1f}%)"
                )
            lines.append("")
        
        if watchlist:
            lines.append("📋 FULL WATCHLIST:")
            lines.append("-" * 40)
            for s in watchlist[:10]:
                lines.append(
                    f"  {s['ticker']:<6} "
                    f"VCP: {s['vcp_score']}  "
                    f"RS: {s['rs_rating']:.0f}"
                )
        
        lines.extend([
            "",
            "System will auto-enter on confirmed breakouts.",
            "",
            "---",
            "Stock Radar V2 Auto Trader",
        ])
        
        msg = "\n".join(lines)
        send_alert("MORNING_SCAN", "SYSTEM", msg)
    
    def _send_daily_report(self, status, triggered: List):
        """Send end of day report."""
        lines = [
            "📊 DAILY PORTFOLIO REPORT",
            "=" * 50,
            "",
            f"Date: {self.today}",
            "",
            f"Portfolio Value: ${status.total_value:,.2f}",
            f"Cash: ${status.cash:,.2f}",
            f"Positions: ${status.positions_value:,.2f}",
            "",
            f"Daily P&L: ${status.daily_pnl:+,.2f} ({status.daily_pnl_pct:+.2f}%)",
            f"Total P&L: ${status.total_pnl:+,.2f} ({status.total_pnl_pct:+.2f}%)",
            "",
        ]
        
        if status.open_positions:
            lines.append(f"OPEN POSITIONS ({len(status.open_positions)}):")
            lines.append("-" * 40)
            for p in status.open_positions:
                lines.append(
                    f"  {p.ticker:<6} "
                    f"{p.shares} sh @ ${p.entry_price:.2f}  "
                    f"Stop: ${p.current_stop:.2f}"
                )
            lines.append("")
        
        if triggered:
            lines.append(f"TRADES CLOSED TODAY ({len(triggered)}):")
            lines.append("-" * 40)
            for t in triggered:
                lines.append(
                    f"  {t.ticker:<6} "
                    f"{t.exit_reason}  "
                    f"${t.exit_price:.2f}  "
                    f"{t.return_pct:+.1f}%"
                )
            lines.append("")
        
        # Get performance stats
        stats = self.engine.get_performance_stats()
        if stats.get('total_trades', 0) > 0:
            lines.extend([
                "PERFORMANCE STATS:",
                "-" * 40,
                f"  Total trades: {stats['total_trades']}",
                f"  Win rate: {stats.get('win_rate', 0):.1f}%",
                f"  Profit factor: {stats.get('profit_factor', 0):.2f}",
                "",
            ])
        
        lines.extend([
            "---",
            "Stock Radar V2 Auto Trader",
        ])
        
        msg = "\n".join(lines)
        send_alert("DAILY_REPORT", "SYSTEM", msg)


# CLI entry points for cron
def morning_routine():
    """Run morning routine - called from cron."""
    trader = AutoTrader()
    return trader.run_morning_routine(send_emails=True)


def breakout_check():
    """Check for breakouts - called from cron."""
    trader = AutoTrader()
    return trader.run_breakout_check(send_emails=True)


def evening_routine():
    """Run evening routine - called from cron."""
    trader = AutoTrader()
    return trader.run_evening_routine(send_emails=True)


if __name__ == "__main__":
    # Test run
    trader = AutoTrader()
    
    print("\n" + "=" * 60)
    print("TESTING AUTO TRADER")
    print("=" * 60)
    
    # Run morning routine
    morning_results = trader.run_morning_routine(send_emails=False)
    
    print("\n" + "=" * 60)
    
    # Run breakout check
    breakout_results = trader.run_breakout_check(send_emails=False)
    
    print("\n" + "=" * 60)
    
    # Run evening routine
    evening_results = trader.run_evening_routine(send_emails=False)
