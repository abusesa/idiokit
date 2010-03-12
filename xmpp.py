import sys
import timer
import threado
import socket
import sockets
import callqueue
from jid import JID

import core
import disco
import muc
import ping
from xmlcore import Element, ElementParser
from core import STREAM_NS, STANZA_NS

class StreamError(core.XMPPError):
    def __init__(self, element):
        core.XMPPError.__init__(self, "stream level error", 
                                element, core.STREAM_ERROR_NS)

RESTART = object()

@threado.stream_fast
def element_stream(inner, socket, domain):
    stream_element = Element("stream:stream")
    stream_element.set_attr("to", domain)
    stream_element.set_attr("xmlns", core.STANZA_NS)
    stream_element.set_attr("xmlns:stream", STREAM_NS)
    stream_element.set_attr("version", "1.0")

    parser = ElementParser()
    socket.send(stream_element.serialize_open())
    while True:
        yield inner, socket

        for element in inner:
            if element is RESTART:
                parser = ElementParser()
                socket.send(stream_element.serialize_open())
            else:
                socket.send(element.serialize())

        for data in socket:
            for element in parser.feed(data):
                if element.named("error", STREAM_NS):
                    raise StreamError(element)
                inner.send(element)

class Resolver(object):
    DEFAULT_XMPP_PORT = 5222

    def __init__(self, domain, forced_host=None, forced_port=None):
        self.host = forced_host
        self.port = forced_port if forced_port is None else self.DEFAULT_XMPP_PORT

    def resolve(self, domain, service="xmpp-client"):
        if self.host is not None:
            for result in self._getaddrinfo(self.host, self.port):
                yield result
            return

        any_resolved = False

        for resolver in (self._dig(domain, service),
                         self._getaddrinfo(domain, service),
                         self._getaddrinfo(domain, self.DEFAULT_XMPP_PORT)):
            for result in resolver:
                any_resolved = True
                yield result
            if any_resolved:
                return

        if not any_resolved:
            raise core.XMPPError("could not resolve server address")

    def _getaddrinfo(self, host_or_domain, port_or_service):
        try:
            for result in socket.getaddrinfo(host_or_domain, 
                                             port_or_service, 
                                             socket.AF_INET, 
                                             socket.SOCK_STREAM, 
                                             socket.IPPROTO_TCP):
                yield result
        except socket.gaierror:
            return

    def _dig(self, domain, service):
        from subprocess import Popen, PIPE

        command = "dig", "+short", "srv", "_%s._tcp.%s" % (service, domain)
        try:
            popen = Popen(command, stdout=PIPE, stdin=PIPE, stderr=PIPE)
            lines = popen.communicate()[0].splitlines()
        except OSError:
            return

        results = list()
        for line in lines:
            try:
                priority, _, port, host = line.split()
                port = int(port)
                priority = int(priority)
            except ValueError:
                continue
            results.append((priority, host, port))

        for _, host, port in sorted(results):
            for result in self._getaddrinfo(host, port):
                yield result

class XMPP(threado.GeneratorStream):
    def __init__(self, jid, password, host=None, port=None):
        threado.GeneratorStream.__init__(self)

        self.elements = None
        self.listeners = set()
        self.final_event = None

        self.jid = JID(jid)
        self.password = password

        self.resolver = Resolver(host, port)

    @threado.stream
    def connect(inner, self):
        socket_error = None
        resolver = self.resolver.resolve(self.jid.domain)

        while True:
            try:
                family, socktype, proto, _, address = yield inner.thread(resolver.next)
                sock = None
                socket_error = None
                try:
                    sock = sockets.Socket(family, socktype, proto)
                    yield inner.sub(sock.connect(address))
                except socket.error, socket_error:
                    if sock is not None:
                        yield inner.sub(sock.close())
                    continue
                break
            except StopIteration:
                break
        if socket_error is not None:
            raise socket_error

        self.elements = element_stream(sock, self.jid.domain)

        yield inner.sub(core.require_tls(self.elements))
        yield inner.sub(sock.ssl())
        self.elements.send(RESTART)

        yield inner.sub(core.require_sasl(self.elements, self.jid, 
                                          self.password))
        self.elements.send(RESTART)

        self.jid = yield inner.sub(core.require_bind_and_session(self.elements, 
                                                                 self.jid))
        self.core = core.Core(self)
        self.disco = disco.Disco(self)
        self.muc = muc.MUC(self)
        self.ping = ping.Ping(self)
        self.start()

    def run(self):
        yield self.inner.sub(self.elements 
                             | self._distribute() 
                             | self._keepalive())

    @threado.stream
    def _keepalive(inner, self, interval=60.0):
        while True:
            yield inner.sub(self.ping.ping(self.jid.bare()))
            yield inner, timer.sleep(interval)

    @threado.stream_fast
    def _distribute(inner, self):
        try:
            while True:
                yield inner

                for elements in inner:
                    for callback in self.listeners:
                        callback(True, elements)
        except:
            _, exc, tb = sys.exc_info()
            self.final_event = False, (exc, tb)

            for callback in self.listeners:
                callback(*self.final_event)
            self.listeners.clear()
            raise

    def add_listener(self, func, *args, **keys):
        callback = threado.Callback(func, *args, **keys)
        def _add():
            if self.final_event:
                callback(*self.final_event)
            else:
                self.listeners.add(callback)
        callqueue.add(_add)
        return callback

    def discard_listener(self, callback):
        callqueue.add(self.listeners.discard, callback)

@threado.stream
def connect(inner, *args, **keys):
    xmpp = XMPP(*args, **keys)
    yield inner.sub(xmpp.connect())
    inner.finish(xmpp)
