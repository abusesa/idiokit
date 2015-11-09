from .. import idiokit, socket, ssl, xmlcore, timer
from . import core, disco, muc, ping, _resolve
from .jid import JID


class StreamError(core.XMPPError):
    def __init__(self, element):
        core.XMPPError.__init__(self, "stream level error", element, core.STREAM_ERROR_NS)


class Restart(Exception):
    pass


@idiokit.stream
def throw(exception):
    yield timer.sleep(0.0)
    raise exception


def element_stream(sock, domain, timeout, ws_ping_interval=10.0):
    @idiokit.stream
    def write():
        stream_element = xmlcore.Element("stream:stream")
        stream_element.set_attr("to", domain)
        stream_element.set_attr("xmlns", core.STANZA_NS)
        stream_element.set_attr("xmlns:stream", core.STREAM_NS)
        stream_element.set_attr("version", "1.0")
        yield sock.sendall(stream_element.serialize_open(), timeout=timeout)

        while True:
            try:
                element = yield timer.timeout(ws_ping_interval, idiokit.next())
            except timer.Timeout:
                # Send a whitespace heartbeat when no XML output data has
                # appeared after ws_ping_interval seconds of waiting.
                yield sock.sendall(" ", timeout=timeout)
            else:
                yield sock.sendall(element.serialize(), timeout=timeout)

    @idiokit.stream
    def read():
        parser = xmlcore.ElementParser()

        try:
            while True:
                data = yield sock.recv(65536)
                if not data:
                    raise core.XMPPError("connection lost")

                for element in parser.feed(data):
                    if element.named("error", core.STREAM_NS):
                        raise StreamError(element)
                    yield idiokit.send(element)
        except Restart:
            pass

    return idiokit.pipe(write(), read())


@idiokit.stream
def _get_socket(domain, host, port, timeout):
    results = yield _resolve.resolve(domain, host, port)

    error = core.XMPPError("could not resolve server address")
    for family, host, port in results:
        try:
            sock = socket.Socket(family)
        except socket.SocketError as error:
            continue

        try:
            yield sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            yield sock.connect((host, port), timeout=timeout)
        except socket.SocketError as error:
            yield sock.close()
            continue

        idiokit.stop(sock)

    raise error


@idiokit.stream
def _init_ssl(sock, require_cert, ca_certs, certfile, keyfile, hostname, timeout):
    sock = yield ssl.wrap_socket(
        sock,
        require_cert=require_cert,
        ca_certs=ca_certs,
        certfile=certfile,
        keyfile=keyfile,
        timeout=timeout
    )
    if require_cert:
        cert = yield sock.getpeercert()
        ssl.match_hostname(cert, hostname)
    idiokit.stop(sock)


@idiokit.stream
def connect(
    jid,
    password,
    host=None,
    port=None,
    ssl_verify_cert=True,
    ssl_ca_certs=None,
    ssl_certfile=None,
    ssl_keyfile=None,
    timeout=120.0
):
    jid = JID(jid)
    sock = yield _get_socket(jid.domain, host, port, timeout)

    elements = element_stream(sock, jid.domain, timeout=timeout)
    yield core.require_tls(elements)
    yield throw(Restart()) | elements | idiokit.consume()

    hostname = jid.domain if host is None else host
    sock = yield _init_ssl(sock, ssl_verify_cert, ssl_ca_certs, ssl_certfile, ssl_keyfile, hostname, timeout)

    elements = element_stream(sock, jid.domain, timeout=timeout)
    yield core.require_sasl(elements, jid, password)
    yield throw(Restart()) | elements | idiokit.consume()

    elements = element_stream(sock, jid.domain, timeout=timeout)
    jid = yield core.require_bind_and_session(elements, jid)
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
