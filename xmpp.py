import util
import threado
import socket
import sockets
import weakref
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

        self.text = None
        for text_element in element.children("text", core.STREAM_ERROR_NS): 
            self.text = text_element.text

RESTART = object()

@threado.stream
def element_stream(inner, socket, domain):
    stream_element = Element("stream:stream")
    stream_element.set_attr("to", domain)
    stream_element.set_attr("xmlns", core.STANZA_NS)
    stream_element.set_attr("xmlns:stream", STREAM_NS)
    stream_element.set_attr("version", "1.0")

    while True:
        parser = ElementParser()
        socket.send(stream_element.serialize_open())
                
        while True:
            data = yield inner, socket
            if data is RESTART:
                break

            if inner.was_source:
                socket.send(data.serialize())
                continue

            for element in parser.feed(data):
                if element.named("error", STREAM_NS):
                    raise StreamError(element)
                inner.send(element)

def _resolve_with_getaddrinfo(host_or_domain, port_or_service):
    try:
        return socket.getaddrinfo(host_or_domain, 
                                  port_or_service, 
                                  0, 
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

class XMPP(threado.ThreadedStream):
    DEFAULT_XMPP_PORT = 5222

    def __init__(self, jid, password, host=None, port=None):
        threado.ThreadedStream.__init__(self)

        self.elements = None
        self.channels = weakref.WeakKeyDictionary()

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

    def connect(self):
        socket_error = None

        for family, socktype, proto, _, address in self.resolve_service():
            sock = None
            socket_error = None
            try:
                sock = sockets.Socket(family, socktype, proto)
                sock.connect(address)
            except socket.error, socket_error:
                if sock is not None:
                    sock.close()
                continue
            break
        if socket_error is not None:
            raise socket_error

        self.elements = element_stream(sock, self.jid.domain)
        
        core.require_tls(self.elements)
        sock.ssl()
        self.elements.send(RESTART)
        
        core.require_sasl(self.elements, self.jid, self.password)
        self.elements.send(RESTART)
        
        self.jid = core.require_bind_and_session(self.elements, self.jid)
        self.core = core.Core(self)
        self.disco = disco.Disco(self)
        self.muc = muc.MUC(self)
        self.start()

    def run(self):
        try:
            for data in self.inner + self.elements:
                if self.inner.was_source:
                    self.elements.send(data)
                    continue

                for channel_ref in self.channels.keyrefs():
                    channel = channel_ref()
                    if channel is None:
                        continue
                    for element in data:
                        channel.send(element)
        except:
            self.elements.rethrow()
            for channel in self.channels:
                channel.rethrow()
            raise

    def stream(self):
        channel = threado.Channel()
        self.channels[channel] = None
        return channel + self
