"""
Stock Radar Configuration

Loads settings from environment variables with sensible defaults.
"""

import os
import logging
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
    STOCK_OF_DAY_MIN_SCORE = int(os.getenv('MIN_SOTD_SCORE', '35'))

    # Quality Gates - Stock filters (applied BEFORE scoring)
    MIN_STOCK_PRICE = float(os.getenv('MIN_STOCK_PRICE', '5.0'))
    MIN_MARKET_CAP = int(os.getenv('MIN_MARKET_CAP', '500000000'))  # $500M
    MIN_AVG_VOLUME = int(os.getenv('MIN_AVG_VOLUME', '500000'))  # 500K shares

    # Insider purchase minimum
    MIN_INSIDER_PURCHASE = int(os.getenv('MIN_INSIDER_PURCHASE', '50000'))  # $50K

    # Options liquidity gates
    MIN_OPTIONS_AVG_VOLUME = int(os.getenv('MIN_OPTIONS_VOLUME', '500'))
    MIN_OPEN_INTEREST = int(os.getenv('MIN_OPEN_INTEREST', '1000'))

    # SOTD quality requirements
    MIN_ACTIVE_SIGNALS = int(os.getenv('MIN_ACTIVE_SIGNALS', '2'))
    MIN_INSIDER_OR_OPTIONS_SCORE = 10  # At least one strong signal required

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


def setup_logging(level: str = None):
    """
    Configure logging for the stock_radar system.

    Logs to both console and a rotating file in the logs directory.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR). Defaults to INFO.
    """
    log_level = getattr(logging, (level or os.getenv('LOG_LEVEL', 'INFO')).upper(), logging.INFO)
    logs_dir = Config.LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "stock_radar.log"

    # Configure root stock_radar logger
    logger = logging.getLogger('stock_radar')
    logger.setLevel(log_level)

    # Avoid adding duplicate handlers
    if not logger.handlers:
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_fmt = logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_fmt)
        logger.addHandler(console_handler)

        # File handler
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5_000_000, backupCount=5
        )
        file_handler.setLevel(log_level)
        file_fmt = logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_fmt)
        logger.addHandler(file_handler)

    return logger


# Singleton instance
config = Config()

# Ensure directories exist on import
config.ensure_dirs()
