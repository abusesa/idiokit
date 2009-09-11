import util
import threado
import sockets
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

import weakref

class XMPP(threado.ThreadedStream):
    def __init__(self, jid, password):
        threado.ThreadedStream.__init__(self)

        self.input = threado.Channel()
        self.send = self.input.send
        self.throw = self.input.throw
        self.rethrow = self.input.rethrow

        self.elements = None

        self.jid = JID(jid)
        self.password = password
        self.channels = weakref.WeakKeyDictionary()

    def connect(self):
        family, addr = util.resolve_service(self.jid.domain, "xmpp-client")

        socket = sockets.Socket(family)
        socket.connect(addr)
        self.elements = ElementStream(socket, self.jid.domain)
        
        core.require_tls(self.elements)
        socket.ssl()
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
