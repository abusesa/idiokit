from __future__ import with_statement
import collections
import threading
import util
import time
import random
import sys

class Timeout(Exception):
    pass

local = threading.local()

def source():
    return getattr(local, "source", None)

class Reg(object):
    @property
    def was_source(self):
        return source() is self

    def register(self, callback):
        pass

    def unregister(self, callback):
        pass

    def __add__(self, other):
        return Either(self, other)

    def __enter__(self):
        pass

    def __exit__(self, *args, **keys):
        self.finish()

    def next(self, timeout=None):
        condition = threading.Condition()
        result = list()

        def _callback(source, final, success, value):
            with condition:
                if result:
                    return False
                result.append((source, success, value))
                condition.notify()
                return True

        if timeout is None:
            expire = float("infinity")
        else:
            expire = time.time() + timeout

        self.register(_callback)
        try:
            with condition:
                if util.in_main_thread():
                    while not result and time.time() < expire:
                        condition.wait(max(0.0, min(expire-time.time(), 10.0)))
                elif not result:
                    condition.wait(timeout)
                if not result:
                    result.append(None)
        finally:
            self.unregister(_callback)

        if result[0] is None:
            raise Timeout()

        source, success, value = result[0]
        local.source = source
        if success:
            return value
        type, exc, tb = value
        raise type, exc, tb

    def __iter__(self):
        return self

class Buffered(Reg):
    def __init__(self):
        Reg.__init__(self)
        self.queue = collections.deque()
        self.callbacks = collections.deque()

    @util.synchronized
    def register(self, callback):
        if not self.queue:
            self.callbacks.append(callback)
            return
        
        final, success, value = self.queue[0]
        if callback(self, final, success, value) and not final:
            self.queue.popleft()

    @util.synchronized
    def unregister(self, callback):
        try:
            self.callbacks.remove(callback)
        except ValueError:
            pass

    @util.synchronized
    def signal(self, final, success, value):
        while self.callbacks:
            callback = self.callbacks.popleft()
            if callback(self, final, success, value):
                if final:
                    self.queue.append((final, success, value))
                return
        self.queue.append((final, success, value))

class Channel(Buffered):
    def send(self, *value):
        if not value:
            value = None
        elif len(value) == 1:
            value = value[0]
        self.signal(False, True, value)

    def throw(self, exception, traceback=None):
        self.signal(False, False, (type(exception), exception, traceback))

    def rethrow(self):
        _, exception, traceback = sys.exc_info()
        self.throw(exception, traceback)

    def _finish(self, success, value):
        self.signal(True, success, value)

class Either(Reg):
    def __init__(self, left, right):
        Reg.__init__(self)
        self.left = left
        self.right = right

    def register(self, callback):
        self.left.register(callback)
        self.right.register(callback)

        if random.random() > 0.5:
            self.left, self.right = self.right, self.left

    def unregister(self, callback):
        self.left.unregister(callback)
        self.right.unregister(callback)

def any_of(first, *streams):
    if len(streams) == 0:
        return first
    if len(streams) == 1:
        return Either(first, streams[0])
    cut = len(streams) // 2
    return any_of(first + streams[:cut], streams[cut:])

class ThreadedStream(Buffered):
    def __init__(self):
        Buffered.__init__(self)

        self.output = Channel()
        self.output.register(self._callback)

        self.thread = None

    def _callback(self, source, final, success, value):
        self.signal(final, success, value)
        if not final:
            self.output.register(self._callback)
        return True

    @util.synchronized
    def start(self):
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._main)
        self.thread.setDaemon(True)
        self.thread.start()

    def _main(self):
        try:
            self.run()
        except:
            self.output._finish(False, sys.exc_info())
        else:
            self.output._finish(False, (StopIteration, StopIteration(), None))

    def run(self):
        return
