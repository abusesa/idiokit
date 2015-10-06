from __future__ import absolute_import

from functools import partial

from . import idiokit
from ._selectloop import cancel as selectloop_cancel, select as selectloop_select


def _cancel(node, _, __):
    selectloop_cancel(node)


def select(read, write, error, timeout=None):
    event = idiokit.Event()
    node = selectloop_select(read, write, error, timeout, event.succeed)
    event.result().listen(partial(_cancel, node))
    return event
