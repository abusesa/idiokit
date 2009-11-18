from __future__ import with_statement
import threading
import time
import heapq
import atexit
import threado

class TimerThread(object):
    def __init__(self):
        self.condition = threading.Condition(threading.Lock())
        self.heap = list()
        self.thread = None

        atexit.register(self.stop)
        
    def start(self):
        with self.condition:
            if self.thread is not None:
                return
            self.thread = threading.Thread(target=self.loop)
            self.thread.setDaemon(True)
            self.thread.start()

    def stop(self):
        with self.condition:
            if self.thread is None:
                return
            thread = self.thread
            self.thread = None
            self.condition.notify()
        thread.join()

    def loop(self):
        with self.condition:
            while self.thread is threading.currentThread():
                current_time = time.time()

                while self.heap:
                    expire_time, channel = self.heap[0]
                    if expire_time > current_time:
                        break
                    heapq.heappop(self.heap)
                    channel.finish()

                if self.heap:
                    timeout = max(self.heap[0][0]-current_time, 0.0)
                else:
                    timeout = None
                self.condition.wait(timeout)

    def _wait(self, delay):
        expire_time = time.time() + delay
        channel = threado.Channel()
        item = expire_time, channel

        with self.condition:
            heapq.heappush(self.heap, item)
            if self.heap[0] is item:
                self.condition.notify()
        self.start()

        return channel

    @threado.stream
    def sleep(inner, self, delay):
        waiter = self._wait(delay)
        while not waiter.was_source:
            yield inner, waiter
        inner.finish()
timer_thread = TimerThread()

sleep = timer_thread.sleep
