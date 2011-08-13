import threading
import functools
import contextlib

class CallNode(object):
    __slots__ = "func", "args", "keys", "next"

    def __init__(self, func, args, keys):
        self.func = func
        self.args = args
        self.keys = keys

        self.next = None

class CallQueue(object):
    def __init__(self):
        self.exclusive_lock = threading.Lock()

        queue_lock = threading.Lock()
        self.queue_acquire = queue_lock.acquire
        self.queue_release = queue_lock.release

        self.head = None
        self.tail = None
        self.callback = None

    def iterate(self):
        self.queue_acquire()

        head = self.head
        self.head = None
        self.tail = None

        self.queue_release()

        while head is not None:
            head.func(*head.args, **head.keys)
            head = head.next
        
    def add(self, func, *args, **keys):
        new_tail = CallNode(func, args, keys)

        self.queue_acquire()

        old_tail = self.tail
        self.tail = new_tail

        if old_tail is not None:
            old_tail.next = new_tail
            self.queue_release()
            return

        self.head = new_tail
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
            tail = self.tail
            self.queue_release()

            if tail is not None:
                callback()

            try:
                yield self.iterate
            finally:
                self.queue_acquire()
                self.callback = old_callback
                tail = self.tail
                self.queue_release()

                if old_callback is not None and tail is not None:
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
