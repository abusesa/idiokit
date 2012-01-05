from __future__ import absolute_import

import socket

from .. import idiokit, sockets, xmlcore, timer, threadpool
from . import resolve
from . import core, disco, muc, ping
from .jid import JID

class StreamError(core.XMPPError):
    def __init__(self, element):
        core.XMPPError.__init__(self, "stream level error",
                                element, core.STREAM_ERROR_NS)

class Restart(idiokit.Signal):
    pass

@idiokit.stream
def element_stream(socket, domain):
    parser = xmlcore.ElementParser()

    stream_element = xmlcore.Element("stream:stream")
    stream_element.set_attr("to", domain)
    stream_element.set_attr("xmlns", core.STANZA_NS)
    stream_element.set_attr("xmlns:stream", core.STREAM_NS)
    stream_element.set_attr("version", "1.0")

    yield socket.write(stream_element.serialize_open())

    @idiokit.stream
    def write():
        while True:
            element = yield idiokit.next()
            yield socket.writeall(element.serialize())

    @idiokit.stream
    def read():
        while True:
            data = yield socket.read()
            for element in parser.feed(data):
                if element.named("error", core.STREAM_NS):
                    raise StreamError(element)
                yield idiokit.send(element)

    try:
        yield write() | read()
    except Restart:
        pass

@idiokit.stream
def _get_socket(domain, host, port):
    resolver = resolve.Resolver(host, port)
    error = core.XMPPError("could not resolve server address")

    results = iter(resolver.resolve(domain))

    while True:
        try:
            item = yield threadpool.thread(results.next)
        except StopIteration:
            raise error

        family, socktype, proto, _, addr = item
        try:
            sock = sockets.Socket(family, socktype, proto)
        except socket.error, error:
            continue

        try:
            yield sock.connect(addr)
        except socket.error, error:
            yield sock.close()
            continue

        idiokit.stop(sock)

@idiokit.stream
def connect(jid, password,
            host=None, port=None,
            rate_limiter=None,
            ssl_verify_cert=True,ssl_ca_certs=None):
    jid = JID(jid)
    sock = yield _get_socket(jid.domain, host, port)

    elements = element_stream(sock, jid.domain)
    yield core.require_tls(elements)
    yield elements.throw(Restart)

    identity = host if host is not None else jid.domain
    yield sock.ssl(verify_cert=ssl_verify_cert,
                   ca_certs=ssl_ca_certs,
                   identity=identity)
    elements = element_stream(sock, jid.domain)

    yield core.require_sasl(elements, jid, password)
    yield elements.throw(Restart)
    elements = element_stream(sock, jid.domain)

    jid = yield core.require_bind_and_session(elements, jid)

    if rate_limiter is not None:
        elements = idiokit.pipe(rate_limiter, elements)
    idiokit.stop(XMPP(jid, elements))

class XMPP(idiokit.Proxy):
    def __init__(self, jid, elements):
        idiokit.Proxy.__init__(self, elements)
        idiokit.pipe(self._keepalive(), elements)

        self.jid = jid

        self.core = core.Core(self)
        self.disco = disco.Disco(self)
        self.muc = muc.MUC(self)
        self.ping = ping.Ping(self)

    @idiokit.stream
    def _keepalive(self, interval=60.0):
        while True:
            yield self.ping.ping(self.jid.bare())
            yield timer.sleep(interval)
