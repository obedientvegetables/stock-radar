"""
Tests for the scoring algorithm overhaul.

Verifies:
1. Quality filter rejects penny stocks and micro-caps
2. Insider $50K minimum purchase threshold works
3. Options liquidity gate blocks illiquid options
4. No-trade day logic triggers correctly
5. Scaling insider bonus works correctly
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import date

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import config


class TestQualityFilter:
    """Test stock quality filter (Fix 1)."""

    def _mock_yf_ticker(self, price=100.0, market_cap=10_000_000_000, avg_volume=2_000_000):
        """Create a mock yfinance Ticker with given attributes."""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            'currentPrice': price,
            'regularMarketPrice': price,
            'marketCap': market_cap,
            'averageVolume': avg_volume,
        }
        return mock_ticker

    @patch('signals.quality_filter.yf')
    def test_penny_stock_rejected(self, mock_yf):
        """VNRX at $0.28 should be rejected."""
        from signals.quality_filter import passes_quality_filter

        mock_yf.Ticker.return_value = self._mock_yf_ticker(price=0.28, market_cap=50_000_000, avg_volume=100_000)

        passes, reason = passes_quality_filter("VNRX")
        assert passes is False
        assert "Price" in reason
        assert "below" in reason

    @patch('signals.quality_filter.yf')
    def test_upxi_rejected_on_price(self, mock_yf):
        """UPXI at $2.10 should be rejected."""
        from signals.quality_filter import passes_quality_filter

        mock_yf.Ticker.return_value = self._mock_yf_ticker(price=2.10, market_cap=100_000_000, avg_volume=200_000)

        passes, reason = passes_quality_filter("UPXI")
        assert passes is False
        assert "Price" in reason

    @patch('signals.quality_filter.yf')
    def test_micro_cap_rejected(self, mock_yf):
        """Stock with $100M market cap should be rejected (need $500M+)."""
        from signals.quality_filter import passes_quality_filter

        mock_yf.Ticker.return_value = self._mock_yf_ticker(price=15.0, market_cap=100_000_000, avg_volume=1_000_000)

        passes, reason = passes_quality_filter("SMALL")
        assert passes is False
        assert "Market cap" in reason

    @patch('signals.quality_filter.yf')
    def test_illiquid_stock_rejected(self, mock_yf):
        """Stock with 50K avg volume should be rejected (need 500K+)."""
        from signals.quality_filter import passes_quality_filter

        mock_yf.Ticker.return_value = self._mock_yf_ticker(price=50.0, market_cap=5_000_000_000, avg_volume=50_000)

        passes, reason = passes_quality_filter("ILLIQ")
        assert passes is False
        assert "volume" in reason.lower()

    @patch('signals.quality_filter.yf')
    def test_quality_stock_passes(self, mock_yf):
        """ALLY-like stock ($50+, large cap, liquid) should pass."""
        from signals.quality_filter import passes_quality_filter

        mock_yf.Ticker.return_value = self._mock_yf_ticker(price=37.0, market_cap=10_000_000_000, avg_volume=5_000_000)

        passes, reason = passes_quality_filter("ALLY")
        assert passes is True
        assert "Passes" in reason

    @patch('signals.quality_filter.yf')
    def test_filter_universe(self, mock_yf):
        """Test bulk filtering of multiple tickers."""
        from signals.quality_filter import filter_universe

        def side_effect(ticker):
            mocks = {
                'AAPL': self._mock_yf_ticker(price=180.0, market_cap=2_800_000_000_000, avg_volume=50_000_000),
                'VNRX': self._mock_yf_ticker(price=0.28, market_cap=50_000_000, avg_volume=100_000),
                'UPXI': self._mock_yf_ticker(price=2.10, market_cap=100_000_000, avg_volume=200_000),
                'ALLY': self._mock_yf_ticker(price=37.0, market_cap=10_000_000_000, avg_volume=5_000_000),
            }
            return mocks.get(ticker, self._mock_yf_ticker())

        mock_yf.Ticker.side_effect = side_effect

        passed, rejected = filter_universe(['AAPL', 'VNRX', 'UPXI', 'ALLY'])

        assert 'AAPL' in passed
        assert 'ALLY' in passed
        assert len(rejected) == 2
        rejected_tickers = [t for t, _ in rejected]
        assert 'VNRX' in rejected_tickers
        assert 'UPXI' in rejected_tickers


class TestInsiderMinimum:
    """Test insider $50K minimum purchase threshold (Fix 2)."""

    @patch('signals.insider_signal.get_db')
    def test_small_purchase_filtered(self, mock_get_db):
        """A $9,885 purchase should not count as meaningful."""
        from signals.insider_signal import get_insider_activity

        # Mock DB returning a small purchase
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                'insider_name': 'John Doe',
                'insider_title': 'Director',
                'trade_type': 'P',
                'shares': 1000,
                'price_per_share': 9.885,
                'total_value': 9885.0,
                'trade_date': '2026-01-20',
            }
        ]
        mock_conn.execute.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        activity = get_insider_activity("TEST")

        # Should not count as meaningful buying
        assert activity["has_buying"] is False
        assert activity["filtered_out_count"] == 1

    @patch('signals.insider_signal.get_db')
    def test_large_purchase_counts(self, mock_get_db):
        """A $991K purchase should count as meaningful."""
        from signals.insider_signal import get_insider_activity

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                'insider_name': 'Jane CEO',
                'insider_title': 'CEO',
                'trade_type': 'P',
                'shares': 20000,
                'price_per_share': 49.55,
                'total_value': 991000.0,
                'trade_date': '2026-01-20',
            }
        ]
        mock_conn.execute.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        activity = get_insider_activity("ALLY")

        assert activity["has_buying"] is True
        assert activity["total_value"] == 991000.0
        assert activity["ceo_cfo_buying"] is True

    @patch('signals.insider_signal.get_db')
    def test_scaling_bonus_1m_plus(self, mock_get_db):
        """$1M+ purchase should get +6 bonus."""
        from signals.insider_signal import score_insider

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                'insider_name': 'Jane CEO',
                'insider_title': 'CEO',
                'trade_type': 'P',
                'shares': 30000,
                'price_per_share': 50.0,
                'total_value': 1_500_000.0,
                'trade_date': '2026-01-20',
            }
        ]
        mock_conn.execute.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        signal = score_insider("TEST")

        # Should have: +5 base + 12 CEO + 6 (>$1M) = 23
        assert signal.score == 23
        assert any("+6" in item for item in signal.details["score_breakdown"])

    @patch('signals.insider_signal.get_db')
    def test_scaling_bonus_500k(self, mock_get_db):
        """$500K-$1M purchase should get +4 bonus."""
        from signals.insider_signal import score_insider

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                'insider_name': 'Bob CFO',
                'insider_title': 'CFO',
                'trade_type': 'P',
                'shares': 10000,
                'price_per_share': 75.0,
                'total_value': 750_000.0,
                'trade_date': '2026-01-20',
            }
        ]
        mock_conn.execute.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        signal = score_insider("TEST")

        # Should have: +5 base + 12 CFO + 4 ($500K-$1M) = 21
        assert signal.score == 21
        assert any("+4" in item for item in signal.details["score_breakdown"])

    @patch('signals.insider_signal.get_db')
    def test_scaling_bonus_100k(self, mock_get_db):
        """$100K-$500K purchase should get +2 bonus."""
        from signals.insider_signal import score_insider

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                'insider_name': 'Alice President',
                'insider_title': 'President',
                'trade_type': 'P',
                'shares': 2000,
                'price_per_share': 100.0,
                'total_value': 200_000.0,
                'trade_date': '2026-01-20',
            }
        ]
        mock_conn.execute.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        signal = score_insider("TEST")

        # Should have: +5 base + 6 C-Suite + 2 ($100K-$500K) = 13
        assert signal.score == 13
        assert any("+2" in item for item in signal.details["score_breakdown"])


class TestOptionsLiquidityGate:
    """Test options liquidity gate (Fix 3)."""

    @patch('signals.options_signal.get_db')
    def test_illiquid_options_zero_score(self, mock_get_db):
        """Options with avg volume < 500 should score 0."""
        from signals.options_signal import score_options

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        # Return options data with very low average volume
        mock_row = {
            'call_volume': 200,
            'put_volume': 50,
            'call_oi': 300,
            'put_oi': 100,
            'avg_call_volume_20d': 100,  # Very low
            'avg_put_volume_20d': 30,    # Very low
            'call_volume_ratio': 2.0,     # Would normally score
            'put_call_ratio': 0.25,
            'unusual_calls': 1,
            'unusual_puts': 0,
        }
        mock_cursor.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        signal = score_options("ILLIQ")

        assert signal.score == 0
        assert "illiquid" in signal.details.get("reason", "").lower()

    @patch('signals.options_signal.get_db')
    def test_low_open_interest_zero_score(self, mock_get_db):
        """Options with open interest < 1000 should score 0."""
        from signals.options_signal import score_options

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_row = {
            'call_volume': 1000,
            'put_volume': 200,
            'call_oi': 400,       # Low OI
            'put_oi': 200,        # Low OI
            'avg_call_volume_20d': 400,
            'avg_put_volume_20d': 200,  # Total avg = 600 (passes volume check)
            'call_volume_ratio': 2.5,
            'put_call_ratio': 0.2,
            'unusual_calls': 1,
            'unusual_puts': 0,
        }
        mock_cursor.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        signal = score_options("LOWOI")

        assert signal.score == 0
        assert "open interest" in signal.details.get("reason", "").lower()

    @patch('signals.options_signal.get_db')
    def test_liquid_options_scores_normally(self, mock_get_db):
        """Options with sufficient liquidity should score normally."""
        from signals.options_signal import score_options

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_row = {
            'call_volume': 5000,
            'put_volume': 1000,
            'call_oi': 10000,
            'put_oi': 5000,
            'avg_call_volume_20d': 2000,
            'avg_put_volume_20d': 800,   # Total avg = 2800 (passes)
            'call_volume_ratio': 2.5,     # 2-3x = +8
            'put_call_ratio': 0.2,        # < 0.5 = +4
            'unusual_calls': 1,           # +3
            'unusual_puts': 0,
        }
        mock_cursor.fetchone.return_value = mock_row
        mock_conn.execute.return_value = mock_cursor
        mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        signal = score_options("LIQUID")

        # Should score: +8 (2.5x) + 4 (low P/C) + 3 (unusual) = 15
        assert signal.score == 15


class TestNoTradeDays:
    """Test no-trade day logic (Fix 4)."""

    def _make_signal(self, ticker, insider=0, options=0, social=0):
        """Create a mock CombinedSignal."""
        from signals.combiner import CombinedSignal
        from signals.insider_signal import InsiderSignal
        from signals.options_signal import OptionsSignal
        from signals.social_signal import SocialSignal

        return CombinedSignal(
            ticker=ticker,
            date=date.today(),
            insider_score=insider,
            options_score=options,
            social_score=social,
            total_score=insider + options + social,
            insider_signal=InsiderSignal(ticker, insider, 0, 0, False, False, 0, "", "", "", {}),
            options_signal=OptionsSignal(ticker, options, 0, 0, 0, 0, False, False, {}),
            social_signal=SocialSignal(ticker, social, 0, 0, 0, 0, 0.0, False, {}),
            action="WATCH",
            tier="C",
            position_size="NONE",
            entry_price=None,
            stop_price=None,
            target_price=None,
            notes="",
        )

    def test_no_trade_when_score_too_low(self):
        """Best candidate scoring 28 should trigger NO_TRADE."""
        from signals.combiner import select_stock_of_the_day

        candidates = [
            self._make_signal("LOW1", insider=15, options=8, social=5),  # Score 28
            self._make_signal("LOW2", insider=10, options=5, social=3),  # Score 18
        ]

        pick, reason = select_stock_of_the_day(candidates)

        assert pick is None
        assert "below minimum" in reason

    def test_no_trade_when_too_few_signals(self):
        """Stock with only 1 active signal should trigger NO_TRADE."""
        from signals.combiner import select_stock_of_the_day

        candidates = [
            self._make_signal("ONESIG", insider=20, options=0, social=20),  # Score 40, but only 2 signals
        ]

        # With MIN_ACTIVE_SIGNALS = 2, this should pass (2 signals active: insider + social)
        pick, reason = select_stock_of_the_day(candidates)
        assert pick is not None  # 2 active signals = passes

        # Now test with only 1 signal
        candidates = [
            self._make_signal("ONESIG", insider=40, options=0, social=0),  # Score 40, only 1 signal
        ]

        pick, reason = select_stock_of_the_day(candidates)
        assert pick is None
        assert "active signal" in reason

    def test_no_trade_when_no_strong_signal(self):
        """Stock with no insider/options >= 10 should trigger NO_TRADE."""
        from signals.combiner import select_stock_of_the_day

        candidates = [
            self._make_signal("WEAK", insider=8, options=8, social=20),  # Score 36, passes min score
        ]

        pick, reason = select_stock_of_the_day(candidates)

        assert pick is None
        assert "No strong" in reason

    def test_trade_when_quality_met(self):
        """Stock meeting all criteria should be selected."""
        from signals.combiner import select_stock_of_the_day

        candidates = [
            self._make_signal("GOOD", insider=17, options=12, social=10),  # Score 39
        ]

        pick, reason = select_stock_of_the_day(candidates)

        assert pick is not None
        assert pick.ticker == "GOOD"
        assert "Meets all quality criteria" in reason

    def test_highest_score_selected(self):
        """Among qualifying candidates, highest score should win."""
        from signals.combiner import select_stock_of_the_day

        candidates = [
            self._make_signal("MED", insider=15, options=12, social=10),   # Score 37
            self._make_signal("HIGH", insider=20, options=15, social=12),  # Score 47
            self._make_signal("LOW", insider=12, options=10, social=5),    # Score 27 (below min)
        ]

        pick, reason = select_stock_of_the_day(candidates)

        assert pick is not None
        assert pick.ticker == "HIGH"

    def test_empty_candidates(self):
        """Empty candidate list should return NO_TRADE."""
        from signals.combiner import select_stock_of_the_day

        pick, reason = select_stock_of_the_day([])

        assert pick is None
        assert "No candidates" in reason


class TestConfigDefaults:
    """Test that configuration defaults are set correctly."""

    def test_min_stock_price(self):
        assert config.MIN_STOCK_PRICE == 5.0

    def test_min_market_cap(self):
        assert config.MIN_MARKET_CAP == 500_000_000

    def test_min_avg_volume(self):
        assert config.MIN_AVG_VOLUME == 500_000

    def test_min_insider_purchase(self):
        assert config.MIN_INSIDER_PURCHASE == 50_000

    def test_min_options_avg_volume(self):
        assert config.MIN_OPTIONS_AVG_VOLUME == 500

    def test_min_open_interest(self):
        assert config.MIN_OPEN_INTEREST == 1000

    def test_min_sotd_score(self):
        assert config.STOCK_OF_DAY_MIN_SCORE == 35

    def test_min_active_signals(self):
        assert config.MIN_ACTIVE_SIGNALS == 2

    def test_min_insider_or_options_score(self):
        assert config.MIN_INSIDER_OR_OPTIONS_SCORE == 10


class TestInsiderTitleClassification:
    """Test that insider title classification works correctly."""

    def test_ceo(self):
        from signals.insider_signal import classify_insider_title
        assert classify_insider_title("Chief Executive Officer") == "CEO/CFO"
        assert classify_insider_title("CEO") == "CEO/CFO"

    def test_cfo(self):
        from signals.insider_signal import classify_insider_title
        assert classify_insider_title("Chief Financial Officer") == "CEO/CFO"
        assert classify_insider_title("CFO") == "CEO/CFO"

    def test_csuite(self):
        from signals.insider_signal import classify_insider_title
        assert classify_insider_title("President") == "C-Suite"
        assert classify_insider_title("COO") == "C-Suite"
        assert classify_insider_title("Chief Technology Officer") == "C-Suite"

    def test_director(self):
        from signals.insider_signal import classify_insider_title
        assert classify_insider_title("Director") == "Director"
        assert classify_insider_title("Independent Director") == "Director"

    def test_vice_president_not_csuite(self):
        from signals.insider_signal import classify_insider_title
        assert classify_insider_title("Vice President") == "Other"
