from __future__ import absolute_import

from .. import idiokit
from ..xmlcore import Element
from .jid import JID

DISCO_INFO_NS = "http://jabber.org/protocol/disco#info"
DISCO_ITEMS_NS = "http://jabber.org/protocol/disco#items"


class DiscoItem(object):
    def __init__(self, jid, node=None, name=None):
        self.jid = JID(jid)
        self.node = node
        self.name = name


class DiscoIdentity(object):
    def __init__(self, category, type, name=None):
        self.category = category
        self.type = type
        self.name = name


class DiscoInfo(object):
    def __init__(self, identities, features):
        self.identities = set(identities)
        self.features = set(features)


class Disco(object):
    def __init__(self, xmpp):
        self.xmpp = xmpp

        self.features = set()
        self.identities = set()
        self.nodes = dict()

        self.xmpp.core.iq_handler(self._info_iq, "query", DISCO_INFO_NS)
        self.xmpp.core.iq_handler(self._items_iq, "query", DISCO_ITEMS_NS)
        self.add_feature(DISCO_INFO_NS)
        self.add_node(None, self._node_handler)
        self.add_identity("client", "bot")

    def _node_handler(self):
        items = [DiscoItem(self.xmpp.jid, node) for node in self.nodes]
        return self.features, self.identities, items

    def _items_iq(self, element, payload):
        node = payload.get_attr("node", None)
        handler = self.nodes.get(node, None)
        if handler is None:
            return False

        _, _, items = handler()

        result = Element("query", xmlns=DISCO_ITEMS_NS)
        for item in items:
            item_element = Element("item", jid=item.jid)
            if item.node is not None:
                item_element.set_attr("node", item.node)
            if item.name is not None:
                item_element.set_attr("name", item.name)
            result.add(item_element)

        self.xmpp.core.iq_result(element, result)
        return True

    def _info_iq(self, element, payload):
        identities = self.identities
        features = self.features

        node = payload.get_attr("node", None)
        handler = self.nodes.get(node, None)
        if handler is None:
            return False

        features, identities, _ = handler()

        result = Element("query", xmlns=DISCO_INFO_NS)
        for identity in identities:
            id_element = Element("identity")
            id_element.set_attr("category", identity.category)
            id_element.set_attr("type", identity.type)
            if identity.name is not None:
                id_element.set_attr("name", identity.name)
            result.add(id_element)
        for feature in features:
            result.add(Element("feature", var=feature))

        self.xmpp.core.iq_result(element, result)
        return True

    def add_node(self, node, handler):
        self.nodes[node] = handler

    def add_feature(self, feature):
        self.features.add(feature)

    def add_identity(self, category, type, name=None):
        identity = DiscoIdentity(category, type, name)
        self.identities.add(identity)

    @idiokit.stream
    def info(self, jid, node=None):
        query = Element("query", xmlns=DISCO_INFO_NS)
        if node is not None:
            query.set_attr("node", node)

        elements = yield self.xmpp.core.iq_get(query, to=jid)

        query = elements.children("query", DISCO_INFO_NS)
        identities = list()
        for identity in query.children("identity").with_attrs("category", "type"):
            category = identity.get_attr("category")
            type = identity.get_attr("type")
            name = identity.get_attr("name", None)
            identities.append(DiscoIdentity(category, type, name))

        features = list()
        for feature in query.children("feature").with_attrs("var"):
            features.append(feature.get_attr("var"))
        idiokit.stop(DiscoInfo(identities, features))

    @idiokit.stream
    def items(self, jid, node=None):
        query = Element("query", xmlns=DISCO_ITEMS_NS)
        if node is not None:
            query.set_attr("node", node)

        elements = yield self.xmpp.core.iq_get(query, to=jid)

        query = elements.children("query", DISCO_ITEMS_NS)
        items = list()
        for item in query.children("item").with_attrs("jid"):
            jid = item.get_attr("jid")
            node = item.get_attr("node", None)
            name = item.get_attr("name", None)
            items.append(DiscoItem(jid, node, name))
        idiokit.stop(items)
