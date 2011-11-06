from __future__ import absolute_import

import random
import string

from .. import idiokit
from ..xmlcore import Element
from . import disco
from .core import STANZA_NS, XMPPError
from .jid import JID

MUC_NS = "http://jabber.org/protocol/muc"
USER_NS = MUC_NS + "#user"
OWNER_NS = MUC_NS + "#owner"
ROOMS_NODE = "http://jabber.org/protocol/muc#rooms"

class MUCError(XMPPError):
    pass

def gen_random(length=8):
    return "".join(random.choice(string.digits) for _ in xrange(length))

def parse_presence(elements, own_jid):
    presences = elements.named("presence", STANZA_NS)

    for presence in presences.with_attrs("from"):
        other_jid = JID(presence.get_attr("from"))
        if other_jid.bare() != own_jid.bare():
            continue

        type = presence.get_attr("type", None)
        if other_jid == own_jid and type == "error":
            raise MUCError("could not join room", presence.children("error"))

        x = presence.children("x", USER_NS)
        codes = set()
        for status in x.children("status").with_attrs("code"):
            codes.add(status.get_attr("code"))

        for item in x.children("item").with_attrs("affiliation", "role"):
            jid = item.get_attr("jid", None)
            if jid is not None:
                jid = JID(jid)

            affiliation = item.get_attr("affiliation")
            role = item.get_attr("role")
            participant = MUCParticipant(other_jid, affiliation, role,
                                         presence.children(), jid)
            return participant, codes
    return None

@idiokit.stream
def join_room(jid, xmpp, output, password=None, history=False):
    participants = list()

    x = Element("x", xmlns=MUC_NS)
    if password is not None:
        password_element = Element("password")
        password_element.text = password
        x.add(password_element)
    if not history:
        history_element = Element("history", maxstanzas="0")
        x.add(history_element)
    yield xmpp.core.presence(x, to=JID(jid))

    while True:
        element = yield output.next()

        parsed = parse_presence(element, jid)
        if parsed is None:
            continue

        participant, codes = parsed
        participants.append(participant)

        if "201" in codes:
            submit = Element("x", xmlns="jabber:x:data", type="submit")
            query = Element("query", xmlns=OWNER_NS)
            query.add(submit)
            xmpp.core.iq_set(query, to=jid.bare())

        if participant.name == jid or "110" in codes:
            idiokit.stop(participant.name, participants)

class MUCRoom(idiokit.Proxy):
    def __init__(self, jid, muc, output, participants):
        self.jid = JID(jid)
        self.participants = participants

        self._muc = muc
        self._xmpp = muc.xmpp

        idiokit.Proxy.__init__(self, self._input() | output | self._output())

    @idiokit.stream
    def _input(self):
        bare_jid = self.jid.bare()

        while True:
            elements = yield idiokit.next()
            attrs = dict(type="groupchat")
            yield self._xmpp.core.message(bare_jid, *elements, **attrs)

    @idiokit.stream
    def _output(self):
        try:
            while True:
                elements = yield idiokit.next()

                yield idiokit.send(elements)

                for presence in elements.named("presence").with_attrs("from"):
                    sender = JID(presence.get_attr("from"))

                    if presence.get_attr("type", None) != "unavailable":
                        continue
                    if sender == self.jid:
                        return
                    for x in presence.children("x", USER_NS):
                        if x.children("status").with_attrs("code", "110"):
                            return
        finally:
            self._muc._exit_room(self)

class MUCParticipant(object):
    def __init__(self, name, affiliation, role, payload, jid=None):
        self.name = name
        self.affiliation = affiliation
        self.role = role
        self.jid = jid
        self.payload = payload

@idiokit.stream
def channel():
    while True:
        obj = yield idiokit.next()
        yield idiokit.send(obj)

class MUC(object):
    def __init__(self, xmpp):
        self.xmpp = xmpp
        self.xmpp.disco.add_feature(MUC_NS)
        self.xmpp.disco.add_node(ROOMS_NODE, self._node_handler)
        self.rooms = dict()

        self._main = idiokit.pipe(self.xmpp, self._dispatch())
        self._muc = None

    @idiokit.stream
    def _dispatch(self):
        while True:
            elements = yield idiokit.next()

            for element in elements.with_attrs("from"):
                bare = JID(element.get_attr("from")).bare()
                for output in self.rooms.get(bare, ()):
                    output.send(element)

    def _node_handler(self):
        features = list()
        identities = [disco.DiscoIdentity("client", "bot")]
        items = [disco.DiscoItem(room) for room in self.rooms]
        return features, identities, items

    def _exit_room(self, room):
        rooms = self.rooms.get(room.jid.bare(), set())
        rooms.discard(room)
        if not rooms:
            self.rooms.pop(room.room_jid.bare(), None)

    @idiokit.stream
    def _test_muc(self, domain):
        info = yield self.xmpp.disco.info(domain)
        if MUC_NS not in info.features:
            raise MUCError("%r is not a multi-user chat service" % domain)

        for identity in info.identities:
            if identity.category == "conference" and identity.type == "text":
                idiokit.stop(domain)

        raise MUCError("%r is not a multi-user chat service" % domain)

    @idiokit.stream
    def _resolve_muc(self):
        items = yield self.xmpp.disco.items(self.xmpp.jid.domain)
        for item in items:
            if item.node is not None and item.jid != item.jid.domain:
                continue

            try:
                domain = yield self._test_muc(item.jid)
            except MUCError:
                continue
            else:
                break
        else:
            domain = yield self._test_muc("conference." + self.xmpp.jid.domain)

        idiokit.stop(domain)

    @idiokit.stream
    def _full_room_jid(self, room):
        if "@" in unicode(room):
            jid = JID(room)
            if jid.resource is not None:
                raise MUCError("illegal room JID (contains a resource)")

            node = jid.node
            domain = yield self._test_muc(jid.domain)
        else:
            node = room
            if self._muc is None:
                self._muc = self._resolve_muc()
            domain = yield self._muc.fork()

        idiokit.stop(JID(node, domain))

    @idiokit.stream
    def join(self, room, nick=None, password=None, history=False):
        jid = yield self._full_room_jid(room)
        if nick is None:
            nick = self.xmpp.jid.node
        jid = JID(jid.node, jid.domain, nick)

        output = channel()
        idiokit.pipe(self._main.fork(), output)
        self.rooms.setdefault(jid.bare(), set()).add(output)
        try:
            while True:
                try:
                    jid, participants = yield join_room(jid,
                                                        self.xmpp, output,
                                                        password, history)
                except MUCError, me:
                    if (me.type, me.condition) != ("cancel", "conflict"):
                        raise
                    jid = JID(jid.node, jid.domain, nick+"-"+gen_random())
                else:
                    break
        except:
            outputs = self.rooms.get(jid.bare(), set())
            outputs.discard(output)
            if not outputs:
                self.rooms.pop(jid.bare(), None)
            output.signal(idiokit.Signal)
            raise
        else:
            idiokit.stop(MUCRoom(jid, self, output, participants))
