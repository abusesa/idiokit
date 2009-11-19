from __future__ import with_statement
import collections
import callqueue
import threading
import weakref
import random
import sys

def peel_args(args):
    if not args:
        return None
    if len(args) == 1:
        return args[0]
    return args

class Finished(Exception):
    pass

class Callback(object):
    def __init__(self, func, *args, **keys):
        self.func = func
        self.args = args
        self.keys = keys

    def __call__(self, *args, **keys):
        new_args = self.args + args
        new_keys = dict(self.keys)
        new_keys.update(keys)
        return self.func(*new_args, **new_keys)

class Empty(Exception):
    pass

class NotFinished(Exception):
    pass

class Reg(object):
    _local = threading.local()

    @property
    def was_source(self):
        return getattr(self._local, "source", None) is self

    _with_callbacks = set()
    _with_callbacks_lock = threading.Lock()

    def _update_callbacks(self):
        with self._with_callbacks_lock:
            if self.message_callbacks or self.finish_callbacks:
                self._with_callbacks.add(self)
            else:
                self._with_callbacks.discard(self)

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
            callback(self)

        if result is not None:
            with self.lock:
                callbacks = self.finish_callbacks
                self.finish_callbacks = set()
            for callback in callbacks:
                callback(self)

        self._update_callbacks()

    def add_message_callback(self, func, *args, **keys):
        callback = Callback(func, *args, **keys)
        with self.lock:
            if self._id is None:
                self.message_callbacks.add(callback)
                self._update_callbacks()
                return callback
        callback(self)
        return callback

    def discard_message_callback(self, callback):
        with self.lock:
            self.message_callbacks.discard(callback)
        self._update_callbacks()

    def add_finish_callback(self, func, *args, **keys):
        callback = Callback(func, *args, **keys)
        with self.lock:
            if self._result is None:
                self.finish_callbacks.add(callback)
                self._update_callbacks()
                return callback
        callback(self)
        return callback

    def discard_finish_callback(self, callback):
        with self.lock:
            self.finish_callbacks.discard(callback)
        self._update_callbacks()

    def __iter__(self):
        next = self.next
        try:
            while True:
                yield next()
        except Empty:
            return

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

    def next(self):
        item = self.next_raw()
        if item is None:
            raise Empty()
        final, throw, args = item
        if throw:
            type, exc, tb = args
            raise type, exc, tb
        if final:
            raise Finished(*args)
        return peel_args(args)

    def result(self):
        with self.lock:
            if self._result is None:
                raise NotFinished()

            throw, args = self._result
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
        self.queue_lock = threading.Lock()
        self.queue = collections.deque()

    def send(self, *values):
        self._push(False, False, values)

    def throw(self, exc, tb=None):
        self._push(True, True, (type(exc), exc, tb))

    def finish(self, *args):
        self._push(True, False, args)

    def _push(self, final, throw, args):
        with self.queue_lock:
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
        with self.queue_lock:
            if self.queue and self.queue[-1][0]:
                return True
            return False

    def _next_raw(self):
        with self.queue_lock:
            if not self.queue:
                return None

            final, throw, args = self.queue.popleft()
            if final:
                self.queue.append((final, throw, args))
            return final, throw, args

class _Pipeable(Reg):
    def __init__(self):
        Reg.__init__(self)

        self.pipe_lock = threading.Lock()
        self.pipes = dict()
        self.pipes_pending = collections.deque()
        self.final = None

    def _pipe_callback(self, other):
        with self.pipe_lock:
            if other not in self.pipes:
                return
            self.pipes[other] = None

            self.pipes_pending.append(other)
            if len(self.pipes_pending) > 1:
                return
        self.signal_activity()

    def _finish(self, throw, args):
        with self.pipe_lock:
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
        with self.pipe_lock:
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
            with self.pipe_lock:
                if self.final:
                    return self.final
                if not self.pipes_pending:
                    return None
                other = self.pipes_pending.popleft()

            item = other.next_raw()
            if item is None:
                with self.pipe_lock:
                    _id = object()
                    self.pipes[other] = _id
                callback = other.add_message_callback(self._pipe_callback)
                with self.pipe_lock:
                    if self.pipes.get(other, None) is _id:
                        self.pipes[other] = callback
                        continue
                other.discard_message_callback(callback)
            else:
                final, throw, args = item
                if final:
                    with self.pipe_lock:
                        callback = self.pipes.pop(other, None)
                    other.discard_message_callback(callback)
                    if not throw:
                        throw = True
                        args = Finished, Finished(*args), None
                else:
                    with self.pipe_lock:
                        self.pipes_pending.append(other)
                return False, throw, args

    def next_is_final(self):
        with self.pipe_lock:
            return self.final is not None

class _Stackable(Reg):
    def __init__(self):
        Reg.__init__(self)

        self.stack_lock = threading.Lock()
        self.stack = collections.deque()
        self.final = None

    def _stack_callback(self, other):
        with self.stack_lock:
            if self.final is not None:
                return
            if not self.stack:
                return
            if other is not self.stack[0]:
                return
        self.signal_activity()

    def _stack(self, other):
        with self.stack_lock:
            if self.final is not None:
                return
            self.stack.append(other)
        self.next_is_final()
        self.signal_activity()
            
    def _finish(self, throw, args):
        with self.stack_lock:
            if self.final is not None:
                return
            self.final = True, throw, args
        self.next_is_final()
        self.signal_activity((throw, args))
        
    def _next_raw(self):
        while True:
            with self.stack_lock:
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

            with self.stack_lock:
                if other is self.stack[0]:
                    self.stack.popleft()

    def next_is_final(self):
        while True:
            with self.stack_lock:
                if not self.stack:
                    return self.final is not None
                other = self.stack[0]

            if not other.next_is_final():
                return False

            with self.stack_lock:
                if other is self.stack[0]:
                    self.stack.popleft()

class Inner(_Pipeable):
    def __init__(self, outer):
        _Pipeable.__init__(self)
        self.outer_ref = weakref.ref(outer)

    def send(self, *values):
        outer = self.outer_ref()
        if outer is not None:
            outer.inner_send(*values)

    def finish(self, *values):
        raise Finished(*values)

    def _finish(self, throw, args):
        _Pipeable._finish(self, throw, args)

        outer = self.outer_ref()
        if outer is not None:
            outer.inner_finish(throw, args)

    def thread(self, func, *args, **keys):
        import threadpool
        return threadpool.run(func, *args, **keys)

    def sub(self, other):
        def _callback(channel, _):
            try:
                result = other.result()
            except:
                channel.rethrow()
            else:
                channel.finish(result)

        channel = Channel()
        other.pipe(self)
        other.add_finish_callback(_callback, channel)

        outer = self.outer_ref()
        if outer is not None:        
            outer.inner_sub(other)
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
    @classmethod
    def step(cls, gen, inner, callbacks, fast, source):
        if source not in callbacks:
            return
        del callbacks[source]

        if not source:
            callback = source.add_message_callback(callqueue.add, cls.step, gen, inner, callbacks, fast)
            callbacks[source] = callback
            return
        elif not fast:
            item = source.next_raw()

            if item is None:
                callback = source.add_message_callback(callqueue.add, cls.step, gen, inner, callbacks, fast)
                callbacks[source] = callback
                return

            final, throw, args = item
            # FIXME: should this be done?
            # if final and not throw:
            #     throw = True
            #     args = Finished, Finished(*args), None
            cls._local.source = source

        try:
            if fast:
                next = gen.next()
            else:
                if throw:
                    next = gen.throw(*args)
                else:
                    next = gen.send(peel_args(args))
        except (StopIteration, Finished), exc:
            inner._finish(False, exc.args)
            for source, callback in callbacks.items():
                source.discard_message_callback(callback)
            callbacks.clear()
        except:
            inner._finish(True, sys.exc_info())
            for source, callback in callbacks.items():
                source.discard_message_callback(callback)
            callbacks.clear()
        else:
            if next is None:
                next = [null_source]
            elif isinstance(next, Reg):
                next = [next]
            else:
                next = list(set(next))
                random.shuffle(next)

            old_callbacks = set(callbacks)
            for other in next:
                if other in callbacks:
                    old_callbacks.discard(other)
                else:
                    callqueue.add(cls.step, gen, inner, callbacks, fast, other)
                    callbacks[other] = None
            for other in old_callbacks:
                callback = callbacks.pop(other, None)
                other.discard_message_callback(callback)

    def __init__(self, fast=False):
        _Stackable.__init__(self)

        self.inner = Inner(self)
        self.input = Channel()
        self.output = Channel()

        self.inner._pipe(self.input)
        self._stack(self.output)

        self._started = False
        self._fast = fast
        
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
        with self.stack_lock:
            old_output = self.output
            self.output = Channel()
        old_output.finish()
        self._stack(other)
        self._stack(self.output)

    def start(self):
        with self.lock:
            if self._started:
                return
            self._started = True

        gen = self.run()
        callbacks = dict()
        callbacks[null_source] = None
        callqueue.add(self.step, gen, self.inner, callbacks, self._fast, null_source)

    def run(self):
        while True:
            yield self.inner
            list(self.inner)

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
    def _stream(*args, **keys):
        return FuncStream(False, func, *args, **keys)
    return _stream

def stream_fast(func):
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

    def _left_finish_callback(self, _):
        with self.lock:
            self.left_has_result = True
            if not self.right_has_result:
                return
        try:
            self.signal_activity((False, self.right.result()))
        except:
            self.signal_activity((True, sys.exc_info()))

    def _right_finish_callback(self, _):
        self.left._pipe_broken()
        with self.lock:
            self.right_has_result = True
            if not self.left_has_result:
                return
        try:
            self.signal_activity((False, self.right.result()))
        except:
            self.signal_activity((True, sys.exc_info()))

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
def throws(inner):
    while True:
        yield inner
        list(inner)

def run(main, redirect_signals=False):
    import signal

    def _signal(*args, **keys):
        main.throw(KeyboardInterrupt())
    sigint = signal.getsignal(signal.SIGINT)
    sigterm = signal.getsignal(signal.SIGTERM)

    if redirect_signals:
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
        return main.result()
    finally:
        if redirect_signals:
            signal.signal(signal.SIGINT, sigint)
            signal.signal(signal.SIGTERM, sigterm)
