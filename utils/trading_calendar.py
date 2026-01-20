"""
Trading Calendar Utilities

Handles NYSE trading day checks and holiday scheduling for 2025-2026.
"""

from datetime import date, timedelta
from typing import Optional


# NYSE holidays for 2025-2026
# Source: https://www.nyse.com/markets/hours-calendars
NYSE_HOLIDAYS = {
    # 2025
    date(2025, 1, 1),    # New Year's Day
    date(2025, 1, 20),   # Martin Luther King Jr. Day
    date(2025, 2, 17),   # Presidents' Day
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 26),   # Memorial Day
    date(2025, 6, 19),   # Juneteenth
    date(2025, 7, 4),    # Independence Day
    date(2025, 9, 1),    # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 12, 25),  # Christmas

    # 2026
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # Martin Luther King Jr. Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed, 7/4 is Saturday)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
}


def is_trading_day(check_date: Optional[date] = None) -> bool:
    """
    Check if a given date is a NYSE trading day.

    Returns False for:
    - Weekends (Saturday, Sunday)
    - NYSE holidays

    Args:
        check_date: Date to check. Defaults to today.

    Returns:
        True if the market is open on this day, False otherwise.
    """
    if check_date is None:
        check_date = date.today()

    # Check for weekend (Saturday=5, Sunday=6)
    if check_date.weekday() >= 5:
        return False

    # Check for NYSE holidays
    if check_date in NYSE_HOLIDAYS:
        return False

    return True


def next_trading_day(from_date: Optional[date] = None) -> date:
    """
    Find the next trading day from a given date.

    If from_date is a trading day, returns the next trading day after it.
    If from_date is not a trading day, returns the next trading day.

    Args:
        from_date: Starting date. Defaults to today.

    Returns:
        The next NYSE trading day.
    """
    if from_date is None:
        from_date = date.today()

    # Start with the day after from_date
    next_day = from_date + timedelta(days=1)

    # Keep advancing until we find a trading day
    while not is_trading_day(next_day):
        next_day += timedelta(days=1)

    return next_day


def previous_trading_day(from_date: Optional[date] = None) -> date:
    """
    Find the previous trading day from a given date.

    Args:
        from_date: Starting date. Defaults to today.

    Returns:
        The previous NYSE trading day.
    """
    if from_date is None:
        from_date = date.today()

    # Start with the day before from_date
    prev_day = from_date - timedelta(days=1)

    # Keep going back until we find a trading day
    while not is_trading_day(prev_day):
        prev_day -= timedelta(days=1)

    return prev_day


def trading_days_until(target_date: date, from_date: Optional[date] = None) -> int:
    """
    Count trading days between two dates.

    Args:
        target_date: End date (exclusive)
        from_date: Start date (inclusive). Defaults to today.

    Returns:
        Number of trading days between the dates.
    """
    if from_date is None:
        from_date = date.today()

    count = 0
    current = from_date

    while current < target_date:
        if is_trading_day(current):
            count += 1
        current += timedelta(days=1)

    return count


if __name__ == "__main__":
    # Test the functions
    today = date.today()

    print(f"Today: {today}")
    print(f"Is trading day: {is_trading_day(today)}")
    print(f"Next trading day: {next_trading_day(today)}")
    print(f"Previous trading day: {previous_trading_day(today)}")

    # Test some holidays
    print("\nHoliday checks:")
    for holiday in sorted(list(NYSE_HOLIDAYS))[:5]:
        print(f"  {holiday}: is_trading_day={is_trading_day(holiday)}")
