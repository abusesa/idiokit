from __future__ import with_statement
import time
import timer
import threado
import threading
import collections

class ThreadPool(object):
    def __init__(self, thread_timeout=5.0):
        self.thread_timeout = thread_timeout
        self.check_interval = 1.0

        self.condition = threading.Condition(threading.Lock())
        self.free_threads = set()
        self.queue = collections.deque()

        self.timer = None

    def _callback(self, _):
        with self.condition:
            self.timer = timer.sleep(self.check_interval)
            self.timer.register(self._callback)
            self.condition.notifyAll()

    def run(self, func, *args, **keys):
        channel = threado.Channel()

        with self.condition:
            if self.timer is None:
                self.timer = timer.sleep(self.check_interval)
                self.timer.register(self._callback)

            self.queue.append((channel, func, args, keys))
            if not self.free_threads:
                thread = threading.Thread(target=self._thread)
                thread.setDaemon(True)
                thread.start()
            self.condition.notify()
                
        return channel

    def _thread(self):
        current_thread = threading.currentThread()
        expire_time = time.time() + self.thread_timeout

        while True:
            with self.condition:
                self.free_threads.add(current_thread)
                    
                while True:
                    if not self.queue:
                        self.condition.wait()

                    if not self.queue and time.time() < expire_time:
                        continue

                    self.free_threads.discard(current_thread)
                    if not self.queue:
                        return

                    item = self.queue.popleft()
                    if item is None:
                        return
                    break
                    
            channel, func, args, keys = item
            try:
                result = func(*args, **keys)
            except:
                channel.rethrow()
            else:
                channel.send(result)
thread_pool = ThreadPool()

run = thread_pool.run
