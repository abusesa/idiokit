from __future__ import absolute_import

import os
import errno
import select as _select

from . import idiokit, threadpool, values


class _ValueStream(idiokit.Stream):
    _head = values.Value(None)

    def __init__(self, value):
        idiokit.Stream.__init__(self)

        self._value = value

    def pipe_left(self, *args, **keys):
        pass
    pipe_right = pipe_left

    def head(self):
        return self._head

    def result(self):
        return self._value


class Select(object):
    def __init__(self):
        self._pipes = list()

    def _do_select(self, *args, **keys):
        while True:
            try:
                return _select.select(*args, **keys)
            except _select.error as se:
                if se.args[0] == errno.EINTR:
                    continue
                raise se

    @idiokit.stream
    def select(self, read, write, error, timeout=None):
        if not self._pipes:
            self._pipes.append(os.pipe())
        rfd, wfd = self._pipes.pop()

        read = (rfd,) + tuple(read)
        value = threadpool.run(self._do_select, read, write, error, timeout)

        event = idiokit.Event()
        value.listen(event.set)

        try:
            result = yield event
        finally:
            if not value.unsafe_is_set():
                os.write(wfd, "\x00")
                try:
                    yield _ValueStream(value)
                finally:
                    os.read(rfd, 1)
            self._pipes.append((rfd, wfd))

        idiokit.stop(result)


select = Select().select
