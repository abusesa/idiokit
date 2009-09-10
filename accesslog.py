import re
from time import strptime, timezone
from calendar import timegm

# Parse dates with time.strptime and then cache them, as time.strptime
# seems to be really slow at least on OSX 10.5 python 2.5. Do not
# cache non-parsing dates, as there are only so many parsing dates,
# but an infinite amount of non-parsing ones.
DATE_CACHE = dict()

LINE_REX = re.compile(r'(.*) (.*) (.*) \[(.*?)\] "(.*)" (\d+) (.*) "(.*)" "(.*)"')
TIME_REX = re.compile(r'(\d{1,2}/.+?/\d{4}):(\d{1,2}):(\d{1,2}):(\d{1,2})\s+((?:\-|\+)\d{4})')

class LogLineError(Exception):
    def __init__(self, line, message):
        Exception.__init__(self, message)
        self.line = line

class LogLine(object):
    def __init__(self, source, ident, user, timestamp, 
                 request, code, size, refer, agent):
        self.source = source
        self.ident = ident
        self.user = user
        self.timestamp = timestamp
        self.request = request
        self.code = code
        self.size = size
        self.referrer = refer
        self.user_agent = agent

def map_to_None(*values):
    for value in values:
        yield (value if value.strip() not in ["", "-"] else None)

def parse_line(line):
    match = LINE_REX.match(line)
    if not match:
        raise LogLineError(line, "invalid log line")

    groups = map_to_None(*match.groups())
    source, ident, user, time, request, code, size, refer, agent = groups

    try:
        size = int(size) if size else None
    except ValueError:
        raise LogLineError(line, "non-integer size")

    match = TIME_REX.match(time)
    if not match:
        raise LogLineError(line, "invalid timestamp ('%s')" % time)

    date, hour, min, sec, tz = match.groups()

    timestamp = DATE_CACHE.get(date, None)
    try:
        if timestamp is None:
            timestamp = timegm(strptime(date, "%d/%b/%Y"))
            DATE_CACHE[date] = timestamp
    except ValueError:
        raise LogLineError(line, "invalid date ('%s')" % date)

    tz = int(tz)

    hour, min, sec = map(int, [hour, min, sec])
    hour -= tz / 100
    min -= tz % 100
    timestamp += hour * 3600 + min * 60 + sec

    return LogLine(source, ident, user, timestamp, 
                   request, code, size, refer, agent)
