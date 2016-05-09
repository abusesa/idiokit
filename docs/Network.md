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
        yield conn.sendall(data)


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
        yield sock.sendall(line)


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

```python
import sys
import idiokit
import idiokit.http.client


@idiokit.stream
def main(url):
    request = yield idiokit.http.client.request("GET", url)
    response = yield request.finish()

    while True:
        data = yield response.read(1024)
        if not data:
            break
        sys.stdout.write(data)
        sys.stdout.flush()


idiokit.main_loop(main("https://github.com"))
```

Dealing with unix domain sockets:

```python
client = idiokit.http.client.Client()
client.mount("http+unix://", idiokit.http.client.HTTPUnixAdapter())
request = yield client.request("GET", "http+unix://%2Fpath%2Fto%2Fsocket/")
```

### HTTP Server

```python
import httplib

import idiokit
from idiokit.http.server import serve_http


@idiokit.stream
def handler(addr, request, response):
    if request.method != "POST":
        yield response.write_status(httplib.METHOD_NOT_ALLOWED)
        return

    if request.uri != "/echo":
        yield response.write_status(httplib.TEMPORARY_REDIRECT)
        yield response.write_headers({
            "location": "/echo"
        })
        return

    while True:
        data = yield request.read(512)
        print data
        if not data:
            break
        yield response.write(data)


idiokit.main_loop(serve_http(handler, "localhost", 8080))
```

```console
$ curl -L -d 'Hello, World!' http://localhost:8080/
Hello, World!
```

## idiokit.dns

```python
import idiokit
from idiokit import dns


@idiokit.stream
def output(record_type, resolver):
    try:
        records = yield resolver
    except (ValueError, dns.DNSError):
        return

    print record_type, "records:"
    for result in records:
        print "   ", result


@idiokit.stream
def main(name):
    yield output("CNAME", dns.cname(name))
    yield output("A", dns.a(name))
    yield output("AAAA", dns.aaaa(name))
    yield output("TXT", dns.txt(name))
    yield output("MX", dns.mx(name))
    yield output("PTR", dns.ptr(name))


idiokit.main_loop(main("www.github.com"))
```

## idiokit.xmpp

```python
import getpass
import idiokit
from idiokit.xmpp import connect, jid


@idiokit.stream
def prevent_feedback_loop(own_jid):
    while True:
        elements = yield idiokit.next()

        for message in elements.named("message").with_attrs("from"):
            sender = jid.JID(message.get_attr("from"))
            if sender == own_jid:
                continue

            for body in message.children("body"):
                yield idiokit.send(body)


@idiokit.stream
def echobot(username, password, roomname):
    xmpp = yield connect(username, password)
    room = yield xmpp.muc.join(roomname)

    yield room | prevent_feedback_loop(room.jid) | room


username = raw_input("Username: ")
password = getpass.getpass()
roomname = raw_input("Channel: ")
idiokit.main_loop(echobot(username, password, roomname))
```

## idiokit.irc

```python
import idiokit
from idiokit.irc import connect


@idiokit.stream
def filter_messages(own_nick, channel):
    while True:
        prefix, command, params = yield idiokit.next()
        if command != "PRIVMSG":
            continue
        if not params or params[0] != channel:
            continue
        yield idiokit.send(command, *params)


@idiokit.stream
def echobot(host, port, channel):
    irc = yield connect(host, port, "echobot")
    yield irc.join(channel)
    yield irc | filter_messages(irc.nick, channel) | irc


host = raw_input("Host: ")
port = int(raw_input("Port: "))
channel = raw_input("Channel: ")
idiokit.main_loop(echobot(host, port, channel))
```
