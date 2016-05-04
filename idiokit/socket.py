from __future__ import absolute_import

import os
import time
import errno
import contextlib
import socket as _socket

from . import idiokit, threadpool, select, timer

# Import constants from the standard socket module.
for _name in getattr(_socket, "__all__", dir(_socket)):
    if not _name.isupper():
        continue
    if any(_name.startswith(x) for x in ["_", "SSL_"]):
        continue
    globals()[_name] = getattr(_socket, _name)


class SocketError(IOError):
    pass


class SocketHError(SocketError):
    pass


class SocketTimeout(SocketError):
    pass


class SocketGAIError(SocketError):
    pass


@contextlib.contextmanager
def wrapped_socket_errors():
    try:
        yield
    except _socket.timeout as err:
        raise SocketTimeout(*err.args)
    except _socket.gaierror as err:
        raise SocketGAIError(*err.args)
    except _socket.herror as err:
        raise SocketHError(*err.args)
    except _socket.error as err:
        raise SocketError(*err.args)


def countdown(timeout):
    while timeout is None:
        yield None

    prev = time.time()
    yield max(timeout, 0.0)

    while True:
        now = time.time()
        timeout -= max(now - prev, 0.0)
        if timeout <= 0:
            raise SocketTimeout("timed out")

        prev = now
        yield max(timeout, 0.0)


def check_sendable_type(value):
    if isinstance(value, (str, buffer)):
        return

    name = type(value).__name__
    msg = "expected string or buffer, got {0}".format(name)
    raise TypeError(msg)


_ALLOWED_SOCKET_ERRNOS = frozenset([
    errno.EINTR,
    errno.ENOBUFS,
    errno.EAGAIN,
    errno.EWOULDBLOCK
])


def _wrapped_call(default_result, func, *args, **keys):
    try:
        result = func(*args, **keys)
    except _socket.error as err:
        if err.errno not in _ALLOWED_SOCKET_ERRNOS:
            raise
        return default_result
    return result


def _sendto_with_flags(string, flags, address, timeout=None):
    return string, flags, address, timeout


def _sendto_without_flags(string, address, timeout=None):
    return string, 0, address, timeout


class _Socket(object):
    @property
    def family(self):
        return self._socket.family

    @property
    def type(self):
        return self._socket.type

    @property
    def proto(self):
        return self._socket.proto

    def __init__(self, socket):
        # Some CPython 2.x standard socket module functions such as
        # socket.fromfd and socket.socketpair return socket._realsocket
        # instances which do not work with ssl.wrap_socket (see e.g.
        # https://bugs.python.org/issue13942). Work around this by wrapping
        # socket._realsocket instances to socket.SocketType.
        if isinstance(socket, _socket._realsocket):
            socket = _socket.socket(_sock=socket)

        self._socket = socket

        with wrapped_socket_errors():
            self._socket.setblocking(False)

    @idiokit.stream
    def getpeername(self, *args, **keys):
        yield timer.sleep(0.0)

        with wrapped_socket_errors():
            idiokit.stop(self._socket.getpeername(*args, **keys))

    @idiokit.stream
    def getsockname(self, *args, **keys):
        yield timer.sleep(0.0)

        with wrapped_socket_errors():
            idiokit.stop(self._socket.getsockname(*args, **keys))

    @idiokit.stream
    def bind(self, address):
        yield timer.sleep(0.0)

        with wrapped_socket_errors():
            self._socket.bind(address)

    @idiokit.stream
    def listen(self, backlog):
        yield timer.sleep(0.0)

        with wrapped_socket_errors():
            self._socket.listen(backlog)

    @idiokit.stream
    def accept(self, timeout=None):
        with wrapped_socket_errors():
            for timeout in countdown(timeout):
                yield select.select((self._socket,), (), (), timeout)

                result = _wrapped_call(None, self._socket.accept)
                if result is not None:
                    socket, address = result
                    idiokit.stop(_Socket(socket), address)

    @idiokit.stream
    def connect(self, address, timeout=None):
        yield timer.sleep(0.0)

        for timeout in countdown(timeout):
            with wrapped_socket_errors():
                code = self._socket.connect_ex(address)

            if code in (errno.EALREADY, errno.EINPROGRESS):
                yield select.select((), (self._socket,), (), timeout)
                continue
            if code in (0, errno.EISCONN):
                return
            raise SocketError(code, os.strerror(code))

    @idiokit.stream
    def shutdown(self, how):
        with wrapped_socket_errors():
            yield threadpool.thread(self._socket.shutdown, how)

    @idiokit.stream
    def close(self):
        with wrapped_socket_errors():
            yield threadpool.thread(self._socket.close)

    @idiokit.stream
    def recv(self, bufsize, flags=0, timeout=None):
        if bufsize <= 0:
            yield timer.sleep(0.0)
            idiokit.stop("")

        with wrapped_socket_errors():
            for timeout in countdown(timeout):
                yield select.select((self._socket,), (), (), timeout)

                result = _wrapped_call(None, self._socket.recv, bufsize, flags)
                if result is not None:
                    idiokit.stop(result)

    @idiokit.stream
    def recvfrom(self, bufsize, flags=0, timeout=None):
        if bufsize <= 0:
            yield timer.sleep(0.0)
            idiokit.stop("")

        with wrapped_socket_errors():
            for timeout in countdown(timeout):
                yield select.select((self._socket,), (), (), timeout)

                result = _wrapped_call(None, self._socket.recvfrom, bufsize, flags)
                if result is not None:
                    idiokit.stop(result)

    @idiokit.stream
    def send(self, data, flags=0, timeout=None):
        check_sendable_type(data)

        with wrapped_socket_errors():
            for timeout in countdown(timeout):
                yield select.select((), (self._socket,), (), timeout)

                count = _wrapped_call(None, self._socket.send, data, flags)
                if count is not None:
                    idiokit.stop(count)

    @idiokit.stream
    def sendall(self, data, flags=0, timeout=None):
        check_sendable_type(data)

        offset = 0
        length = len(data)
        with wrapped_socket_errors():
            for timeout in countdown(timeout):
                yield select.select((), (self._socket,), (), timeout)

                offset += _wrapped_call(0, self._socket.send, buffer(data, offset), flags)
                if offset >= length:
                    break

    @idiokit.stream
    def sendto(self, data, *args, **keys):
        check_sendable_type(data)

        try:
            data, flags, address, timeout = _sendto_with_flags(data, *args, **keys)
        except TypeError:
            data, flags, address, timeout = _sendto_without_flags(data, *args, **keys)

        with wrapped_socket_errors():
            for timeout in countdown(timeout):
                yield select.select((), (self._socket,), (), timeout)

                count = _wrapped_call(None, self._socket.sendto, data, flags, address)
                if count is not None:
                    idiokit.stop(count)

    @idiokit.stream
    def getsockopt(self, *args, **keys):
        yield timer.sleep(0)

        with wrapped_socket_errors():
            result = self._socket.getsockopt(*args, **keys)
        idiokit.stop(result)

    @idiokit.stream
    def setsockopt(self, *args, **keys):
        yield timer.sleep(0)

        with wrapped_socket_errors():
            result = self._socket.setsockopt(*args, **keys)
        idiokit.stop(result)

    def fileno(self):
        with wrapped_socket_errors():
            return self._socket.fileno()

    # Not implemented:
    # connect_ex: Use connect(...)
    # recv_into, recvfrom_into: Use recv(...) and recvfrom(...)
    # setblocking, settimeout, gettimeout: Use Socket.<method>(..., timeout=<seconds>)
    # ioctl
    # makefile


class Socket(_Socket):
    def __init__(self, *args, **keys):
        with wrapped_socket_errors():
            raw_socket = _socket.socket(*args, **keys)
        _Socket.__init__(self, raw_socket)


def fromfd(*args, **keys):
    with wrapped_socket_errors():
        raw_socket = _socket.fromfd(*args, **keys)
    return _Socket(raw_socket)


def socketpair(*args, **keys):
    with wrapped_socket_errors():
        left, right = _socket.socketpair(*args, **keys)

    try:
        return _Socket(left), _Socket(right)
    except:
        left.close()
        right.close()
        raise
