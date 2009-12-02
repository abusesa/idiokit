from __future__ import with_statement
import threado
import socket
import select
import os
import errno
import threading

from socket import error

def check_connection(sock):
    ifd, _, _ = select.select([sock], [], [], 0.0)
    if ifd and not sock.recv(1, socket.MSG_PEEK):
        raise socket.error(errno.ECONNRESET, os.strerror(errno.ECONNRESET))

def ssl_wrapper(sock, func, *args, **keys):
    while True:
        try:
            return func(*args, **keys)
        except socket.sslerror, se:
            if se.args[0] == socket.SSL_ERROR_WANT_WRITE:
                select.select([], [sock], [])
            elif se.args[0] == socket.SSL_ERROR_WANT_READ:
                select.select([sock], [], [])
                check_connection(sock)
            else:
                raise

ALLOWED_SOCKET_ERRNOS = set([errno.EINTR, errno.ENOBUFS, 
                             errno.EAGAIN, errno.EWOULDBLOCK])

def socket_wrapper(sock, read, func, *args, **keys):
    try:
        data = func(*args, **keys)
        if read and not data:
            check_connection(sock)
        return data
    except socket.sslerror:
        raise
    except socket.error, se:
        if se.args[0] not in ALLOWED_SOCKET_ERRNOS:
            raise
        elif read:
            return ""
        else:
            return 0

def blocking_action(func):
    @threado.stream
    def _blocking(inner, self, *args, **keys):
        channel = threado.Channel()

        def _action():
            try:
                channel.finish(func(self, *args, **keys))
            except:
                channel.rethrow()
        self.send(_action)
        self.start()

        result = yield channel, self.stop_channel
        if self.stop_channel.was_source:
            if channel.has_result():
                result = channel.result()
            else:
                result = yield inner.thread(func, self, *args, **keys)
        inner.finish(result)
                
    return _blocking

class Socket(threado.GeneratorStream):
    def __init__(self, *args, **keys):
        threado.GeneratorStream.__init__(self)

        self.socket = socket.socket(*args, **keys)

        self._read = None
        self._write = None
        self.closed = False
        self.stop_channel = threado.Channel()

    @blocking_action
    def connect(self, *args, **keys):
        def _socket_read(amount):
            return socket_wrapper(self.socket, True, self.socket.recv, amount)
        def _socket_write(data):
            return socket_wrapper(self.socket, False, self.socket.send, data)
        self.socket.setblocking(True)
        self.socket.connect(*args, **keys)
        self.socket.setblocking(False)
        self._read = _socket_read
        self._write = _socket_write

    @blocking_action
    def ssl(self):
        def _ssl_read(amount):
            return socket_wrapper(self.socket, True, ssl_wrapper, 
                                  self.socket, ssl.read, amount)
        def _ssl_write(data):
            return socket_wrapper(self.socket, True, ssl_wrapper, 
                                  self.socket, ssl.write, data)
            
        self.socket.setblocking(True)
        ssl = socket.ssl(self.socket)
        self.socket.setblocking(False)
        self._read = _ssl_read
        self._write = _ssl_write

    @blocking_action
    def close(self):
        self.closed = True

    def run(self):
        rfd, wfd = os.pipe()
        try:
            yield self.inner.thread(self._run, self.inner, rfd, wfd)
        finally:
            self.stop_channel.finish()

            with self.lock:
                os.write(wfd, "\x00")        
                os.close(rfd)
                os.close(wfd)

            try:
                self.socket.setblocking(True)
                self.socket.shutdown(socket.SHUT_RDWR)
            except socket.error:
                pass
            self.socket.close()

    def _socket_callback(self, wfd, _):
        with self.lock:
            try:
                os.write(wfd, "\x00")
            except OSError, ose:
                if ose.errno != errno.EBADF:
                    raise

    def _run(self, inner, rfd, wfd, chunk_size=2**16):
        data = None

        while not self.closed:
            if data is None:
                try:
                    next = inner.next()
                except threado.Empty:
                    inner.add_message_callback(self._socket_callback, wfd)
                else:
                    if not callable(next):
                        data = next
                    else:
                        next()
                        continue

            ifd = [rfd, self.socket] if self._read else [rfd]
            ofd = [self.socket] if (self._write and data is not None) else []

            ifd, ofd, _ = select.select(ifd, ofd, [])
            if rfd in ifd:
                os.read(rfd, chunk_size)
                
            if self.socket in ifd:
                output = self._read(chunk_size)
                inner.send(output)
                    
            if self.socket in ofd:
                amount = self._write(data)
                if len(data) > amount:
                    data = data[amount:]
                else:
                    data = None
