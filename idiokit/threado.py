from __future__ import absolute_import

import sys
import functools

from . import idiokit, values, threadpool

# Helpers

NULL = idiokit.Event()
NULL.succeed(None)

class _ValueStream(idiokit.Stream):
    _head = values.Value(None)

    def __init__(self, value):
        idiokit.Stream.__init__(self)
        self._value = value

    def pipe_left(self, *args, **keys):
        pass
    pipe_right = pipe_left

    def head(self):
        return self._head

    def result(self):
        return self._value

# threado.Finished

Finished = StopIteration

# threado.Channel

def _channel():
    while True:
        item = yield idiokit.next()
        yield idiokit.send(item)

class Channel(idiokit.Generator):
    def __init__(self):
        idiokit.Generator.__init__(self, _channel())

    def finish(self, *args):
        self.throw(StopIteration, StopIteration(*args), None)

# threado.stream and threado.GeneratorStream

class _Sub(object):
    def __init__(self, wrapped):
        self.wrapped = wrapped

class Inner(object):
    def __init__(self, outer):
        self._outer = outer

    def send(self, *args):
        outer = self._outer
        if outer is not None:
            outer._output.stack(idiokit.send(*args))

    def sub(self, other):
        return _Sub(other)

    def flush(self):
        return NULL

    def thread(self, func, *args, **keys):
        return _ValueStream(threadpool.run(func, *args, **keys))

    def finish(self, *args):
        idiokit.stop(*args)

    def _close(self):
        self._outer = None

@idiokit.stream
def _next_or_result(stream):
    result = yield stream.next()
    idiokit.stop(result)

class GeneratorStream(idiokit.Generator):
    def __init__(self):
        self._started = idiokit.Value()
        self.inner = Inner(self)

        idiokit.Generator.__init__(self, self._wrapped())

    def _transform(self, next):
        if isinstance(next, _Any):
            return next.resolve(self)

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

        return _Any(*next).resolve(self)

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

# threado.any and "yield left, right" support

def any(left, right):
    return _Any(left, right)

class _Either(values.Value):
    def __init__(self, left, right):
        values.Value.__init__(self)

        self._left = left
        self._right = right

        left.listen(self._listen_left)
        right.listen(self._listen_right)

        if self.is_set():
            left.unlisten(self._listen_left)
            right.unlisten(self._listen_right)

    def _listen_left(self, value):
        if not self.set((False, (self._left,))):
            return
        self._right.unlisten(self._listen_right)

    def _listen_right(self, value):
        if not self.set((False, (self._right,))):
            return
        self._left.unlisten(self._listen_left)

class _Any(object):
    def __init__(self, left, right):
        self.left = left
        self.right = right

    @idiokit.stream
    def resolve(self, context):
        left = self.left
        right = self.right

        if left is right:
            idiokit.stop((yield left))

        if right is context.inner:
            left, right = right, left

        piped = None

        if left is context.inner:
            piped = idiokit.Piped()
            piped.add(context._messages.head())
            piped.add(context._signals.head())
            piped.add(context._broken.head())
            left_head = piped.head()
        else:
            left_head = left.head()
        right_head = right.head()

        try:
            while True:
                head = yield _ValueStream(_Either(left_head, right_head))
                promise = head.get()
                if promise is None:
                    if head is left_head:
                        result = yield _ValueStream(left.result())
                    else:
                        result = yield _ValueStream(right.result())
                    break

                consumed, value, next = promise
                consumed.set()

                wrapped = values.Value()
                value.listen(lambda x: wrapped.set((False, (x,))))
                result = yield _ValueStream(wrapped)
                if result is not None:
                    result = yield _ValueStream(value)
                    break

                if head is left_head:
                    left_head = next
                else:
                    right_head = next
        finally:
            if piped is not None:
                piped.close()

        if head is left_head:
            idiokit.stop(left, result)
        idiokit.stop(right, result)

# Rest of threado.*

dev_null = idiokit.consume
pipe = idiokit.pipe
run = idiokit.main_loop
