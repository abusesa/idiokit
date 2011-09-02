from __future__ import with_statement

import threading

_UNDEFINED = object()

class ValueBase(object):
    _lock = threading.Lock()

    def __init__(self, value=_UNDEFINED):
        if value is _UNDEFINED:
            self._value = None
            self._listeners = set()
        else:
            self._value = value
            self._listeners = None

    def is_set(self):
        with self._lock:
            return self._listeners is None

    def get(self):
        with self._lock:
            return self._value

    def _set(self, value=None):
        with self._lock:
            listeners = self._listeners
            if listeners is None:
                return False

            self._value = value
            self._listeners = None
    
        for callback in listeners:
            callback(value)
        return True

    def listen(self, callback):
        with self._lock:
            listeners = self._listeners
            if listeners is not None:
                listeners.add(callback)
                return

        callback(self._value)

    def unlisten(self, callback):
        with self._lock:
            listeners = self._listeners
            if listeners is not None:
                listeners.discard(callback)

class Value(ValueBase):
    set = ValueBase._set

class Which(ValueBase):
    def __init__(self, left, right):
        ValueBase.__init__(self)

        self._left = left
        self._right = right

        listen_left = self._listen_left
        listen_right = self._listen_right

        left.listen(listen_left)
        right.listen(listen_right)

        if self.is_set():
            left.unlisten(listen_left)
            right.unlisten(listen_right)

    def _listen_left(self, value):
        if not self._set((self._left, value)):
            return
        self._right.unlisten(self._listen_right)

    def _listen_right(self, value):
        if not self._set((self._right, value)):
            return
        self._left.unlisten(self._listen_left)

class Flow(object):
    _lock = threading.Lock()

    def __init__(self, gen):
        self._gen = gen
        self._result = None

        self._step(None)

    def _step(self, value):
        with self._lock:
            gen = self._gen
            if gen is None:
                return
            self._result = None

        try:
            result = gen.send(value)
        except StopIteration:
            with self._lock:
                self._gen = None
        else:
            result.listen(self._step)

            with self._lock:
                if self._gen is not None:
                    if self._result is None:
                        self._result = result
                    return

            result.unlisten(self._step)
            gen.close()

    def close(self):
        with self._lock:
            gen = self._gen
            if gen is None:
                return
            self._gen = None

            result = self._result
            if result is None:
                return
            self._result = None

        if result is not None:
            result.unlisten(self._step)
        gen.close()
