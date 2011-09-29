import time
import heapq
import threado
import threading

class _Timer(threado.GeneratorStream):
    def __init__(self):
        threado.GeneratorStream.__init__(self)
        self.event = threading.Event()
        self.start()

    def run(self):
        heap = list()

        null = threado.Channel()
        null.finish()

        while True:
            if not heap:
                item = yield self.inner
                source = self.inner
            else:
                source, item = yield threado.any(self.inner, null)

            if self.inner is source:
                heapq.heappush(heap, item)

            current_time = time.time()
            while heap and heap[0][0] <= current_time:
                _, channel = heapq.heappop(heap)
                channel.finish()

            if heap:
                timeout = heap[0][0]-current_time
                yield self.inner.thread(self.event.wait, timeout)
                self.event.clear()

    @threado.stream
    def sleep(inner, self, delay):
        if delay <= 0:
            inner.finish()

        expire_time = time.time() + delay
        channel = threado.Channel()

        self.send(expire_time, channel)
        self.event.set()

        while not channel.has_result():
            yield inner, channel
        inner.finish()
global_timer = _Timer()

sleep = global_timer.sleep
