from __future__ import with_statement, absolute_import

import time
import threading
import functools

from . import idiokit, threadpool, values

class Node(object):
    __slots__ = "index", "value"

    def __init__(self, index, value):
        self.index = index
        self.value = value

def _swap(array, left, right):
    array[left.index] = right
    array[right.index] = left
    left.index, right.index = right.index, left.index
    return right, left

def _up(array, node):
    while node.index > 0:
        parent = array[(node.index - 1) // 2]
        if parent.value <= node.value:
            break
        _swap(array, node, parent)

def _down(array, node):
    length = len(array)

    while True:
        smallest = node

        left_index = 2 * node.index + 1
        if left_index < length:
            left = array[left_index]
            if left.value < node.value:
                smallest = left

        right_index = left_index + 1
        if right_index < length:
            right = array[right_index]
            if right.value < node.value:
                smallest = right

        if node is smallest:
            break

        _swap(array, node, smallest)

class HeapError(Exception):
    pass

class Heap(object):
    def __init__(self):
        self._heap = list()

    def _get(self, node):
        if not self._heap:
            raise HeapError("empty heap")

        if node is None:
            node = self._heap[0]

        if self._heap[node.index] is not node:
            raise HeapError("node not in the heap")

        return node

    def push(self, value):
        node = Node(len(self._heap), value)
        self._heap.append(node)
        _up(self._heap, node)
        return node

    def peek(self, node=None):
        return self._get(node).value

    def pop(self, node=None):
        node = self._get(node)

        last = self._heap.pop()
        if last is not node:
            self._heap[node.index] = last
            last.index = node.index
            _down(self._heap, last)
        return node.value

    def __nonzero__(self):
        return not not self._heap

class TimerValue(values.ValueBase):
    def cancel(self, value=None):
        return self._set(value=None)

class Timer(object):
    def __init__(self):
        self._heap = Heap()
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
            except HeapError:
                pass

    def set(self, delay, args=None):
        value = TimerValue()

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
