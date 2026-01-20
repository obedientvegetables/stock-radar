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
    DEFAULT_STOP_PCT = float(os.getenv("DEFAULT_STOP_PCT", "0.05"))
    DEFAULT_TARGET_PCT = float(os.getenv("DEFAULT_TARGET_PCT", "0.10"))

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
