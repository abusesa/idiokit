import util
import threado
import socket
import sockets
import weakref
from jid import JID

import core
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

class RestartElementStream(BaseException):
    pass

class ElementStream(threado.ThreadedStream):
    def __init__(self, socket, domain):
        threado.ThreadedStream.__init__(self)

        self.socket = socket
        self.domain = domain

        self.input = threado.Channel()
        self.send = self.input.send
        self.throw = self.input.throw
        self.rethrow = self.input.rethrow
        self.start()

    def restart(self):
        self.input.throw(RestartElementStream())

    def _run(self):
        stream_element = Element("stream:stream")
        stream_element.set_attr("to", self.domain)
        stream_element.set_attr("xmlns", core.STANZA_NS)
        stream_element.set_attr("xmlns:stream", STREAM_NS)
        stream_element.set_attr("version", "1.0")
        self.socket.send(stream_element.serialize_open())

        parser = ElementParser()
        for data in threado.any_of(self.input, self.socket):
            if threado.source() is self.socket:
                # print "->", repr(data)
                elements = parser.feed(data)
                for element in elements:
                    if element.filter("error", STREAM_NS):
                        raise StreamError(element)
                    self.output.send(element)
            else:
                data = data.serialize()
                # print "<-", repr(data)
                self.socket.send(data)

    def run(self):
        while True:
            try:
                self._run()
            except RestartElementStream:
                pass

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

        self.input = threado.Channel()
        self.send = self.input.send
        self.throw = self.input.throw
        self.rethrow = self.input.rethrow

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

        self.elements = ElementStream(sock, self.jid.domain)
        
        core.require_tls(self.elements)
        sock.ssl()
        self.elements.restart()
        
        core.require_sasl(self.elements, self.jid, self.password)
        self.elements.restart()
        
        self.jid = core.require_bind_and_session(self.elements, self.jid)
        self.core = core.Core(self)
        self.muc = muc.MUC(self)
        self.start()

    def run(self):
        try:
            for data in threado.any_of(self.input, self.elements):
                if threado.source() is self.elements:
                    for channel_ref in self.channels.keyrefs():
                        channel = channel_ref()
                        if channel is None:
                            continue
                        for element in data:
                            channel.send(element)
                else:
                    self.elements.send(data)
        except:
            self.elements.rethrow()
            for channel in self.channels:
                channel.rethrow()
            raise

    def stream(self):
        channel = threado.Channel()
        self.channels[channel] = None
        return threado.any_of(channel, self)
