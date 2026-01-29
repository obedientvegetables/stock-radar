"""
Stock Radar Configuration

Loads settings from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(Path(__file__).parent.parent / ".env")


class Config:
    """Central configuration for Stock Radar."""

    # Paths
    BASE_DIR = Path(__file__).parent.parent
    DATA_DIR = BASE_DIR / "data"
    LOGS_DIR = BASE_DIR / "logs"
    DB_PATH = DATA_DIR / "radar.db"

    # Email Configuration
    EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
    EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
    EMAIL_USERNAME = os.getenv("EMAIL_USERNAME")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
    EMAIL_TO = os.getenv("EMAIL_TO")
    EMAIL_FROM = os.getenv("EMAIL_FROM")

    # API Keys
    ADANOS_API_KEY = os.getenv("ADANOS_API_KEY")
    ADANOS_API_BASE = os.getenv("ADANOS_API_BASE", "https://api.adanos.org/reddit/stocks/v1")
    STOCKTWITS_ACCESS_TOKEN = os.getenv("STOCKTWITS_ACCESS_TOKEN")

    # SEC EDGAR (required for insider trading data)
    SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "StockRadar contact@example.com")
    SEC_RATE_LIMIT = 5  # requests per second (conservative, SEC allows 10)

    # Scoring Thresholds
    INSIDER_MIN_SCORE = int(os.getenv("INSIDER_MIN_SCORE", "15"))
    OPTIONS_MIN_SCORE = int(os.getenv("OPTIONS_MIN_SCORE", "15"))
    SOCIAL_MIN_SCORE = int(os.getenv("SOCIAL_MIN_SCORE", "10"))

    # Signal Weights (max scores)
    INSIDER_MAX_SCORE = 30
    OPTIONS_MAX_SCORE = 25
    SOCIAL_MAX_SCORE = 20
    TOTAL_MAX_SCORE = INSIDER_MAX_SCORE + OPTIONS_MAX_SCORE + SOCIAL_MAX_SCORE  # 75

    # Risk Management
    MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.10"))
    DEFAULT_STOP_PCT = float(os.getenv("DEFAULT_STOP_PCT", "0.10"))  # 10% stop loss
    DEFAULT_TARGET_PCT = float(os.getenv("DEFAULT_TARGET_PCT", "0.20"))  # 20% profit target

    # Stock of the Day
    STOCK_OF_DAY_MIN_SCORE = 25  # Minimum score to qualify as Stock of the Day

    # Paper Trading
    PAPER_PORTFOLIO_SIZE = float(os.getenv("PAPER_PORTFOLIO_SIZE", "10000"))

    # Lookback periods
    INSIDER_LOOKBACK_DAYS = 14
    OPTIONS_VOLUME_LOOKBACK = 20
    SOCIAL_VELOCITY_LOOKBACK = 7

    # Market regime thresholds
    VIX_HIGH = 25
    VIX_EXTREME = 35
    FEAR_GREED_LOW = 25

    # =========================================================
    # V2 MOMENTUM TRADING SYSTEM CONFIGURATION
    # =========================================================

    # Trend Template Thresholds (Minervini criteria)
    MIN_STOCK_PRICE = float(os.getenv("MIN_STOCK_PRICE", "10.0"))
    MIN_MARKET_CAP = float(os.getenv("MIN_MARKET_CAP", "500000000"))  # $500M
    MIN_AVG_VOLUME = int(os.getenv("MIN_AVG_VOLUME", "500000"))  # shares/day
    RS_MIN_RATING = int(os.getenv("RS_MIN_RATING", "70"))  # Top 30% of market

    # Fundamental Thresholds
    MIN_EPS_GROWTH = float(os.getenv("MIN_EPS_GROWTH", "15"))  # % YoY
    MIN_REVENUE_GROWTH = float(os.getenv("MIN_REVENUE_GROWTH", "10"))  # % YoY

    # VCP Pattern Detection
    MAX_BASE_DEPTH = float(os.getenv("MAX_BASE_DEPTH", "35"))  # % max pullback in base
    MIN_CONTRACTIONS = int(os.getenv("MIN_CONTRACTIONS", "2"))
    MAX_CONTRACTIONS = int(os.getenv("MAX_CONTRACTIONS", "5"))
    MIN_BASE_LENGTH = int(os.getenv("MIN_BASE_LENGTH", "15"))  # days
    MAX_BASE_LENGTH = int(os.getenv("MAX_BASE_LENGTH", "65"))  # days
    VOLUME_DRY_UP_THRESHOLD = float(os.getenv("VOLUME_DRY_UP_THRESHOLD", "0.5"))  # Volume < 50% of avg

    # V2 Position Sizing
    V2_PAPER_PORTFOLIO_SIZE = float(os.getenv("V2_PAPER_PORTFOLIO_SIZE", "50000"))  # $50K paper trading
    V2_MAX_POSITION_PCT = float(os.getenv("V2_MAX_POSITION_PCT", "0.20"))  # Max 20% in single position
    V2_MAX_POSITIONS = int(os.getenv("V2_MAX_POSITIONS", "6"))  # Max concurrent positions
    V2_DEFAULT_STOP_PCT = float(os.getenv("V2_DEFAULT_STOP_PCT", "0.07"))  # 7% stop loss
    V2_DEFAULT_TARGET_PCT = float(os.getenv("V2_DEFAULT_TARGET_PCT", "0.20"))  # 20% profit target
    V2_MAX_RISK_PER_TRADE = float(os.getenv("V2_MAX_RISK_PER_TRADE", "0.02"))  # 2% portfolio risk per trade

    # Breakout Detection
    BREAKOUT_VOLUME_MULTIPLIER = float(os.getenv("BREAKOUT_VOLUME_MULTIPLIER", "1.5"))  # 1.5x avg volume
    MAX_CHASE_PCT = float(os.getenv("MAX_CHASE_PCT", "0.05"))  # Don't buy more than 5% above pivot
    EARNINGS_BUFFER_DAYS = int(os.getenv("EARNINGS_BUFFER_DAYS", "5"))  # No trades within 5 days of earnings

    # Stop Management
    BREAKEVEN_TRIGGER_PCT = float(os.getenv("BREAKEVEN_TRIGGER_PCT", "0.05"))  # Move to breakeven after +5%
    TRAILING_TRIGGER_PCT = float(os.getenv("TRAILING_TRIGGER_PCT", "0.10"))  # Start trailing after +10%
    TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.10"))  # Trail at 10% from high

    # Alerts Configuration
    ALERT_EMAIL = os.getenv("ALERT_EMAIL", "true").lower() == "true"
    ALERT_SMS = os.getenv("ALERT_SMS", "false").lower() == "true"
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
    ALERT_PHONE_NUMBER = os.getenv("ALERT_PHONE_NUMBER")

    # External APIs for Fundamentals
    FMP_API_KEY = os.getenv("FMP_API_KEY")  # Financial Modeling Prep
    FMP_API_BASE = "https://financialmodelingprep.com/api/v3"
    ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

    # Watchlist Settings
    WATCHLIST_EXPIRY_DAYS = int(os.getenv("WATCHLIST_EXPIRY_DAYS", "10"))  # Remove after 10 days if not triggered
    WATCHLIST_MIN_SCORE = int(os.getenv("WATCHLIST_MIN_SCORE", "60"))  # Min total score to add to watchlist

    # Scoring Weights for V2
    V2_TREND_WEIGHT = float(os.getenv("V2_TREND_WEIGHT", "0.35"))  # 35%
    V2_FUNDAMENTAL_WEIGHT = float(os.getenv("V2_FUNDAMENTAL_WEIGHT", "0.25"))  # 25%
    V2_PATTERN_WEIGHT = float(os.getenv("V2_PATTERN_WEIGHT", "0.25"))  # 25%
    V2_RS_WEIGHT = float(os.getenv("V2_RS_WEIGHT", "0.15"))  # 15%

    @classmethod
    def ensure_dirs(cls):
        """Create required directories if they don't exist."""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def validate(cls):
        """Check that required configuration is present."""
        issues = []

        if not cls.SEC_USER_AGENT or "example.com" in cls.SEC_USER_AGENT:
            issues.append("SEC_USER_AGENT should be set to your email for SEC EDGAR access")

        if not cls.EMAIL_USERNAME or not cls.EMAIL_PASSWORD:
            issues.append("Email credentials not configured (EMAIL_USERNAME, EMAIL_PASSWORD)")

        return issues


# Singleton instance
config = Config()

# Ensure directories exist on import
config.ensure_dirs()
