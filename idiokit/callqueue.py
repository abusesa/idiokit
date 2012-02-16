import threading
import contextlib
import collections

class CallQueue(object):
    create_deque = staticmethod(collections.deque)

    def __init__(self):
        self.exclusive_lock = threading.Lock()

        queue_lock = threading.Lock()
        self.queue_acquire = queue_lock.acquire
        self.queue_release = queue_lock.release

        self.local = threading.local()
        self.queue = self.create_deque()
        self.callback = None

    def iterate(self):
        self.queue_acquire()
        try:
            queue = self.queue
            self.queue = self.create_deque()
        finally:
            self.queue_release()

        try:
            self.local.current = queue
            while queue:
                func, args, keys = queue.popleft()
                func(*args, **keys)
        finally:
            self.local.current = None

    def add(self, func, *args, **keys):
        self.queue_acquire()
        try:
            empty = not self.queue
            self.queue.append((func, args, keys))
            if not empty:
                return

            callback = self.callback
        finally:
            self.queue_release()

        if callback is not None:
            callback()

    def asap(self, func, *args, **keys):
        try:
            current = self.local.current
        except AttributeError:
            current = None
            self.local.current = None

        if current is None:
            self.add(func, *args, **keys)
        else:
            current.append((func, args, keys))

    @contextlib.contextmanager
    def exclusive(self, callback):
        self.exclusive_lock.acquire()
        try:
            self.queue_acquire()
            try:
                old_callback = self.callback
                self.callback = callback
                empty = not self.queue
            finally:
                self.queue_release()

            if not empty:
                callback()

            try:
                yield
            finally:
                self.queue_acquire()
                try:
                    self.callback = old_callback
                    empty = not self.queue
                finally:
                    self.queue_release()

                if old_callback is not None and not empty:
                    old_callback()
        finally:
            self.exclusive_lock.release()

global_queue = CallQueue()

exclusive = global_queue.exclusive
iterate = global_queue.iterate
add = global_queue.add
asap = global_queue.asap
