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


class Timeout(Exception):
    pass


@idiokit.stream
def timeout(timeout, stream=None, throw=Timeout()):
    if stream is None:
        stream = idiokit.Event()

    node = _selectloop.sleep(timeout, stream.throw, throw)
    try:
        result = yield stream
    finally:
        _selectloop.cancel(node)
    idiokit.stop(result)
