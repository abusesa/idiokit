import threado
from xmpp import XMPP
from xmlcore import Element, Query
from core import XMPPError

PUBSUB_NS = "http://jabber.org/protocol/pubsub"
EVENT_NS = PUBSUB_NS + "#event"

def fetch(xmpp, node):
    pubsub = Element("pubsub", xmlns=PUBSUB_NS)
    items = Element("items", node=node)
    pubsub.add(items)

    try:
        elements = xmpp.core.iq_get(pubsub)
    except XMPPError:
        return None

    pubsubs = elements.children("pubsub", PUBSUB_NS)
    items = pubsubs.children("items").with_attrs(node=node)
    return items.children("item").children()

def publish(xmpp, node, *elements):
    pubsub = Element("pubsub", xmlns=PUBSUB_NS)
    
    publish = Element("publish", node=node)
    pubsub.add(publish)
    
    item = Element("item")
    publish.add(item)

    item.add(*elements)
    xmpp.core.iq_set(pubsub)

@threado.thread
def pep_stream(inner, xmpp, node):
    stream = xmpp.stream()

    pubsub = Element("pubsub", xmlns=PUBSUB_NS)
    subscribe = Element("subscribe", node=node, jid=xmpp.jid.bare())
    pubsub.add(subscribe)
    xmpp.core.iq_set(pubsub, to=xmpp.jid.bare())

    #elements = fetch(xmpp, node)
    #if elements is not None:
    #    inner.send(elements)

    for elements in inner + stream:
        if inner.was_source:
            publish(xmpp, node, *elements)
        else:
            own_jid = unicode(xmpp.jid.bare())
            messages = elements.named("message").with_attrs(FROM=own_jid)
            events = messages.children("event", EVENT_NS)
            items = events.children("items").with_attrs(node=node)
            inner.send(items.children("item").children())
