from __future__ import absolute_import

import sys
import signal
import inspect
import threading
import collections
from functools import partial, wraps

from ._selectloop import sleep, asap, iterate
from .values import Value


NULL = Value(None)


class BrokenPipe(Exception):
    pass


class _Queue(object):
    def __init__(self, auto_consume=False):
        self._tail = Value()

        if auto_consume:
            self._head = None
        else:
            self._head = self._tail
            self._head.listen(self._move)

    def _move(self, _, __):
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

            self._head = head

    def head(self):
        head = self._head
        if head is None:
            return self._tail
        return head


class Piped(_Queue):
    def __init__(self, auto_consume=False):
        _Queue.__init__(self, auto_consume)

        self._closed = False
        self._sealed = False

        self._ready = collections.deque()
        self._heads = set()

    def _add(self, head):
        if self._sealed:
            return

        self._heads.add(head)
        head.unsafe_listen(self._promise)

    def _promise(self, head, promise):
        if self._closed:
            return
        self._heads.remove(head)

        if promise is None:
            if self._sealed and not self._ready and not self._heads:
                self._closed = True
                self._tail.unsafe_set(None)
            return

        if self._ready:
            self._ready.append(promise)
            return

        self._ready.append(promise)

        next = Value()
        tail = self._tail
        self._tail = next

        next_consumed = Value()
        next_value = Value()
        tail.unsafe_set((next_consumed, next_value, next))
        next_consumed.unsafe_listen(partial(self._consumed, next_value))

    def _consumed(self, value, _, __):
        if self._closed:
            value.unsafe_set(None)
            return

        consumed, original, head = self._ready.popleft()
        if self._ready:
            next = Value()
            tail = self._tail
            self._tail = next

            next_consumed = Value()
            next_value = Value()
            tail.unsafe_set((next_consumed, next_value, next))
            next_consumed.unsafe_listen(partial(self._consumed, next_value))

        consumed.unsafe_set()
        original.unsafe_listen(value.unsafe_proxy)

        self._heads.add(head)
        head.unsafe_listen(self._promise)

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

        for head in heads:
            head.unsafe_unlisten(self._promise)

    def add(self, head):
        if head is NULL:
            return
        asap(self._add, head)

    def seal(self):
        asap(self._seal)

    def close(self):
        asap(self._close)


def peel_args(args):
    if not args:
        return None
    elif len(args) == 1:
        return args[0]
    return args


def fill_exc(args):
    exc_type, exc_value, exc_tb = args + (None,) * (3 - len(args))
    try:
        raise exc_type, exc_value, exc_tb
    except:
        exc_type, exc_value, _ = sys.exc_info()
    return exc_type, exc_value, exc_tb


def require_stream(obj):
    if isinstance(obj, Stream):
        return obj
    raise TypeError("expected a stream, got {0!r}".format(obj))


class Stream(object):
    def fork(self, *args, **keys):
        return _Fork(self, *args, **keys)

    def _send(self, throw, args):
        send = _SendBase(self.result(), throw, args)
        if throw:
            self.pipe_left(NULL, send._head)
        else:
            self.pipe_left(send._head, NULL)
        return send

    def send(self, *args):
        return self._send(False, args)

    def throw(self, *args):
        if not args:
            args = sys.exc_info()
        return self._send(True, args)

    def next(self):
        return Event() | self.fork() | Next()

    def __or__(self, other):
        return _PipePair(self, require_stream(other))

    def __ror__(self, other):
        return _PipePair(require_stream(other), self)


class _MapOutput(_Queue):
    def __init__(self, messages, signals, func, args, keys):
        _Queue.__init__(self)

        self._func = func
        self._args = args
        self._keys = keys

        self._gen = None
        self._result = Value()

        self._messages = messages
        self._signals = signals

        self._signals.listen(self._got_signal)
        self._messages.listen(self._got_message)
        self._result.listen(self._close)

    def _close(self, _, __):
        self._gen = None
        self._signals = None
        self._messages = None

    def _set_exception_result(self, args):
        exc_type, exc_value, exc_tb = fill_exc(args)
        if issubclass(exc_type, StopIteration):
            self._result.unsafe_set((False, exc_value.args))
        else:
            self._result.unsafe_set((True, args))

    def _got_signal(self, _, __):
        if self._result.unsafe_is_set():
            return

        while True:
            if not self._signals.unsafe_is_set():
                return self._signals.unsafe_listen(self._got_signal)

            promise = self._signals.unsafe_get()
            if promise is None:
                return

            consumed, value, head = promise
            consumed.unsafe_set()

            if not value.unsafe_is_set():
                return value.unsafe_listen(self._got_signal)

            self._signals = head

            result = value.unsafe_get()
            if result is None:
                continue

            throw, args = result
            if not throw:
                continue

            self._tail.unsafe_set(None)
            self._set_exception_result(args)
            return

    def _got_message(self, _, __):
        if self._result.unsafe_is_set():
            return

        args = None

        while True:
            if self._gen is None and args is None:
                if not self._messages.unsafe_is_set():
                    return self._messages.unsafe_listen(self._got_message)

                promise = self._messages.unsafe_get()
                if promise is None:
                    self._tail.unsafe_set(None)
                    return

                consumed, value, head = promise
                consumed.unsafe_set()

                if not value.unsafe_is_set():
                    return value.unsafe_listen(self._got_message)

                self._messages = head

                result = value.unsafe_get()
                if result is None:
                    continue

                throw, args = result
                if throw:
                    self._tail.unsafe_set(None)
                    self._set_exception_result(args)
                    return

            try:
                if self._gen is None:
                    gen = self._func(peel_args(args), *self._args, **self._keys)
                    args = None
                    if gen is None:
                        continue
                    self._gen = iter(gen)

                try:
                    obj = self._gen.next()
                except StopIteration:
                    self._gen = None
                    continue
            except:
                self._gen = None
                self._tail.unsafe_set(None)
                self._result.unsafe_set((True, sys.exc_info()))
                return

            next_consumed = Value()
            next_value = Value((False, (obj,)))
            next_head = Value()

            tail = self._tail
            self._tail = next_head
            tail.unsafe_set((next_consumed, next_value, next_head))

            if not next_consumed.unsafe_is_set():
                return next_consumed.unsafe_listen(self._got_message)

    def result(self):
        return self._result


class Map(Stream):
    def __init__(self, func, *args, **keys):
        Stream.__init__(self)

        self._messages = Piped(True)
        self._signals = Piped(True)
        self._output = _MapOutput(self._messages.head(), self._signals.head(), func, args, keys)
        self._output.result().listen(self._got_result)

    def _got_result(self, _, __):
        self._messages.close()
        self._signals.close()

    def pipe_left(self, messages, signals):
        self._signals.add(signals)
        self._messages.add(messages)

    def pipe_right(self, broken):
        self._signals.add(broken)

    def result(self, *args, **keys):
        return self._output.result()

    def head(self):
        return self._output.head()


class _SendBase(Stream):
    _CONSUMED = object()

    def __init__(self, parent, throw, args):
        self._parent = parent
        self._message = throw, args

        self._consumed = Value()
        self._value = Value()
        self._head = Value((self._consumed, self._value, NULL))
        self._result = Value()

        self._input = Piped(True)

        self._consumed.listen(self._on_consumed)
        if self._parent is not None:
            self._parent.listen(self._on_parent)
        self._input.head().listen(self._on_input)

    def _on_consumed(self, _, __):
        if self._consumed is None:
            return

        self._consumed = None
        self._input.add(Value((NULL, Value(self._CONSUMED), NULL)))

    def _on_parent(self, _, (throw, args)):
        if self._parent is None:
            return
        self._parent = None

        if not throw:
            args = (BrokenPipe, BrokenPipe(*args), None)
        self._input.add(Value((NULL, Value((True, args)), NULL)))

    def _on_input(self, _, promise):
        consume, value, head = promise
        consume.unsafe_set()
        value.unsafe_listen(partial(self._on_value, head))

    def _on_value(self, head, _, result):
        if result is None:
            head.unsafe_listen(self._on_input)
            return

        if result is self._CONSUMED:
            self._value.unsafe_set(self._message)
            self._result.unsafe_set((False, ()))
        else:
            self._value.unsafe_set(None)
            self._result.unsafe_set(result)
        self._value = None
        self._message = None

        if self._consumed is not None:
            self._consumed.unsafe_unlisten(self._on_consumed)
            self._consumed = None

        if self._parent is not None:
            self._parent.unsafe_unlisten(self._on_parent)
            self._parent = None

        self._input.close()
        self._head = NULL

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
        return self._head


class _Fork(Stream):
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

    def _stream_result(self, _, result):
        if self._result.unsafe_set(result):
            self._messages.close()
            self._signals.close()
            self._stream = None

    def _signal_promise(self, _, promise):
        if promise is None:
            return
        consume, value, head = promise
        consume.unsafe_set()
        value.unsafe_listen(partial(self._signal_value, head))

    def _signal_value(self, head, _, result):
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

    def _message_promise(self, _, promise):
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
        value.unsafe_listen(partial(self._message_value, head, next_value, next_message))

    def _message_value(self, head, next_value, next_message, _, result):
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


class _GeneratorBasedStreamOutput(_Queue):
    def __init__(self):
        _Queue.__init__(self)

        self._stack = collections.deque()
        self._closed = False

    def unsafe_stack(self, stream):
        if self._closed:
            return

        if self._stack:
            self._stack.append(stream)
            return

        head = stream.head()
        if head is not NULL:
            self._stack.append(head)
            self._handle(None, None)

    def _handle(self, _, __):
        while self._stack:
            head = self._stack[0]
            if not head.unsafe_is_set():
                return head.unsafe_listen(self._handle)

            promise = head.unsafe_get()
            if promise is None:
                self._stack.popleft()

                if self._stack:
                    self._stack[0] = self._stack[0].head()
                elif self._closed:
                    self._tail.unsafe_set(None)
                continue

            consume, value, head = promise
            if not self._tail.unsafe_is_set():
                self._tail.unsafe_set((Value(), value, Value()))

            next_consume, _, next_tail = self._tail.unsafe_get()
            if not next_consume.unsafe_is_set():
                return next_consume.unsafe_listen(self._handle)

            consume.unsafe_set()
            self._tail = next_tail
            self._stack[0] = head

    def unsafe_close(self):
        if self._closed:
            return
        self._closed = True

        if self._stack:
            return
        self._tail.unsafe_set(None)


class GeneratorBasedStream(Stream):
    _running = set()

    def __init__(self, gen):
        self._gen = gen

        self._messages = Piped()
        self._signals = Piped()
        self._broken = Piped()

        self._output = _GeneratorBasedStreamOutput()
        self._result = Value()

        asap(self._start)

    def _start(self):
        self._running.add(self)
        self._next(False, ())
        del self

    def _step(self, _, (throw, args)):
        sleep(0.0, self._next, throw, args)
        del self, throw, args

    def _next(self, throw, args):
        try:
            if throw:
                next = require_stream(self._gen.throw(*args))
            else:
                next = require_stream(self._gen.send(peel_args(args)))
        except StopIteration as stop:
            self._close(False, stop.args)
            del stop
        except:
            self._close(True, sys.exc_info())
        else:
            next.pipe_left(self._messages.head(), self._signals.head())
            next.pipe_right(self._broken.head())

            self._output.unsafe_stack(next)

            next.result().unsafe_listen(self._step)
            del next
        del self, throw, args

    def _close(self, throw, args):
        self._output.unsafe_close()

        self._messages.close()
        self._signals.close()
        self._broken.close()

        self._result.unsafe_set((throw, args))

        self._gen.close()
        self._gen = None
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

    def _promise(self, _, promise):
        consume, value, head = promise
        consume.unsafe_set()
        value.unsafe_listen(partial(self._value, head))

    def _value(self, head, _, result):
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


class _PipePair(Stream):
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

    def _left_result(self, _, (throw, args)):
        if throw:
            self._signal_head.unsafe_set((NULL, Value((True, args)), NULL))
        else:
            self._signal_head.unsafe_set(None)
        self._right.result().unsafe_listen(self._result.unsafe_proxy)

    def _right_result(self, _, (throw, args)):
        if not throw:
            throw = True
            args = (BrokenPipe, BrokenPipe(*args), None)
        self._broken_head.unsafe_set((NULL, Value((throw, args)), NULL))

    def _message_promise(self, _, promise):
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

    def _message_final(self, _, (throw, args)):
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

        self._proxied = require_stream(proxied)

    def pipe_right(self, *args, **keys):
        return self._proxied.pipe_right(*args, **keys)

    def pipe_left(self, *args, **keys):
        return self._proxied.pipe_left(*args, **keys)

    def head(self, *args, **keys):
        return self._proxied.head(*args, **keys)

    def result(self, *args, **keys):
        return self._proxied.result(*args, **keys)


def stream(func):
    if not inspect.isgeneratorfunction(func):
        raise TypeError("{0!r} is not a generator function".format(func))

    @wraps(func)
    def _stream(*args, **keys):
        return GeneratorBasedStream(func(*args, **keys))
    return _stream


def send(*args):
    return Send(False, args)


def map(func, *args, **keys):
    return Map(func, *args, **keys)


def pipe(first, *rest):
    if not rest:
        return require_stream(first)
    cut = len(rest) // 2
    return _PipePair(pipe(first, *rest[:cut]), pipe(*rest[cut:]))


next = Next


def stop(*args):
    raise StopIteration(*args)


def consume():
    return map(lambda x: None)


class Signal(BaseException):
    _signames = dict()

    for name in dir(signal):
        if not name.startswith("SIG"):
            continue
        if name.startswith("SIG_"):
            continue

        signum = getattr(signal, name)
        if type(signum) != int:
            continue

        _signames[signum] = name
    del name

    def __init__(self, signum):
        BaseException.__init__(self, signum)

    @property
    def signum(self):
        return self.args[0]

    def __str__(self):
        signum = self.signum

        result = "caught signal " + repr(signum)
        if signum in self._signames:
            result += " (" + self._signames[signum] + ")"
        return result


def main_loop(main, catch_signals=(signal.SIGINT, signal.SIGTERM, signal.SIGUSR1, signal.SIGUSR2)):
    def handle_signal(signum, _):
        thread = threading.Thread(target=main.throw, args=(Signal(signum),))
        thread.daemon = True
        thread.start()

    previous_signal_handlers = []
    try:
        for signum in set(catch_signals):
            previous_signal_handlers.append((signum, signal.getsignal(signum)))
            signal.signal(signum, handle_signal)

        is_set = main.result().unsafe_is_set
        while not is_set():
            iterate()
    finally:
        for signum, handler in previous_signal_handlers:
            signal.signal(signum, handler)

    throw, args = main.result().unsafe_get()
    if throw:
        exc_type, exc_value, exc_tb = fill_exc(args)
        raise exc_type, exc_value, exc_tb
    return peel_args(args)
