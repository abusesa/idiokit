from __future__ import absolute_import

from functools import partial
from select import select as _native_select

from . import idiokit
from ._selectloop import cancel as selectloop_cancel, select as selectloop_select


def _handle(has_error, rfds, wfds, xfds, event):
    if has_error:
        try:
            rfds, wfds, xfds = _native_select(rfds, wfds, xfds, 0.0)
        except:
            event.fail()
            return
    event.succeed((rfds, wfds, xfds))


def _cancel(node, _, __):
    selectloop_cancel(node)


def select(read, write, error, timeout=None):
    event = idiokit.Event()
    node = selectloop_select(read, write, error, timeout, _handle, event)
    event.result().listen(partial(_cancel, node))
    return event
