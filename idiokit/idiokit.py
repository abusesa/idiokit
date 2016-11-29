from __future__ import absolute_import

import sys
import signal
import inspect
import numbers
import threading
import collections
from functools import wraps

from ._selectloop import sleep, asap, iterate
from .values import Value

__version__ = "2.8.1"

NULL = Value(None)


class BrokenPipe(Exception):
    pass


class Piped(object):
    def __init__(self):
        self._head = Value()
        self._tail = self._head

        self._closed = False

        self._next = None
        self._queue = None
        self._heads = None

    def head(self):
        return self._head

    def _add(self, head):
        if head is NULL:
            return

        if not self._closed:
            if head.unsafe_is_set():
                self._on_promise(head, head.unsafe_get())
            else:
                if self._heads is None:
                    self._heads = set()
                self._heads.add(head)
                head.unsafe_listen(self._on_promise)

    def _on_promise(self, head, promise):
        if self._heads is not None:
            self._heads.discard(head)

        if not self._closed:
            if promise is None:
                return

            if self._next is not None:
                if self._queue is None:
                    self._queue = collections.deque()
                self._queue.append((head, promise))
                return

            old_consumed, old_value, old_head = promise
            new_consumed = Value()
            self._next = promise
            self._tail = Value()
            self._head.unsafe_set((new_consumed, old_value, self._tail))
            new_consumed.unsafe_listen(self._on_consumed)

    def _on_consumed(self, _, __):
        self._head = self._tail
        if self._closed:
            return

        old_consumed, _, old_head = self._next
        old_consumed.unsafe_set()

        self._next = None
        if self._queue:
            queued_head, queued_promise = self._queue.popleft()
            self._on_promise(queued_head, queued_promise)
        self._add(old_head)

    def _close(self):
        if self._closed:
            return
        self._closed = True

        if self._heads is not None:
            for head in self._heads:
                head.unsafe_unlisten(self._on_promise)

        self._next = None
        self._queue = None
        self._heads = None
        self._tail.unsafe_set(None)

    def add(self, head):
        if head is NULL:
            return
        asap(self._add, head)

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

    def send(self, *args):
        return _SendTo(self, False, args)

    def throw(self, *args):
        if not args:
            args = sys.exc_info()
        return _SendTo(self, True, args)

    def next(self):
        return Event() | self.fork() | Next()

    def __or__(self, other):
        if not isinstance(other, Stream):
            return NotImplemented
        return _PipePair(self, other)


class _Fork(Stream):
    def __init__(self, stream):
        self._stream = stream

        self._result = Value()
        self._input = Value()
        self._output = Value()

        self._messages = Piped()
        self._signals = Piped()

        self._stream_head = self._stream.head()
        self._messages_head = self._messages.head()
        self._signals_head = self._signals.head()

        self._stream._pipe(self._input, NULL, NULL)

        self._messages_head.listen(self._on_message)
        self._signals_head.listen(self._on_signal)
        self._stream_head.listen(self._on_stream)

    def _unlisten_head(self, head, listener):
        head.unsafe_unlisten(listener)

        if head.unsafe_is_set() and head.unsafe_get() is not None:
            consume, value, _ = head.unsafe_get()
            consume.unsafe_unlisten(listener)
            value.unsafe_unlisten(listener)

        return NULL

    def _close_head(self, head):
        if head.unsafe_set(None):
            return head

        promise = head.unsafe_get()
        if promise is None:
            return head

        _, new_value, new_head = promise
        new_value.unsafe_set(None)
        new_head.unsafe_set(None)
        return new_head

    def _close(self, result):
        if not self._result.unsafe_set(result):
            return False

        self._output = self._close_head(self._output)
        self._input = self._close_head(self._input)

        self._stream_head = self._unlisten_head(self._stream_head, self._on_stream)
        self._signals_head = self._unlisten_head(self._signals_head, self._on_signal)
        self._messages_head = self._unlisten_head(self._messages_head, self._on_message)

        self._messages.close()
        self._signals.close()
        self._stream.result().unsafe_unlisten(self._stream_result)
        self._stream = None

        return True

    def _is_closed(self):
        return self._result.unsafe_is_set()

    def _on_stream(self, _, __):
        if self._is_closed():
            return

        while True:
            if not self._stream_head.unsafe_is_set():
                self._stream_head.unsafe_listen(self._on_stream)
                return

            promise = self._stream_head.unsafe_get()
            if promise is None:
                self._output = self._close_head(self._output)
                self._stream.result().unsafe_listen(self._stream_result)
                return

            consume, value, head = promise
            if not self._output.unsafe_is_set():
                self._output.unsafe_set((consume, Value(), Value()))

            if not consume.unsafe_is_set():
                consume.unsafe_listen(self._on_stream)
                return

            if not value.unsafe_is_set():
                value.unsafe_listen(self._on_stream)
                return

            _, new_value, new_head = self._output.unsafe_get()
            new_value.unsafe_set(value.unsafe_get())
            self._output = new_head
            self._stream_head = head

    def _stream_result(self, _, result):
        self._close(result)

    def _on_signal(self, _, __):
        if self._is_closed():
            return

        while True:
            if not self._signals_head.unsafe_is_set():
                self._signals_head.unsafe_listen(self._on_signal)
                return

            promise = self._signals_head.unsafe_get()
            if promise is None:
                return

            consume, value, head = promise
            consume.unsafe_set()
            if not value.unsafe_is_set():
                value.unsafe_listen(self._on_signal)
                return

            result = value.unsafe_get()
            if result is not None and result[0]:
                self._close(result)
                return

            self._signals_head = head

    def _on_message(self, _, __):
        if self._is_closed():
            return

        while True:
            if not self._messages_head.unsafe_is_set():
                self._messages_head.unsafe_listen(self._on_message)
                return

            promise = self._messages_head.unsafe_get()
            if promise is None:
                self._input = self._close_head(self._input)
                return

            consume, value, head = promise
            if not self._input.unsafe_is_set():
                self._input.unsafe_set((consume, Value(), Value()))

            if not value.unsafe_is_set():
                value.unsafe_listen(self._on_message)
                return

            result = value.unsafe_get()
            if result is not None and result[0]:
                self._close(result)
                return

            _, new_value, new_head = self._input.unsafe_get()
            new_value.unsafe_set(result)
            self._input = new_head
            self._messages_head = head

    def _pipe(self, messages, signals, broken):
        self._signals.add(signals)
        self._signals.add(broken)
        self._messages.add(messages)

    def head(self):
        return self._output

    def result(self):
        return self._result


class GeneratorBasedStream(Stream):
    _running = set()

    def __init__(self, gen):
        self._gen = gen

        self._messages = Piped()
        self._signals = Piped()
        self._broken = Piped()

        self._head = Value()
        self._tail = self._head

        self._current_promise = None
        self._current_result = None
        self._current_head = None

        self._result = Value()
        asap(self._start)

    def _start(self):
        try:
            self._running.add(self)
            self._next(False, ())
        finally:
            self = None

    def _next(self, throw, args):
        try:
            if throw:
                next = require_stream(self._gen.throw(*args))
            else:
                next = require_stream(self._gen.send(peel_args(args)))
        except StopIteration as stop:
            self._close(False, stop.args)
        except:
            self._close(True, sys.exc_info())
        else:
            next._pipe(self._messages.head(), self._signals.head(), self._broken.head())

            self._current_result = next.result()
            self._current_head = next.head()
            self._on_promise(None, None)
        finally:
            # Set all local variables to None so references to their
            # original values won't be held in potential traceback objects.
            self = None
            next = None
            stop = None
            throw = None
            args = None

    def _on_promise(self, _, __):
        while True:
            if self._current_promise is None:
                if not self._current_head.unsafe_is_set():
                    self._current_head.unsafe_listen(self._on_promise)
                    return

                promise = self._current_head.unsafe_get()
                if promise is None:
                    self._on_result(self._current_result, None)
                    return

                consume, value, head = promise
                self._tail = Value()
                self._head.unsafe_set((consume, value, self._tail))
                self._current_promise = promise

            consume, value, head = self._current_promise

            if not value.unsafe_is_set():
                value.unsafe_listen(self._on_promise)
                return

            if value.unsafe_get() is None:
                consume.unsafe_set()

            if not consume.unsafe_is_set():
                consume.unsafe_listen(self._on_promise)
                return

            self._current_head = head
            self._current_promise = None
            self._head = self._tail

    def _on_result(self, result, _):
        if not result.unsafe_is_set():
            result.unsafe_listen(self._on_result)
            return

        self._current_promise = None
        self._current_result = None
        self._current_head = None
        throw, args = result.unsafe_get()
        sleep(0.0, self._next, throw, args)

    def _close(self, throw, args):
        self._messages.close()
        self._signals.close()
        self._broken.close()

        self._head.unsafe_set(None)
        self._result.unsafe_set((throw, args))

        self._gen.close()
        self._gen = None
        self._running.discard(self)

    def _pipe(self, messages, signals, broken):
        self._signals.add(signals)
        self._broken.add(broken)
        self._messages.add(messages)

    def head(self):
        return self._head

    def result(self):
        return self._result


class Next(Stream):
    def __init__(self):
        self._result = Value()
        self._heads = None
        self._next = None
        self._queue = None
        self._closed = False

    def _on_promise(self, head, _):
        while not self._closed:
            if not head.unsafe_is_set():
                if self._heads is None:
                    self._heads = set()
                self._heads.add(head)
                head.unsafe_listen(self._on_promise)
                return

            if self._heads is not None:
                self._heads.discard(head)

            promise = head.unsafe_get()
            if promise is None:
                return

            if self._next is not None:
                if self._queue is None:
                    self._queue = collections.deque()
                self._queue.append(promise)
                return

            consume, value, head = promise
            consume.unsafe_set()
            if not value.unsafe_is_set():
                self._next = promise
                value.unsafe_listen(self._on_value)
                return

            result = value.unsafe_get()
            if result is not None:
                self._close(result)
                return

    def _on_value(self, _, result):
        while not self._closed:
            if result is not None:
                self._close(result)
                return

            _, _, head = self._next
            if not self._queue:
                self._next = None
                self._on_promise(head, None)
                return

            self._next = self._queue.pop()
            self._on_promise(head, None)

            consume, value, head = self._next
            consume.unsafe_set()
            if not value.unsafe_is_set():
                value.unsafe_listen(self._on_value)
                return

            result = value.unsafe_get()

    def _close(self, result):
        if self._closed:
            return

        next = self._next
        heads = self._heads

        self._closed = True
        self._heads = None
        self._next = None
        self._queue = None

        if next:
            _, value, _ = next
            value.unsafe_unlisten(self._on_value)

        if heads:
            for head in heads:
                head.unsafe_unlisten(self._on_promise)

        self._result.unsafe_set(result)

    def _do_pipe(self, heads):
        for head in heads:
            if head is not NULL:
                self._on_promise(head, None)

    def _pipe(self, messages, signals, broken):
        asap(self._do_pipe, (signals, broken, messages))

    def head(self):
        return NULL

    def result(self):
        return self._result


class Event(Next):
    def succeed(self, *args):
        Next._pipe(self, Value((NULL, Value((False, args)), NULL)), NULL, NULL)

    def fail(self, *args):
        if not args:
            args = sys.exc_info()
        Next._pipe(self, NULL, Value((NULL, Value((True, args)), NULL)), NULL)

    def _pipe(self, _, signals, broken):
        Next._pipe(self, NULL, signals, broken)


class _Send(Next):
    _CONSUMED = object()
    _RESULT = Value((NULL, Value(_CONSUMED), NULL))

    def __init__(self, throw, args):
        Next.__init__(self)

        self._message = throw, args

        self._consumed = Value()
        self._value = Value()
        self._head = Value((self._consumed, self._value, NULL))

        self._consumed.unsafe_listen(self._on_consumed)

    def _on_consumed(self, consumed, _):
        Next._pipe(self, self._RESULT, NULL, NULL)

    def _close(self, result):
        if result is self._CONSUMED:
            value = self._message
            result = False, ()
        else:
            value = None
            self._consumed.unsafe_unlisten(self._on_consumed)
            self._consumed.unsafe_set()
        self._value.unsafe_set(value)
        Next._close(self, result)

    def _pipe(self, _, signals, broken):
        Next._pipe(self, NULL, signals, broken)

    def head(self):
        return self._head


class _SendTo(_Send):
    def __init__(self, target, throw, args):
        _Send.__init__(self, throw, args)

        self._target = target
        self._target.result().listen(self._on_target)

        if throw:
            self._target._pipe(NULL, _Send.head(self), NULL)
        else:
            self._target._pipe(_Send.head(self), NULL, NULL)

    def _on_target(self, _, (throw, args)):
        if not throw:
            args = (BrokenPipe, BrokenPipe(*args), None)
        Next._pipe(self, NULL, NULL, Value((NULL, Value((True, args)), NULL)))

    def _close(self, result):
        self._target.result().unsafe_unlisten(self._on_target)
        self._target = None

        _Send._close(self, result)

    def head(self):
        return NULL


class _PipePair(Stream):
    def __init__(self, left, right):
        self._left = left
        self._right = right

        self._message_head = Value()
        self._signal_head = Value()
        self._broken_head = Value()
        right._pipe(self._message_head, self._signal_head, NULL)
        left._pipe(NULL, NULL, self._broken_head)

        self._result = Value()

        self._right.result().listen(self._right_result)
        self._left.result().listen(self._left_result)
        self._left.head().listen(self._message_promise)

    def _left_result(self, _, (throw, args)):
        if self._check_result():
            return

        if throw:
            self._signal_head.unsafe_set((NULL, Value((True, args)), NULL))
        else:
            self._signal_head.unsafe_set(None)

    def _right_result(self, _, (throw, args)):
        if self._check_result():
            return

        if not throw:
            throw = True
            args = (BrokenPipe, BrokenPipe(*args), None)
        self._broken_head.unsafe_set((NULL, Value((throw, args)), NULL))

    def _check_result(self):
        result = self._result
        if result.unsafe_is_set():
            return True

        left_result = self._left.result()
        if not left_result.unsafe_is_set():
            return False

        right_result = self._right.result()
        if not right_result.unsafe_is_set():
            return False

        result_value = right_result.unsafe_get()
        self._result.unsafe_set(result_value)
        return True

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

        old_head.unsafe_set((consume, value, new_head))
        head.unsafe_listen(self._message_promise)

    def _message_final(self, _, (throw, args)):
        if not throw:
            args = StopIteration, StopIteration(*args), None
            self._message_head.unsafe_set((NULL, Value((True, args)), NULL))

    def _pipe(self, messages, signals, broken):
        self._left._pipe(messages, signals, NULL)
        self._right._pipe(NULL, NULL, broken)

    def head(self):
        return self._right.head()

    def result(self):
        return self._result


class Proxy(Stream):
    def __init__(self, proxied):
        Stream.__init__(self)

        self._proxied = require_stream(proxied)

    def _pipe(self, *args, **keys):
        return self._proxied._pipe(*args, **keys)

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


@stream
def map(func, *args, **keys):
    while True:
        value = yield next()

        iterable = func(value, *args, **keys)
        if iterable is None:
            continue

        for result in iterable:
            yield send(result)


def pipe(first, *rest):
    if not rest:
        return require_stream(first)
    cut = len(rest) // 2
    return _PipePair(pipe(first, *rest[:cut]), pipe(*rest[cut:]))


next = Next


def send(*args):
    return _Send(False, args)


def stop(*args):
    raise StopIteration(*args)


def consume():
    return map(lambda x: None)


class Signal(Exception):
    _signames = None

    @classmethod
    def _get_signal_names(cls, signum):
        r"""
        Return a lexigocraphically sorted tuple of symbolic names
        for the given signal number.

        >>> Signal._get_signal_names(signal.SIGINT)
        ('SIGINT',)

        Return an empty tuple when no names are found.

        >>> Signal._get_signal_names(signal.NSIG + 1)
        ()
        """

        if cls._signames is None:
            signames = {}

            for name, value in inspect.getmembers(signal):
                if not name.startswith("SIG"):
                    continue
                if name.startswith("SIG_"):
                    continue
                if not isinstance(value, numbers.Integral):
                    continue
                signames.setdefault(value, []).append(name)

            for key, names in signames.iteritems():
                signames[key] = tuple(sorted(names))

            cls._signames = signames

        return cls._signames.get(signum, ())

    def __init__(self, signum):
        Exception.__init__(self, signum)

    @property
    def signum(self):
        return self.args[0]

    def __str__(self):
        signum = self.signum
        result = "caught signal " + repr(signum)

        names = self._get_signal_names(signum)
        if names:
            result += " (" + " / ".join(names) + ")"

        return result


def main_loop(main, catch_signals=(signal.SIGINT, signal.SIGTERM, signal.SIGUSR1, signal.SIGUSR2)):
    def handle_signal(signum, _):
        thread = threading.Thread(target=asap, args=[main.throw, Signal(signum)])
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
