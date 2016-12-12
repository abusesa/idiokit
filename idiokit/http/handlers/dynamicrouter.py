from __future__ import absolute_import

import httplib
import urlparse
import re

from ... import idiokit
from ..server import Server, ServerRequest, as_server
from . import utils

# TODO: add method based routing


class DynamicRouter(Server):
    class _InvalidPath(Exception):
        pass

    class _RouteNotFound(Exception):
        pass

    def __init__(self, *args, **keys):
        # TODO: add possibility to create static endpoints
        self._routes = []

    def route(self, *args):
        def wrap(func):
            route_str = args[0]
            methods = args[1:]

            @idiokit.stream
            def check_method(addr, request, response, **kwargs):
                allow = ", ".join(methods)
                if request.method not in methods:
                    yield response.write_status(httplib.METHOD_NOT_ALLOWED)
                    yield response.write_headers({"Allow": allow})
                    return
                yield func(addr, request, response, **kwargs)

            route_pattern = self._build_route_pattern(route_str)
            self._routes.append((route_pattern, as_server(check_method)))
            self._routes.sort(key=lambda (x, y): x.pattern.count("/"), reverse=True)

            return check_method
        return wrap

    @staticmethod
    def _build_route_pattern(route):
        route_regex = re.sub(r'(<\w+>)', r'(?P\1.+)', route)
        return re.compile("^{}$".format(route_regex))

    def _get_route_match(self, request):
        path = request.uri
        try:
            urlparse.urlparse(path)
            utils.normpath(path)
        except ValueError:
            raise self._InvalidPath()

        for route_pattern, view_function in self._routes:
            m = route_pattern.match(path)
            if m:
                return m.groupdict(), view_function, ServerRequest(
                    request.method,
                    # urlparse.urlunparse(new_uri_parts),
                    # "/",
                    # TODO: check that this matches the original router output
                    request.uri,
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

    # TODO: add: def request_continue(...

    @idiokit.stream
    def request(self, addr, request, response):
        try:
            route_match = self._get_route_match(request)
            if route_match:
                kwargs, handler, request = route_match
                for v in kwargs.values():
                    if "/" in v:
                        raise self._RouteNotFound()
        except self._InvalidPath:
            yield response.write_status(code=httplib.BAD_REQUEST)
        except self._RouteNotFound:
            yield response.write_status(code=httplib.NOT_FOUND)
        else:
            yield handler.request(addr, request, response, **kwargs)
