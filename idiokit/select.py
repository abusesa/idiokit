from __future__ import absolute_import

from . import idiokit, _selectloop


@idiokit.stream
def select(read, write, error, timeout=None):
    event = idiokit.Event()
    node = _selectloop.select(read, write, timeout, event.succeed)
    try:
        rfds, wfds = yield event
    except:
        _selectloop.cancel(node)
        raise
    idiokit.stop(rfds, wfds, ())
