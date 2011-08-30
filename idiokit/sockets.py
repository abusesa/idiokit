from __future__ import absolute_import

import os
import sys
import errno
import socket
import functools

from . import idiokit, ssl, select, threadpool

ALLOWED_SOCKET_ERRNOS = frozenset([errno.EINTR, errno.ENOBUFS, 
                                   errno.EAGAIN, errno.EWOULDBLOCK])

def _read(func):
    @idiokit.stream
    @functools.wraps(func)
    def wrapped(self, max_amount):
        if max_amount <= 0:
            idiokit.stop("")

        while True:
            try:
                data = func(self, max_amount)
                if data:
                    idiokit.stop(data)
                
                ifd, _, _ = select.select((self._socket,), (), (), 0.0)
                if ifd:
                    data = func(self, max_amount)
                    if data:
                        idiokit.stop(data)

                    msg = os.strerror(errno.ECONNRESET)
                    raise socket.error(errno.ECONNRESET, msg)
            except ssl.SSLError, sslerror:
                if sslerror.args[0] == ssl.SSL_ERROR_WANT_WRITE:
                    yield select.async_select((), (self._socket,), ())
                elif sslerror.args[0] == ssl.SSL_ERROR_WANT_READ:
                    yield select.async_select((self._socket,), (), ())
                else:
                    raise
            except socket.error, error:
                if error.args[0] not in ALLOWED_SOCKET_ERRNOS:
                    raise

            yield select.async_select((self._socket,), (), ())

    return wrapped

def _write(func):
    @idiokit.stream
    @functools.wraps(func)
    def wrapped(self, data):
        if not data:
            idiokit.stop(0)

        while True:
            try:
                amount = func(self, data)
                if amount > 0:
                    idiokit.stop(amount)
            except ssl.SSLError, sslerror:
                if sslerror.args[0] == ssl.SSL_ERROR_WANT_WRITE:
                    yield select.async_select((), (self._socket,), ())
                elif sslerror.args[0] == ssl.SSL_ERROR_WANT_READ:
                    yield select.async_select((self._socket,), (), ())
                else:
                    raise
            except socket.error, error:
                if error.args[0] in ALLOWED_SOCKET_ERRNOS:
                    raise

            yield select.async_select((), (self._socket,), ())

    return wrapped

def _close(sock):
    try:
        sock.setblocking(True)
        sock.shutdown(socket.SHUT_RDWR)
    except socket.error:
        pass
    sock.close()

class _Base(object):
    @idiokit.stream
    def read(self, amount):
        idiokit.stop("")
        yield

    @idiokit.stream
    def write(self, data):
        idiokit.stop(0)
        yield

    def close(self):
        return

class _PlainSocket(_Base):
    def __init__(self, socket):
        self._socket = socket
        
    @_read
    def read(self, amount):
        return self._socket.recv(amount)

    @_write
    def write(self, data):
        return self._socket.send(data)

    def close(self):
        _close(self._socket)

class _SSLSocket(_Base):
    def __init__(self, socket, ssl_socket):
        self._socket = socket
        self._ssl = ssl_socket
        
    @_read
    def read(self, amount):
        return self._ssl.read(amount)

    @_write
    def write(self, data):
        return self._ssl.write(data)

    def close(self):
        _close(self._socket)

class Socket(object):
    def __init__(self, *args, **keys):
        self._socket = socket.socket(*args, **keys)
        self._socket.setblocking(False)
        self._wrapped = _Base()

    @idiokit.stream
    def connect(self, *args, **keys):
        try:
            self._socket.connect(*args, **keys)
        except socket.error, error:
            if error.args[0] not in (errno.EALREADY, errno.EINPROGRESS):
                raise error

        yield select.async_select((self._socket,), (self._socket,), ())
        self._wrapped = _PlainSocket(self._socket)

    @idiokit.stream
    def ssl(self, *args, **keys):
        event = idiokit.Event()

        def _wrap():
            try:
                result = ssl.wrap_socket(self._socket, *args, **keys)
            except:
                event.fail(*sys.exc_info())
            else:
                event.succeed(result)

        self._socket.setblocking(True)
        try:
            threadpool.run(_wrap)
            ssl_socket = yield event
        finally:
            self._socket.setblocking(False)
        self._wrapped = _SSLSocket(self._socket, ssl_socket)

    def read(self, max_amount=2**16):
        return self._wrapped.read(max_amount)

    def write(self, data):
        return self._wrapped.write(data)
