from __future__ import absolute_import

import os
import re
import urllib
import urlparse

from .. import idiokit, socket, ssl
from ..dns import host_lookup
from .server import write_headers, read_headers, normalized_headers, get_header_single, get_header_list, get_content_length, _LimitedWriter, _ChunkedWriter, _Buffered, _Limited, _Chunked, ConnectionLost
from . import httpversion


class RequestError(Exception):
    pass


@idiokit.stream
def write_request_line(socket, method, uri, http_version):
    yield socket.sendall("{0} {1} {2}\r\n".format(method, uri, http_version))


@idiokit.stream
def read_status_line(buffered):
    line = yield buffered.read_line()
    if not line:
        raise ConnectionLost()

    match = re.match(r"^([^ ]+) (\d{3}) ([^\r\n]*)\r?\n$", line)
    if not match:
        raise RequestError("could not parse status line")

    http_version_string, code_string, reason = match.groups()
    try:
        http_version = httpversion.HTTPVersion.from_string(http_version_string)
    except ValueError:
        raise RequestError("invalid HTTP version")

    idiokit.stop(http_version, int(code_string), reason)


class ClientResponse(object):
    def __init__(self, http_version, status_code, status_reason, headers, buffered):
        self._http_version = http_version
        self._status_code = status_code
        self._status_reason = status_reason
        self._headers = headers
        self._reader = self._resolve_reader(http_version, headers, buffered)

    @property
    def http_version(self):
        return self._http_version

    @property
    def status_code(self):
        return self._status_code

    @property
    def status_reason(self):
        return self._status_reason

    @property
    def headers(self):
        return self._headers

    def _resolve_reader(self, http_version, headers, buffered):
        if http_version == httpversion.HTTP10:
            return self._resolve_reader_http10(headers, buffered)
        elif http_version == httpversion.HTTP11:
            return self._resolve_reader_http11(headers, buffered)
        raise RequestError("HTTP version {0} not supported".format(http_version))

    def _resolve_reader_http10(self, headers, buffered):
        content_length = get_content_length(headers, None)
        if content_length is None:
            return buffered
        return _Limited(buffered, content_length)

    def _resolve_reader_http11(self, headers, buffered):
        transfer_encoding = get_header_list(headers, "transfer-encoding", None)
        content_length = get_content_length(headers, None)

        if transfer_encoding is not None:
            transfer_encoding = transfer_encoding.lower()

        if transfer_encoding == "chunked":
            return _Chunked(buffered)
        if transfer_encoding in (None, "identity") and content_length is not None:
            return _Limited(buffered, content_length)
        if transfer_encoding in (None, "identity"):
            return buffered
        raise ValueError("either content-length or transfer-encoding: chunked must be used")

    def read(self, amount):
        return self._reader.read(amount)


class ClientRequest(object):
    def __init__(self, method, uri, headers, writer, buffered):
        self._uri = uri
        self._method = method
        self._headers = headers
        self._writer = writer
        self._buffered = buffered

    @property
    def method(self):
        return self._method

    @property
    def uri(self):
        return self._uri

    @property
    def headers(self):
        return self._headers

    def write(self, data):
        return self._writer.write(data)

    @idiokit.stream
    def finish(self):
        yield self._writer.finish()
        http_version, code, reason = yield read_status_line(self._buffered)
        headers = yield read_headers(self._buffered)
        idiokit.stop(ClientResponse(http_version, code, reason, headers, self._buffered))


def _normalize_verify(verify):
    if isinstance(verify, basestring):
        require_cert = True
        ca_certs = verify
    elif verify is True:
        require_cert = True
        ca_certs = None
    elif verify is False:
        require_cert = False
        ca_certs = None
    else:
        raise TypeError("\"verify\" parameter must be a boolean or a string")
    return require_cert, ca_certs


def _normalize_cert(cert):
    if cert is None:
        certfile = None
        keyfile = None
    elif isinstance(cert, basestring):
        certfile = cert
        keyfile = cert
    else:
        certfile, keyfile = cert
    return certfile, keyfile


class _Adapter(object):
    @idiokit.stream
    def connect(self, client, url):
        yield None


class _HTTPAdapter(_Adapter):
    default_port = 80

    @idiokit.stream
    def connect(self, client, url):
        parsed = urlparse.urlparse(url)

        host = parsed.hostname
        port = self.default_port if parsed.port is None else parsed.port
        results = yield host_lookup(host, client.resolver)

        family, ip = results[0]
        sock = socket.Socket(family)
        yield sock.connect((ip, port), timeout=client.timeout)
        idiokit.stop(host, sock)


class _HTTPSAdapter(_HTTPAdapter):
    default_port = 443

    @idiokit.stream
    def connect(self, client, url):
        require_cert, ca_certs = _normalize_verify(client.verify)
        certfile, keyfile = _normalize_cert(client.cert)

        hostname, sock = yield _HTTPAdapter.connect(self, client, url)
        sock = yield ssl.wrap_socket(
            sock,
            certfile=certfile,
            keyfile=keyfile,
            require_cert=require_cert,
            ca_certs=ca_certs,
            timeout=client.timeout
        )
        if require_cert:
            cert = yield sock.getpeercert()
            ssl.match_hostname(cert, hostname)
        idiokit.stop(hostname, sock)


class HTTPUnixAdapter(_Adapter):
    @idiokit.stream
    def connect(self, client, url):
        hostname = urlparse.urlparse(url).netloc
        _, at, right = hostname.partition("@")
        if at:
            hostname = right

        socket_path = os.path.join("/", urllib.unquote(hostname))

        sock = socket.Socket(socket.AF_UNIX)
        yield sock.connect(socket_path, timeout=client.timeout)
        idiokit.stop(hostname, sock)


class Client(object):
    def __init__(self, resolver=None, timeout=60.0, verify=True, cert=None,
                 user_agent=None):
        _normalize_verify(verify)
        _normalize_cert(cert)

        self._resolver = resolver
        self._verify = verify
        self._cert = cert
        self._timeout = timeout

        self._user_agents = ["idiokit/{0}".format(idiokit.__version__)]
        if user_agent is not None:
            self._user_agents.insert(0, user_agent)

        self._mounts = {}
        self.mount("http://", _HTTPAdapter())
        self.mount("https://", _HTTPSAdapter())

    @property
    def resolver(self):
        return self._resolver

    @property
    def timeout(self):
        return self._timeout

    @property
    def verify(self):
        return self._verify

    @property
    def cert(self):
        return self._cert

    @property
    def user_agent(self):
        return ' '.join(self._user_agents)

    def mount(self, prefix, adapter):
        """
        Set the adapter for handling URLs that start with the given prefix.

        The prefix comparison is case-insensitive and the longest matching
        prefix wins.
        """

        self._mounts[prefix] = adapter

    def _adapter_for_url(self, url):
        url = url.lower()

        choice = None
        for prefix, adapter in self._mounts.iteritems():
            if not url.startswith(prefix):
                continue

            if choice is None or len(choice[0]) < prefix:
                choice = prefix, adapter

        if choice is None:
            raise ValueError("can not handle the URL")
        return choice[1]

    @idiokit.stream
    def request(self, method, url, headers={}, data=""):
        adapter = self._adapter_for_url(url)
        hostname, sock = yield adapter.connect(self, url)

        writer, headers = self._resolve_headers(method, hostname, headers, data, sock)

        parsed = urlparse.urlparse(url)
        path = urlparse.urlunparse(["", "", "/" if parsed.path == "" else parsed.path, "", parsed.query, ""])
        yield write_request_line(sock, method, path, httpversion.HTTP11)
        yield write_headers(sock, headers)

        request = ClientRequest(method, url, headers, writer, _Buffered(sock))
        yield request.write(data)
        idiokit.stop(request)

    def _resolve_headers(self, method, host, headers, data, socket):
        headers = normalized_headers(headers)
        if headers.get("host", None) is None:
            headers["host"] = host

        if headers.get("user-agent") is None:
            headers["user-agent"] = self.user_agent

        connection = get_header_single(headers, "connection", "close")
        if connection.lower() != "close":
            raise ValueError("unknown connection value '{0}'".format(connection))
        headers["connection"] = connection

        transfer_encoding = get_header_list(headers, "transfer-encoding", None)
        content_length = get_content_length(headers, len(data))

        if transfer_encoding is not None:
            if transfer_encoding.lower() not in ("identity", "chunked"):
                raise ValueError("unknown transfer encoding '{0}'".format(transfer_encoding))
            transfer_encoding = transfer_encoding.lower()

        if method == "HEAD":
            if content_length != 0:
                raise ValueError("no content-length != 0 allowed for HEAD requests")
            writer = _LimitedWriter(socket, 0, "no response body allowed for HEAD requests")
            headers["content-length"] = 0
        elif transfer_encoding == "chunked":
            writer = _ChunkedWriter(socket)
        else:
            writer = _LimitedWriter(socket, content_length, "content length set to {0} bytes".format(content_length))
            headers["content-length"] = content_length

        return writer, headers


request = Client().request
