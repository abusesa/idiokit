from __future__ import with_statement

import sys
import threading
import time
import collections

import threado
import callqueue

class ThreadPool(object):
    _time = time.time
    _sleep = time.sleep
    _add = callqueue.add
    _exc_info = sys.exc_info

    def __init__(self, idle_time=5.0):
        self.idle_time = idle_time

        self.all = set()
        self.free = collections.deque()
        self.lock = threading.Lock()
        self.supervisor = None

    def run(self, func, *args, **keys):
        channel = threado.Channel()

        with self.lock:
            if self.free:
                lock, stack, since = self.free.pop()
            else:
                lock = threading.Lock()
                lock.acquire()

                stack = list()

                thread = threading.Thread(target=self._thread, args=(lock, stack))
                thread.setDaemon(True)
                thread.start()

                self.all.add(lock)

            stack.append((channel, func, args, keys))
            lock.release()

            if not self.supervisor:
                self.supervisor = threading.Thread(target=self._supervisor)
                self.supervisor.setDaemon(True)
                self.supervisor.start()

        return channel

    def _supervisor(self):
        while True:
            self._sleep(self.idle_time / 2.0)

            with self.lock:
                while self.free:
                    lock, stack, since = self.free[0]
                    if self._time() - since < self.idle_time:
                        break

                    self.free.popleft()
                    self.all.discard(lock)
                    lock.release()

                if not self.all:
                    self.supervisor = None
                    break

    def _thread(self, lock, stack):
        while True:
            lock.acquire()

            with self.lock:
                if lock not in self.all:
                    break
            
            channel, func, args, keys = stack.pop()
            try:
                result = func(*args, **keys)
            except:
                _, exc, tb = self._exc_info()
                self._add(channel.throw, exc, tb)
            else:
                self._add(channel.finish, result)

            with self.lock:
                self.free.append((lock, stack, self._time()))

thread_pool = ThreadPool()
run = thread_pool.run
