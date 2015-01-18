from __future__ import absolute_import

import os
import time
import errno
import contextlib
import socket as _socket

from . import idiokit, threadpool, select, timer

# Import constants from the standard socket module.
for _name in getattr(_socket, "__all__", dir(_socket)):
    if not (_name.isupper() and "_" in _name):
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


def _countdown_none():
    yield True, None

    while True:
        yield False, None


def _countdown_seconds(seconds):
    prev = time.time()
    yield True, max(seconds, 0.0)

    while True:
        now = time.time()
        seconds -= max(now - prev, 0.0)
        if seconds <= 0:
            raise SocketTimeout("timed out")

        prev = now
        yield False, max(seconds, 0.0)


def countdown(timeout):
    if timeout is None:
        return _countdown_none()
    return _countdown_seconds(timeout)


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


@idiokit.stream
def _recv(socket, timeout, func, *args, **keys):
    for first, timeout in countdown(timeout):
        if not first:
            yield select.select((socket,), (), (), timeout)

        try:
            data = func(*args, **keys)
        except _socket.error as err:
            if err.errno not in _ALLOWED_SOCKET_ERRNOS:
                raise
        else:
            idiokit.stop(data)


@idiokit.stream
def _send(socket, timeout, func, *args, **keys):
    for first, timeout in countdown(timeout):
        if not first:
            yield select.select((), (socket,), (), timeout)

        try:
            bytes = func(*args, **keys)
        except _socket.error as err:
            if err.errno not in _ALLOWED_SOCKET_ERRNOS:
                raise
        else:
            idiokit.stop(bytes)


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
            socket, address = yield _recv(self._socket, timeout, self._socket.accept)
        idiokit.stop(_Socket(socket), address)

    @idiokit.stream
    def connect(self, address, timeout=None):
        for first, timeout in countdown(timeout):
            if not first:
                yield select.select((), (self._socket,), (), timeout)

            with wrapped_socket_errors():
                code = self._socket.connect_ex(address)

            if code in (errno.EALREADY, errno.EINPROGRESS):
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
            result = yield _recv(self._socket, timeout, self._socket.recv, bufsize, flags)
        idiokit.stop(result)

    @idiokit.stream
    def recvfrom(self, bufsize, flags=0, timeout=None):
        if bufsize <= 0:
            yield timer.sleep(0.0)
            idiokit.stop("")

        with wrapped_socket_errors():
            result = yield _recv(self._socket, timeout, self._socket.recvfrom, bufsize, flags)
        idiokit.stop(result)

    @idiokit.stream
    def send(self, data, flags=0, timeout=None):
        check_sendable_type(data)

        with wrapped_socket_errors():
            result = yield _send(self._socket, timeout, self._socket.send, data, flags)
        idiokit.stop(result)

    @idiokit.stream
    def sendall(self, data, flags=0, timeout=None):
        check_sendable_type(data)

        offset = 0
        length = len(data)

        with wrapped_socket_errors():
            for _, timeout in countdown(timeout):
                buf = buffer(data, offset)
                bytes = yield _send(self._socket, timeout, self._socket.send, buf, flags)

                offset += bytes
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
            result = yield _send(self._socket, timeout, self._socket.sendto, data, flags, address)
        idiokit.stop(result)

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
