from __future__ import with_statement
import collections
import threading
import time
import sys
import callqueue
import weakref
import contextlib
import util

def in_main_thread():
    MainThread = getattr(threading, "_MainThread", threading.Thread)
    return isinstance(threading.currentThread(), MainThread)

class Timeout(Exception):
    pass

class Finished(BaseException):
    pass

class Event(object):
    @property
    def value(self):
        if self.success:
            if not self.args:
                return None
            elif len(self.args) == 1:
                return self.args[0]
            return self.args

        exc, tb = self.args
        raise type(exc), exc, tb

    def __init__(self, source, final, success, *args):
        self.source = source
        self.success = success
        self.final = final
        self.args = args

    def reparented(self, source):
        return Event(source, self.final, self.success, *self.args)

class Reg(object):
    _local = threading.local()

    _with_callbacks = set()
    _with_callbacks_lock = threading.Lock()

    @classmethod
    def _update_callbacks(cls, source):
        with cls._with_callbacks_lock:
            if source.callbacks:
                cls._with_callbacks.add(source)
            else:
                cls._with_callbacks.discard(source)

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
        self.callbacks = collections.deque()
        self.pending_activity = False

    def peek(self):
        return None

    def consume(self):
        return None

    @util.synchronized
    def signal_activity(self):
        if self.pending_activity:
            return
        self.pending_activity = True
        callqueue.add(self._loop)

    @util.synchronized
    def _loop(self):
        self.pending_activity = False

        for callback in list(self.callbacks):
            if not self.peek():
                break
            if callback not in self.callbacks:
                continue
            callback = self.callbacks.popleft()
            callback(self)
        self._update_callbacks(self)

    @util.synchronized
    def register(self, func, *args, **keys):
        callback = callqueue.Callback(func, *args, **keys)

        self.callbacks.append(callback)
        self.signal_activity()
        self._update_callbacks(self)
        return callback

    @util.synchronized
    def unregister(self, callback):
        try:
            self.callbacks.remove(callback)
        except ValueError:
            pass
        finally:
            self._update_callbacks(self)

    def next(self, timeout=None):
        condition = threading.Condition()
        result = list()

        def _callback(source):
            with condition:
                if result:
                    return
                result.append(source.consume())
                condition.notify()

        if timeout is None:
            timeout = float("infinity")

        callback = self.register(_callback)
        try:
            with condition:
                if not result:
                    condition.wait(timeout)
                    result.append(None)
        finally:
            self.unregister(callback)

        if result[0] is None:
            raise Timeout()

        event = result[0]
        self._local.source = event.source
        return event.value 

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
        self.queue = collections.deque()
        self.callbacks = collections.deque()

    @util.synchronized
    def push(self, final, success, *values):
        if self.queue and self.queue[-1].final:
            return
        self.queue.append(Event(self, final, success, *values))
        self.signal_activity()

    @util.synchronized
    def peek(self):
        if not self.queue:
            return None
        return self.queue[0]

    @util.synchronized
    def consume(self):
        if not self.queue:
            return None

        event = self.queue.popleft()
        if event.final:
            self.queue.append(event)
        return event

class Channel(Buffered):
    def send(self, *values):
        self.push(False, True, *values)

    def throw(self, exception, traceback=None):
        self.push(False, False, exception, traceback)

    def rethrow(self):
        _, exception, traceback = sys.exc_info()
        self.throw(exception, traceback)

    def finish(self, exc=Finished(), tb=None):
        self.push(True, False, exc, tb)

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

        for source in set(aggregated):
            self._reregister(source)
            
    def _reregister(self, source):
        self.sources[source] = source.register(self._callback, self.ref)

    @util.synchronized
    def _append_pending(self, source):
        self.sources[source] = None
        self.pending_sources.append(source)
        self.signal_activity()

    @util.synchronized
    def _peek_or_consume(self, peek=False):
        while self.pending_sources:
            source = self.pending_sources.popleft()

            if peek:
                event = source.peek()
            else:
                event = source.consume()

            if event.final:
                self.sources.pop(source, None)
                continue

            if event is None:
                self._reregister(source)
                continue

            if peek:
                self.pending_sources.appendleft(source)
            else:
                self._reregister(source)
            return event

        if not self.sources:
            return Event(self, True, False, Finished(), None)
        return None

    @util.synchronized
    def peek(self):
        return self._peek_or_consume(peek=True)

    @util.synchronized
    def consume(self):
        return self._peek_or_consume(peek=False)

    def send(self, *values):
        for source in self.sources:
            source.send(*values)

    def throw(self, exc, tb=None):
        for source in self.sources:
            source.throw(exc, tb)

    def rethrow(self, *values):
        _, exc, tb = sys.exc_info()
        self.throw(exc, tb)

    def finish(self, exc=Finished(), tb=None):
        for source in self.sources:
            source.finished(exc, tb)

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

    def rethrow(self):
        _, exc, tb = sys.exc_info()
        self.throw(exc, tb)

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

    def rethrow(self):
        _, exc, tb = sys.exc_info()
        self.throw(exc, tb)

    def finish(self, exc=Finished(), tb=None):
        self.inner.push(True, False, exc, tb)

null_source = Buffered()
null_source.push(True, True)

class GeneratorStream(Outer):
    _refs = dict()

    @classmethod
    def step(cls, ref, source):
        if ref not in cls._refs:
            return
        gen, inner = cls._refs.get(ref, None)

        event = source.consume()
        with event.source.as_source():
            try:
                try:
                    value = event.value
                except:
                    next = gen.throw(*sys.exc_info())
                else:
                    next = gen.send(value)
            except (StopIteration, Finished):
                inner._finish()
            except:
                _, exc, tb = sys.exc_info()
                inner.throw(exc, tb)
                inner._finish()
                cls._refs.pop(ref, None)
            else:
                if next is None:
                    next = null_source
                elif not isinstance(next, Reg):
                    next = Par(*next)
                next.register(cls.step, ref)

    def __init__(self):
        Outer.__init__(self)

        gen = self.run()
        ref = weakref.ref(self)

        self._refs[ref] = gen, self.inner
        self.step(ref, null_source)

    def run(self):
        yield

class FuncStream(GeneratorStream):
    def __init__(self, func, *args, **keys):
        self.func = func
        self.args = args
        self.keys = keys
        GeneratorStream.__init__(self)

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

    @util.synchronized
    def start(self):
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
        args = self.inner + (self.args,)
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
        event = source.consume()

        if not (event.final and source is right):
            try:
                value = event.value
            except:
                destination.rethrow()
            else:
                destination.send(*event.args)
                
            if event.final:
                destination.finish(*event.args)
        else:
            left.throw(PipeBroken())

        if not event.final:
            source.register(_callback, destination)
        else:
            finals[source] = event
            if left in finals and right in finals:
                channel.send()
                
    inner.register(_callback, left)
    left.register(_callback, right)
    right.register(_callback, inner)

    yield channel
    
    finals[right].value

def pipe(first, *rest):
    if not rest:
        return first
    return pair(first, pipe(*rest))
