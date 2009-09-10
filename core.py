import uuid
import threado
from jid import JID
from xmlcore import Query, Element, STREAM_NS

STREAM_ERROR_NS = "urn:ietf:params:xml:ns:xmpp-streams"
STANZA_ERROR_NS = "urn:ietf:params:xml:ns:xmpp-stanzas"
SASL_NS = "urn:ietf:params:xml:ns:xmpp-sasl"
BIND_NS = "urn:ietf:params:xml:ns:xmpp-bind"
SESSION_NS = "urn:ietf:params:xml:ns:xmpp-session"
STANZA_NS = "jabber:client"
STARTTLS_NS = "urn:ietf:params:xml:ns:xmpp-tls"

class XMPPError(Exception):
    def __init__(self, message, elements=Query(), ns=STANZA_ERROR_NS):
        for element in elements.children(ns=ns):
            tag = element.tag.replace("-", " ")
            message += " (" + tag + ")"
            break
        Exception.__init__(self, message)

def _iq(send, stream, type, query, **attrs):
    uid = uuid.uuid4().hex
    attrs["id"] = uid

    iq = Element("iq", type=type, **attrs)
    iq.add(query)
    send(iq)

    for elements in stream:
        for element in elements.filter("iq").with_attrs(id=uid):
            type = elements.get_attr("type", None)
            if type == "result":
                return element
            elif type == "error":
                errors = element.children("error", STANZA_NS)
                raise XMPPError("iq failed", errors)
            elif type is None:
                raise XMPPError("type attribute missing for iq stanza")

def require_features(stream):
    elements = stream.next()
    features = elements.filter("features", STREAM_NS)
    if not features:
        raise XMPPError("feature list expected")
    return features

def require_tls(stream):
    features = require_features(stream)

    tls = features.children("starttls", STARTTLS_NS)
    if not tls:
        raise XMPPError("server does not support starttls")

    starttls(stream)

def require_sasl(stream, jid, password):
    features = require_features(stream)
    
    mechanisms = features.children("mechanisms", SASL_NS).children("mechanism")
    for mechanism in mechanisms:
        if mechanism.text != "PLAIN":
            continue
        return sasl_plain(stream, jid, password)

    raise XMPPError("server does not support plain sasl")

def require_bind_and_session(stream, jid):
    features = require_features(stream)
    
    if not features.children("bind", BIND_NS):
        raise XMPPError("server does not support resource binding")
    if not features.children("session", SESSION_NS):
        raise XMPPError("server does not support sessions")

    jid = bind_resource(stream, jid.resource)
    session(stream)
    return jid

def starttls(stream):
    starttls = Element("starttls", xmlns=STARTTLS_NS)
    stream.send(starttls)

    for elements in stream:
        if elements.filter("failure", STARTTLS_NS):
            raise XMPPError("starttls failed", elements)
        if elements.filter("proceed", STARTTLS_NS):
            break

def sasl_plain(stream, jid, password):
    import base64

    data = u"%s\x00%s\x00%s" % (jid.bare(), jid.node, password)
    
    auth = Element("auth", xmlns=SASL_NS, mechanism="PLAIN")
    auth.text = base64.b64encode(data)
    stream.send(auth)

    for elements in stream:
        if elements.filter("failure", SASL_NS):
            raise XMPPError("authentication failed", elements)
        if elements.filter("success", SASL_NS):
            break        

def bind_resource(stream, resource=None):
    bind = Element("bind", xmlns=BIND_NS)
    if resource is not None:
        element = Element("resource")
        element.text = resource
        bind.add(element)

    result = _iq(stream.send, stream, "set", bind)

    for jid in result.children("bind", BIND_NS).children("jid"):
        return JID(jid.text)
    raise XMPPError("no jid supplied by bind")

def session(stream):
    session = Element("session", xmlns=SESSION_NS)
    _iq(stream.send, stream, "set", session)


class Core(object):
    VALID_ERROR_TYPES = set(["cancel", "continue", "modify", "auth", "wait"])

    def __init__(self, xmpp):
        self.xmpp = xmpp
        self.iq_handlers = dict()
        
    def build_error(self, type, condition, text=None, special=None):
        if type not in self.VALID_ERROR_TYPES:
            expected = "/".join(self.VALID_ERROR_TYPES)
            message = "wrong error type (got '%s', expected '%s')"
            raise XMPPError(message % (type, expected))

        error = Element("error", type=type)
        error.add(Element(condition, xmlns=STANZA_ERROR_NS))
        if text is not None:
            error.add(Element("text", xmlns=STANZA_ERROR_NS))
        if special is not None:
            error.add(special)
        return error

    def message(self, to, *payload, **attrs):
        attrs["to"] = to
        attrs["from"] = unicode(self.xmpp.jid)
        message = Element("message", **attrs)
        message.add(*payload)
        self.xmpp.send(message)

    def presence(self, *payload, **attrs):
        attrs["from"] = unicode(self.xmpp.jid)
        presence = Element("presence", **attrs)
        presence.add(*payload)
        self.xmpp.send(presence)

    def iq_get(self, payload, **attrs):
        attrs["from"] = unicode(self.xmpp.jid)
        return _iq(self.xmpp.send, self.xmpp.stream(), "get", payload, **attrs)

    def iq_set(self, payload, **attrs):
        attrs["from"] = unicode(self.xmpp.jid)
        return _iq(self.xmpp.send, self.xmpp.stream(), "set", payload, **attrs)

    def iq_result(self, request, payload=None, **attrs):
        if not request.has_attrs("id"):
            raise XMPPError("request did not have 'id' attribute")
        if not request.has_attrs("from"):
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
        if not request.has_attrs("id"):
            raise XMPPError("request did not have 'id' attribute")
        if not request.has_attrs("from"):
            raise XMPPError("request did not have 'from' attribute")

        attrs["type"] = "error"        
        attrs["to"] = request.get_attr("from")
        attrs["id"] = request.get_attr("id")
        attrs["from"] = unicode(self.xmpp.jid)
            
        iq = Element("iq", **attrs)
        iq.add(request)
        iq.add(error)
        self.xmpp.send(iq)

    def add_iq_handler(self, handler, *args, **keys):
        self.iq_handlers[handler] = args, keys
