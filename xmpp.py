from __future__ import with_statement
import sys
import threado
import socket
import sockets
import callqueue
from jid import JID

import core
import disco
import muc
from xmlcore import Element, ElementParser, STREAM_NS
from core import STANZA_NS

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

def _resolve_with_getaddrinfo(host_or_domain, port_or_service):
    try:
        return socket.getaddrinfo(host_or_domain, 
                                  port_or_service, 
                                  socket.AF_INET, 
                                  socket.SOCK_STREAM, 
                                  socket.IPPROTO_TCP)
    except socket.gaierror:
        return list()

def _resolve_with_dig(domain, service):
    from subprocess import Popen, PIPE

    command = "dig", "+short", "srv", "_%s._tcp.%s" % (service, domain)
    try:
        popen = Popen(command, stdout=PIPE, stdin=PIPE, stderr=PIPE)
        lines = popen.communicate()[0].splitlines()
    except OSError:
        return list()

    results = list()
    for line in lines:
        try:
            priority, _, port, host = line.split()
            port = int(port)
            priority = int(priority)
        except ValueError:
            continue
        results.append((priority, host, port))

    return [(host, port) for (_, host, port) in sorted(results)]

class Event(object):
    @property
    def result(self):
        if self.success:
            return self.args
        type, exc, tb = self.args
        raise type, exc, tb

    def __init__(self, success, args):
        self.success = success
        self.args = args

class XMPP(threado.GeneratorStream):
    DEFAULT_XMPP_PORT = 5222

    def __init__(self, jid, password, host=None, port=None):
        threado.GeneratorStream.__init__(self, fast=True)

        self.elements = None
        self.listeners = set()
        self.final_event = None

        self.jid = JID(jid)
        self.password = password
        self.host = host
        self.port = port
        if self.host is not None and self.port is None:
            self.port = self.DEFAULT_XMPP_PORT

    def resolve_service(self):
        if self.host is not None:
            addresses = [(self.host, self.port)]
        else:
            domain = self.jid.domain
            service = "xmpp-client"
            results = list(_resolve_with_getaddrinfo(domain, service))
            if results:
                for result in results:
                    yield result
                return
            
            addresses = list(_resolve_with_dig(domain, service))
            if not addresses:
                addresses.append((self.jid.domain, self.DEFAULT_XMPP_PORT))

        any_resolved = False
        for host, port in addresses:
            for result in _resolve_with_getaddrinfo(host, port):
                any_resolved = True
                yield result

        if not any_resolved:
            raise core.XMPPError("could not resolve server address")

    @threado.stream
    def connect(inner, self):
        socket_error = None
        resolver = self.resolve_service()
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
        self.start()

    def run(self):
        try:
            while True:
                yield self.inner, self.elements

                for element in self.inner:
                    self.elements.send(element)

                for elements in self.elements:
                    event = Event(True, elements)
                    for callback in self.listeners:
                        callback(event)
        except:
            self.elements.rethrow()
            self.final_event = Event(False, sys.exc_info())
            for callback in self.listeners:
                callback(self.final_event)
            self.listeners.clear()
            raise

    def add_listener(self, func, *args, **keys):
        callback = threado.Callback(func, *args, **keys)
        def _add():
            if self.final_event:
                callback(self.final_event)
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
