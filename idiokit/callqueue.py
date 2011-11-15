import threading
import contextlib

class CallQueue(object):
    class CallNode(object):
        __slots__ = "func", "args", "keys", "next"

        def __init__(self, func, args, keys):
            self.func = func
            self.args = args
            self.keys = keys

            self.next = None

    _node_cache = None

    def __init__(self):
        self.exclusive_lock = threading.Lock()

        queue_lock = threading.Lock()
        self.queue_acquire = queue_lock.acquire
        self.queue_release = queue_lock.release

        self.local = threading.local()
        self.head = None
        self.tail = None
        self.callback = None

    def iterate(self):
        self.queue_acquire()

        head = self.head
        tail = self.tail
        self.head = None
        self.tail = None

        self.queue_release()

        if head is None:
            return

        try:
            self.local.current = True

            while head is not None:
                head.func(*head.args, **head.keys)

                head.func = None
                head.args = None
                head.keys = None

                head = head.next
        finally:
            self.local.current = False

        self.queue_acquire()

        tail.next = self._node_cache
        self._node_cache = head

        self.queue_release()

    def add(self, func, *args, **keys):
        self.queue_acquire()

        new_tail = self._node_cache
        if new_tail is None:
            new_tail = self.CallNode(func, args, keys)
        else:
            self._node_cache = new_tail.next

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

    def asap(self, func, *args, **keys):
        try:
            current = self.local.current
        except AttributeError:
            current = False
            self.local.current = False

        if current:
            func(*args, **keys)
        else:
            self.add(func, *args, **keys)

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

global_queue = CallQueue()

exclusive = global_queue.exclusive
iterate = global_queue.iterate
add = global_queue.add
asap = global_queue.asap
