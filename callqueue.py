from __future__ import with_statement
import contextlib
from thread import allocate_lock

class CallQueue(object):
    def __init__(self):
        self.exclusive_lock = allocate_lock()
        self.queue_lock = allocate_lock()
        
        self.queue = list()
        self.callback = None
        
    def add(self, func, *args, **keys):
        self.queue_lock.acquire()
        try:
            self.queue.append((func, args, keys))
            if self.callback is not None:
                self.callback()
                self.callback = None
        finally:
            self.queue_lock.release()

    @contextlib.contextmanager
    def exclusive(self, callback):
        queue_lock = self.queue_lock
        acquire = queue_lock.acquire
        release = queue_lock.release

        def iterate():
            acquire()
            try:
                queue = self.queue
                self.queue = list()
                self.callback = callback
            finally:
                release()

            for func, args, keys in queue:
                func(*args, **keys)

        with self.exclusive_lock:
            with queue_lock:
                old_callback = self.callback
                self.callback = callback

            if callback is not None:
                callback()

            try:
                yield iterate
            finally:
                with queue_lock:
                    self.callback = old_callback

                if old_callback is not None:
                    old_callback()

global_queue = CallQueue()

exclusive = global_queue.exclusive
add = global_queue.add
