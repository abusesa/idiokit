from __future__ import with_statement, absolute_import

import os
import time
import errno
import contextlib
import socket as _socket

from . import idiokit, threadpool, select, timer

SHUT_RD = _socket.SHUT_RD
SHUT_WR = _socket.SHUT_WR
SHUT_RDWR = _socket.SHUT_RDWR

if hasattr(_socket, "AF_UNIX"):
    AF_UNIX = _socket.AF_UNIX
AF_INET = _socket.AF_INET
AF_INET6 = _socket.AF_INET6

SOCK_STREAM = _socket.SOCK_STREAM
SOCK_DGRAM = _socket.SOCK_DGRAM

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
    except _socket.timeout, err:
        raise SocketTimeout(*err.args)
    except _socket.gaierror, err:
        raise SocketGAIError(*err.args)
    except _socket.herror, err:
        raise SocketHError(*err.args)
    except _socket.error, err:
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

_ALLOWED_SOCKET_ERRNOS = set([
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
        except _socket.error, err:
            if err.args[0] not in _ALLOWED_SOCKET_ERRNOS:
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
        except _socket.error, err:
            if err.args[0] not in _ALLOWED_SOCKET_ERRNOS:
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
        with wrapped_socket_errors():
            result = yield _recv(self._socket, timeout, self._socket.recv, bufsize, flags)
        idiokit.stop(result)

    @idiokit.stream
    def recvfrom(self, bufsize, flags=0, timeout=None):
        with wrapped_socket_errors():
            result = yield _recv(self._socket, timeout, self._socket.recvfrom, bufsize, flags)
        idiokit.stop(result)

    @idiokit.stream
    def send(self, string, flags=0, timeout=None):
        with wrapped_socket_errors():
            result = yield _send(self._socket, timeout, self._socket.send, string, flags)
        idiokit.stop(result)

    @idiokit.stream
    def sendall(self, string, flags=0, timeout=None, chunk_size=4096):
        offset = 0
        length = len(string)

        for _, timeout in countdown(timeout):
            chunk = string[offset:offset+chunk_size]

            bytes = yield self.send(chunk, flags, timeout=timeout)

            offset += bytes
            if offset >= length:
                break

    @idiokit.stream
    def sendto(self, *args, **keys):
        try:
            string, flags, address, timeout = _sendto_with_flags(*args, **keys)
        except TypeError:
            string, flags, address, timeout = _sendto_without_flags(*args, **keys)

        with wrapped_socket_errors():
            result = yield _send(self._socket, timeout, self._socket.sendto, string, flags, address)
        idiokit.stop(result)

    # Not implemented:
    # connect_ex: Use connect(...)
    # recv_into, recvfrom_into: Use recv(...) and recvfrom(...)
    # setblocking, settimeout, gettimeout: Use Socket.<method>(..., timeout=<seconds>)
    # ioctl, getsockopt, setsockopt
    # fileno, makefile

class Socket(_Socket):
    def __init__(self, *args, **keys):
        with wrapped_socket_errors():
            raw_socket = _socket.socket(*args, **keys)
        _Socket.__init__(self, raw_socket)
