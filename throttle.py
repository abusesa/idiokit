import time
import heapq
import threado

class Throttle(threado.ThreadedStream):
    def __init__(self, throttle_time, grace_period=0.0):
        threado.ThreadedStream.__init__(self)

        self.throttle_time = throttle_time
        self.grace_period = grace_period
        self.expirations = list()
        self.values = dict()

    def send(self, *args, **keys):
        threado.ThreadedStream.send(self, *args, **keys)
        self.start()

    def throw(self, *args, **keys):
        threado.ThreadedStream.throw(self, *args, **keys)
        self.start()

    def rethrow(self, *args, **keys):
        threado.ThreadedStream.rethrow(self, *args, **keys)
        self.start()

    def _expire(self):
        current_time = time.time()

        while self.expirations:
            expiration_time, key = self.expirations[0]
            if expiration_time > current_time:
                break

            heapq.heappop(self.expirations)
            values = self.values.pop(key, None)
            if not values:
                continue
            self.inner.send(key, values)

            expiration_time = current_time + self.throttle_time
            heapq.heappush(self.expirations, (expiration_time, key))
            self.values[key] = list()
            
    def _feed(self, key, value):
        if key in self.values:
            self.values[key].append(value)
        else:
            expire_time = time.time() + self.grace_period
            heapq.heappush(self.expirations, (expire_time, key))
            self.values[key] = [value]

    def _timeout(self):
        if not self.expirations:
            return None
        return max(self.expirations[0][0]-time.time(), 0.0)

    def run(self):
        while True:
            try:
                message = self.inner.next(self._timeout())
            except threado.Timeout:
                self._expire()
            except:
                for key, values in self.values.iteritems():
                    self.inner.send(key, values)
                raise
            else:
                self._feed(*message)
