from __future__ import absolute_import

import sys
import functools
import threading

from . import idiokit, values, callqueue, threadpool

NULL = idiokit.Event()
NULL.succeed(None)

Finished = StopIteration

def _channel():
    while True:
        item = yield idiokit.next()
        yield idiokit.send(item)

class Channel(idiokit.Generator):
    def __init__(self):
        idiokit.Generator.__init__(self, _channel())

    def finish(self, *args):
        self.throw(StopIteration(*args))

class _Sub(object):
    def __init__(self, wrapped):
        self.wrapped = wrapped

class _ValueStream(idiokit.Stream):
    _head = values.Value(None)

    def __init__(self, value):
        idiokit.Stream.__init__(self)

        self._value = value

    def pipe_left(self, *args, **keys):
        pass
    pipe_right = pipe_left

    def message_head(self):
        return self._head

    def result(self):
        return self._value

class Inner(object):
    def __init__(self, outer):
        self._outer = outer

    def send(self, *args):
        msg = values.Value((values.Value(None),
                            values.Value((False, args)),
                            values.Value(None)))
        self._outer._output.stack(msg)

    def sub(self, other):
        return _Sub(other)

    def flush(self):
        return NULL

    def thread(self, func, *args, **keys):
        return _ValueStream(threadpool.run(func, *args, **keys))

    def finish(self, *args):
        idiokit.stop(*args)

    def _close(self):
        self._outer = NULL

@idiokit.stream
def _next_or_result(stream):
    result = yield stream.next()
    idiokit.stop(result)

class _Any(object):
    def __init__(self, left, right):
        self.left = left
        self.right = right

def any(left, right):
    return _Any(left, right)

def _any(self, left, right):
    if left is right:
        return left

    result = values.Value()

    def flow(left, right):
        if right is self.inner:
            right, left = left, right

        piped = None

        if left is self.inner:
            piped = idiokit.Piped()
            piped.add(self._messages.head())
            piped.add(self._signals.head())
            piped.add(self._broken.head())
            left_head = piped.head()
        else:
            left_head = left.message_head()

        right_head = right.message_head()

        try:
            while True:
                head, promise = yield values.Which(left_head, right_head)
                if promise is None:
                    if head is left_head:
                        throw, args = yield left.result()
                    else:
                        throw, args = yield right.result()
                    break

                consumed, value, next = promise
                consumed.set()

                item = yield value
                if item is not None:
                    throw, args = item
                    break

                if head is left_head:
                    left_head = next
                else:
                    right_head = next
        finally:
            if piped is not None:
                piped.close()

        if not throw:
            source = left if head is left_head else right
            args = source, idiokit.peel_args(args)
        result.set((throw, args))

    values.Flow(flow(left, right))
    return _ValueStream(result)

class GeneratorStream(idiokit.Generator):
    def __init__(self):
        self._started = idiokit.Value()

        self.inner = Inner(self)

        idiokit.Generator.__init__(self, self._wrapped())

    def _transform(self, next):
        if isinstance(next, _Any):
            return _any(self, next.left, next.right)

        if isinstance(next, _Sub):
            return next.wrapped

        if next is None:
            return NULL

        if next is self.inner:
            next = idiokit.next()
            next.pipe_left(self._messages.head(), self._signals.head())
            next.pipe_right(self._broken.head())
            return idiokit.Event() | next

        if isinstance(next, idiokit.Stream):
            return _next_or_result(next)

        return _any(self, *next)

    def __iter__(self):
        return _iter(values.Value(None), self.message_head(), self.result())

    def _wrapped(self):
        yield _ValueStream(self._started)

        args = None
        throw = False
        gen = self.run()

        try:
            while True:
                if throw:
                    next = gen.throw(*args)
                else:
                    next = gen.send(args)

                next = self._transform(next)
                try:
                    args = yield next
                    throw = False
                except:
                    args = sys.exc_info()
                    throw = True
        finally:
            self.inner._close()

    def start(self):
        self._started.set((False, ()))

    def run(self):
        return ()

class FuncStream(GeneratorStream):
    def __init__(self, func, *args, **keys):
        GeneratorStream.__init__(self)

        self.func = func
        self.args = args
        self.keys = keys

    def run(self):
        return self.func(self.inner, *self.args, **self.keys)

def stream(func):
    @functools.wraps(func)
    def _stream(*args, **keys):
        result = FuncStream(func, *args, **keys)
        result.start()
        return result
    return _stream

@idiokit.stream
def dev_null():
    while True:
        yield idiokit.next()

pipe = idiokit.pipe
run = idiokit.main_loop
