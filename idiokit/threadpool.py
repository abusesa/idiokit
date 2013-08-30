from __future__ import absolute_import

import sys
import threading
import collections

from . import idiokit, timer, _time, _selectloop


class ThreadPool(object):
    _Event = idiokit.Event
    _sleep = staticmethod(timer.sleep)
    _deque = staticmethod(collections.deque)
    _Thread = staticmethod(threading.Thread)
    _Lock = staticmethod(threading.Lock)
    _exc_info = staticmethod(sys.exc_info)
    _asap = staticmethod(_selectloop.asap)
    _monotonic = _time.monotonic

    def __init__(self, idle_time=1.0):
        self.idle_time = idle_time

        self.lock = self._Lock()
        self.supervisor = None

        self.alive = 0
        self.threads = self._deque()
        self.queue = self._deque()

    def run(self, func, *args, **keys):
        event = self._Event()

        with self.lock:
            if self.threads:
                _, lock, queue = self.threads.pop()
                queue.append((event, func, args, keys))
                lock.release()
            else:
                lock = self._Lock()
                queue = [(event, func, args, keys)]

                thread = self._Thread(target=self._thread, args=(lock, queue))
                thread.daemon = True
                thread.start()

                self.alive += 1

            if self.supervisor is None:
                self.supervisor = self._supervisor()

        return event

    @idiokit.stream
    def _supervisor(self):
        while True:
            while True:
                yield self._sleep(self.idle_time / 2.0)

                with self.lock:
                    if self.alive == 0:
                        break

                    cut = self._monotonic() - self.idle_time
                    while self.threads and self.threads[0][0] < cut:
                        _, lock, queue = self.threads.popleft()
                        queue.append(None)
                        lock.release()

            yield self._sleep(self.idle_time)
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

            event, func, args, keys = item

            try:
                throw = False
                args = (func(*args, **keys),)
            except:
                throw = True
                args = self._exc_info()

            with self.lock:
                self.threads.append((self._monotonic(), lock, queue))

            if throw:
                self._asap(event.fail, *args)
            else:
                self._asap(event.succeed, *args)


global_threadpool = ThreadPool()
thread = global_threadpool.run
