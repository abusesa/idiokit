from __future__ import with_statement
import threading
import contextlib

class CallQueue(object):
    def __init__(self):
        self.queue_lock = threading.Lock()
        self.exclusive_lock = threading.RLock()

        self.queue = list()
        self.callback = None

        self.thread = threading.Thread(target=self._run)
        self.thread.setDaemon(True)
        self.thread.start()

    def _run(self):
        event = threading.Event()
        while True:
            self.iterate(event.set)
            event.wait()
            event.clear()
        
    def add(self, func, *args, **keys):
        with self.queue_lock:
            self.queue.append((func, args, keys))
            if self.callback is not None:
                self.callback()
                self.callback = None

    @contextlib.contextmanager
    def exclusive(self):
        with self.exclusive_lock:
            yield

    def iterate(self, callback=None):
        with self.exclusive_lock:
            with self.queue_lock:
                queue = self.queue
                self.queue = list()
                self.callback = callback
                
            for func, args, keys in queue:
                func(*args, **keys)
global_queue = CallQueue()

iterate = global_queue.iterate
exclusive = global_queue.exclusive
add = global_queue.add
