from . import idiokit, _selectloop


@idiokit.stream
def sleep(delay):
    event = idiokit.Event()
    node = _selectloop.sleep(delay, event.succeed)
    try:
        yield event
    except:
        _selectloop.cancel(node)
        raise
