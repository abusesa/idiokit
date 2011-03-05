from __future__ import with_statement
import collections
import callqueue
import threading
import functools
import random
import sys

def peel_args(args):
    if not args:
        return None
    elif len(args) == 1:
        return args[0]
    return args

class Finished(Exception):
    pass

class Callback(object):
    __slots__ = "func", "args", "keys"

    def __init__(self, func, args, keys):
        self.func = func
        self.args = args
        self.keys = keys

    def call(self, *args):
        new_args = self.args + args
        return self.func(*new_args, **self.keys)

class NotFinished(Exception):
    pass

class Reg(object):
    _local = threading.local()

    @property
    def was_source(self):
        return getattr(self._local, "source", None) is self

    def __init__(self):
        self.lock = threading.Lock()
        self.message_callbacks = set()
        self.finish_callbacks = set()

        self._id = None
        self._result = None

    def signal_activity(self, result=None):
        with self.lock:
            self._result = result
            self._id = object()
            callbacks = self.message_callbacks
            self.message_callbacks = set()
        for callback in callbacks:
            callback.call(self)

        if result is not None:
            with self.lock:
                callbacks = self.finish_callbacks
                self.finish_callbacks = set()
            for callback in callbacks:
                callback.call(self)

    def add_message_callback(self, func, *args, **keys):
        callback = Callback(func, args, keys)
        with self.lock:
            if self._id is None:
                self.message_callbacks.add(callback)
                return callback
        callback.call(self)
        return callback

    def discard_message_callback(self, callback):
        with self.lock:
            self.message_callbacks.discard(callback)

    def add_finish_callback(self, func, *args, **keys):
        callback = Callback(func, args, keys)
        with self.lock:
            if self._result is None:
                self.finish_callbacks.add(callback)
                return callback
        callback.call(self)
        return callback

    def discard_finish_callback(self, callback):
        with self.lock:
            self.finish_callbacks.discard(callback)

    def __iter__(self):
        next_raw = self.next_raw

        while True:
            item = next_raw()
            if item is None:
                return

            final, throw, args = item
            if throw:
                type, exc, tb = args
                raise type, exc, tb
            if final:
                raise Finished(*args)

            yield peel_args(args)

    def __or__(self, other):
        return PipePair(self, other)

    def has_result(self):
        with self.lock:
            return self._result is not None

    def __nonzero__(self):
        with self.lock:
            return self._id is not None

    def next_raw(self):
        with self.lock:
            _id = self._id
            if _id is None:
                return None
            
        item = self._next_raw()
        if item is None:
            with self.lock:
                if self._id is _id:
                    self._id = None
            return None

        final, throw, args = item
        with self.lock:
            if final:
                self._result = throw, args
                if self._id is None:
                    self._id = object()
        return item

    def result_raw(self):
        with self.lock:
            if self._result is None:
                raise NotFinished()
            return self._result

    def result(self):
        throw, args = self.result_raw()
        if not throw:
            return peel_args(args)
        type, exc, tb = args
        raise type, exc, tb

    def rethrow(self):
        _, exception, traceback = sys.exc_info()
        self.throw(exception, traceback)

    # implement these

    def next_is_final(self):
        raise NotImplementedError()

    def _next_raw(self):
        raise NotImplementedError()

    def pipe(self, other):
        raise NotImplementedError("this stream is not pipeable")

    def send(self, *values):
        return

    def throw(self, exc, tb=None):
        return

class Channel(Reg):
    def __init__(self):
        Reg.__init__(self)
        self.queue = collections.deque()

    def send(self, *values):
        self._push(False, False, values)

    def throw(self, exc, tb=None):
        self._push(True, True, (type(exc), exc, tb))

    def finish(self, *args):
        self._push(True, False, args)

    def _push(self, final, throw, args):
        with self.lock:
            if self.queue and self.queue[-1][0]:
                return
            self.queue.append((final, throw, args))
            if final:
                result = throw, args
            elif len(self.queue) == 1:
                result = None
            else:
                return
        self.signal_activity(result)

    def next_is_final(self):
        with self.lock:
            if self.queue and self.queue[0][0]:
                return True
            return False

    def _next_raw(self):
        with self.lock:
            if not self.queue:
                return None

            final, throw, args = self.queue.popleft()
            if final:
                self.queue.append((final, throw, args))
            return final, throw, args

class _Pipeable(Reg):
    def __init__(self):
        Reg.__init__(self)

        self.pipes = dict()
        self.pipes_pending = collections.deque()
        self.final = None

    def _pipe_callback(self, other):
        with self.lock:
            if other not in self.pipes:
                return
            self.pipes[other] = None

            self.pipes_pending.append(other)
            if len(self.pipes_pending) > 1:
                return
        self.signal_activity()

    def _finish(self, throw, args):
        with self.lock:
            if self.final is not None:
                return
            self.final = True, throw, args
            self.pipes_pending.clear()
            pipes = dict(self.pipes)
            self.pipes.clear()

        for other, callback in pipes.items():
            other.discard_message_callback(callback)
        self.signal_activity((throw, args))

    def _pipe(self, other):
        with self.lock:
            if self.final is not None:
                return
            if other in self.pipes:
                return
            self.pipes[other] = None
            self.pipes_pending.append(other)
            if len(self.pipes_pending) > 1:
                return
        self.signal_activity()

    def _next_raw(self):
        while True:
            with self.lock:
                if self.final:
                    return self.final
                if not self.pipes_pending:
                    return None
                other = self.pipes_pending.popleft()

            item = other.next_raw()
            if item is None:
                with self.lock:
                    _id = object()
                    self.pipes[other] = _id
                callback = other.add_message_callback(self._pipe_callback)
                with self.lock:
                    if self.pipes.get(other, None) is _id:
                        self.pipes[other] = callback
                        continue
                other.discard_message_callback(callback)
            else:
                final, throw, args = item
                if final:
                    with self.lock:
                        callback = self.pipes.pop(other, None)
                    other.discard_message_callback(callback)
                    if not throw:
                        throw = True
                        args = Finished, Finished(*args), None
                else:
                    with self.lock:
                        self.pipes_pending.append(other)
                return False, throw, args

    def next_is_final(self):
        with self.lock:
            return self.final is not None

class _Stackable(Reg):
    def __init__(self):
        Reg.__init__(self)

        self.stack = collections.deque()
        self.final = None

    def _stack_callback(self, other):
        with self.lock:
            if self.final is not None:
                return
            if not self.stack:
                return
            if other is not self.stack[0]:
                return
        self.signal_activity()

    def _stack(self, other):
        with self.lock:
            if self.final is not None:
                return
            self.stack.append(other)
        self.next_is_final()
        self.signal_activity()
            
    def _finish(self, throw, args):
        with self.lock:
            if self.final is not None:
                return
            self.final = True, throw, args
        self.next_is_final()
        self.signal_activity((throw, args))
        
    def _next_raw(self):
        while True:
            with self.lock:
                if self.stack:
                    other = self.stack[0]
                elif self.final:
                    return self.final
                else:
                    return None
            
            item = other.next_raw()
            if item is None:
                other.add_message_callback(self._stack_callback)
                return None

            final, throw, args = item
            if not final:
                return item

            with self.lock:
                if self.stack and other is self.stack[0]:
                    self.stack.popleft()

    def next_is_final(self):
        while True:
            with self.lock:
                if not self.stack:
                    return self.final is not None
                other = self.stack[0]

            if not other.next_is_final():
                return False

            with self.lock:
                if self.stack and other is self.stack[0]:
                    self.stack.popleft()

class Inner(_Pipeable):
    def __init__(self, outer):
        _Pipeable.__init__(self)
        self.outer = outer

    def send(self, *values):
        if self.outer is not None:
            self.outer.inner_send(*values)

    def finish(self, *values):
        raise Finished(*values)

    def _finish(self, throw, args):
        _Pipeable._finish(self, throw, args)

        if self.outer is not None:
            self.outer.inner_finish(throw, args)
            self.outer = None

    def thread(self, func, *args, **keys):
        import threadpool
        return threadpool.run(func, *args, **keys)

    def sub(self, other):
        def _callback(channel, _):
            throw, args = other.result_raw()
            if throw:
                _, exc, tb = args
                channel.throw(exc, tb)
            else:
                channel.finish(*args)

        channel = Channel()
        other.pipe(self)
        other.add_finish_callback(_callback, channel)

        if self.outer is not None:        
            self.outer.inner_sub(other)
        return channel

class BrokenPipe(Exception):
    pass

class NullSource(Reg):
    def __init__(self):
        Reg.__init__(self)
        self.signal_activity()
    
    def _next_raw(self):
        return False, False, ()
null_source = NullSource()

class GeneratorStream(_Stackable):
    _running_streams = set()

    def start(self):
        with self.lock:
            if self._started:
                return
            self._started = True
        self._gen = self.run()
        callqueue.add(self._begin)

    def _begin(self):
        self._callbacks[null_source] = None
        self._running_streams.add(self)
        self._step(null_source)

    def _end(self, throw, args):
        self._gen = None
        self._running_streams.discard(self)
        self.inner._finish(throw, args)

    def _step(self, source):
        callbacks = self._callbacks
        if source not in callbacks:
            return

        if not self._fast:
            item = source.next_raw()
            if item is None:
                cb = source.add_message_callback(callqueue.add, self._step)
                callbacks[source] = cb
                return
            final, throw, args = item
            self._local.source = source
        elif not source:
            cb = source.add_message_callback(callqueue.add, self._step)
            callbacks[source] = cb
            return

        for other, callback in callbacks.items():
            other.discard_message_callback(callback)
        callbacks.clear()

        try:
            if self._fast:
                next = self._gen.next()
            else:
                if throw:
                    next = self._gen.throw(*args)
                else:
                    next = self._gen.send(peel_args(args))
        except (StopIteration, Finished), exc:
            self._end(False, exc.args)
        except:
            self._end(True, sys.exc_info())
        else:
            if next is None:
                next = (null_source,)
            elif isinstance(next, Reg):
                next = (next,)
            else:
                next = list(set(next))
                random.shuffle(next)

            for other in next:
                callbacks[other] = None
                callqueue.add(self._step, other)

    def __init__(self, fast=False):
        _Stackable.__init__(self)

        self.inner = Inner(self)
        self._gen = None
        self._callbacks = dict()

        self._started = False
        self._fast = fast

        self.input = Channel()
        self.output = Channel()

        self.inner._pipe(self.input)
        self._stack(self.output)
        
    def pipe(self, other):
        return self.inner._pipe(other)

    def _pipe_broken(self):
        self.throw(BrokenPipe())

    def send(self, *values):
        self.input.send(*values)

    def throw(self, exc, tb=None):
        self.input.throw(exc, tb)

    def inner_send(self, *args):
        self.output.send(*args)

    def inner_finish(self, throw, args):
        self._finish(throw, args)
        if throw:
            type, exc, tb = args
            self.output.throw(exc, tb)
        else:
            self.output.finish(*args)

    def inner_sub(self, other):
        with self.lock:
            old_output = self.output
            self.output = Channel()
        old_output.finish()
        self._stack(other)
        self._stack(self.output)

    def run(self):
        while True:
            yield self.inner
            tuple(self.inner)

class FuncStream(GeneratorStream):
    def __init__(self, fast, func, *args, **keys):
        GeneratorStream.__init__(self, fast)
        self.func = func
        self.args = args
        self.keys = keys
        self.start()

    def run(self):
        args = (self.inner,) + self.args
        return self.func(*args, **self.keys)

def stream(func):
    @functools.wraps(func)
    def _stream(*args, **keys):
        return FuncStream(False, func, *args, **keys)
    return _stream

def stream_fast(func):
    @functools.wraps(func)
    def _stream_fast(*args, **keys):
        return FuncStream(True, func, *args, **keys)
    return _stream_fast

class PipePair(Reg):
    def __init__(self, left, right):
        Reg.__init__(self)

        self.left = left
        self.right = right

        self.left_has_result = False
        self.right_has_result = False
        self.input = Channel()

        self.left.pipe(self.input)
        self.right.pipe(self.left)
        self.left.add_finish_callback(self._left_finish_callback)
        self.right.add_finish_callback(self._right_finish_callback)
        self.right.add_message_callback(self._callback)

    def _finish(self):
        self.signal_activity(self.right.result_raw())

    def _left_finish_callback(self, _):
        with self.lock:
            self.left_has_result = True
            if not self.right_has_result:
                return
        self._finish()

    def _right_finish_callback(self, _):
        self.left._pipe_broken()
        with self.lock:
            self.right_has_result = True
            if not self.left_has_result:
                return
        self._finish()

    def _callback(self, _):
        self.signal_activity()
        
    def _pipe_broken(self):
        self.right._pipe_broken()

    def pipe(self, other):
        self.left.pipe(other)

    def _next_raw(self):
        item = self.right.next_raw()
        if item is None:
            self.right.add_message_callback(self._callback)
            return None
        final, throw, args = item
        if final and not self.left_has_result:
            return None
        return item

    def send(self, *values):
        self.input.send(*values)

    def throw(self, exc, tb=None):
        self.input.throw(exc, tb)

    def next_is_final(self):
        return self.right.next_is_final()

def pipe(first, *rest):
    if not rest:
        return first
    cut = len(rest) // 2
    return PipePair(pipe(first, *rest[:cut]), pipe(*rest[cut:]))

@stream
def dev_null(inner):
    while True:
        yield inner
        list(inner)

def run(main, throw_on_signal=None):
    import signal

    def _signal(*args, **keys):
        main.throw(throw_on_signal)
    sigint = signal.getsignal(signal.SIGINT)
    sigterm = signal.getsignal(signal.SIGTERM)

    if throw_on_signal is not None:
        signal.signal(signal.SIGINT, _signal)
        signal.signal(signal.SIGTERM, _signal)

    event = threading.Event()
    try:
        with callqueue.exclusive(event.set) as iterate:
            while not main.has_result():
                iterate()
                while not (main.has_result() or event.isSet()):
                    event.wait(0.5)
                event.clear()
    finally:
        if throw_on_signal is not None:
            signal.signal(signal.SIGINT, sigint)
            signal.signal(signal.SIGTERM, sigterm)

    throw, args = main.result_raw()
    if throw:
        type, exc, tb = args
        raise type, exc, tb
    return peel_args(args)

import unittest

class StreamTests(object):
    stream_class = None

    def setUp(self):
        self.stream = self.stream_class()
        
    def tearDown(self):
        self.stream = None
    
    def test_new_stream_starts_empty(self):
        assert not self.stream

    def test_new_stream_next_is_not_final(self):
        assert not self.stream.next_is_final()

class TestChannel(StreamTests, unittest.TestCase):
    stream_class = Channel

    def test_becomes_empty(self):
        self.stream.send()
        for _ in self.stream: break
        assert not self.stream

    def test_next_is_final(self):
        self.stream.finish()
        assert self.stream.next_is_final()

    def test_next_is_not_final(self):
        self.stream.send()
        self.stream.finish()
        assert not self.stream.next_is_final()

    def test_next_becomes_final(self):
        self.stream.send()
        self.stream.finish()
        for _ in self.stream: break
        assert self.stream.next_is_final()

    def test_finishing(self):
        unique = object()
        self.stream.finish(unique)
        assert self.stream.next_raw() == (True, False, (unique,))

class AggregateTests(object):
    aggregate_method = None
    aggregate_finish_method = None

    def test_aggregate_stays_empty(self):
        self.aggregate_method(self.stream, Channel())
        assert not self.stream

    def test_aggregate_becomes_empty(self):
        channel = Channel()
        channel.send()

        self.aggregate_method(self.stream, channel)
        for _ in self.stream: break
        assert not self.stream

    def test_finishing(self):
        unique = object()
        self.aggregate_finish_method(self.stream, False, (unique,))
        assert self.stream.next_raw() == (True, False, (unique,))

    def test_next_is_final(self):
        self.aggregate_finish_method(self.stream, False, ())
        assert self.stream.next_is_final()

class Test_Pipeable(StreamTests, AggregateTests, unittest.TestCase):
    stream_class = _Pipeable
    aggregate_method = stream_class._pipe
    aggregate_finish_method = stream_class._finish

    def test_finishing_when_pending_data(self):
        channel = Channel()
        channel.send()

        self.stream._pipe(channel)
        self.stream._finish(False, ())
        assert self.stream.next_is_final()

class Test_Stackable(StreamTests, AggregateTests, unittest.TestCase):
    stream_class = _Stackable
    aggregate_method = stream_class._stack
    aggregate_finish_method = stream_class._finish

    def test_next_is_not_final(self):
        channel = Channel()
        channel.send()

        self.stream._stack(channel)
        self.stream._finish(False, ())
        assert not self.stream.next_is_final()

if __name__ == "__main__":
    unittest.main()
