import threado
import socket
import collections
import select
import os
import util
import errno

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
    def _blocking(self, *args, **keys):
        channel = threado.Channel()

        def _action():
            try:
                channel.send(func(self, *args, **keys))
            except:
                channel.rethrow()
        self.send(_action)
        self.start()

        for result in channel + self.stop_channel:
            return result
        return _action()
    return _blocking

class Socket(threado.ThreadedStream):
    def __init__(self, *args, **keys):
        threado.ThreadedStream.__init__(self)
        self.pipe = os.pipe()
        self.socket = socket.socket(*args, **keys)
        self.buffer = collections.deque()

        self._read = None
        self._write = None
        self.closed = False
        self.stop_channel = threado.Channel()

        self.inner.register(self._callback)

    @blocking_action
    @util.synchronized
    def _throw(self, type, exc, tb):
        raise type, exc, tb

    @util.synchronized
    def _callback(self, source):
        event = source.consume()

        try:
            data = event.value
        except:
            self._throw(*sys.exc_info())
        else:
            self.buffer.append(data)

        if event.final:
            self.close()
        else:
            source.register(self._callback)

        if self.pipe is not None:
            rfd, wfd = self.pipe
            os.write(wfd, "\x00")

    @util.synchronized
    def _cleanup(self):
        if self.pipe is None:
            return

        rfd, wfd = self.pipe
        os.write(wfd, "\x00")        
        os.close(rfd)
        os.close(wfd)

        self.pipe = None

    @blocking_action
    @util.synchronized
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
    @util.synchronized
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
    @util.synchronized
    def close(self):
        try:
            self.socket.setblocking(True)
            self.socket.shutdown(socket.SHUT_RDWR)
        except socket.error:
            pass
        self.socket.close()
        self.closed = True

    def run(self):
        try:
            self._run()
        finally:
            self.stop_channel.finish()
            self._cleanup()

    def _run(self, chunk_size=2**16):
        pipe = self.pipe
        if pipe is None:
            return

        rfd, wfd = pipe
        while not self.closed:
            if self.buffer and callable(self.buffer[0]):
                func = self.buffer.popleft()
                func()
                continue

            ifd = [rfd, self.socket] if self._read else [rfd]
            ofd = [self.socket] if (self._write and self.buffer) else []

            ifd, ofd, _ = select.select(ifd, ofd, [])
            if rfd in ifd:
                os.read(rfd, 2**16)

            if self.socket in ifd:
                data = self._read(chunk_size)
                self.inner.send(data)

            if (self.socket in ofd 
                and self.buffer 
                and not callable(self.buffer[0])):
                data = self.buffer.popleft()
                amount = self._write(data)
                if len(data) > amount:
                    self.buffer.appendleft(data[amount:])
