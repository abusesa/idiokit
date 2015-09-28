from __future__ import absolute_import

import uuid
import base64

from .. import idiokit, xmlcore
from .jid import JID

STREAM_NS = "http://etherx.jabber.org/streams"
STREAM_ERROR_NS = "urn:ietf:params:xml:ns:xmpp-streams"
STANZA_ERROR_NS = "urn:ietf:params:xml:ns:xmpp-stanzas"
SASL_NS = "urn:ietf:params:xml:ns:xmpp-sasl"
BIND_NS = "urn:ietf:params:xml:ns:xmpp-bind"
SESSION_NS = "urn:ietf:params:xml:ns:xmpp-session"
STANZA_NS = "jabber:client"
STARTTLS_NS = "urn:ietf:params:xml:ns:xmpp-tls"


class XMPPError(Exception):
    def __init__(self, message, elements=(), ns=STANZA_ERROR_NS):
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
        return "{0} ({1})".format(self.args[0], extra)


def _iq_build(type, query, **attrs):
    uid = uuid.uuid4().hex[:16]
    attrs["id"] = uid

    iq = xmlcore.Element("iq", type=type, **attrs)
    iq.add(query)
    return uid, iq


@idiokit.stream
def _iq_wait(uid):
    while True:
        elements = yield idiokit.next()

        for element in elements.named("iq").with_attrs(id=uid):
            type = element.get_attr("type", None)

            if type == "result":
                idiokit.stop(element)

            if type == "error":
                errors = element.children("error", STANZA_NS)
                raise XMPPError("iq failed", errors)

            if type is None:
                raise XMPPError("type attribute missing for iq stanza")


@idiokit.stream
def _iq(stream, iq_type, query, **attrs):
    uid, iq = _iq_build(iq_type, query, **attrs)

    forked = stream.fork()
    yield forked.send(iq)
    result = yield idiokit.Event() | forked | _iq_wait(uid)
    idiokit.stop(result)


@idiokit.stream
def require_features(stream):
    while True:
        elements = yield stream.next()

        features = elements.named("features", STREAM_NS)
        if features:
            idiokit.stop(features)


@idiokit.stream
def require_tls(stream):
    features = yield require_features(stream)

    tls = features.children("starttls", STARTTLS_NS)
    if not tls:
        raise XMPPError("server does not support starttls")
    yield starttls(stream)


@idiokit.stream
def require_sasl(stream, jid, password):
    features = yield require_features(stream)

    mechanisms = features.children("mechanisms", SASL_NS).children("mechanism")
    for mechanism in mechanisms:
        if mechanism.text != "PLAIN":
            continue
        result = yield sasl_plain(stream, jid, password)
        idiokit.stop(result)
    raise XMPPError("server does not support plain sasl")


@idiokit.stream
def require_bind_and_session(stream, jid):
    jid = JID(jid)
    features = yield require_features(stream)

    if not features.children("bind", BIND_NS):
        raise XMPPError("server does not support resource binding")
    if not features.children("session", SESSION_NS):
        raise XMPPError("server does not support sessions")

    jid = yield bind_resource(stream, jid.resource)
    yield session(stream)
    idiokit.stop(jid)


@idiokit.stream
def starttls(stream):
    yield stream.send(xmlcore.Element("starttls", xmlns=STARTTLS_NS))

    while True:
        elements = yield stream.next()
        if elements.named("failure", STARTTLS_NS):
            raise XMPPError("starttls failed", elements)
        if elements.named("proceed", STARTTLS_NS):
            break


@idiokit.stream
def sasl_plain(stream, jid, password):
    password = unicode(password).encode("utf-8")
    data = "\x00" + jid.node.encode("utf-8") + "\x00" + password

    auth = xmlcore.Element("auth", xmlns=SASL_NS, mechanism="PLAIN")
    auth.text = base64.b64encode(data)
    yield stream.send(auth)

    while True:
        elements = yield stream.next()

        if elements.named("failure", SASL_NS):
            raise XMPPError("authentication failed", elements)
        if elements.named("success", SASL_NS):
            break


@idiokit.stream
def bind_resource(stream, resource=None):
    bind = xmlcore.Element("bind", xmlns=BIND_NS)
    if resource is not None:
        element = xmlcore.Element("resource")
        element.text = resource
        bind.add(element)
    result = yield _iq(stream, "set", bind)

    for jid in result.children("bind", BIND_NS).children("jid"):
        idiokit.stop(JID(jid.text))
    raise XMPPError("no jid supplied by bind")


@idiokit.stream
def session(stream):
    session = xmlcore.Element("session", xmlns=SESSION_NS)
    yield _iq(stream, "set", session)


class _IqHandler(object):
    def __init__(self, core, func, args, keys):
        self._core = core
        self._func = func
        self._args = args
        self._keys = keys

    def handle(self, iq):
        payload = iq.children(*self._args, **self._keys)
        if payload and self._func(iq, list(payload)[0]):
            return True
        return False

    def remove(self):
        core = self._core
        if core is None:
            return False

        self._core = None
        try:
            core._iq_handlers.remove(self)
        except ValueError:
            return False
        return True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.remove()
        return False


class Core(object):
    _VALID_ERROR_TYPES = frozenset(["cancel", "continue", "modify", "auth", "wait"])

    def __init__(self, xmpp):
        self._xmpp = xmpp
        self._iq_handlers = list()
        self._iq_uids = dict()
        idiokit.pipe(xmpp, idiokit.map(self._map_iqs))

    def iq_handler(self, func, *args, **keys):
        handler = _IqHandler(self, func, args, keys)
        self._iq_handlers.append(handler)
        return handler

    def _map_iqs(self, elements):
        for iq in elements.named("iq", STANZA_NS).with_attrs("type"):
            if iq.get_attr("type").lower() not in ("get", "set"):
                uid = iq.get_attr("id", None)
                if uid is not None and uid in self._iq_uids:
                    self._iq_uids[uid].send(iq)
                continue

            for handler in self._iq_handlers:
                if handler.handle(iq):
                    break
            else:
                error = self.build_error("cancel", "service-unavailable")
                self.iq_error(iq, error)

    def build_error(self, type, condition, text=None, special=None):
        if type not in self._VALID_ERROR_TYPES:
            expected = "/".join(self._VALID_ERROR_TYPES)
            raise XMPPError("wrong error type (got '{0}', expected '{1}')".format(type, expected))

        error = xmlcore.Element("error", type=type)
        error.add(xmlcore.Element(condition, xmlns=STANZA_ERROR_NS))
        if text is not None:
            text_element = xmlcore.Element("text", xmlns=STANZA_ERROR_NS)
            text_element.text = text
            error.add(text_element)
        if special is not None:
            error.add(special)
        return error

    def message(self, to, *payload, **attrs):
        attrs["to"] = to
        message = xmlcore.Element("message", **attrs)
        message.add(*payload)
        return self._xmpp.send(message)

    def presence(self, *payload, **attrs):
        presence = xmlcore.Element("presence", **attrs)
        presence.add(*payload)
        return self._xmpp.send(presence)

    @idiokit.stream
    def _iq(self, iq_type, payload, **attrs):
        uid, iq = _iq_build(iq_type, payload, **attrs)

        waiter = _iq_wait(uid)
        self._iq_uids[uid] = waiter

        try:
            yield self._xmpp.send(iq)
            result = yield idiokit.Event() | waiter
        finally:
            self._iq_uids.pop(uid, None)
        idiokit.stop(result)

    def iq_get(self, payload, **attrs):
        return self._iq("get", payload, **attrs)

    def iq_set(self, payload, **attrs):
        return self._iq("set", payload, **attrs)

    def iq_result(self, request, payload=None, **attrs):
        if not request.with_attrs("id"):
            raise XMPPError("request did not have 'id' attribute")
        if not request.with_attrs("from"):
            raise XMPPError("request did not have 'from' attribute")

        attrs["type"] = "result"
        attrs["to"] = request.get_attr("from")
        attrs["id"] = request.get_attr("id")
        attrs["from"] = unicode(self._xmpp.jid)

        iq = xmlcore.Element("iq", **attrs)
        if payload is not None:
            iq.add(payload)
        return self._xmpp.send(iq)

    def iq_error(self, request, error, **attrs):
        if not request.with_attrs("id"):
            raise XMPPError("request did not have 'id' attribute")
        if not request.with_attrs("from"):
            raise XMPPError("request did not have 'from' attribute")

        attrs["type"] = "error"
        attrs["to"] = request.get_attr("from")
        attrs["id"] = request.get_attr("id")

        iq = xmlcore.Element("iq", **attrs)
        iq.add(request)
        iq.add(error)
        return self._xmpp.send(iq)
