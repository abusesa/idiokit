from __future__ import absolute_import

from functools import partial

from . import idiokit
from ._selectloop import cancel as selectloop_cancel, sleep as selectloop_sleep


def _cancel(node, _, __):
    selectloop_cancel(node)


def sleep(delay):
    event = idiokit.Event()
    node = selectloop_sleep(delay, event.succeed)
    event.result().listen(partial(_cancel, node))
    return event


class Timeout(Exception):
    pass


def timeout(timeout, stream=None, throw=Timeout()):
    if stream is None:
        stream = idiokit.Event()
    node = selectloop_sleep(timeout, stream.throw, throw)
    stream.result().listen(partial(_cancel, node))
    return stream
