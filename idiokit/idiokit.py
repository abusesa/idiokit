from __future__ import with_statement, absolute_import

import sys
import inspect
import threading
import functools
import collections

from . import callqueue
from .values import Value

def _isgenfunc(func):
    # Return True if func is a generator function, False otherwise.

    if not inspect.isfunction(func):
        return False

    # Python data model documentation:
    # "The following flag bits are defined for co_flags: [...]
    #  bit 0x20 is set if the function is a generator."
    return func.func_code.co_flags & 0x20 != 0x00

# Use inspect.isgeneratorfunction if available, fall back to
# _isgenfunc otherwise.
isgenfunc = getattr(inspect, "isgeneratorfunction", _isgenfunc)

NULL = Value(None)

class BrokenPipe(Exception):
    pass

class _Queue(object):
    _lock = threading.Lock()

    def __init__(self, auto_consume=False):
        self._tail = Value()

        if auto_consume:
            self._head = None
        else:
            self._head = self._tail
            self._head.listen(self._move)

    def _move(self, _):
        while True:
            if not self._head.unsafe_is_set():
                return self._head.unsafe_listen(self._move)

            promise = self._head.unsafe_get()
            if promise is None:
                return

            consumed, value, head = promise
            if not consumed.unsafe_is_set():
                if not value.unsafe_is_set():
                    return value.unsafe_listen(self._move)
                if value.unsafe_get() is not None:
                    return consumed.unsafe_listen(self._move)
                consumed.unsafe_set()

            with self._lock:
                self._head = head

    def head(self):
        with self._lock:
            head = self._head
            if head is None:
                head = self._tail
        return head

class Piped(_Queue):
    def __init__(self, auto_consume=False):
        _Queue.__init__(self, auto_consume)

        self._closed = False
        self._sealed = False

        self._ready = collections.deque()
        self._heads = dict()

    def _add(self, head):
        if head is NULL:
            return

        if self._sealed:
            return

        key = object()
        listener = functools.partial(self._promise, key)
        self._heads[key] = head, listener

        head.unsafe_listen(listener)

    def _promise(self, key, promise):
        if self._closed:
            return
        del self._heads[key]

        if promise is None:
            if self._sealed and not self._ready and not self._heads:
                tail = self._tail
                self._closed = True
            else:
                return
        elif self._ready:
            self._ready.append(promise)
            return
        else:
            _, value, _ = promise
            self._ready.append(promise)

            next = Value()
            tail = self._tail
            self._tail = next

        if promise is None:
            tail.unsafe_set(None)
            return

        next_consume = Value()
        next_value = Value()
        tail.unsafe_set((next_consume, next_value, next))
        next_consume.unsafe_listen(functools.partial(self._consume, next_value))

    def _consume(self, value, _):
        if self._closed:
            promise = None
        else:
            promise = self._ready.popleft()

            consume, original, head = promise

            key = object()
            listener = functools.partial(self._promise, key)
            self._heads[key] = head, listener

            if self._ready:
                next = Value()
                tail = self._tail
                self._tail = next
            else:
                tail = None

        if promise is None:
            value.unsafe_set(None)
            return

        consume.unsafe_set()
        original.unsafe_listen(value.set)

        if tail is not None:
            next_consume = Value()
            next_value = Value()
            tail.unsafe_set((next_consume, next_value, next))
            next_consume.unsafe_listen(functools.partial(self._consume, next_value))

        head.unsafe_listen(listener)

    def _seal(self):
        if self._sealed:
            return
        self._sealed = True

        if self._heads or self._ready:
            return

        self._closed = True
        self._tail.unsafe_set(None)

    def _close(self):
        if self._closed:
            return
        self._closed = True
        self._sealed = True

        heads = self._heads

        self._heads = None
        self._ready = None

        self._tail.unsafe_set(None)
        self._head = NULL

        for head, listener in heads.itervalues():
            head.unsafe_unlisten(listener)

    def add(self, head):
        callqueue.asap(self._add, head)

    def seal(self):
        callqueue.asap(self._seal)

    def close(self):
        callqueue.asap(self._close)

def peel_args(args):
    if not args:
        return None
    elif len(args) == 1:
        return args[0]
    return args

class Stream(object):
    def fork(self, *args, **keys):
        return Fork(self, *args, **keys)

    def _send(self, signal, throw, args):
        send = _SendBase(self.result(), throw, args)
        if signal:
            self.pipe_left(NULL, send._head)
        else:
            self.pipe_left(send._head, NULL)
        return send

    def send(self, *args):
        return self._send(False, False, args)

    def throw(self, *args):
        if not args:
            args = sys.exc_info()
        return self._send(False, True, args)

    def signal(self, *args):
        if not args:
            args = sys.exc_info()
        return self._send(True, True, args)

    def next(self):
        return Event() | self.fork() | Next()

    def __or__(self, other):
        return PipePair(self, other)

class _SendBase(Stream):
    _lock = threading.Lock()

    _CONSUMED = object()
    _PARENT = object()

    def __init__(self, parent, throw, args):
        self._parent = parent
        self._message = throw, args

        self._consumed = Value()
        self._value = Value()
        self._head = Value((self._consumed, self._value, NULL))
        self._result = Value()

        self._input = Piped(True)
        self._input_head = self._input.head()

        self._consumed.listen(self._set_consumed)
        if self._parent is not None:
            self._parent.listen(self._set_parent)
        self._input_head.listen(self._input_promise)

    def _set_consumed(self, _):
        self._input.add(Value((NULL, Value(self._CONSUMED), NULL)))

    def _set_parent(self, _):
        self._input.add(Value((NULL, Value(self._PARENT), NULL)))

    def _input_promise(self, promise):
        consumed, value, self._input_head = promise
        consumed.unsafe_set()
        value.unsafe_listen(self._input_value)

    def _input_value(self, value):
        if value is None:
            self._input_head.unsafe_listen(self._input_promise)
            return

        if value is self._PARENT:
            self._value.unsafe_set(None)
            throw, args = self._parent.unsafe_get()
            if not throw:
                throw = True
                args = (BrokenPipe, BrokenPipe(*args), None)
            self._result.unsafe_set((throw, args))
        elif self._parent is not None:
            self._parent.unsafe_unlisten(self._set_parent)
        self._parent = None

        if value is self._CONSUMED:
            self._value.unsafe_set(self._message)
            self._result.unsafe_set((False, ()))
        else:
            self._consumed.unsafe_unlisten(self._set_consumed)
        self._message = None

        if value not in (self._CONSUMED, self._PARENT):
            self._value.unsafe_set(None)
            self._result.unsafe_set(value)
        self._input.close()
        self._input_head = None

        with self._lock:
            self._head = NULL

    def _output_head(self):
        with self._lock:
            return self._head

    def pipe_left(self, _, signal_head):
        self._input.add(signal_head)

    def pipe_right(self, broken_head):
        self._input.add(broken_head)

    def head(self):
        return NULL

    def result(self):
        return self._result

class Send(_SendBase):
    def __init__(self, throw, args):
        _SendBase.__init__(self, None, throw, args)

    def head(self):
        return self._output_head()

class Fork(Stream):
    def __init__(self, stream):
        self._stream = stream

        self._messages = Piped(True)
        self._signals = Piped(True)

        self._output = Piped()
        self._output.add(self._stream.head())
        self._output.seal()

        self._result = Value()

        self._current = Value()
        self._messages.head().listen(self._message_promise)
        self._signals.head().listen(self._signal_promise)

        self._stream.pipe_left(self._current, NULL)
        self._stream.result().listen(self._stream_result)

    def _stream_result(self, result):
        if self._result.unsafe_set(result):
            self._messages.close()
            self._signals.close()
            self._stream = None

    def _signal_promise(self, promise):
        if promise is None:
            return

        consume, value, head = promise
        consume.unsafe_set()
        value.unsafe_listen(functools.partial(self._signal_value, head))

    def _signal_value(self, head, result):
        if result is None or not result[0]:
            head.unsafe_listen(self._signal_promise)
            return

        throw, args = result

        self._messages.close()
        self._signals.close()

        if self._result.unsafe_set(result):
            self._output.close()
            self._stream.result().unsafe_unlisten(self._stream_result)
            self._stream = None

    def _message_promise(self, promise):
        if promise is None:
            self._current.unsafe_set(None)
            self._current = None
            return

        consume, value, head = promise
        next_value = Value()
        next_message = Value()

        current = self._current
        self._current = next_message
        current.unsafe_set((consume, next_value, next_message))
        value.unsafe_listen(functools.partial(self._message_value, head, next_value, next_message))

    def _message_value(self, head, next_value, next_message, result):
        if result is None or not result[0]:
            next_value.unsafe_set(result)
            head.unsafe_listen(self._message_promise)
            return

        throw, args = result

        next_value.unsafe_set(None)
        next_message.unsafe_set(None)
        self._messages.close()
        self._signals.close()

        if self._result.unsafe_set(result):
            self._output.close()
            self._stream.result().unsafe_unlisten(self._stream_result)
            self._stream = None

    def pipe_left(self, messages, signals):
        self._signals.add(signals)
        self._messages.add(messages)

    def pipe_right(self, broken):
        self._signals.add(broken)

    def head(self):
        return self._output.head()

    def result(self):
        return self._result

class _GeneratorOutput(_Queue):
    def __init__(self):
        _Queue.__init__(self)

        self._stack = collections.deque()
        self._closed = False

    def stack(self, stream):
        head = stream.head()
        if head is NULL:
            return

        if self._closed:
            return

        if self._stack:
            self._stack.append(stream)
            return

        self._stack.append(None)

        head.unsafe_listen(self._promise)

    def _promise(self, promise):
        if promise is None:
            stack = self._stack
            stack.popleft()

            if stack:
                stream = stack[0]
                stack[0] = None
            else:
                stream = None
            closed = self._closed

            if stream is None:
                if closed:
                    self._tail.unsafe_set(None)
            else:
                stream.head().unsafe_listen(self._promise)
        else:
            consume, value, head = promise

            tail = self._tail
            self._tail = Value()

            next_consume = Value()
            tail.unsafe_set((next_consume, value, self._tail))

            next_consume.unsafe_listen(functools.partial(self._consumed, consume, head))

    def _consumed(self, consume, head, _):
        consume.unsafe_set()
        head.unsafe_listen(self._promise)

    def close(self):
        if self._closed:
            return
        self._closed = True

        if self._stack:
            return
        self._tail.unsafe_set(None)

class Generator(Stream):
    _running = set()

    def __init__(self, gen):
        self._gen = gen

        self._messages = Piped()
        self._signals = Piped()
        self._broken = Piped()

        self._output = _GeneratorOutput()

        self._result = Value()

        self._step = functools.partial(callqueue.add, self._next)
        callqueue.add(self._start)

    def _start(self):
        self._running.add(self)
        self._next((False, ()))

    def _next(self, (throw, args)):
        try:
            if throw:
                next = self._gen.throw(*args)
            else:
                next = self._gen.send(peel_args(args))
        except StopIteration, stop:
            self._close(False, stop.args)
        except:
            self._close(True, sys.exc_info())
        else:
            if not isinstance(next, Stream):
                error = TypeError("expected a stream, got %r" % (next,))
                self._step((True, (TypeError, error, None)))
                return

            next.pipe_left(self._messages.head(), self._signals.head())
            next.pipe_right(self._broken.head())

            self._output.stack(next)

            next.result().unsafe_listen(self._step)

    def _close(self, throw, args):
        self._output.close()

        self._messages.close()
        self._signals.close()
        self._broken.close()

        self._result.unsafe_set((throw, args))

        self._gen = None
        self._step = None
        self._running.discard(self)

    def pipe_left(self, messages, signals):
        self._messages.add(messages)
        self._signals.add(signals)

    def pipe_right(self, pipes):
        self._broken.add(pipes)

    def head(self):
        return self._output.head()

    def result(self):
        return self._result

class Next(Stream):
    def __init__(self):
        self._result = Value()
        self._input = Piped(True)
        self._input.head().listen(self._promise)

    def _promise(self, promise):
        consume, value, head = promise
        consume.unsafe_set()
        value.unsafe_listen(functools.partial(self._value, head))

    def _value(self, head, result):
        if result is None:
            head.unsafe_listen(self._promise)
        else:
            self._input.close()
            self._result.unsafe_set(result)

    def pipe_left(self, messages, signals):
        self._input.add(signals)
        self._input.add(messages)

    def pipe_right(self, pipes):
        self._input.add(pipes)

    def head(self):
        return NULL

    def result(self):
        return self._result

class Event(Next):
    def set(self, args):
        Next.pipe_left(self, NULL, Value((NULL, Value(args), NULL)))

    def succeed(self, *args):
        return self.set((False, args))

    def fail(self, *args):
        return self.set((True, args))

    def pipe_left(self, _, signal_head):
        Next.pipe_left(self, NULL, signal_head)

class PipePair(Stream):
    def __init__(self, left, right):
        self._left = left
        self._right = right

        self._message_head = Value()
        self._signal_head = Value()
        self._broken_head = Value()
        right.pipe_left(self._message_head, self._signal_head)
        left.pipe_right(self._broken_head)

        self._result = Value()

        self._right.result().listen(self._right_result)
        self._left.result().listen(self._left_result)
        self._left.head().listen(self._message_promise)

    def _left_result(self, (throw, args)):
        if throw:
            self._signal_head.unsafe_set((NULL, Value((True, args)), NULL))
        else:
            self._signal_head.unsafe_set(None)
        self._right.result().unsafe_listen(self._result.set)

    def _right_result(self, (throw, args)):
        if not throw:
            throw = True
            args = (BrokenPipe, BrokenPipe(*args), None)
        self._broken_head.unsafe_set((NULL, Value((throw, args)), NULL))

    def _message_promise(self, promise):
        if self._right.result().unsafe_is_set():
            return

        if promise is None:
            self._left.result().unsafe_listen(self._message_final)
            return

        consume, value, head = promise

        old_head = self._message_head
        new_head = Value()
        self._message_head = new_head

        if not old_head.unsafe_set((consume, value, new_head)):
            return

        head.unsafe_listen(self._message_promise)

    def _message_final(self, (throw, args)):
        if not throw:
            args = StopIteration, StopIteration(*args), None
            self._message_head.unsafe_set((NULL, Value((True, args)), NULL))

    def pipe_left(self, *args, **keys):
        return self._left.pipe_left(*args, **keys)

    def pipe_right(self, *args, **keys):
        return self._right.pipe_right(*args, **keys)

    def head(self):
        return self._right.head()

    def result(self):
        return self._result

class Proxy(Stream):
    def __init__(self, proxied):
        Stream.__init__(self)

        self._proxied = proxied

    def pipe_right(self, *args, **keys):
        return self._proxied.pipe_right(*args, **keys)

    def pipe_left(self, *args, **keys):
        return self._proxied.pipe_left(*args, **keys)

    def head(self, *args, **keys):
        return self._proxied.head(*args, **keys)

    def result(self, *args, **keys):
        return self._proxied.result(*args, **keys)

def stream(func):
    if not isgenfunc(func):
        raise TypeError("%r is not a generator function" % func)

    @functools.wraps(func)
    def _stream(*args, **keys):
        return Generator(func(*args, **keys))
    return _stream

def send(*args):
    return Send(False, args)

def pipe(first, *rest):
    if not rest:
        return first
    cut = len(rest) // 2
    return PipePair(pipe(first, *rest[:cut]), pipe(*rest[cut:]))

next = Next

def stop(*args):
    raise StopIteration(*args)

@stream
def consume():
    while True:
        yield next()

class Signal(BaseException):
    pass

def main_loop(main):
    import signal

    def _signal(code, _):
        consume = Value()
        value = Value((True, (Signal, Signal(code), None)))
        obj = Value((consume, value, NULL))

        thread = threading.Thread(target=main.pipe_left, args=(NULL, obj))
        thread.setDaemon(True)
        thread.start()

    sigint = signal.getsignal(signal.SIGINT)
    sigterm = signal.getsignal(signal.SIGTERM)

    signal.signal(signal.SIGINT, _signal)
    signal.signal(signal.SIGTERM, _signal)

    result = main.result()
    event = threading.Event()
    iterate = callqueue.iterate
    try:
        with callqueue.exclusive(event.set):
            while True:
                iterate()

                if result.unsafe_is_set():
                    break

                while not event.isSet():
                    event.wait(0.5)
                event.clear()

            throw, args = result.unsafe_get()
    finally:
        signal.signal(signal.SIGINT, sigint)
        signal.signal(signal.SIGTERM, sigterm)

    if throw:
        exc_type, exc_value, exc_tb = args + (None,) * (3-len(args))
        raise exc_type, exc_value, exc_tb
    return peel_args(args)
