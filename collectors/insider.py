"""
SEC EDGAR Form 4 Insider Trading Collector

Fetches and parses Form 4 filings (insider transactions) from SEC EDGAR.
We focus on PURCHASES - insider buying is the predictive signal.

SEC EDGAR Notes:
- Rate limit: 10 requests/second (we use 5 to be safe)
- User-Agent header required with contact email
- Form 4 must be filed within 2 business days of transaction
"""

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

import feedparser
import requests
from ratelimit import limits, sleep_and_retry

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import config
from utils.db import get_db


# SEC EDGAR endpoints
SEC_FORM4_RSS = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&company=&dateb=&owner=include&count={count}&output=atom"
SEC_BASE_URL = "https://www.sec.gov"


@dataclass
class InsiderTrade:
    """Represents a single insider transaction."""
    ticker: str
    company_name: str
    insider_name: str
    insider_title: str
    trade_type: str  # 'P' for purchase, 'S' for sale
    shares: int
    price_per_share: float
    total_value: float
    shares_owned_after: int
    trade_date: date
    filed_date: date
    form_type: str
    source_url: str

    def is_open_market_purchase(self) -> bool:
        """Check if this is an open market purchase (not grant/exercise)."""
        return self.trade_type == 'P' and self.price_per_share > 0

    def is_ceo_cfo(self) -> bool:
        """Check if insider is CEO or CFO."""
        title = (self.insider_title or "").upper()
        return "CEO" in title or "CFO" in title or "CHIEF EXECUTIVE" in title or "CHIEF FINANCIAL" in title


@sleep_and_retry
@limits(calls=config.SEC_RATE_LIMIT, period=1)
def _sec_request(url: str) -> requests.Response:
    """Make a rate-limited request to SEC EDGAR."""
    headers = {
        "User-Agent": config.SEC_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response


def fetch_recent_form4_filings(count: int = 100) -> list[dict]:
    """
    Fetch recent Form 4 filings from SEC EDGAR RSS feed.

    Args:
        count: Number of filings to fetch (max 100)

    Returns:
        List of filing metadata dicts with 'link', 'title', 'updated'
    """
    url = SEC_FORM4_RSS.format(count=min(count, 100))
    response = _sec_request(url)

    feed = feedparser.parse(response.content)
    filings = []

    for entry in feed.entries:
        # Extract CIK and accession number from link
        # Link format: https://www.sec.gov/Archives/edgar/data/CIK/ACCESSION/
        filings.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "updated": entry.get("updated", ""),
            "summary": entry.get("summary", ""),
        })

    return filings


def get_form4_xml_url(filing_url: str) -> Optional[str]:
    """
    Get the URL to the raw XML version of a Form 4 filing.

    Args:
        filing_url: URL to the filing index page

    Returns:
        URL to the raw XML file, or None if not found
    """
    try:
        response = _sec_request(filing_url)
        html = response.text

        # Look for XML file links
        # SEC has styled XML (in xslF345X05/ directory) and raw XML (in root)
        # We want the raw XML file
        xml_pattern = r'href="([^"]+\.xml)"'
        matches = re.findall(xml_pattern, html, re.IGNORECASE)

        # First pass: find raw XML (not in xsl directory)
        for match in matches:
            lower_match = match.lower()
            # Skip index files
            if "index" in lower_match:
                continue
            # Skip styled XML transforms (contain xsl in path)
            if "/xsl" in lower_match or "xsl/" in lower_match:
                continue
            # This should be the raw XML
            return urljoin(filing_url, match)

        return None

    except Exception as e:
        print(f"Error getting XML URL from {filing_url}: {e}")
        return None


def parse_form4_xml(xml_url: str) -> list[InsiderTrade]:
    """
    Parse a Form 4 XML file to extract transactions.

    Args:
        xml_url: URL to the Form 4 XML file

    Returns:
        List of InsiderTrade objects
    """
    trades = []

    try:
        response = _sec_request(xml_url)
        root = ET.fromstring(response.content)

        def find_text(element, tag_name, default=""):
            """Find text for a tag, searching recursively."""
            if element is None:
                return default
            # Search for the tag recursively
            found = element.find(".//" + tag_name)
            if found is not None and found.text:
                return found.text.strip()
            return default

        # Get issuer (company) info
        issuer = root.find("issuer")
        ticker = find_text(issuer, "issuerTradingSymbol", "").upper()
        company_name = find_text(issuer, "issuerName", "")

        # Skip if no ticker or ticker is too long (not a regular stock)
        if not ticker or len(ticker) > 5:
            return trades

        # Get reporting owner info
        owner = root.find("reportingOwner")
        insider_name = find_text(owner, "rptOwnerName", "")

        # Get title from officer title or relationship
        insider_title = find_text(owner, "officerTitle", "")

        # Check relationship for director/officer status
        relationship = owner.find(".//reportingOwnerRelationship") if owner else None
        if relationship is not None:
            is_director = find_text(relationship, "isDirector", "") in ("true", "1")
            is_officer = find_text(relationship, "isOfficer", "") in ("true", "1")
            is_ten_percent = find_text(relationship, "isTenPercentOwner", "") in ("true", "1")

            if not insider_title:
                if is_officer:
                    insider_title = "Officer"
                elif is_director:
                    insider_title = "Director"
                elif is_ten_percent:
                    insider_title = "10% Owner"

        # Get filing date from periodOfReport
        period_of_report = find_text(root, "periodOfReport", "")
        try:
            filed_date = datetime.strptime(period_of_report, "%Y-%m-%d").date() if period_of_report else date.today()
        except ValueError:
            filed_date = date.today()

        # Parse non-derivative transactions (regular stock purchases/sales)
        # Look in nonDerivativeTable
        nd_table = root.find("nonDerivativeTable")
        if nd_table is not None:
            for txn in nd_table.findall("nonDerivativeTransaction"):
                trade = _parse_transaction(
                    txn, ticker, company_name, insider_name, insider_title, filed_date, xml_url
                )
                if trade:
                    trades.append(trade)

    except ET.ParseError as e:
        print(f"XML parse error for {xml_url}: {e}")
    except Exception as e:
        print(f"Error parsing Form 4 from {xml_url}: {e}")

    return trades


def _parse_transaction(
    txn_element,
    ticker: str,
    company_name: str,
    insider_name: str,
    insider_title: str,
    filed_date: date,
    source_url: str
) -> Optional[InsiderTrade]:
    """Parse a single transaction element from Form 4 XML."""

    def find_value(parent, *path_parts):
        """Navigate through nested elements to find value text."""
        current = parent
        for part in path_parts:
            if current is None:
                return ""
            current = current.find(part)
        if current is not None and current.text:
            return current.text.strip()
        return ""

    # Transaction code: P=Purchase, S=Sale, A=Grant, M=Exercise, G=Gift, etc.
    txn_coding = txn_element.find("transactionCoding")
    txn_code = find_value(txn_coding, "transactionCode")

    # We only want open market purchases (code 'P') and sales (code 'S')
    # Skip grants (A), exercises (M), gifts (G), conversions (C), etc.
    if txn_code not in ("P", "S"):
        return None

    # Transaction amounts
    txn_amounts = txn_element.find("transactionAmounts")

    # Acquired/Disposed: A=Acquisition, D=Disposition
    acquired_disposed = find_value(txn_amounts, "transactionAcquiredDisposedCode", "value")

    # Map to our trade type
    if txn_code == "P" and acquired_disposed == "A":
        trade_type = "P"  # Purchase
    elif txn_code == "S" and acquired_disposed == "D":
        trade_type = "S"  # Sale
    else:
        return None

    # Get transaction details
    try:
        shares = int(float(find_value(txn_amounts, "transactionShares", "value") or "0"))
    except ValueError:
        shares = 0

    try:
        price = float(find_value(txn_amounts, "transactionPricePerShare", "value") or "0")
    except ValueError:
        price = 0.0

    # Skip if no shares or no price (likely a grant or non-monetary transaction)
    if shares <= 0 or price <= 0:
        return None

    total_value = shares * price

    # Get shares owned after transaction
    post_txn = txn_element.find("postTransactionAmounts")
    try:
        shares_after = int(float(find_value(post_txn, "sharesOwnedFollowingTransaction", "value") or "0"))
    except ValueError:
        shares_after = 0

    # Get transaction date
    txn_date_str = find_value(txn_element, "transactionDate", "value")
    try:
        trade_date = datetime.strptime(txn_date_str, "%Y-%m-%d").date() if txn_date_str else filed_date
    except ValueError:
        trade_date = filed_date

    return InsiderTrade(
        ticker=ticker,
        company_name=company_name,
        insider_name=insider_name,
        insider_title=insider_title,
        trade_type=trade_type,
        shares=shares,
        price_per_share=price,
        total_value=total_value,
        shares_owned_after=shares_after,
        trade_date=trade_date,
        filed_date=filed_date,
        form_type="4",
        source_url=source_url,
    )


def save_trades(trades: list[InsiderTrade]) -> int:
    """
    Save insider trades to database.

    Args:
        trades: List of InsiderTrade objects

    Returns:
        Number of new trades inserted
    """
    inserted = 0

    with get_db() as conn:
        for trade in trades:
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO insider_trades
                    (ticker, company_name, insider_name, insider_title, trade_type,
                     shares, price_per_share, total_value, shares_owned_after,
                     trade_date, filed_date, form_type, source_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade.ticker,
                        trade.company_name,
                        trade.insider_name,
                        trade.insider_title,
                        trade.trade_type,
                        trade.shares,
                        trade.price_per_share,
                        trade.total_value,
                        trade.shares_owned_after,
                        trade.trade_date.isoformat(),
                        trade.filed_date.isoformat(),
                        trade.form_type,
                        trade.source_url,
                    )
                )
                if conn.total_changes > 0:
                    inserted += 1
            except Exception as e:
                print(f"Error saving trade {trade.ticker} {trade.insider_name}: {e}")

    return inserted


def update_daily_aggregates(target_date: Optional[date] = None):
    """
    Update the insider_daily aggregation table.

    Args:
        target_date: Date to aggregate, or None for all dates with new data
    """
    with get_db() as conn:
        if target_date:
            dates = [(target_date.isoformat(),)]
        else:
            # Get all dates with trades not yet aggregated
            cursor = conn.execute(
                """
                SELECT DISTINCT trade_date FROM insider_trades
                WHERE trade_date NOT IN (SELECT date FROM insider_daily)
                """
            )
            dates = cursor.fetchall()

        for (date_str,) in dates:
            # Calculate aggregates for this date
            cursor = conn.execute(
                """
                SELECT
                    ticker,
                    SUM(CASE WHEN trade_type = 'P' THEN 1 ELSE 0 END) as buy_txns,
                    SUM(CASE WHEN trade_type = 'S' THEN 1 ELSE 0 END) as sell_txns,
                    SUM(CASE WHEN trade_type = 'P' THEN total_value ELSE 0 END) as buy_value,
                    SUM(CASE WHEN trade_type = 'S' THEN total_value ELSE 0 END) as sell_value,
                    COUNT(DISTINCT CASE WHEN trade_type = 'P' THEN insider_name END) as unique_buyers,
                    COUNT(DISTINCT CASE WHEN trade_type = 'S' THEN insider_name END) as unique_sellers,
                    MAX(CASE WHEN trade_type = 'P' AND (
                        insider_title LIKE '%CEO%' OR insider_title LIKE '%CFO%' OR
                        insider_title LIKE '%Chief Executive%' OR insider_title LIKE '%Chief Financial%'
                    ) THEN 1 ELSE 0 END) as ceo_cfo_buying
                FROM insider_trades
                WHERE trade_date = ?
                GROUP BY ticker
                """,
                (date_str,)
            )

            for row in cursor.fetchall():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO insider_daily
                    (ticker, date, buy_transactions, sell_transactions, buy_value, sell_value,
                     unique_buyers, unique_sellers, ceo_cfo_buying)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["ticker"],
                        date_str,
                        row["buy_txns"],
                        row["sell_txns"],
                        row["buy_value"],
                        row["sell_value"],
                        row["unique_buyers"],
                        row["unique_sellers"],
                        bool(row["ceo_cfo_buying"]),
                    )
                )


def collect_insider_data(count: int = 100, purchases_only: bool = True) -> dict:
    """
    Main collection function - fetch and parse recent Form 4 filings.

    Args:
        count: Number of filings to fetch
        purchases_only: If True, only save purchases (not sales)

    Returns:
        Dict with collection statistics
    """
    stats = {
        "filings_fetched": 0,
        "filings_parsed": 0,
        "trades_found": 0,
        "purchases_found": 0,
        "trades_saved": 0,
        "errors": [],
    }

    print(f"Fetching {count} recent Form 4 filings...")
    filings = fetch_recent_form4_filings(count)
    stats["filings_fetched"] = len(filings)

    all_trades = []

    for i, filing in enumerate(filings):
        try:
            # Get XML URL
            xml_url = get_form4_xml_url(filing["link"])
            if not xml_url:
                continue

            # Parse the XML
            trades = parse_form4_xml(xml_url)
            stats["filings_parsed"] += 1

            for trade in trades:
                stats["trades_found"] += 1
                if trade.trade_type == "P":
                    stats["purchases_found"] += 1

                if not purchases_only or trade.trade_type == "P":
                    all_trades.append(trade)

            # Progress indicator
            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{len(filings)} filings...")

        except Exception as e:
            stats["errors"].append(f"{filing['link']}: {str(e)}")

    # Save to database
    if all_trades:
        stats["trades_saved"] = save_trades(all_trades)
        update_daily_aggregates()

    return stats


def get_recent_purchases(days: int = 14, min_value: float = 0) -> list[dict]:
    """
    Get recent insider purchases from the database.

    Args:
        days: Number of days to look back
        min_value: Minimum transaction value

    Returns:
        List of purchase records
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT
                ticker, company_name, insider_name, insider_title,
                shares, price_per_share, total_value, trade_date, filed_date
            FROM insider_trades
            WHERE trade_type = 'P'
              AND trade_date >= ?
              AND total_value >= ?
            ORDER BY trade_date DESC, total_value DESC
            """,
            (cutoff, min_value)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_tickers_with_buying(days: int = 14, min_value: float = 100000) -> list[str]:
    """
    Get list of tickers with insider buying activity.

    Args:
        days: Number of days to look back
        min_value: Minimum total buy value

    Returns:
        List of ticker symbols
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT ticker, SUM(total_value) as total_buy_value
            FROM insider_trades
            WHERE trade_type = 'P'
              AND trade_date >= ?
            GROUP BY ticker
            HAVING SUM(total_value) >= ?
            ORDER BY total_buy_value DESC
            """,
            (cutoff, min_value)
        )
        return [row["ticker"] for row in cursor.fetchall()]


if __name__ == "__main__":
    # Test collection
    print("Testing insider data collection...")
    print(f"User-Agent: {config.SEC_USER_AGENT}")
    print()

    stats = collect_insider_data(count=50, purchases_only=True)

    print()
    print("Collection Results:")
    print(f"  Filings fetched: {stats['filings_fetched']}")
    print(f"  Filings parsed:  {stats['filings_parsed']}")
    print(f"  Trades found:    {stats['trades_found']}")
    print(f"  Purchases found: {stats['purchases_found']}")
    print(f"  Trades saved:    {stats['trades_saved']}")

    if stats["errors"]:
        print(f"  Errors: {len(stats['errors'])}")

    print()
    print("Recent notable purchases:")
    for p in get_recent_purchases(days=7, min_value=100000)[:10]:
        print(f"  {p['ticker']}: {p['insider_name']} ({p['insider_title']}) - ${p['total_value']:,.0f}")
