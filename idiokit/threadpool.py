from __future__ import with_statement

import time
import threading
import collections

class ThreadPool(object):
    _time = staticmethod(time.time)
    _sleep = staticmethod(time.sleep)
    _deque = staticmethod(collections.deque)
    _Thread = staticmethod(threading.Thread)
    _Lock = staticmethod(threading.Lock)
    _Condition = staticmethod(threading.Condition)

    def __init__(self, idle_time=1.0):
        self.idle_time = idle_time

        self.elapsed_time = 0
        self.previous_time = None

        self.lock = self._Lock()
        self.supervisor = None

        self.alive = 0
        self.threads = self._deque()
        self.queue = self._deque()

    def _elapsed(self):
        now = self._time()
        if self.previous_time is not None and self.previous_time <= now:
            self.elapsed_time += now - self.previous_time
        self.previous_time = now
        return self.elapsed_time

    def run(self, func, *args, **keys):
        with self.lock:
            if self.threads:
                _, lock, queue = self.threads.pop()
                queue.append((func, args, keys))
                lock.release()
            else:
                lock = self._Lock()
                queue = [(func, args, keys)]

                thread = self._Thread(target=self._thread, args=(lock, queue))
                thread.setDaemon(True)
                thread.start()

                self.alive += 1

            if self.supervisor is None:
                self.supervisor = self._Thread(target=self._supervisor)
                self.supervisor.setDaemon(True)
                self.supervisor.start()

    def _supervisor(self):
        while True:
            while True:
                self._sleep(self.idle_time / 2.0)

                with self.lock:
                    if self.alive == 0:
                        break

                    cut = self._elapsed() - self.idle_time
                    while self.threads and self.threads[0][0] < cut:
                        _, lock, queue = self.threads.popleft()
                        queue.append(None)
                        lock.release()

            self._sleep(self.idle_time)
            with self.lock:
                if self.alive == 0:
                    self.supervisor = None
                    return

    def _thread(self, lock, queue):
        while True:
            lock.acquire()

            item = queue.pop()
            if item is None:
                with self.lock:
                    self.alive -= 1
                return

            func, args, keys = item
            func(*args, **keys)

            with self.lock:
                self.threads.append((self._elapsed(), lock, queue))

run = ThreadPool().run
