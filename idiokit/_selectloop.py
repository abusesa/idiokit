from __future__ import absolute_import

import os
import errno
import threading
import collections
import select as _select

from . import heap, _time


class SelectLoop(object):
    _inf = float("inf")
    _monotonic = _time.monotonic
    _deque = collections.deque

    def __init__(self):
        self._lock = threading.Lock()
        self._rfd, self._wfd = os.pipe()
        self._pending = False

        self._reads = {}
        self._writes = {}
        self._heap = heap.Heap()
        self._local = threading.local()

        self._immediate = []

    def select(self, rfds, wfds, timeout, callback, *args, **keys):
        if timeout is None:
            timestamp = self._inf
        else:
            timestamp = self._monotonic() + max(timeout, 0.0)

        with self._lock:
            node = self._heap.push((timestamp, tuple(rfds), tuple(wfds), callback, args, keys))
            should_wake = node is self._heap.head()

            for fd in rfds:
                if fd not in self._reads:
                    should_wake = True
                    self._reads[fd] = set()
                self._reads[fd].add(node)
            for fd in wfds:
                if fd not in self._writes:
                    should_wake = True
                    self._writes[fd] = set()
                self._writes[fd].add(node)

            if should_wake and not self._pending:
                os.write(self._wfd, "\x00")
                self._pending = True
        return node

    def _call(self, _rfds, _wfds, callback, args, keys):
        callback(*args, **keys)

    def sleep(self, timeout, callback, *args, **keys):
        return self.select((), (), timeout, self._call, callback, args, keys)

    def _next(self, callback, args, keys):
        with self._lock:
            self._immediate.append((callback, args, keys))

            if not self._pending:
                os.write(self._wfd, "\x00")
                self._pending = True
        return None

    def next(self, callback, *args, **keys):
        return self._next(callback, args, keys)

    def asap(self, callback, *args, **keys):
        try:
            current = self._local.current
        except AttributeError:
            current = None
            self._local.current = None

        if current is None:
            return self._next(callback, args, keys)
        current.append((callback, args, keys))
        return None

    def _cancel(self, node):
        _, rfds, wfds, _, _, _ = self._heap.pop(node)

        for fd in rfds:
            nodes = self._reads[fd]
            nodes.discard(node)
            if not nodes:
                del self._reads[fd]

        for fd in wfds:
            nodes = self._writes[fd]
            nodes.discard(node)
            if not nodes:
                del self._writes[fd]

    def cancel(self, node):
        if node is None:
            return

        try:
            with self._lock:
                self._cancel(node)
        except heap.HeapError:
            return False
        return True

    def _prepare(self):
        with self._lock:
            rfds = self._reads.keys()
            wfds = self._writes.keys()

            timeout = None

            if self._heap:
                timestamp = self._heap.peek()[0]
                if timestamp < self._inf:
                    timeout = max(0.0, timestamp - self._monotonic())

            if self._immediate:
                timeout = 0.0

            if timeout is None or timeout > 0.0:
                if self._pending:
                    os.read(self._rfd, 1)
                    self._pending = False
                rfds.append(self._rfd)
        return rfds, wfds, timeout

    def _select(self, rfds, wfds, timeout):
        if timeout is not None and timeout <= 0.0 and not rfds and not wfds:
            return (), ()

        while True:
            try:
                rfds, wfds, _ = _select.select(rfds, wfds, [], timeout)
            except _select.error as error:
                if error.args[0] == errno.EINTR:
                    continue
                raise
            else:
                break
        return rfds, wfds

    def _process(self, rfds, wfds):
        nodes = {}
        calls = self._deque()
        now = self._monotonic()

        with self._lock:
            for fd in rfds:
                for node in self._reads.get(fd, ()):
                    _, _, _, func, args, keys = self._heap.peek(node)
                    if node not in nodes:
                        nodes[node] = [], [], func, args, keys
                    nodes[node][0].append(fd)

            for fd in wfds:
                for node in self._writes.get(fd, ()):
                    _, _, _, func, args, keys = self._heap.peek(node)
                    if node not in nodes:
                        nodes[node] = [], [], func, args, keys
                    nodes[node][1].append(fd)

            for node, (rfds, wfds, func, args, keys) in nodes.iteritems():
                self._cancel(node)
                calls.append((func, (rfds, wfds) + args, keys))

            while self._heap:
                node = self._heap.head()
                timestamp, rfds, wfds, func, args, keys = self._heap.peek(node)
                if timestamp > now:
                    break
                self._cancel(node)
                calls.append((func, ((), ()) + args, keys))

            calls.extend(self._immediate)
            self._immediate = []

        return calls

    def _perform(self, calls):
        self._local.current = calls
        while calls:
            func, args, keys = calls.popleft()
            func(*args, **keys)
        self._local.current = None

    def iterate(self):
        rfds, wfds, timeout = self._prepare()
        rfds, wfds = self._select(rfds, wfds, timeout)
        calls = self._process(rfds, wfds)
        self._perform(calls)

global_select_loop = SelectLoop()
cancel = global_select_loop.cancel
select = global_select_loop.select
asap = global_select_loop.asap
next = global_select_loop.next
sleep = global_select_loop.sleep
iterate = global_select_loop.iterate
