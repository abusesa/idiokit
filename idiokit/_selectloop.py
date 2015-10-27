from __future__ import absolute_import

import os
import errno
import select
import threading
import collections

from . import heap, _time


class SelectLoop(object):
    _INFINITY = float("inf")
    _EINTR = errno.EINTR

    _read = os.read
    _write = os.write
    _monotonic = _time.monotonic
    _native_select = select.select
    _select_error = select.error
    _HeapError = heap.HeapError

    def __init__(self):
        self._lock = threading.Lock()
        self._rfd, self._wfd = os.pipe()
        self._pending = False

        self._reads = {}
        self._writes = {}
        self._excepts = {}

        self._heap = heap.Heap()
        self._nodes = collections.defaultdict(lambda: ([], [], []))

        self._immediate = collections.deque()
        self._calls = collections.deque()
        self._local = threading.local()

    def select(self, rfds, wfds, xfds, timeout, callback, *args, **keys):
        types = tuple(rfds), tuple(wfds), tuple(xfds)
        return self._select_add(types, timeout, callback, args, keys)

    def sleep(self, timeout, callback, *args, **keys):
        return self._select_add(None, timeout, callback, args, keys)

    def asap(self, callback, *args, **keys):
        try:
            current = self._local.current
        except AttributeError:
            current = None
            self._local.current = None

        if current is None:
            return self._select_add(None, 0.0, callback, args, keys)
        current.append((callback, args, keys))
        return None

    def cancel(self, node):
        if node is None:
            return

        try:
            with self._lock:
                self._pop_node(node)
        except self._HeapError:
            return False
        return True

    def _select_add(self, types, timeout, callback, args, keys):
        if timeout is None:
            timestamp = self._INFINITY
        elif timeout <= 0.0:
            timestamp = 0.0
        else:
            timestamp = self._monotonic() + timeout

        with self._lock:
            if types is None and timestamp == 0.0:
                self._immediate.append((callback, args, keys))
                node = None
                should_wake = True
            else:
                node = self._heap.push((timestamp, types, callback, args, keys))
                should_wake = node is self._heap.head()

            if types is not None:
                rfds, wfds, xfds = types
                should_wake = self._select_add_type(node, rfds, self._reads) or should_wake
                should_wake = self._select_add_type(node, wfds, self._writes) or should_wake
                should_wake = self._select_add_type(node, xfds, self._excepts) or should_wake

            if should_wake and not self._pending:
                self._write(self._wfd, "\x00")
                self._pending = True
        return node

    def _select_add_type(self, node, fds, target):
        should_wake = False

        for fd in fds:
            if fd not in target:
                should_wake = True
                target[fd] = set()
            target[fd].add(node)

        return should_wake

    def _pop_node(self, node):
        _, types, func, args, keys = self._heap.pop(node)

        if types is not None:
            rfds, wfds, xfds = types
            self._pop_type(node, rfds, self._reads)
            self._pop_type(node, wfds, self._writes)
            self._pop_type(node, xfds, self._excepts)

        return func, args, keys

    def _pop_type(self, node, fds, target):
        for fd in fds:
            nodes = target[fd]
            nodes.discard(node)
            if not nodes:
                del target[fd]

    def _prepare(self):
        with self._lock:
            rfds = self._reads.keys()
            wfds = self._writes.keys()
            xfds = self._excepts.keys()

            timeout = None

            if self._immediate:
                timeout = 0.0
            elif self._heap:
                timestamp = self._heap.peek()[0]
                if timestamp < self._INFINITY:
                    timeout = max(0.0, timestamp - self._monotonic())

            if timeout != 0.0:
                if self._pending:
                    while True:
                        try:
                            self._read(self._rfd, 1)
                        except OSError as ose:
                            if ose.errno != self._EINTR:
                                raise ose
                        else:
                            break

                    self._pending = False
                rfds.append(self._rfd)
        return rfds, wfds, xfds, timeout

    def _select(self, rfds, wfds, xfds, timeout):
        if timeout is not None and timeout <= 0.0 and not rfds and not wfds and not xfds:
            return False, (), (), ()

        try:
            rfds, wfds, xfds = self._native_select(rfds, wfds, xfds, timeout)
        except BaseException as exc:
            if isinstance(exc, self._select_error) and exc.args[0] == self._EINTR:
                return False, (), (), ()
            rfds, wfds, xfds = self._collect_errors(rfds, wfds, xfds)
            return True, rfds, wfds, xfds

        return False, rfds, wfds, xfds

    def _check_error(self, rfds=(), wfds=(), xfds=()):
        try:
            self._native_select(rfds, wfds, xfds, 0.0)
        except:
            return True
        return False

    def _collect_errors(self, rfds, wfds, xfds):
        rfds_bad = tuple(x for x in rfds if self._check_error(rfds=(x,)))
        wfds_bad = tuple(x for x in wfds if self._check_error(wfds=(x,)))
        xfds_bad = tuple(x for x in xfds if self._check_error(xfds=(x,)))
        return rfds_bad, wfds_bad, xfds_bad

    def _process(self, has_errors, rfds, wfds, xfds):
        now = None
        nodes = self._nodes

        with self._lock:
            calls = self._immediate

            for fd in rfds:
                for node in self._reads.get(fd, ()):
                    nodes[node][0].append(fd)
            for fd in wfds:
                for node in self._writes.get(fd, ()):
                    nodes[node][1].append(fd)
            for fd in xfds:
                for node in self._excepts.get(fd, ()):
                    nodes[node][2].append(fd)

            for node, (rfds, wfds, xfds) in nodes.iteritems():
                func, args, keys = self._pop_node(node)
                calls.append((func, (has_errors, rfds, wfds, xfds) + args, keys))

            while self._heap:
                timestamp, types, func, args, keys = self._heap.peek()
                if timestamp == self._INFINITY:
                    break
                if timestamp > 0.0:
                    if now is None:
                        now = self._monotonic()
                    if timestamp > now:
                        break

                if types is None:
                    calls.append((func, args, keys))
                else:
                    calls.append((func, (False, (), (), ()) + args, keys))
                self._pop_node(self._heap.head())

            self._immediate = self._calls
            self._calls = calls

        nodes.clear()
        return calls

    def _perform(self, calls):
        self._local.current = calls
        while calls:
            func, args, keys = calls.popleft()
            func(*args, **keys)
        self._local.current = None

    def iterate(self):
        rfds, wfds, xfds, timeout = self._prepare()
        has_errors, rfds, wfds, xfds = self._select(rfds, wfds, xfds, timeout)
        calls = self._process(has_errors, rfds, wfds, xfds)
        self._perform(calls)

global_select_loop = SelectLoop()
select = global_select_loop.select
sleep = global_select_loop.sleep
asap = global_select_loop.asap
cancel = global_select_loop.cancel
iterate = global_select_loop.iterate
