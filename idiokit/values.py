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
