from __future__ import with_statement
import time
import socket
import threading
import collections
         
def synchronized(method):
    master_lock = threading.Lock()
    lock_name = "_synchronized_lock"

    def _method(self, *args, **keys):
        lock = getattr(self, lock_name, None)
        if lock is None:
            with master_lock:
                lock = getattr(self, lock_name, None)
                if lock is None:
                    lock = threading.RLock()
                    setattr(self, lock_name, lock)
        with lock:
            return method(self, *args, **keys)
    return _method

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

def in_main_thread():
    MainThread = getattr(threading, "_MainThread", threading.Thread)
    return isinstance(threading.currentThread(), MainThread)

def is_generator(func):
    func = getattr(func, "im_func", func)
    return func.func_code.co_flags & 0x20 == 0x20

def stdin():
    import os
    import select
    import threado

    class StandardInput(threado.ThreadedStream):
        def __init__(self):
            threado.ThreadedStream.__init__(self)
            self.start()

        def run(self, chunk_size=2**16, sleep_time=0.5):
            line_buffer = LineBuffer()
            
            while True:
                ifd, _, _ = select.select([0], [], [], sleep_time)
                if not ifd:
                    continue

                data = os.read(0, chunk_size)
                if not data:
                    time.sleep(sleep_time)
                for line in line_buffer.feed(data):
                    self.output.send(line)

    return StandardInput()
