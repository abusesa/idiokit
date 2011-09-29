from __future__ import with_statement

import uuid
import base64
import contextlib

import threado
from jid import JID
from xmlcore import Query, Element

STREAM_NS = "http://etherx.jabber.org/streams"
STREAM_ERROR_NS = "urn:ietf:params:xml:ns:xmpp-streams"
STANZA_ERROR_NS = "urn:ietf:params:xml:ns:xmpp-stanzas"
SASL_NS = "urn:ietf:params:xml:ns:xmpp-sasl"
BIND_NS = "urn:ietf:params:xml:ns:xmpp-bind"
SESSION_NS = "urn:ietf:params:xml:ns:xmpp-session"
STANZA_NS = "jabber:client"
STARTTLS_NS = "urn:ietf:params:xml:ns:xmpp-tls"

class XMPPError(Exception):
    def __init__(self, message, elements=Query(), ns=STANZA_ERROR_NS):
        self.type = None
        self.condition = None
        self.text = None

        for element in elements:
            self.type = element.get_attr("type", None)
            for child in element.children(ns=ns):
                self.condition = child.name
                break
            for child in element.children("text", ns):
                self.text = child.text
                break
            break

        Exception.__init__(self, message)

    def __str__(self):
        extra = self.text
        if extra is None and self.condition is not None:
            extra = self.condition.replace("-", " ")
        if extra is None:
            return self.args[0]
        return self.args[0] + " (%s)" % extra

@threado.stream
def _iq(inner, send, stream, type, query, **attrs):
    uid = uuid.uuid4().hex[:16]
    attrs["id"] = uid

    iq = Element("iq", type=type, **attrs)
    iq.add(query)
    send(iq)

    while True:
        source, elements = yield threado.any(inner, stream)
        if inner is source:
            continue

        for element in elements.named("iq").with_attrs(id=uid):
            type = element.get_attr("type", None)
            if type == "result":
                inner.finish(element)
            elif type == "error":
                errors = element.children("error", STANZA_NS)
                raise XMPPError("iq failed", errors)
            elif type is None:
                raise XMPPError("type attribute missing for iq stanza")

@threado.stream
def require_features(inner, stream):
    while True:
        source, elements = yield threado.any(inner, stream)
        if stream is source:
            break

    features = elements.named("features", STREAM_NS)
    if not features:
        raise XMPPError("feature list expected")
    inner.finish(features)

@threado.stream
def require_tls(inner, stream):
    features = yield inner.sub(require_features(stream))

    tls = features.children("starttls", STARTTLS_NS)
    if not tls:
        raise XMPPError("server does not support starttls")
    yield inner.sub(starttls(stream))

@threado.stream
def require_sasl(inner, stream, jid, password):
    features = yield inner.sub(require_features(stream))

    mechanisms = features.children("mechanisms", SASL_NS).children("mechanism")
    for mechanism in mechanisms:
        if mechanism.text != "PLAIN":
            continue
        result = yield inner.sub(sasl_plain(stream, jid, password))
        inner.finish(result)
    raise XMPPError("server does not support plain sasl")

@threado.stream
def require_bind_and_session(inner, stream, jid):
    features = yield inner.sub(require_features(stream))

    if not features.children("bind", BIND_NS):
        raise XMPPError("server does not support resource binding")
    if not features.children("session", SESSION_NS):
        raise XMPPError("server does not support sessions")

    jid = yield inner.sub(bind_resource(stream, jid.resource))
    yield inner.sub(session(stream))
    inner.finish(jid)

@threado.stream
def starttls(inner, stream):
    starttls = Element("starttls", xmlns=STARTTLS_NS)
    stream.send(starttls)

    while True:
        source, elements = yield threado.any(inner, stream)
        if inner is source:
            continue

        if elements.named("failure", STARTTLS_NS):
            raise XMPPError("starttls failed", elements)
        if elements.named("proceed", STARTTLS_NS):
            break

@threado.stream
def sasl_plain(inner, stream, jid, password):
    password = unicode(password).encode("utf-8")
    data = "\x00" + jid.node.encode("utf-8") + "\x00" + password

    auth = Element("auth", xmlns=SASL_NS, mechanism="PLAIN")
    auth.text = base64.b64encode(data)
    stream.send(auth)

    while True:
        source, elements = yield threado.any(inner, stream)
        if inner is source:
            continue

        if elements.named("failure", SASL_NS):
            raise XMPPError("authentication failed", elements)
        if elements.named("success", SASL_NS):
            break

@threado.stream
def bind_resource(inner, stream, resource=None):
    bind = Element("bind", xmlns=BIND_NS)
    if resource is not None:
        element = Element("resource")
        element.text = resource
        bind.add(element)
    result = yield inner.sub(_iq(stream.send, stream, "set", bind))

    for jid in result.children("bind", BIND_NS).children("jid"):
        inner.finish(JID(jid.text))
    raise XMPPError("no jid supplied by bind")

@threado.stream
def session(inner, stream):
    session = Element("session", xmlns=SESSION_NS)
    yield inner.sub(_iq(stream.send, stream, "set", session))

def _stream_callback(channel, success, value):
    if success:
        channel.send(value)
    else:
        channel.throw(*value)

@contextlib.contextmanager
def _stream(xmpp):
    channel = threado.Channel()
    callback = xmpp.add_listener(_stream_callback, channel)
    try:
        yield channel
    finally:
        xmpp.discard_listener(callback)

class Core(object):
    VALID_ERROR_TYPES = set(["cancel", "continue", "modify", "auth", "wait"])

    def __init__(self, xmpp):
        self.xmpp = xmpp
        self.iq_handlers = list()
        self.xmpp.add_listener(self._iq_dispatcher)

    def add_iq_handler(self, handler, *args, **keys):
        self.iq_handlers.append((handler, args, keys))

    def _iq_dispatcher(self, success, elements):
        if not success:
            return

        for iq in elements.named("iq", STANZA_NS).with_attrs("type"):
            if iq.get_attr("type").lower() not in ("get", "set"):
                continue

            for handler, args, keys in self.iq_handlers:
                payload = iq.children(*args, **keys)
                if payload and handler(iq, list(payload)[0]):
                    break
            else:
                error = self.build_error("cancel", "service-unavailable")
                self.iq_error(iq, error)

    def build_error(self, type, condition, text=None, special=None):
        if type not in self.VALID_ERROR_TYPES:
            expected = "/".join(self.VALID_ERROR_TYPES)
            message = "wrong error type (got '%s', expected '%s')"
            raise XMPPError(message % (type, expected))

        error = Element("error", type=type)
        error.add(Element(condition, xmlns=STANZA_ERROR_NS))
        if text is not None:
            text_element = Element("text", xmlns=STANZA_ERROR_NS)
            text_element.text = text
            error.add(text_element)
        if special is not None:
            error.add(special)
        return error

    def message(self, to, *payload, **attrs):
        attrs["to"] = to
        message = Element("message", **attrs)
        message.add(*payload)
        self.xmpp.send(message)

    def presence(self, *payload, **attrs):
        presence = Element("presence", **attrs)
        presence.add(*payload)
        self.xmpp.send(presence)

    @threado.stream
    def iq_get(inner, self, payload, **attrs):
        with _stream(self.xmpp) as stream:
            result = yield inner.sub(_iq(self.xmpp.send, stream, "get", payload, **attrs))
        inner.finish(result)

    @threado.stream
    def iq_set(inner, self, payload, **attrs):
        with _stream(self.xmpp) as stream:
            result = yield inner.sub(_iq(self.xmpp.send, stream, "set", payload, **attrs))
        inner.finish(result)

    def iq_result(self, request, payload=None, **attrs):
        if not request.with_attrs("id"):
            raise XMPPError("request did not have 'id' attribute")
        if not request.with_attrs("from"):
            raise XMPPError("request did not have 'from' attribute")

        attrs["type"] = "result"
        attrs["to"] = request.get_attr("from")
        attrs["id"] = request.get_attr("id")
        attrs["from"] = unicode(self.xmpp.jid)

        iq = Element("iq", **attrs)
        if payload is not None:
            iq.add(payload)
        self.xmpp.send(iq)

    def iq_error(self, request, error, **attrs):
        if not request.with_attrs("id"):
            raise XMPPError("request did not have 'id' attribute")
        if not request.with_attrs("from"):
            raise XMPPError("request did not have 'from' attribute")

        attrs["type"] = "error"
        attrs["to"] = request.get_attr("from")
        attrs["id"] = request.get_attr("id")

        iq = Element("iq", **attrs)
        iq.add(request)
        iq.add(error)
        self.xmpp.send(iq)
