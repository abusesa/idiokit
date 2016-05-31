# Network Programming

The original proposition for idiokit was to make writing complex XMPP bots easier (`idiokit.xmpp`). By necessity idiokit had to support basic socket programming (`idiokit.socket`,o `idiokit.ssl`) from the start, but has also grown other handy capabilities along the way (`idiokit.http`, `idiokit.dns`, `idiokit.irc`).


## Plain Sockets (idiokit.socket)

`idiokit.socket` has been built to mimic the structure of Python's native `socket` module. Or at least the parts of it that deal directly with sockets: `socket.getaddrinfo` and such do not have counterparts in `idiokit.socket`.

You create a new socket object with `idiokit.socket.Socket(...)`, and those objects offer almost all methods native socket objects do, just asynchronously versions of them. Let's build echo client and server along the lines of the [standard library example](https://docs.python.org/2/library/socket.html#example). Compare and contrast how the `idiokit.socket` methods map to the native `socket` ones.

### Echo Server

```python
import idiokit
from idiokit import socket


@idiokit.stream
def server(host, port):
    s = socket.Socket(socket.AF_INET, socket.SOCK_STREAM)
    yield s.bind((host, port))
    yield s.listen(1)

    conn, addr = yield s.accept()
    print "Connected by:", addr
    while True:
        data = yield conn.recv(1024, timeout=15.0)
        if not data:
            break
        yield conn.sendall(data, timeout=15.0)
    yield conn.close()


idiokit.main_loop(server("localhost", 8080))
```

The above code demonstrates an additional feature: Timeouts can be set per method call. For example the line `data = yield conn.recv(1024, timeout=15.0)` will wait for only for 15 seconds and raise `socket.SocketTimeout` if the server can't receive any input within the time limit. The `timeout` keyword argument can be passed to many `idiokit.socket` methods like `connect`, `recv`, `send` and `sendall`.

### Echo Client

```python
import idiokit
from idiokit import socket


@idiokit.stream
def client(host, port):
    s = socket.Socket(socket.AF_INET, socket.SOCK_STREAM)

    yield s.connect((host, port))
    yield s.sendall("Hello, World!")
    data = yield s.recv(1024)
    yield s.close()
    print "Received", repr(data)


idiokit.main_loop(client("localhost", 8080))
```


## SSL / TLS Sockets (idiokit.ssl)

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


## Streaming HTTP (idiokit.http)

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
        if not data:
            break
        yield response.write(data)


idiokit.main_loop(serve_http(handler, "localhost", 8080))
```

```console
$ curl -L -d 'Hello, World!' http://localhost:8080/
Hello, World!
```


## Asynchronous DNS (idiokit.dns)

```python
import idiokit
from idiokit import dns

@idiokit.stream
def output(record_type, query, resolver):
    try:
        records = yield resolver
    except (ValueError, dns.DNSError):
        return

    print record_type, "records for", query
    for result in records:
        print "   ", result


@idiokit.stream
def main():
    name = "www.github.com"

    yield output("CNAME", name, dns.cname(name))
    yield output("A", name, dns.a(name))
    yield output("AAAA", name, dns.aaaa(name))
    yield output("TXT", name, dns.txt(name))
    yield output("MX", name, dns.mx(name))

    name = "131.252.30.192.in-addr.arpa"
    yield output("PTR", name, dns.ptr(name))

    ip = "192.30.252.131"
    yield output("PTR (using reverse_lookup() helper)", ip, dns.reverse_lookup(ip))


idiokit.main_loop(main())
```


## XMPP (idiokit.xmpp)

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


## IRC (idiokit.irc)

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
