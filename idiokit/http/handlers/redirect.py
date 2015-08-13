from __future__ import absolute_import

import httplib
import urlparse

from ... import idiokit
from . import utils


def redirect(where):
    @idiokit.stream
    def _redirect(addr, request, response):
        yield response.write_status(httplib.FOUND)
        yield response.write_headers({
            "location": utils.normpath(urlparse.urlparse(request.uri).path, root_path=where)
        })
        yield response.finish()
    return _redirect
