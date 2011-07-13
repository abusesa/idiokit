from __future__ import with_statement, absolute_import

import os
import sys
import errno
import threading
import select as _select

from . import idiokit, threadpool, values

def select(*args, **keys):
    while True:
        try:
            return _select.select(*args, **keys)
        except _select.error, se:
            if se.args[0] == errno.EINTR:
                continue
            raise se

_pipes = list()

def _select_in_thread(value, read, write, error, timeout):
    try:
        result = select(read, write, error, timeout)
    except:
        value.set((True, sys.exc_info()))
    else:
        value.set((False, (result,)))

class _ValueStream(idiokit.Stream):
    _head = values.Value(None)

    def __init__(self, value):
        idiokit.Stream.__init__(self)

        self._result = values.Value()
        value.listen(self._set)

    def pipe_left(self, *args, **keys):
        pass
    pipe_right = pipe_left

    def message_head(self):
        return self._head

    def _set(self, _):
        self._result.set((False, ()))

    def result(self):
        return self._result

@idiokit.stream
def async_select(read, write, error, timeout=None):
    value = idiokit.Value()
    
    if not _pipes:
        _pipes.append(os.pipe())
    rfd, wfd = _pipes.pop()

    try:
        read = (rfd,) + tuple(read)
        threadpool.run(_select_in_thread, value, read, write, error, timeout)

        event = idiokit.Event()
        value.listen(event.set)
        
        try:
            result = yield event
        except:
            exc_info = sys.exc_info()

            os.write(wfd, "\x00")
            try:
                yield _ValueStream(value)
            finally:
                os.read(rfd, 1)

            exc_type, exc_value, exc_tb = exc_info
            raise exc_type, exc_value, exc_tb
        else:
            idiokit.stop(result)
    finally:
        _pipes.append((rfd, wfd))
