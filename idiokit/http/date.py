import time


_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_date(timestamp=None):
    """
    >>> format_date(0)
    'Thu, 01 Jan 1970 00:00:00 GMT'
    """

    if timestamp is None:
        timestamp = time.time()
    ts = time.gmtime(timestamp)

    return "{weekday}, {day:02d} {month} {year:04d} {hour:02d}:{minute:02d}:{second:02d} GMT".format(
        weekday=_WEEKDAYS[ts.tm_wday],
        day=ts.tm_mday,
        month=_MONTHS[ts.tm_mon - 1],
        year=ts.tm_year,
        hour=ts.tm_hour,
        minute=ts.tm_min,
        second=ts.tm_sec
    )
