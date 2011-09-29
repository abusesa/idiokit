from __future__ import with_statement, absolute_import

import os
import errno
import socket
import select
import functools
from socket import error

from . import ssl, threado

ALLOWED_SOCKET_ERRNOS = frozenset([errno.EINTR,
                                   errno.ENOBUFS,
                                   errno.EAGAIN,
                                   errno.EWOULDBLOCK])

def _do_select(*args, **keys):
    while True:
        try:
            return select.select(*args, **keys)
        except select.error, se:
            if se.args[0] == errno.EINTR:
                continue
            raise se

def _check_connection(sock):
    ifd, _, _ = _do_select([sock], [], [], 0.0)
    if ifd and not sock.recv(1, socket.MSG_PEEK):
        raise socket.error(errno.ECONNRESET, os.strerror(errno.ECONNRESET))

def _read(func):
    @functools.wraps(func)
    def wrapped(self, *args, **keys):
        try:
            data = func(self, *args, **keys)
            if not data:
                _check_connection(self._socket)
            return data
        except ssl.SSLError:
            raise
        except socket.error, se:
            if se.args[0] not in ALLOWED_SOCKET_ERRNOS:
                raise
        return ""
    return wrapped

def _write(func):
    @functools.wraps(func)
    def wrapped(*args, **keys):
        try:
            return func(*args, **keys)
        except ssl.SSLError:
            raise
        except socket.error, se:
            if se.args[0] in ALLOWED_SOCKET_ERRNOS:
                raise
        return 0
    return wrapped

def _close(sock):
    try:
        sock.setblocking(True)
        sock.shutdown(socket.SHUT_RDWR)
    except socket.error:
        pass
    sock.close()

class _Base(object):
    def can_read(self):
        return False
    can_write = needs_read = needs_write = can_read

    def fileno(self):
        return None

    def read(self, amount):
        return ""

    def write(self, data):
        return 0

    def close(self):
        return

class _PlainSocket(_Base):
    def __init__(self, socket):
        self._socket = socket

    def fileno(self):
        return self._socket.fileno()

    def can_read(self):
        return True
    can_write = can_read

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
        self._needs = None

    def fileno(self):
        return self._socket.fileno()

    def can_read(self):
        return True
    can_write = can_read

    def needs_read(self):
        return self._needs == ssl.SSL_ERROR_WANT_READ

    def needs_write(self):
        return self._needs == ssl.SSL_ERROR_WANT_WRITE

    @_read
    def read(self, amount):
        self._needs = None
        try:
            return self._ssl.read(amount)
        except ssl.SSLError, e:
            if e.args[0] in (ssl.SSL_ERROR_WANT_WRITE,
                             ssl.SSL_ERROR_WANT_READ):
                self._needs = e.args[0]
                return ""
            raise e

    @_write
    def write(self, data):
        self._needs = None
        try:
            return self._ssl.write(data)
        except ssl.SSLError, e:
            if e.args[0] in (ssl.SSL_ERROR_WANT_WRITE,
                             ssl.SSL_ERROR_WANT_READ):
                self._needs = e.args[0]
                return 0
            raise e

    def close(self):
        _close(self._socket)

def _blocking(func):
    @threado.stream
    def wrapped(inner, self, *args, **keys):
        channel = threado.Channel()

        def _action():
            try:
                channel.finish(func(self, *args, **keys))
            except:
                channel.rethrow()
        self.send(_action)
        self.start()

        result = yield channel, self._stop_channel
        if self._stop_channel.has_result():
            if channel.has_result():
                result = channel.result()
            else:
                result = yield inner.thread(func, self, *args, **keys)
        inner.finish(result)
    return wrapped

class Socket(threado.GeneratorStream):
    def __init__(self, *args, **keys):
        threado.GeneratorStream.__init__(self)

        self._socket = socket.socket(*args, **keys)
        self._wrapped = _Base()
        self._closed = False
        self._stop_channel = threado.Channel()

    @_blocking
    def connect(self, *args, **keys):
        self._socket.setblocking(True)
        self._socket.connect(*args, **keys)
        self._socket.setblocking(False)

        self._wrapped = _PlainSocket(self._socket)

    @_blocking
    def ssl(self, *args, **keys):
        self._socket.setblocking(True)
        ssl_socket = ssl.wrap_socket(self._socket, *args, **keys)
        self._socket.setblocking(False)

        self._wrapped = _SSLSocket(self._socket, ssl_socket)

    @_blocking
    def close(self):
        self._closed = True

    def run(self):
        rfd, wfd = os.pipe()
        try:
            yield self.inner.thread(self._run, self.inner, rfd, wfd)
        finally:
            self._stop_channel.finish()

            with self.lock:
                os.write(wfd, "\x00")
                os.close(rfd)
                os.close(wfd)

            self._wrapped.close()

    def _socket_callback(self, wfd, _):
        with self.lock:
            try:
                os.write(wfd, "\x00")
            except OSError, ose:
                if ose.errno != errno.EBADF:
                    raise

    def _run(self, inner, rfd, wfd, chunk_size=2**16):
        data = ""

        while True:
            while not data:
                item = inner.next_raw()
                if item is None:
                    inner.add_message_callback(self._socket_callback, wfd)
                    break

                final, throw, args = item
                if throw:
                    type, exc, tb = args
                    raise type, exc, tb
                if final:
                    raise Finished(*args)

                next = threado.peel_args(args)
                if callable(next):
                    next()
                else:
                    data = next

            if self._closed:
                return

            wrapped = self._wrapped

            if (wrapped.needs_read() or
                (wrapped.can_read() and not wrapped.needs_write())):
                ifd = (rfd, self._wrapped)
            else:
                ifd = (rfd,)

            if (wrapped.needs_write() or
                (wrapped.can_write() and data and not wrapped.needs_read())):
                ofd = (self._wrapped,)
            else:
                ofd = ()

            ifd, ofd, _ = _do_select(ifd, ofd, ())
            if rfd in ifd:
                os.read(rfd, chunk_size)

            if self._wrapped in ifd:
                output = self._wrapped.read(chunk_size)
                inner.send(output)

            if self._wrapped in ofd:
                amount = self._wrapped.write(data)
                data = data[amount:]
