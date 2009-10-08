from __future__ import with_statement
import threading
import contextlib

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

class CallQueue(object):
    def __init__(self):
        self.queue_lock = threading.RLock()
        self.exclusive_lock = threading.RLock()

        self.queue = list()
        self.callback = None

        self.thread = threading.Thread(target=self._run)
        self.thread.setDaemon(True)
        self.thread.start()
        
    def add(self, func, *args, **keys):
        call = Callback(func, *args, **keys)
        with self.queue_lock:
            self.queue.append(call)
            if self.callback is not None:
                callback, self.callback = self.callback, None
                callback()
        return call

    def remove(self, call):
        with self.queue_lock:
            try:
                self.queue.remove(call)
            except ValueError:
                return False
        return True

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
                
            for call in queue:
                call()

    def _run(self):
        event = threading.Event()

        while True:
            self.iterate(event.set)
            event.wait()
            event.clear()
global_queue = CallQueue()

iterate = global_queue.iterate
exclusive = global_queue.exclusive
add = global_queue.add
remove = global_queue.remove
