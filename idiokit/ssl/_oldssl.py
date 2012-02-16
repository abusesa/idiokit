from __future__ import with_statement, absolute_import

import socket as _socket

from .. import idiokit, socket, select, timer, threadpool

PROTOCOL_SSLv23 = PROTOCOL_SSLv3 = PROTOCOL_TLSv1 = object()

class SSLError(socket.SocketError):
    pass

@idiokit.stream
def _wrapped(ssl, timeout, func, *args, **keys):
    with socket.wrapped_socket_errors():
        for _, timeout in socket.countdown(timeout):
            try:
                result = func(*args, **keys)
            except _socket.sslerror, err:
                if err.args[0] == _socket.SSL_ERROR_WANT_READ:
                    yield select.select((ssl,), (), ())
                elif err.args[0] == _socket.SSL_ERROR_WANT_WRITE:
                    yield select.select((), (ssl,), ())
                else:
                    raise SSLError(*err.args)
            else:
                idiokit.stop(result)

@idiokit.stream
def wrap_socket(sock,
                keyfile=None,
                certfile=None,
                server_side=False,
                ssl_version=None,
                require_cert=False,
                ca_certs=None,
                timeout=None):
    if require_cert:
        raise SSLError(None, "module 'ssl' required for certificate verification")
    if ssl_version is not None:
        raise SSLError(None, "module 'ssl' required for setting the SSL version")
    if timeout is not None:
        raise SSLError(None, "module 'ssl' required for timeout support")

    raw_socket = sock._socket
    with socket.wrapped_socket_errors():
        try:
            raw_socket.setblocking(True)
            ssl = yield threadpool.thread(_socket.ssl, raw_socket, keyfile, certfile)
        finally:
            raw_socket.setblocking(False)
    idiokit.stop(_SSLSocket(raw_socket, ssl))

class _SSLSocket(object):
    def __init__(self, socket, ssl):
        self._socket = socket
        self._ssl = ssl

    @idiokit.stream
    def getpeercert(self, binary_form=False):
        yield timer.sleep(0.0)
        idiokit.stop("" if binary_form else {})

    @idiokit.stream
    def recv(self, bufsize, flags=0, timeout=None):
        if flags != 0:
            raise ValueError("flags not supported by SSL sockets")
        result = yield _wrapped(self._socket, timeout, self._ssl.read, bufsize)
        idiokit.stop(result)

    @idiokit.stream
    def send(self, data, flags=0, timeout=None):
        if flags != 0:
            raise ValueError("flags not supported by SSL sockets")
        result = yield _wrapped(self._socket, timeout, self._ssl.write, data)
        idiokit.stop(result)

    @idiokit.stream
    def sendall(self, string, flags=0, timeout=None, chunk_size=1024):
        offset = 0
        length = len(string)

        for _, timeout in socket.countdown(timeout):
            chunk = string[offset:offset+chunk_size]

            bytes = yield self.send(chunk, flags, timeout)

            offset += bytes
            if offset >= length:
                break
