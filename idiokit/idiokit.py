from __future__ import absolute_import

import sys
import signal
import inspect
import threading
import collections
from functools import partial, wraps

from ._selectloop import sleep, asap, iterate
from .values import Value

__version__ = "2.3.0"

NULL = Value(None)


class BrokenPipe(Exception):
    pass


class Piped(object):
    def __init__(self):
        self._head = Value()
        self._tail = self._head

        self._closed = False
        self._sealed = False

        self._next = None
        self._queue = None
        self._heads = None

    def head(self):
        return self._head

    def _add(self, head):
        if self._sealed:
            return
        self._on_new_head(head)

    def _on_new_head(self, head):
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
                self._maybe_close()
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
        self._on_new_head(old_head)

    def _maybe_close(self):
        if self._sealed and not self._next and not self._queue and not self._heads:
            self._close()

    def _seal(self):
        if self._sealed:
            return
        self._sealed = True
        self._maybe_close()

    def _close(self):
        if self._closed:
            return
        self._closed = True
        self._sealed = True

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

        self._messages = Piped()
        self._signals = Piped()

        self._output = Piped()
        self._output.add(self._stream.head())
        self._output.seal()

        self._result = Value()

        self._current = Value()
        self._messages.head().listen(self._message_promise)
        self._signals.head().listen(self._signal_promise)

        self._stream._pipe(self._current, NULL, NULL)
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

    def _pipe(self, messages, signals, broken):
        self._signals.add(signals)
        self._signals.add(broken)
        self._messages.add(messages)

    def head(self):
        return self._output.head()

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
        self._current_count = 0

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
            self._on_promise(next.head(), None)
        finally:
            # Set all local variables to None so references to their
            # original values won't be held in potential traceback objects.
            self = None
            next = None
            stop = None
            throw = None
            args = None

    def _on_promise(self, head, _):
        self._current_promise = None
        self._current_count = 0

        if not head.unsafe_is_set():
            head.unsafe_listen(self._on_promise)
            return

        promise = head.unsafe_get()
        if promise is None:
            self._on_result(self._current_result, None)
            return

        self._current_promise = promise
        consume, value, head = promise

        new_consume = Value()
        self._tail = Value()
        self._head.unsafe_set((new_consume, value, self._tail))
        value.unsafe_listen(self._on_value)
        new_consume.unsafe_listen(self._on_consume)

    def _on_value(self, _, result):
        if result is None:
            new_consume, _, _ = self._head.unsafe_get()
            new_consume.unsafe_set()
        self._inc_count()

    def _on_consume(self, _, __):
        consume, value, head = self._current_promise
        consume.unsafe_set()
        self._inc_count()

    def _inc_count(self):
        self._current_count += 1
        if self._current_count < 2:
            return

        consume, value, head = self._current_promise
        self._head = self._tail
        self._on_promise(head, None)

    def _on_result(self, result, _):
        if not result.unsafe_is_set():
            result.unsafe_listen(self._on_result)
            return

        self._current_result = None
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


def _iter_signal_names():
    for name in dir(signal):
        if not name.startswith("SIG"):
            continue
        if name.startswith("SIG_"):
            continue

        signum = getattr(signal, name)
        if type(signum) != int:
            continue

        yield signum, name


class Signal(BaseException):
    _signames = dict(_iter_signal_names())

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
