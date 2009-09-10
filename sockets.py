import threado
import socket
import collections
import threading
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

class Socket(threado.ThreadedStream):
    def __init__(self, *args, **keys):
        threado.ThreadedStream.__init__(self)
        self.pipe = os.pipe()
        self.socket = socket.socket(*args, **keys)
        self._ssl = None
        self.buffer = collections.deque()
        self.close_channel = threado.Channel()

    def _read(self, amount):
        return socket_wrapper(self.socket, True, self.socket.recv, amount)
    
    def _write(self, data):
        return socket_wrapper(self.socket, False, self.socket.send, data)

    @util.synchronized
    def send(self, data):
        self.buffer.append(data)

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

    def connect(self, *args, **keys):
        self.socket.setblocking(True)
        self.socket.connect(*args, **keys)
        self.socket.setblocking(False)
        self.start()

    def ssl(self):
        channel = threado.Channel()

        def _ssl():
            self.socket.setblocking(True)
            self._ssl = socket.ssl(self.socket)
            self.socket.setblocking(False)
            self._read = self._ssl_read
            self._write = self._ssl_write
            channel.send()

        self.send(_ssl)
        channel.next()

    def close(self):
        def _close():
            self.socket.setblocking(True)
            self.socket.shutdown(socket.SHUT_RDWR)
            self.socket.close()
            raise StopIteration()

        self.send(_close)
        self.close_channel.next()

    def _ssl_read(self, amount):
        return socket_wrapper(self.socket, True, ssl_wrapper, 
                              self.socket, self._ssl.read, amount)

    def _ssl_write(self, data):
        return socket_wrapper(self.socket, False, ssl_wrapper, 
                              self.socket, self._ssl.write, data)

    def stop(self):
        pass

    def run(self):
        try:
            self._run()
        finally:
            self.close_channel._finish(True, None)
            self._cleanup()

    def _run(self, chunk_size=2**16):
        pipe = self.pipe
        if pipe is None:
            return

        rfd, wfd = pipe
        while True:
            while self.buffer and callable(self.buffer[0]):
                func = self.buffer.popleft()
                func()

            ifd = [rfd, self.socket]
            ofd = [] if not self.buffer else [self.socket]

            ifd, ofd, _ = select.select(ifd, ofd, [])
            if rfd in ifd:
                os.read(rfd, 2**16)

            if self.socket in ifd:
                data = self._read(chunk_size)
                self.output.send(data)

            if self.socket in ofd and self.buffer and not callable(self.buffer[0]):
                data = self.buffer.popleft()
                amount = self._write(data)
                if len(data) > amount:
                    self.buffer.appendleft(data[amount:])
