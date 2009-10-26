import time
import collections
         
class LineBuffer(object):
    def __init__(self):
        self.buffer = list()
        self.pending = collections.deque()

    def feed(self, data=""):
        lines = (data + " ").splitlines()
        for line in lines[:-1]:
            self.buffer.append(line)
            self.pending.append("".join(self.buffer))
            self.buffer = list()

        data = lines[-1][:-1]
        if data:
            self.buffer.append(data)

        while self.pending:
            yield self.pending.popleft()

class TimedCache(object):
    def __init__(self, cache_time):
        self.cache = dict()
        self.queue = collections.deque()
        self.cache_time = cache_time

    def _expire(self):
        current_time = time.time()

        while self.queue:
            expire_time, key = self.queue[0]
            if expire_time > current_time:
                break
            self.queue.popleft()

            other_time, _ = self.cache[key]
            if other_time == expire_time:
                del self.cache[key]

    def get(self, key, default):
        self._expire()
        if key not in self.cache:
            return default
        _, value = self.cache[key]
        return value

    def set(self, key, value):
        self._expire()
        expire_time = time.time() + self.cache_time
        self.queue.append((expire_time, key))
        self.cache[key] = expire_time, value

def guess_encoding(text):
    if isinstance(text, unicode):
        return text

    for encoding in ["ascii", "utf-8", "latin-1"]:
        try:
            return text.decode(encoding)
        except UnicodeDecodeError:
            pass
    return text.decode("ascii", "replace")
