from __future__ import absolute_import

import threading

from . import idiokit, threadpool, callqueue, heap, _time


class Timer(object):
    _monotonic = _time.monotonic

    def __init__(self):
        self._heap = heap.Heap()
        self._event = threading.Event()
        self._running = None

    @idiokit.stream
    def _main(self):
        try:
            while True:
                now = self._monotonic()

                while self._heap and self._heap.peek()[0] <= now:
                    _, event = self._heap.pop()
                    event.succeed()

                if not self._heap:
                    return

                first, _ = self._heap.peek()

                self._event.clear()
                yield threadpool.thread(self._event.wait, first - now)
        finally:
            self._running = None

    @idiokit.stream
    def sleep(self, delay):
        event = idiokit.Event()

        if delay <= 0:
            callqueue.add(event.succeed)
            yield event
            return

        expire = self._monotonic() + delay

        if self._running is None:
            self._running = self._main()

        if not self._heap or self._heap.peek()[0] > expire:
            self._event.set()
        node = self._heap.push((expire, event))

        try:
            yield event
        finally:
            try:
                self._heap.pop(node)
            except heap.HeapError:
                pass

sleep = Timer().sleep
