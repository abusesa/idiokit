from __future__ import with_statement
import threading
import contextlib
from thread import allocate_lock

class CallQueue(object):
    def __init__(self):
        self.lock = allocate_lock()
        
        self.queue = list()

        self.callback = lambda: None
        self.callback_called = True
        self.id = None
        
    def add(self, func, *args, **keys):
        self.lock.acquire()
        try:
            self.queue.append((func, args, keys))
            if not self.callback_called:
                self.callback()
                self.callback_called = True
        finally:
            self.lock.release()

    @contextlib.contextmanager
    def exclusive(self, callback):
        _id = object()
        lock = self.lock

        def iterate():
            with lock:
                if self.id != _id:
                    return
                queue = self.queue
                self.queue = list()
                self.callback_called = False

            for func, args, keys in queue:
                func(*args, **keys)

        with self.lock:
            previous_id = self.id
            previous_callback = self.callback

            self.id = _id
            self.callback = callback

        try:
            yield iterate
        finally:
            with self.lock:
                self.id = previous_id
                self.callback = previous_callback
                self.callback_called = True
                previous_callback()

global_queue = CallQueue()

exclusive = global_queue.exclusive
add = global_queue.add
