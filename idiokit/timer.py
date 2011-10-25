from __future__ import with_statement, absolute_import

import time
import threading
import functools

from . import idiokit, threadpool, values, callqueue, heap

class TimerValue(values.ValueBase):
    def cancel(self, value=None):
        return self._set(value=None)

class Timer(object):
    def __init__(self):
        self._heap = heap.Heap()
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._running = False

    def _run(self):
        while True:
            calls = list()

            with self._lock:
                now = time.time()
                while self._heap and self._heap.peek()[0] <= now:
                    _, value, args = self._heap.pop()
                    calls.append((value, args))

            for value, args in calls:
                value.cancel(args)

            calls = None

            with self._lock:
                if not self._heap:
                    self._running = False
                    return

                timeout = self._heap.peek()[0] - now
                self._event.clear()

            self._event.wait(timeout)

    def _handle(self, node, _):
        with self._lock:
            try:
                self._heap.pop(node)
            except heap.HeapError:
                pass

    def set(self, delay, args=None):
        value = TimerValue()
        if delay <= 0:
            callqueue.add(value.cancel, args)
            return value

        with self._lock:
            node = self._heap.push((time.time() + delay, value, args))
            self._event.set()

            if not self._running:
                self._running = True
                threadpool.run(self._run)

        value.listen(functools.partial(self._handle, node))
        return value

set = Timer().set

@idiokit.stream
def sleep(delay):
    event = idiokit.Event()
    value = set(delay)

    value.listen(event.succeed)
    try:
        yield event
    finally:
        value.cancel()
