import threading
import functools
import contextlib

class CallQueue(object):
    def __init__(self):
        self.exclusive_lock = threading.Lock()

        queue_lock = threading.Lock()
        self.queue_acquire = queue_lock.acquire
        self.queue_release = queue_lock.release
        
        self.queue = None
        self.callback = None        

    def iterate(self):
        self.queue_acquire()

        queue = self.queue
        self.queue = None

        self.queue_release()

        while queue is not None:
            func, args, keys, queue = queue
            func(*args, **keys)
        
    def add(self, func, *args, **keys):
        self.queue_acquire()

        queue = self.queue
        self.queue = (func, args, keys, queue)

        if queue is not None:
            self.queue_release()
            return

        callback = self.callback
        self.queue_release()

        if callback is not None:
            callback()

    @contextlib.contextmanager
    def exclusive(self, callback):
        self.exclusive_lock.acquire()
        try:
            self.queue_acquire()
            old_callback = self.callback
            self.callback = callback
            queue = self.queue
            self.queue_release()

            if queue is not None:
                callback()

            try:
                yield
            finally:
                self.queue_acquire()
                self.callback = old_callback
                queue = self.queue
                self.queue_release()

                if old_callback is not None and queue is not None:
                    old_callback()
        finally:
            self.exclusive_lock.release()

    def queued(self, func):
        add = self.add

        @functools.wraps(func)
        def _queued(*args, **keys):
            add(func, *args, **keys)

        return _queued

global_queue = CallQueue()

exclusive = global_queue.exclusive
iterate = global_queue.iterate
queued = global_queue.queued
add = global_queue.add
