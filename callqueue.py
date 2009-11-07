import threading
import contextlib
from thread import allocate_lock

class CallQueue(object):
    def __init__(self):
        self.queue_lock = allocate_lock()
        self.exclusive_lock = allocate_lock()
        
        self.queue = list()
        self.callback = None

        self.thread = threading.Thread(target=self._run)
        self.thread.setDaemon(True)
        self.thread.start()

    def _run(self):
        lock = allocate_lock()
        acquire = lock.acquire
        release = lock.release
        iterate = self.iterate

        while True:
            acquire()
            iterate(release)
        
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
    def exclusive(self):
        self.exclusive_lock.acquire()
        try:
            yield
        finally:
            self.exclusive_lock.release()

    def iterate(self, callback=None):
        self.exclusive_lock.acquire()
        try:
            self.queue_lock.acquire()
            queue = self.queue
            self.queue = list()
            self.callback = callback
            self.queue_lock.release()
                
            for func, args, keys in queue:
                func(*args, **keys)
        finally:
            self.exclusive_lock.release()

global_queue = CallQueue()

iterate = global_queue.iterate
exclusive = global_queue.exclusive
add = global_queue.add
