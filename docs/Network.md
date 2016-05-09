# Network Programming

## idiokit.socket

### Echo Server

```python
import idiokit
from idiokit import socket


@idiokit.stream
def server(host, port):
    sock = socket.Socket()
    yield sock.bind((host, port))
    yield sock.listen(1)

    conn, addr = yield sock.accept()
    while True:
        data = yield conn.recv(512)
        if not data:
            break
        yield conn.send(data)


idiokit.main_loop(server("localhost", 8080))
```

### Echo Client

```python
import sys
import idiokit
from idiokit import socket, select


@idiokit.stream
def client(host, port):
    sock = socket.Socket()
    yield sock.connect((host, port))
    yield write(sock) | read(sock)


@idiokit.stream
def write(sock):
    while True:
        yield select.select((sys.stdin,), (), ())
        line = sys.stdin.readline()
        yield sock.send(line)


@idiokit.stream
def read(sock):
    while True:
        data = yield sock.recv(1024)
        if not data:
            break
        sys.stdout.write(data)
        sys.stdout.flush()


idiokit.main_loop(client("localhost", 8080))
```

## idiokit.ssl

```python
import sys
import idiokit
from idiokit import socket, ssl


@idiokit.stream
def client(host, port):
    sock = socket.Socket()
    yield sock.connect((host, port))

    ssl_sock = yield ssl.wrap_socket(sock, require_cert=True)
    cert = yield ssl_sock.getpeercert()
    ssl.match_hostname(cert, host)

    yield ssl_sock.sendall("GET / HTTP/1.0\r\n")
    yield ssl_sock.sendall("Host: {0}\r\n\r\n".format(host))
    while True:
        data = yield ssl_sock.recv(1024)
        if not data:
            break
        sys.stdout.write(data)
        sys.stdout.flush()


idiokit.main_loop(client("github.com", 443))
```

Run with `python example.py` and observe the HTML data pouring in. Now change the last line to:

```python
idiokit.main_loop(client("192.30.252.130", 443))
```

```console
$ python example.py
Traceback (most recent call last):
  File "example.py", line 25, in <module>
    idiokit.main_loop(client("192.30.252.130", 443))
  File "/usr/local/lib/python2.7/site-packages/idiokit/idiokit.py", line 354, in _next
    next = require_stream(self._gen.send(peel_args(args)))
  File "example.py", line 13, in client
    ssl.match_hostname(cert, host)
  File "/usr/local/lib/python2.7/site-packages/idiokit/ssl.py", line 373, in match_hostname
    raise SSLCertificateError(message)
idiokit.ssl.SSLCertificateError: hostname '192.30.252.130' doesn't match 'github.com' or 'www.github.com'
```

## idiokit.http

### HTTP Client

### HTTP Server

## idiokit.dns

## idiokit.xmpp

## idiokit.irc
