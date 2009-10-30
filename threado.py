from __future__ import with_statement
import collections
import threading
import sys
import callqueue
import weakref
import contextlib
import time
import random

class Timeout(Exception):
    pass

class Finished(BaseException):
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

def peel_args(args):
    if not args:
        return None
    if len(args) == 1:
        return args[0]
    return args

class Reg(object):
    _local = threading.local()

    _with_callbacks = set()
    _with_callbacks_lock = threading.Lock()

    def _update_callbacks(self):
        with self._with_callbacks_lock:
            if self.callbacks:
                self._with_callbacks.add(self)
            else:
                self._with_callbacks.discard(self)

    @contextlib.contextmanager
    def as_source(self):
        previous = getattr(self._local, "source", None)
        self._local.source = self
        try:
            yield
        finally:
            self._local.source = previous

    @property
    def was_source(self):
        return getattr(self._local, "source", None) is self

    def __init__(self):
        self.lock = threading.Lock()
        self.callbacks = collections.deque()
        self.pending_activity = False

    def send(self, *values):
        return

    def throw(self, exc, tb=None):
        return

    def rethrow(self):
        _, exception, traceback = sys.exc_info()
        self.throw(exception, traceback)

    def peek(self):
        return None

    def consume(self):
        return None

    def signal_activity(self):
        with self.lock:
            if self.pending_activity:
                return
            self.pending_activity = True
        callqueue.add(self._loop)

    def _loop(self):
        with self.lock:
            self.pending_activity = False
            callbacks = list(self.callbacks)

        for current in callbacks:
            if not self.peek():
                break
            with self.lock:
                if not self.callbacks or current not in self.callbacks:
                    continue
                self.callbacks.popleft()
            current(self)
        self._update_callbacks()

    def register(self, func, *args, **keys):
        callback = Callback(func, *args, **keys)
        with self.lock:
            self.callbacks.append(callback)
        self.signal_activity()
        self._update_callbacks()
        return callback

    def unregister(self, callback):
        try:
            with self.lock:
                self.callbacks.remove(callback)
        except ValueError:
            pass
        finally:
            self._update_callbacks()

    def _next_callback(self, condition, result, source):
        with condition:
            if result:
                return
            result.append(source.consume())
            condition.notify()

    def next(self, timeout=None):
        item = self.consume()
        if item is None:
            result = list()
            condition = threading.Condition()
            
            if timeout is None:
                timeout = float("infinity")
            expire_time = time.time() + timeout

            callback = self.register(self._next_callback, condition, result)
            try:
                with condition:
                    while not result:
                        condition.wait(timeout)
                        if result:
                            break
                        if time.time() >= expire_time:
                            result.append(None)
            finally:
                self.unregister(callback)

            if result[0] is None:
                raise Timeout()
            item = result[0]

        origin, final, success, args = item
        self._local.source = origin
        if success:
            return peel_args(args)
        exc, tb = args
        raise type(exc), exc, tb

    def __iter__(self):
        while True:
            try:
                yield self.next()
            except Finished:
                return
    
    def __add__(self, other):
        return Par(self, other)

    def __or__(self, other):
        return pair(self, other)

class Buffered(Reg):
    def __init__(self):
        Reg.__init__(self)
        self.queue_lock = threading.Lock()
        self.queue = collections.deque()

    def push(self, final, success, *args):
        with self.queue_lock:
            if self.queue and self.queue[-1][0]:
                return
            self.queue.append((final, success, args))
        self.signal_activity()

    def peek(self):
        with self.queue_lock:
            if not self.queue:
                return None
            final, success, args = self.queue[0]
            return self, final, success, args

    def consume(self):
        with self.queue_lock:
            if not self.queue:
                return None
            final, success, args = self.queue.popleft()
            if final:
                self.queue.append((final, success, args))
        return self, final, success, args

class Channel(Buffered):
    def send(self, *values):
        self.push(False, True, *values)

    def throw(self, exception, traceback=None):
        self.push(False, False, exception, traceback)

    def finish(self, exc=Finished(), tb=None):
        self.push(True, False, exc, tb)

class AllFinished(Finished):
    pass

class Par(Reg):
    _ref_sources = dict()

    @classmethod
    def _cleanup(cls, ref):
        sources = cls._ref_sources.pop(ref, dict())
        for source, callback in sources.iteritems():
            source.unregister(callback)

    @classmethod
    def _callback(cls, ref, source):
        aggregate = ref()
        if aggregate is not None:
            aggregate._append_pending(source)

    def __init__(self, *aggregated):
        Reg.__init__(self)

        self.pending_sources = collections.deque()
        self.sources = dict()

        self.ref = weakref.ref(self, self._cleanup)
        self._ref_sources[self.ref] = self.sources

        aggregated = list(set(aggregated))
        random.shuffle(aggregated)
        for source in aggregated:
            self._reregister(source)
            
    def _reregister(self, source):
        self.sources[source] = source.register(self._callback, self.ref)

    def _append_pending(self, source):
        with self.lock:
            self.sources[source] = None
            self.pending_sources.append(source)
        self.signal_activity()

    def _peek_or_consume(self, peek=False):
        with self.lock:
            while self.pending_sources:
                source = self.pending_sources.popleft()

                if peek:
                    event = source.peek()
                else:
                    event = source.consume()

                if event is None:
                    self._reregister(source)
                    continue

                origin, final, success, args = event
                if peek:
                    self.pending_sources.appendleft(source)
                elif not final:
                    self._reregister(source)
                else:
                    self.sources.pop(source, None)
                return origin, False, success, args

            if not self.sources:
                return self, True, False, (AllFinished(), None)
            return None

    def peek(self):
        return self._peek_or_consume(peek=True)

    def consume(self):
        return self._peek_or_consume(peek=False)

    def send(self, *values):
        for source in self.sources:
            source.send(*values)

    def throw(self, exc, tb=None):
        for source in self.sources:
            source.throw(exc, tb)

    def finish(self, exc=Finished(), tb=None):
        for source in self.sources:
            source.finish(exc, tb)

class Inner(Buffered):
    def __init__(self, outer):
        Buffered.__init__(self)
        self.outer_ref = weakref.ref(outer)

    def _outer(self):        
        outer = self.outer_ref()
        if outer is not None:
            yield outer

    def send(self, *values):
        for outer in self._outer():
            outer.push(False, True, *values)
            
    def throw(self, exc, tb=None):
        for outer in self._outer():
            outer.push(False, False, exc, tb)

    def _finish(self, exc=Finished(), tb=None):
        for outer in self._outer():
            outer.push(True, False, exc, None)

class Outer(Buffered):
    def __init__(self):
        Buffered.__init__(self)
        self.inner = Inner(self)

    def send(self, *values):
        self.inner.push(False, True, *values)

    def throw(self, exc, tb=None):
        self.inner.push(False, False, exc, tb)

    def finish(self, exc=Finished(), tb=None):
        self.inner.push(True, False, exc, tb)

null_source = Buffered()
null_source.push(True, True)

class GeneratorStream(Outer):
    @classmethod
    def step(cls, gen, inner, callbacks, source):
        item = source.consume()
        if item is None:
            callback = source.register(cls.step, gen, inner, callbacks)
            callbacks[source] = callback
            return

        for other, callback in callbacks.items():
            other.unregister(callback)

        origin, final, success, args = item
        with origin.as_source():
            try:
                if success:
                    next = gen.send(peel_args(args))
                else:
                    exc, tb = args
                    next = gen.throw(type(exc), exc, tb)
            except (StopIteration, Finished):
                inner._finish()
            except:
                _, exc, tb = sys.exc_info()
                inner.throw(exc, tb)
                inner._finish()
            else:
                if next is None:
                    next = [null_source]
                elif isinstance(next, Reg):
                    next = [next]

                callbacks = dict()
                for other in set(next):
                    callback = other.register(cls.step, gen, inner, callbacks)
                    callbacks[other] = callback

    def __init__(self):
        Outer.__init__(self)
        self._started = False

    def start(self):
        with self.lock:
            if self._started:
                return
            self._started = True

        gen = self.run()
        self.step(gen, self.inner, dict(), null_source)

    def run(self):
        yield

class FuncStream(GeneratorStream):
    def __init__(self, func, *args, **keys):
        GeneratorStream.__init__(self)
        self.func = func
        self.args = args
        self.keys = keys
        self.start()

    def run(self):
        args = (self.inner,) + self.args
        return self.func(*args, **self.keys)

def stream(func):
    def _stream(*args, **keys):
        return FuncStream(func, *args, **keys)
    return _stream

class ThreadedStream(Outer):
    def __init__(self):
        Outer.__init__(self)
        self.thread = None

    def start(self):
        with self.lock:
            if self.thread is not None:
                return
            self.thread = threading.Thread(target=self._main)
            self.thread.setDaemon(True)
            self.thread.start()

    def _main(self):
        try:
            self.run()
        except Finished:
            pass
        except:
            _, exc, tb = sys.exc_info()
            self.inner.throw(exc, tb)
        finally:
            self.inner._finish()

    def run(self):
        return

class FuncThread(ThreadedStream):
    def __init__(self, func, *args, **keys):
        ThreadedStream.__init__(self)
        
        self.func = func
        self.args = args
        self.keys = keys
        self.start()
        
    def run(self):
        args = (self.inner,) + self.args
        self.func(*args, **self.keys)

def thread(func):
    def _thread(*args, **keys):
        return FuncThread(func, *args, **keys)
    return _thread

class PipeBroken(BaseException):
    pass

@stream
def pair(inner, left, right):
    finals = dict()
    channel = Channel()

    def _callback(destination, source):
        while True:
            event = source.consume()
            if event is None:
                source.register(_callback, destination)
                break
            
            origin, final, success, args = event
            if not (final and source is right):
                if final:
                    destination.finish(*args)
                elif success:
                    destination.send(*args)
                else:
                    destination.throw(*args)
            else:
                left.throw(PipeBroken())

            if final:
                finals[source] = success, args
                if left in finals and right in finals:
                    channel.send(finals[right])
                break
            
    inner.register(_callback, left)
    left.register(_callback, right)
    right.register(_callback, inner)

    success, args = yield channel
    if success:
        return
    exc, tb = args
    raise type(exc), exc, tb

def pipe(first, *rest):
    if not rest:
        return first
    return pair(pipe(first, *rest[:-1]), rest[-1])

class Throws(Outer):
    def __init__(self):
        Outer.__init__(self)
        self.inner.register(self._callback)

    def _callback(self, source):
        while True:
            event = source.consume()
            if event is None:
                self.inner.register(self._callback)
                return

            origin, final, success, args = event
            if final:
                self.inner._finish(*args)
                return

            if success:
                pass
            else:
                self.inner.throw(*args)

def throws():
    return Throws()
