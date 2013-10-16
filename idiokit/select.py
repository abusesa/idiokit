from . import idiokit, _selectloop


@idiokit.stream
def select(read, write, error, timeout=None):
    event = idiokit.Event()
    node = _selectloop.select(read, write, error, timeout, event.succeed)
    try:
        rfds, wfds, xfds = yield event
    except:
        _selectloop.cancel(node)
        raise
    idiokit.stop(rfds, wfds, xfds)
