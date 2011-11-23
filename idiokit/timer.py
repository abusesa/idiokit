import time
import heapq
import threado
import threading

class _Timer(threado.GeneratorStream):
    def __init__(self):
        threado.GeneratorStream.__init__(self)
        self.event = threading.Event()
        self.heap = list()
        self.start()

    def run(self):
        while True:
            current_time = time.time()
            while self.heap and self.heap[0][0] <= current_time:
                _, channel = heapq.heappop(self.heap)
                channel.finish()

            if self.heap:
                timeout = self.heap[0][0]-current_time
            else:
                timeout = None

            yield self.inner.thread(self.event.wait, timeout)
            self.event.clear()

    @threado.stream
    def sleep(inner, self, delay):
        if delay <= 0:
            inner.finish()

        expire_time = time.time() + delay
        channel = threado.Channel()

        heapq.heappush(self.heap, (expire_time, channel))
        self.event.set()

        while not channel.has_result():
            yield inner, channel
        inner.finish()
global_timer = _Timer()

sleep = global_timer.sleep
