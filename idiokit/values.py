from __future__ import absolute_import

from ._selectloop import asap


_UNDEFINED = object()


def _call(self, listeners, value):
    for callback in listeners:
        callback(self, value)


class Value(object):
    __slots__ = "_value", "_listeners"

    def __init__(self, value=_UNDEFINED):
        self._value = value
        self._listeners = None

    def unsafe_is_set(self):
        return self._value is not _UNDEFINED

    def unsafe_get(self):
        value = self._value
        if value is _UNDEFINED:
            raise ValueError("value has not been set")
        return value

    def unsafe_set(self, value=None):
        if self._value is not _UNDEFINED:
            return False
        self._value = value

        listeners = self._listeners
        if listeners is None:
            return True
        self._listeners = None

        asap(_call, self, listeners, value)
        return True

    def unsafe_listen(self, callback):
        if self._value is _UNDEFINED:
            listeners = self._listeners
            if listeners is None:
                listeners = set()
                self._listeners = listeners
            listeners.add(callback)
            return

        asap(callback, self, self._value)

    def unsafe_unlisten(self, callback):
        listeners = self._listeners
        if listeners is not None:
            listeners.discard(callback)
            if not listeners:
                self._listeners = None

    def set(self, value=None):
        asap(self.unsafe_set, value)

    def listen(self, callback):
        asap(self.unsafe_listen, callback)

    def unlisten(self, callback):
        asap(self.unsafe_unlisten, callback)
