from __future__ import with_statement, absolute_import

import sys
import time
import threading
import collections

from . import idiokit, values, callqueue

class MonotonicTimer(object):
    _time = staticmethod(time.time)

    def __init__(self):
        self._elapsed = 0
        self._origin = self._time()
        self._previous = self._origin

    def elapsed(self):
        now = self._time()
        if now < self._previous:
            self._elapsed += self._previous - self._origin
            self._origin = now
        self._previous = now
        return self._elapsed + (now - self._origin)

class ThreadPool(object):
    _Value = staticmethod(values.Value)
    _sleep = staticmethod(time.sleep)
    _deque = staticmethod(collections.deque)
    _Thread = staticmethod(threading.Thread)
    _Lock = staticmethod(threading.Lock)
    _exc_info = staticmethod(sys.exc_info)
    _callqueue_add = staticmethod(callqueue.add)

    def __init__(self, idle_time=1.0):
        self.idle_time = idle_time

        self.timer = MonotonicTimer()

        self.lock = self._Lock()
        self.supervisor = None

        self.alive = 0
        self.threads = self._deque()
        self.queue = self._deque()

    def run(self, func, *args, **keys):
        value = self._Value()

        with self.lock:
            if self.threads:
                _, lock, queue = self.threads.pop()
                queue.append((value, func, args, keys))
                lock.release()
            else:
                lock = self._Lock()
                queue = [(value, func, args, keys)]

                thread = self._Thread(target=self._thread, args=(lock, queue))
                thread.setDaemon(True)
                thread.start()

                self.alive += 1

            if self.supervisor is None:
                self.supervisor = self._Thread(target=self._supervisor)
                self.supervisor.setDaemon(True)
                self.supervisor.start()

        return value

    def _supervisor(self):
        while True:
            while True:
                self._sleep(self.idle_time / 2.0)

                with self.lock:
                    if self.alive == 0:
                        break

                    cut = self.timer.elapsed() - self.idle_time
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

            value, func, args, keys = item

            try:
                throw = False
                args = (func(*args, **keys),)
            except:
                throw = True
                args = self._exc_info()

            with self.lock:
                self.threads.append((self.timer.elapsed(), lock, queue))

            self._callqueue_add(value.set, (throw, args))

run = ThreadPool().run

def thread(func, *args, **keys):
    value = run(func, *args, **keys)
    event = idiokit.Event()
    value.listen(event.set)

    # Return the Event instance directly instead of yielding it.
    # This way StopIterations are also raised instead of them
    # turning into valid exits.
    return event
