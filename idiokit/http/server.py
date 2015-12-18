# Relevant specifications:
# [RFC 1945]: https://www.ietf.org/rfc/rfc1945.txt
#     "Hypertext Transfer Protocol -- HTTP/1.0"
# [RFC 2616]: https://www.ietf.org/rfc/rfc2616.txt
#     "RFC 2616: Hypertext Transfer Protocol -- HTTP/1.1"
# [RFC 2145]: https://www.ietf.org/rfc/rfc2145.txt
#     "RFC 2145: Use and Interpretation of HTTP Version Numbers"
# [RFC 1123]: https://www.ietf.org/rfc/rfc1123.txt
#     "Requirements for Internet Hosts -- Communication Layers"

from __future__ import absolute_import

import os
import abc
import stat
import errno
import httplib
import collections
from email.message import Message
from email.parser import HeaderParser
from numbers import Integral

from .. import idiokit, socket, timer
from . import httpversion
from . import date


@idiokit.stream
def _close_socket(sock):
    try:
        yield sock.shutdown(socket.SHUT_RDWR)
    except socket.SocketError as error:
        if error.args[0] not in (errno.EBADF, errno.ENOTCONN):
            raise
    yield sock.close()


class ConnectionLost(Exception):
    pass


class BadRequest(Exception):
    def __init__(self, reason=None, code=httplib.BAD_REQUEST):
        if reason is None:
            reason = httplib.responses.get(code, "")

        super(BadRequest, self).__init__(reason, code)

        self._code = code
        self._reason = reason

    @property
    def code(self):
        return self._code

    @property
    def reason(self):
        return self._reason


class BadRequestOverLimit(BadRequest):
    pass


# [RFC 2616][] section 4.2:
# > Multiple message-header fields with the same field-name MAY be present in a
# > message if and only if the entire field-value for that header field is defined
# > as a comma-separated list [i.e., #(values)]. It MUST be possible to combine
# > the multiple header fields into one "field-name: field-value" pair, without
# > changing the semantics of the message, by appending each subsequent
# > field-value to the first, each separated by a comma.


def get_header_single(headers, name, default=None):
    values = headers.get(name.lower(), None)
    if not values:
        return default
    if len(values) == 1:
        return values[0]
    raise BadRequest("multiple {0} headers are not allowed".format(name))


def get_content_length(headers, default=None):
    content_length = get_header_single(headers, "content-length", None)
    if content_length is None:
        return default
    if content_length.isdigit():
        return int(content_length)
    raise BadRequest("invalid Content-Length (not an integer >= 0)")


def get_header_list(headers, name, default=None):
    values = headers.get(name.lower())
    if not values:
        return default
    return ",".join(values)


class _Buffered(object):
    def __init__(self, reader):
        self._reader = reader
        self._buffer = collections.deque()

    @idiokit.stream
    def read(self, amount):
        if not self._buffer:
            data = yield self._reader.recv(amount)
            idiokit.stop(data)

        offset, data = self._buffer[0]
        if len(data) - offset > amount:
            self._buffer[0] = offset + amount, data
        else:
            self._buffer.popleft()
        idiokit.stop(data[offset:offset + amount])

    @idiokit.stream
    def read_line(self, chunk_size=1024, max_size=64 * 1024):
        buf = []
        remaining_size = max_size

        while remaining_size > 0:
            try:
                data = yield self.read(min(chunk_size, remaining_size))
            except:
                self._buffer.extendleft((0, x) for x in buf)
                raise

            if not data:
                raise ConnectionLost("lost connection before a line terminator could be reached")

            n_index = data.find("\n")
            if n_index == -1:
                buf.append(data)
                remaining_size -= len(data)
                continue

            offset = n_index + 1
            if offset < len(data):
                self._buffer.appendleft((offset, data))
            buf.append(data[:offset])
            idiokit.stop("".join(buf))

        raise BadRequestOverLimit("max line length {0} limit crossed".format(max_size))


class _Chunked(object):
    def __init__(self, buffered):
        self._buffered = buffered
        self._next_func = self._start
        self._next_args = ()

    @idiokit.stream
    def _start(self, amount):
        line = yield self._buffered.read_line()

        # [RFC 2616][] section 3.6.1:
        # > All HTTP/1.1 applications [...] ignore chunk-extension extensions
        # > they do not understand.
        chunk_size_hex, _, _ = line.partition(";")
        try:
            chunk_size = int(chunk_size_hex, 16)
        except ValueError:
            raise BadRequest("could not parse data chunk size")

        if chunk_size == 0:
            idiokit.stop(None, self._skip_trailers, ())
        idiokit.stop(None, self._data, (chunk_size,))

    @idiokit.stream
    def _data(self, amount, chunk_size):
        data = yield self._buffered.read(min(amount, chunk_size))
        if not data:
            raise ConnectionLost("lost connection before all chunk data could be read")

        chunk_size -= len(data)
        if chunk_size == 0:
            idiokit.stop(data, self._crlf, ())
        idiokit.stop(data, self._data, (chunk_size,))

    @idiokit.stream
    def _crlf(self, amount):
        line = yield self._buffered.read_line(max_size=2)
        if line not in ("\r\n", "\n"):
            raise BadRequest("invalid chunk end")
        idiokit.stop(None, self._start, ())

    @idiokit.stream
    def _skip_trailers(self, amount):
        line = yield self._buffered.read_line()
        if line in ("\r\n", "\n"):
            idiokit.stop(None, self._done, ())
        idiokit.stop(None, self._skip_trailers, ())

    @idiokit.stream
    def _done(self, amount):
        yield timer.sleep(0.0)
        idiokit.stop("", self._done, ())

    @idiokit.stream
    def read(self, amount):
        data = None

        while data is None:
            func = self._next_func
            args = self._next_args

            data, func, args = yield func(amount, *args)

            self._next_func = func
            self._next_args = args

        idiokit.stop(data)


class _Limited(object):
    def __init__(self, buffered, limit):
        self._buffered = buffered
        self._limit = limit

    @idiokit.stream
    def read(self, amount):
        amount = min(amount, self._limit)
        if amount == 0:
            yield timer.sleep(0.0)
            idiokit.stop("")

        data = yield self._buffered.read(amount)
        if not data and self._limit > 0:
            raise ConnectionLost("lost connection before all data could be read")

        self._limit -= len(data)
        idiokit.stop(data)


class ServerRequest(object):
    def __init__(self, method, uri, http_version, headers, readable):
        self._method = method
        self._uri = uri
        self._http_version = http_version
        self._headers = headers
        self._readable = readable

    @property
    def method(self):
        return self._method

    @property
    def uri(self):
        return self._uri

    @property
    def http_version(self):
        return self._http_version

    @property
    def headers(self):
        return self._headers

    def read(self, amount):
        return self._readable.read(amount)


@idiokit.stream
def write_status_line(socket, http_version, code, reason=None):
    if not (0 <= code <= 999):
        raise ValueError("status code must be a (max) 3-digit integer")

    if reason is None:
        reason = httplib.responses.get(code, "")
    if "\r" in reason or "\n" in reason:
        raise ValueError("CR and/or LF are not allowed in the reason string")

    yield socket.sendall("{0} {1:03} {2}\r\n".format(http_version, code, reason))


def normalized_headers(items):
    """
    >>> normalized_headers({"X-Small-Number-is-Small": 1})
    {'x-small-number-is-small': ['1']}

    >>> normalized_headers({"X-Long-Number-is-Long": 0L})
    {'x-long-number-is-long': ['0']}
    """

    result = dict()

    if callable(getattr(items, "items", None)):
        items = items.items()

    for key, values in items:
        # [RFC 2616][] section 4.2:
        # > Field names are case-insensitive.
        key = key.lower()

        if isinstance(values, (basestring, Integral)):
            values = [values]

        for value in values:
            if isinstance(value, Integral):
                value = str(value)
            result.setdefault(key, []).append(value)

    return result


@idiokit.stream
def write_headers(socket, headers):
    if headers:
        msg = Message()
        for key, values in normalized_headers(headers.items()).iteritems():
            for value in values:
                msg.add_header(key, value)
        header_data = msg.as_string()
        yield socket.sendall(header_data.rstrip("\n").replace("\n", "\r\n") + "\r\n")
    yield socket.sendall("\r\n")


@idiokit.stream
def read_headers(buffered):
    headers = []
    while True:
        line = yield buffered.read_line()
        if not line:
            raise ConnectionLost()

        if line == "\r\n" or line == "\n":
            break
        headers.append(line)

    msg = HeaderParser().parsestr("".join(headers))

    header_dict = normalized_headers(msg.items())
    idiokit.stop(header_dict)


@idiokit.stream
def read_request_line(buffered):
    line = yield buffered.read_line()
    if not line:
        raise ConnectionLost()

    pieces = line.rstrip().split(" ", 2)
    if len(pieces) < 3:
        raise BadRequest("could not parse request line")

    method, uri, http_version_string = pieces
    try:
        http_version = httpversion.HTTPVersion.from_string(http_version_string)
    except ValueError:
        raise BadRequest("invalid HTTP version")
    idiokit.stop(method, uri, http_version)


class WriterError(Exception):
    pass


class WriterFinishError(WriterError):
    pass


class _RawWriter(object):
    def __init__(self, socket):
        self._socket = socket
        self._finished = False

    @idiokit.stream
    def write(self, data):
        if self._finished:
            raise WriterError("already finished")

        if data:
            yield self._socket.sendall(data)
        else:
            yield timer.sleep(0.0)

    @idiokit.stream
    def finish(self):
        if self._finished:
            return
        self._finished = True
        yield timer.sleep(0.0)


class _LimitedWriter(object):
    def __init__(self, socket, length, error_message):
        self._socket = socket
        self._length = length
        self._error_message = error_message

        self._done = 0
        self._finished = False

    @idiokit.stream
    def write(self, data):
        if self._finished:
            raise WriterError("already finished")
        if len(data) + self._done > self._length:
            raise WriterError(self._error_message)

        if data:
            self._done += len(data)
            yield self._socket.sendall(data)
        else:
            yield timer.sleep(0.0)

    @idiokit.stream
    def finish(self):
        if self._finished:
            return
        if self._done < self._length:
            raise WriterFinishError("did not write all {0} bytes".format(self._length))
        self._finished = True
        yield timer.sleep(0.0)


class _ChunkedWriter(object):
    def __init__(self, socket):
        self._socket = socket
        self._finished = False

    @idiokit.stream
    def write(self, data):
        if self._finished:
            raise WriterError("already finished")

        if data:
            yield self._socket.sendall("{0:x}\r\n".format(len(data)))
            yield self._socket.sendall(data)
            yield self._socket.sendall("\r\n")
        else:
            yield timer.sleep(0.0)

    @idiokit.stream
    def finish(self, check_error=True):
        if self._finished:
            return
        self._finished = True
        yield self._socket.sendall("0\r\n\r\n")


class _ServerResponse(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self, socket, request, http_version=httpversion.HTTP11):
        self._socket = socket
        self._request = request
        self._http_version = http_version

        self._status = None
        self._writer = None

    @property
    def http_version(self):
        return self._http_version

    @idiokit.stream
    def write_continue(self, reason=None):
        if self._status is not None:
            raise RuntimeError("status already written")
        yield write_status_line(self._socket, self._http_version, httplib.CONTINUE, reason)
        yield self._socket.sendall("\r\n")

    @idiokit.stream
    def write_status(self, code, reason=None):
        if not isinstance(code, int):
            raise TypeError("expected int, got '{0}'".format(type(code).__name__))
        if self._status is not None:
            raise RuntimeError("status already written")
        self._status = code
        yield write_status_line(self._socket, self._http_version, code, reason)

    @idiokit.stream
    def write_headers(self, header_dict):
        if self._status is None:
            yield self.write_status(httplib.OK)

        if self._writer is not None:
            raise RuntimeError("headers already written")

        request = self._request
        self._request = None
        self._writer, headers = self._finish_headers(request, self._status, header_dict, self._socket)
        yield write_headers(self._socket, headers)

    @idiokit.stream
    def write(self, data):
        if self._writer is None:
            yield self.write_headers({})
        yield self._writer.write(data)

    @idiokit.stream
    def write_stream(self, buffer_size=2 ** 14):
        while True:
            chunk = yield idiokit.next()
            buf = [chunk]
            buf_length = len(chunk)

            try:
                while buf_length < buffer_size:
                    chunk = yield timer.timeout(0.0, idiokit.next())
                    buf.append(chunk)
                    buf_length += len(chunk)
            except StopIteration as stop:
                yield self.write("".join(buf))
                raise stop
            except timer.Timeout:
                pass

            yield self.write("".join(buf))

    @idiokit.stream
    def finish(self):
        if self._writer is None:
            yield self.write_headers({
                "content-length": 0
            })
        yield self._writer.finish()

    @abc.abstractmethod
    def _finish_headers(self, request, status_code, header_dict, socket):
        pass


class ServerResponseHTTP10(_ServerResponse):
    """A reponse object for HTTP/1.0 requests."""

    def _finish_headers(self, request, status_code, header_dict, socket):
        headers = dict(normalized_headers(header_dict.items()))

        content_length = get_content_length(headers, None)
        if 100 <= status_code < 200 or status_code in (204, 304):
            if content_length not in (None, 0):
                raise ValueError("no content-length != 0 allowed for {0} status".format(status_code))
            writer = _LimitedWriter(socket, 0, "no response body allowed for {0} status".format(status_code))
            headers["content-length"] = 0
        elif request.method == "HEAD":
            if content_length not in (None, 0):
                raise ValueError("no content-length != 0 allowed for HEAD requests")
            writer = _LimitedWriter(socket, 0, "no response body allowed for HEAD requests")
            headers["content-length"] = 0
        elif content_length is None:
            writer = _RawWriter(socket)
        else:
            writer = _LimitedWriter(socket, content_length, "content length set to {0} bytes".format(content_length))
            headers["content-length"] = content_length

        return writer, headers


class ServerResponseHTTP11(_ServerResponse):
    """A response object for HTTP/1.1 requests."""

    def _finish_headers(self, request, status_code, header_dict, socket):
        headers = dict(normalized_headers(header_dict.items()))

        connection = get_header_single(headers, "connection", "close")
        if connection.lower() != "close":
            raise ValueError("unknown connection value")
        headers["connection"] = connection

        transfer_encoding = get_header_list(headers, "transfer-encoding", None)
        content_length = get_content_length(headers, None)

        if transfer_encoding is not None:
            transfer_encoding = transfer_encoding.lower()

        if 100 <= status_code < 200 or status_code in (204, 304):
            if content_length not in (None, 0):
                raise ValueError("no content-length != 0 allowed for {0} status".format(status_code))
            writer = _LimitedWriter(socket, 0, "no response body allowed for {0} status".format(status_code))
            headers["content-length"] = 0
        elif request.method == "HEAD":
            if content_length not in (None, 0):
                raise ValueError("no content-length != 0 allowed for HEAD requests")
            writer = _LimitedWriter(socket, 0, "no response body allowed for HEAD requests")
            headers["content-length"] = 0
        elif transfer_encoding == "chunked" or content_length is None:
            writer = _ChunkedWriter(socket)
            headers["transfer-encoding"] = "chunked"
        elif transfer_encoding in (None, "identity") and content_length is not None:
            writer = _LimitedWriter(socket, content_length, "content length set to {0} bytes".format(content_length))
            headers["content-length"] = content_length
        else:
            raise ValueError("either content-length or transfer-encoding: chunked must be used")

        if get_header_single(headers, "date", None) is None:
            headers["date"] = date.format_date()

        return writer, headers


class SupervisorCancel(Exception):
    pass


class SupervisorNotRunning(Exception):
    pass


class _Supervisor(object):
    def __init__(self, source, *args, **keys):
        self._tasks = {}
        self._empty = idiokit.Event()
        self._empty.succeed()
        self._main = source(self, *args, **keys)

    @idiokit.stream
    def supervise(self, task):
        yield timer.sleep(0.0)

        if self._main is None:
            event = idiokit.Event()
            task.result().listen(event.succeed)
            task.throw(SupervisorCancel())
            yield event
            raise SupervisorNotRunning()

        task_key = object()
        self._tasks[task_key] = self._wrap(task_key, task)
        if len(self._tasks) == 1:
            self._empty = idiokit.Event()

    @idiokit.stream
    def _run(self):
        try:
            yield self._main
        finally:
            self._main = None
            for task in self._tasks.itervalues():
                task.throw(SupervisorCancel)
            yield self._empty

    @idiokit.stream
    def _wrap(self, task_key, task):
        try:
            yield task
        except:
            if self._main is not None:
                self._main.throw()
        finally:
            del self._tasks[task_key]
            if not self._tasks:
                self._empty.succeed()


def supervisor(source, *args, **keys):
    supervisor = _Supervisor(source, *args, **keys)
    return supervisor._run()


class Server(object):
    def main(self):
        return idiokit.consume()

    @idiokit.stream
    def request_continue(self, addr, request, response):
        yield response.write_continue()
        yield self.request(addr, request, response)

    @idiokit.stream
    def request(self, addr, request, response):
        yield timer.sleep(0.0)


class _Server(Server):
    def __init__(self, handler):
        self._handler = handler

    def request(self, *args, **keys):
        return self._handler(*args, **keys)


def as_server(server):
    if isinstance(server, Server):
        return server
    elif callable(server):
        return _Server(server)
    else:
        raise TypeError("expected a Server instance or a callable, got '{0}'".format(type(server).__name__))


@idiokit.stream
def serve(server, sock):
    server = as_server(server)

    @idiokit.stream
    def listen_socket(supervisor):
        while True:
            conn, addr = yield sock.accept()
            yield supervisor.supervise(handle_connection(conn, addr))

    @idiokit.stream
    def handle_connection(conn, addr):
        buffered = _Buffered(conn)

        try:
            try:
                method, uri, http_version = yield read_request_line(buffered)
                if http_version.major != 1:
                    raise BadRequest(code=httplib.HTTP_VERSION_NOT_SUPPORTED)

                request_handler = server.request
                if http_version == httpversion.HTTP10:
                    headers = yield read_headers(buffered)

                    content_length = get_content_length(headers, 0)
                    buffered = _Limited(buffered, content_length)

                    request = ServerRequest(method, uri, http_version, headers, buffered)
                    response = ServerResponseHTTP10(conn, request)
                elif http_version >= httpversion.HTTP11:
                    headers = yield read_headers(buffered)

                    host = get_header_single(headers, "host", None)
                    if host is None:
                        raise BadRequest()

                    # [RFC 2616][] section 4.4:
                    # > If the message does include a non-identity
                    # > transfer-coding, the Content-Length MUST be ignored.
                    transfer_encoding = get_header_list(headers, "transfer-encoding", None)
                    content_length = get_content_length(headers, 0)

                    # [RFC 2616][] section 3.6:
                    # > All transfer-coding values are case-insensitive.
                    if transfer_encoding is not None:
                        transfer_encoding = transfer_encoding.lower()

                    if transfer_encoding is None or transfer_encoding == "identity":
                        buffered = _Limited(buffered, content_length)
                    elif transfer_encoding == "chunked":
                        buffered = _Chunked(buffered)
                    else:
                        raise BadRequest(code=httplib.NOT_IMPLEMENTED)

                    expect = get_header_single(headers, "expect", None)
                    if expect is None:
                        request_handler = server.request
                    elif expect == "100-continue":
                        request_handler = server.request_continue
                    else:
                        raise BadRequest(code=httplib.EXPECTATION_FAILED)

                    request = ServerRequest(method, uri, http_version, headers, buffered)
                    response = ServerResponseHTTP11(conn, request)
            except ConnectionLost:
                pass
            except BadRequest as bad:
                yield write_status_line(conn, httpversion.HTTP11, bad.code, bad.reason)
                yield conn.sendall("\r\n")
            else:
                yield request_handler(addr, request, response)
                yield response.finish()
        except socket.SocketError:
            pass
        finally:
            yield _close_socket(conn)

    yield idiokit.pipe(server.main(), supervisor(listen_socket))


@idiokit.stream
def serve_http(server, host, port):
    sock = socket.Socket()
    try:
        yield sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        yield sock.bind((host, port))
        yield sock.listen(5)
        yield serve(server, sock)
    finally:
        yield sock.close()


def parse_permissions(perms):
    flags = [
        stat.S_ISUID,
        stat.S_ISGID,
        stat.S_ISVTX,
        stat.S_IRUSR,
        stat.S_IWUSR,
        stat.S_IXUSR,
        stat.S_IRGRP,
        stat.S_IWGRP,
        stat.S_IXGRP,
        stat.S_IROTH,
        stat.S_IWOTH,
        stat.S_IXOTH
    ]

    if not (0 < len(perms) <= 4 and perms.isdigit()):
        raise ValueError("invalid permissions")
    parsed = int(perms, 8)

    result = 0
    while flags:
        flag = flags.pop()
        if parsed & 1:
            result |= flag
        parsed >>= 1
    return result


@idiokit.stream
def serve_unix_domain_socket(server, path, permissions="0600"):
    if isinstance(permissions, basestring):
        permissions = parse_permissions(permissions)

    sock = socket.Socket(socket.AF_UNIX)
    try:
        os.unlink(path)
    except OSError as ose:
        if ose.args[0] == errno.ENOENT:
            pass

    yield sock.bind(path)
    os.chmod(path, permissions)

    try:
        yield sock.listen(5)
        try:
            yield serve(server, sock)
        finally:
            yield sock.close()
    finally:
        os.unlink(path)
