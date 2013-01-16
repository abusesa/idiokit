from __future__ import absolute_import

from . import callqueue


class Value(object):
    __slots__ = "_value", "_listeners"

    _UNDEFINED = object()
    _ERROR = ValueError("value has not been set")

    def __init__(self, value=_UNDEFINED):
        self._value = value
        self._listeners = None

    def unsafe_is_set(self):
        return self._value is not self._UNDEFINED

    def unsafe_get(self):
        value = self._value
        if value is self._UNDEFINED:
            raise self._ERROR
        return value

    def unsafe_set(self, value=None):
        if self._value is not self._UNDEFINED:
            return False
        self._value = value

        listeners = self._listeners
        if listeners is None:
            return True
        self._listeners = None

        for callback in listeners:
            callqueue.asap(callback, value)
        return True

    def unsafe_listen(self, callback):
        if self._value is self._UNDEFINED:
            listeners = self._listeners
            if listeners is None:
                listeners = set()
                self._listeners = listeners
            listeners.add(callback)
            return

        callqueue.asap(callback, self._value)

    def unsafe_unlisten(self, callback):
        listeners = self._listeners
        if listeners is not None:
            listeners.discard(callback)

    def set(self, value=None):
        callqueue.asap(self.unsafe_set, value)

    def listen(self, callback):
        callqueue.asap(self.unsafe_listen, callback)

    def unlisten(self, callback):
        callqueue.asap(self.unsafe_unlisten, callback)
