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

    # =========================================================================
    # V2 CONFIGURATION: Minervini Momentum System
    # =========================================================================

    # Quality Filters
    MIN_STOCK_PRICE = float(os.getenv("MIN_STOCK_PRICE", "10.0"))
    MIN_MARKET_CAP = float(os.getenv("MIN_MARKET_CAP", "500000000"))  # $500M
    MIN_AVG_VOLUME = int(os.getenv("MIN_AVG_VOLUME", "500000"))  # shares/day
    RS_MIN_RATING = int(os.getenv("RS_MIN_RATING", "70"))  # Top 30%

    # Fundamental Thresholds
    MIN_EPS_GROWTH = float(os.getenv("MIN_EPS_GROWTH", "15"))  # %
    MIN_REVENUE_GROWTH = float(os.getenv("MIN_REVENUE_GROWTH", "10"))  # %

    # VCP Pattern Settings
    MAX_BASE_DEPTH = float(os.getenv("MAX_BASE_DEPTH", "35"))  # %
    MIN_CONTRACTIONS = int(os.getenv("MIN_CONTRACTIONS", "2"))
    MAX_CONTRACTIONS = int(os.getenv("MAX_CONTRACTIONS", "5"))

    # V2 Position Sizing
    V2_PORTFOLIO_SIZE = float(os.getenv("V2_PORTFOLIO_SIZE", "50000"))
    V2_MAX_POSITION_PCT = float(os.getenv("V2_MAX_POSITION_PCT", "0.20"))
    V2_MAX_POSITIONS = int(os.getenv("V2_MAX_POSITIONS", "6"))
    V2_MAX_RISK_PER_TRADE = float(os.getenv("V2_MAX_RISK_PER_TRADE", "0.02"))  # 2%
    V2_DEFAULT_STOP_PCT = float(os.getenv("V2_DEFAULT_STOP_PCT", "0.07"))  # 7%
    V2_DEFAULT_TARGET_PCT = float(os.getenv("V2_DEFAULT_TARGET_PCT", "0.20"))  # 20%

    # Breakout Confirmation
    VOLUME_BREAKOUT_MULTIPLIER = float(os.getenv("VOLUME_BREAKOUT_MULTIPLIER", "1.5"))
    EARNINGS_BUFFER_DAYS = int(os.getenv("EARNINGS_BUFFER_DAYS", "5"))

    # API Keys
    FMP_API_KEY = os.getenv("FMP_API_KEY")  # Financial Modeling Prep

    # V2 Alerts
    ALERT_EMAIL = os.getenv("ALERT_EMAIL", "true").lower() == "true"
    ALERT_SMS = os.getenv("ALERT_SMS", "false").lower() == "true"

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
