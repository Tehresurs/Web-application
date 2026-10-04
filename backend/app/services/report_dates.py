from datetime import date, datetime


def parsed_date(value):
    """Only the report's own date; never substitute the clock or file metadata."""
    if isinstance(value, date):
        return value
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(value or "", pattern).date()
        except (ValueError, TypeError):
            pass
    return None
