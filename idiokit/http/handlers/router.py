from __future__ import absolute_import

import urllib
import httplib
import urlparse

from ... import idiokit
from ..server import Server, ServerRequest, as_server
from . import utils


class Router(Server):
    class _InvalidPath(Exception):
        pass

    class _RouteNotFound(Exception):
        pass

    def __init__(self, *args, **keys):
        self._routes = []

        for route, handler in dict(*args, **keys).iteritems():
            path = self._split_path(utils.normpath(route, unquote=False))
            self._routes.append((path, as_server(handler)))

        self._routes.sort(key=lambda (x, y): len(x), reverse=True)

    def _split_path(self, path):
        pieces = []

        for index, piece in enumerate(path.split("/")):
            if index > 0:
                pieces.append("/")
            pieces.append(piece)

        if pieces and pieces[-1] == "":
            pieces.pop()

        return tuple(pieces)

    def _find(self, request):
        try:
            uri = urlparse.urlparse(request.uri)
        except ValueError:
            raise self._InvalidPath()

        uri_path = urllib.unquote(uri.path)

        try:
            uri_path = utils.normpath(uri_path)
        except ValueError:
            raise self._InvalidPath()

        uri_path = self._split_path(uri_path)
        for path, handler in self._routes:
            cut = len(path)
            if uri_path[:cut] == path:
                new_uri_parts = list(uri)
                new_uri_parts[2] = utils.normpath("".join(uri_path[cut:]))

                return handler, ServerRequest(
                    request.method,
                    urlparse.urlunparse(new_uri_parts),
                    request.http_version,
                    request.headers,
                    request
                )

        raise self._RouteNotFound()

    def main(self):
        if not self._routes:
            return idiokit.consume()
        handlers = set(handler for _, handler in self._routes)
        return idiokit.pipe(*[handler.main() for handler in handlers])

    @idiokit.stream
    def request_continue(self, addr, request, response):
        try:
            handler, request = self._find(request)
        except self._InvalidPath:
            yield response.write_status(code=httplib.BAD_REQUEST)
        except self._RouteNotFound:
            yield response.write_status(code=httplib.NOT_FOUND)
        else:
            yield handler.request_continue(addr, request, response)

    @idiokit.stream
    def request(self, addr, request, response):
        try:
            handler, request = self._find(request)
        except self._InvalidPath:
            yield response.write_status(code=httplib.BAD_REQUEST)
        except self._RouteNotFound:
            yield response.write_status(code=httplib.NOT_FOUND)
        else:
            yield handler.request(addr, request, response)
