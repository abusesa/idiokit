from __future__ import with_statement

import sys
import threading
import functools
import collections

from . import callqueue
from .values import Value

NULL = Value(None)

class BrokenPipe(Exception):
    pass

class _Queue(object):
    _lock = threading.Lock()

    def __init__(self, only_tail=False):
        self._tail = Value()

        if only_tail:
            self._head = None
        else:
            self._head = self._tail
            self._head.listen(self._move_promise)

    def _move_promise(self, promise):
        if promise is None:
            return

        consume, value, head = promise
        value.listen(self._move_value)

    def _move_value(self, result):
        if result is None:
            return self._move_consume(None)

        consume, value, head = self._head.get()
        consume.listen(self._move_consume)

    def _move_consume(self, _):
        consume, value, head = self._head.get()

        with self._lock:
            self._head = head

        head.listen(self._move_promise)

    def head(self):
        with self._lock:
            head = self._head
            result = self._tail if head is None else head
        return result

class Piped(_Queue):
    def __init__(self, *args, **keys):
        _Queue.__init__(self, *args, **keys)

        self._flows = dict()

    def add(self, head):
        if head is NULL:
            return

        with self._lock:
            if self._flows is None:
                return

            key = object()
            callback = functools.partial(self._promise, key)
            self._flows[key] = head, callback

        head.listen(callback)

        with self._lock:
            if self._flows is not None:
                return

        head.unlisten(callback)

    def _promise(self, key, promise):
        with self._lock:
            if self._flows is None:
                return
            if promise is None:
                self._flows.pop(key, None)
                return

            consume, value, head = promise
            _, callback = self._flows[key]
            self._flows[key] = head, callback

            out_next = Value()
            tail = self._tail
            self._tail = out_next

        out_consume = Value()
        out_consume.listen(consume.set)

        tail.set((out_consume, value, out_next))
        head.listen(callback)

        with self._lock:
            if self._flows is not None:
                return

        head.unlisten(callback)

    def close(self):
        with self._lock:
            if self._flows is None:
                return

            flows = self._flows
            self._flows = None

        for head, callback in flows.itervalues():
            head.unlisten(callback)
        self._tail.set(None)

def peel_args(args):
    if not args:
        return None
    elif len(args) == 1:
        return args[0]
    return args

def stream(func):
    @functools.wraps(func)
    def _stream(*args, **keys):
        gen = iter(func(*args, **keys))
        return Generator(gen)
    return _stream

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
        return self._send(False, True, args)

    def signal(self, *args):
        return self._send(False, True, args)

    def next(self):
        return Event() | self.fork() | Next()

    def __or__(self, other):
        return PipePair(self, other)

    # to be deprecated

    def has_result(self):
        return self.result().is_set()

    def rethrow(self):
        self.throw(*sys.exc_info())

class _SendBase(Stream):
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
        consumed.set()
        value.listen(self._input_value)

    def _input_value(self, value):
        if value is None:
            self._input_head.listen(self._input_promise)
            return

        if value is self._PARENT:
            self._value.set(None)
            self._result.set((True, (BrokenPipe, BrokenPipe(), None)))
        elif self._parent is not None:
            self._parent.unlisten(self._set_parent)
        self._parent = None

        if value is self._CONSUMED:
            self._value.set(self._message)
            self._result.set((False, ()))
        else:
            self._consumed.unlisten(self._set_consumed)
        self._message = None

        if value not in (self._CONSUMED, self._PARENT):
            self._value.set(None)
            self._result.set(value)
        self._input.close()
        self._input_head = None

    def pipe_left(self, _, signal_head):
        self._input.add(signal_head)

    def pipe_right(self, broken_head):
        self._input.add(broken_head)

    def message_head(self):
        return NULL

    def result(self):
        return self._result

class Send(_SendBase):
    def __init__(self, throw, args):
        _SendBase.__init__(self, None, throw, args)

    def message_head(self):
        if self._consumed.is_set():
            return NULL
        return self._head

class _ForkOutput(_Queue):
    def __init__(self, head):
        _Queue.__init__(self)

        self._current = head
        self._current.listen(self._promise)

    def _promise(self, promise):
        if promise is None:
            with self._lock:
                self._current = None
            self._tail.set(None)
            return

        with self._lock:
            if self._current is None:
                return
            consumed, value, current = promise
            self._current = current

            old_tail = self._tail
            new_tail = Value()
            self._tail = new_tail

        new_consumed = Value()
        new_consumed.listen(consumed.set)

        old_tail.set((new_consumed, value, new_tail))
        current.listen(self._promise)

    def close(self):
        with self._lock:
            if self._current is None:
                return
            current = self._current
            self._current = None

        self._tail.set(None)
        current.unlisten(self._promise)

class Fork(Stream):
    def __init__(self, stream):
        self._stream = stream

        self._input = Piped(True)
        self._output = _ForkOutput(self._stream.message_head())
        self._result = Value()

        msg = Value()
        self._input.head().listen(functools.partial(self._input_promise, msg))
        self._stream.pipe_left(msg, NULL)
        self._stream.result().listen(self._stream_result)

    def _stream_result(self, result):
        if self._result.set(result):
            self._input.close()
            self._stream = None

    def _input_promise(self, message, promise):
        if promise is None:
            message.set(None)
            return

        consume, value, head = promise
        next_value = Value()
        next_message = Value()

        message.set((consume, next_value, next_message))
        value.listen(functools.partial(self._input_value,
                                       head, next_value, next_message))

    def _input_value(self, head, next_value, next_message, result):
        if result is None or not result[0]:
            next_value.set(result)
            head.listen(functools.partial(self._input_promise, next_message))
            return

        throw, args = result

        next_value.set(None)
        next_message.set(None)
        self._input.close()

        if self._result.set(result):
            self._output.close()
            self._stream.result().unlisten(self._stream_result)
            self._stream = None

    def pipe_left(self, messages, signals):
        self._input.add(signals)
        self._input.add(messages)

    def pipe_right(self, broken):
        self._input.add(broken)

    def message_head(self):
        return self._output.head()

    def result(self):
        return self._result

class _GeneratorOutput(_Queue):
    def __init__(self, *args, **keys):
        _Queue.__init__(self, *args, **keys)

        self._stack = collections.deque()
        self._closed = False

    def stack(self, stream):
        if stream.message_head() is NULL:
            return

        with self._lock:
            if self._closed:
                return

            if self._stack:
                self._stack.append(stream)
                return

            self._stack.append(None)

        stream.message_head().listen(self._promise)

    def _promise(self, promise):
        if promise is None:
            with self._lock:
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
                    self._tail.set(None)
            else:
                stream.message_head().listen(self._promise)
        else:
            consume, value, head = promise

            next_consume = Value()
            next_consume.listen(consume.set)

            tail = self._tail
            self._tail = Value()

            tail.set((next_consume, value, self._tail))
            head.listen(self._promise)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True

            if self._stack:
                return
        self._tail.set(None)

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
            self.close(False, stop.args)
        except:
            self.close(True, sys.exc_info())
        else:
            next.pipe_left(self._messages.head(), self._signals.head())
            next.pipe_right(self._broken.head())

            self._output.stack(next)

            next.result().listen(self._step)

    def close(self, throw, args):
        self._output.close()

        self._messages.close()
        self._signals.close()
        self._broken.close()

        self._result.set((throw, args))

        self._gen = None
        self._step = None
        self._running.discard(self)

    def pipe_left(self, messages, signals):
        self._messages.add(messages)
        self._signals.add(signals)

    def pipe_right(self, pipes):
        self._broken.add(pipes)

    def message_head(self):
        return self._output.head()

    def result(self):
        return self._result

class Next(Stream):
    def __init__(self):
        self._result = Value()
        self._input = Piped(True)
        self._input.head().listen(self._promise)

    def _promise(self, promise):
        if promise is None:
            self._input.close()
            return

        consume, value, head = promise
        consume.set()

        value.listen(functools.partial(self._value, head))

    def _value(self, head, result):
        if result is None:
            head.listen(self._promise)
            return
        self._input.close()
        self._result.set(result)

    def pipe_left(self, messages, signals):
        self._input.add(signals)
        self._input.add(messages)

    def pipe_right(self, pipes):
        self._input.add(pipes)

    def message_head(self):
        return NULL

    def result(self):
        return self._result

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
        self._left.message_head().listen(self._message_promise)

    def _left_result(self, (throw, args)):
        if throw:
            self._signal_head.set((NULL, Value((True, args)), NULL))
        else:
            self._signal_head.set(None)
        self._right.result().listen(self._result.set)

    def _right_result(self, (throw, args)):
        self._broken_head.set((NULL, Value((True, (BrokenPipe,))), NULL))

    def _message_promise(self, promise):
        if self._right.result().is_set():
            return

        if promise is None:
            self._left.result().listen(self._message_final)
            return

        consume, value, head = promise

        old_head = self._message_head
        new_head = Value()
        self._message_head = new_head

        if not old_head.set((consume, value, new_head)):
            return

        head.listen(self._message_promise)

    def _message_final(self, (throw, args)):
        if not throw:
            args = StopIteration, StopIteration(*args), None
            self._message_head.set((NULL, Value((True, args)), NULL))

    def pipe_left(self, *args, **keys):
        return self._left.pipe_left(*args, **keys)

    def pipe_right(self, *args, **keys):
        return self._right.pipe_right(*args, **keys)

    def message_head(self):
        return self._right.message_head()

    def result(self):
        return self._result

class Event(Stream):
    def __init__(self):
        self._result = Value()
        self._input = Piped(True)
        self._input_head = self._input.head()
        self._input_head.listen(self._input_promise)

    def _input_promise(self, promise):
        consumed, value, self._input_head = promise
        consumed.set()
        value.listen(self._input_value)

    def _input_value(self, value):
        if value is None:
            self._input_head.listen(self._input_promise)
            return
        self._input.close()
        self._input_head = None
        self._result.set(value)

    def succeed(self, *args):
        return self.set((False, args))

    def fail(self, *args):
        return self.set((True, args))

    def set(self, args):
        self._input.add(Value((NULL, Value(args), NULL)))

    def pipe_left(self, _, signal_head):
        self._input.add(signal_head)

    def pipe_right(self, broken_head):
        self._input.add(broken_head)

    def message_head(self):
        return NULL

    def result(self):
        return self._result

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

        head = _signal.head
        _signal.head = Value()

        thread = threading.Thread(target=head.set,
                                  args=((consume, value, _signal.head),))
        thread.setDaemon(True)
        thread.start()
    _signal.head = Value()

    main.pipe_left(NULL, _signal.head)

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

                if result.is_set():
                    break

                while not event.isSet():
                    event.wait(0.5)
                event.clear()
    finally:
        signal.signal(signal.SIGINT, sigint)
        signal.signal(signal.SIGTERM, sigterm)

    throw, args = result.get()
    if throw:
        exc_type, exc_value, exc_tb = args + (None,) * (3-len(args))
        raise exc_type, exc_value, exc_tb
    return peel_args(args)
