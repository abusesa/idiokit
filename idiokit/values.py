from __future__ import with_statement

import threading

_UNDEFINED = object()

class Value(object):
    _lock = threading.Lock()

    def __init__(self, value=_UNDEFINED):
        self._value = value
        self._listeners = None

    def is_set(self):
        with self._lock:
            return self._value is not _UNDEFINED

    def get(self):
        with self._lock:
            value = self._value
        return None if value is _UNDEFINED else value

    def set(self, value=None):
        with self._lock:
            if self._value is not _UNDEFINED:
                return False
            self._value = value

            listeners = self._listeners
            if listeners is None:
                return True
            self._listeners = None

        for callback in listeners:
            callback(value)
        return True

    def listen(self, callback):
        with self._lock:
            if self._value is _UNDEFINED:
                listeners = self._listeners
                if listeners is None:
                    listeners = set()
                    self._listeners = listeners
                listeners.add(callback)
                return

        callback(self._value)

    def unlisten(self, callback):
        with self._lock:
            listeners = self._listeners
            if listeners is not None:
                listeners.discard(callback)
