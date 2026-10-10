"""Romanian calendar days: public sources publish by them, and so do our totals."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BUCHAREST = ZoneInfo("Europe/Bucharest")


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=BUCHAREST)
    return start, datetime.combine(day + timedelta(days=1), time.min, tzinfo=BUCHAREST)


def yesterday() -> date:
    return datetime.now(BUCHAREST).date() - timedelta(days=1)
