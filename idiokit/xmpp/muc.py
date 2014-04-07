from __future__ import absolute_import, unicode_literals

import random

from .. import idiokit
from ..xmlcore import Element
from .core import STANZA_NS, XMPPError
from .jid import JID

MUC_NS = "http://jabber.org/protocol/muc"
USER_NS = MUC_NS + "#user"
OWNER_NS = MUC_NS + "#owner"
ROOMS_NODE = "http://jabber.org/protocol/muc#rooms"


class MUCError(XMPPError):
    pass


def gen_random(length=8):
    return "".join(random.choice("0123456789") for _ in range(length))


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
            participant = MUCParticipant(other_jid, affiliation, role, presence.children(), jid)
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
    def __init__(self, jid, xmpp, output, participants):
        self.jid = JID(jid)
        self.participants = participants

        self._xmpp = xmpp
        self._exit_sent = False

        idiokit.Proxy.__init__(self, self._input() | output)

    @idiokit.stream
    def _exit(self):
        if not self._exit_sent:
            self._exit_sent = True
            yield self._xmpp.core.presence(to=self.jid, type="unavailable")

    @idiokit.stream
    def _input(self):
        bare_jid = self.jid.bare()
        attrs = dict(type="groupchat")

        try:
            while True:
                try:
                    elements = yield idiokit.next()
                except StopIteration:
                    yield self._exit()
                    continue

                yield self._xmpp.core.message(bare_jid, *elements, **attrs)
        finally:
            self._exit()


class MUCParticipant(object):
    def __init__(self, name, affiliation, role, payload, jid=None):
        self.name = name
        self.affiliation = affiliation
        self.role = role
        self.jid = jid
        self.payload = payload


class MUC(object):
    def __init__(self, xmpp):
        self.xmpp = xmpp
        self.xmpp.disco.add_feature(MUC_NS)
        self.xmpp.disco.add_node(ROOMS_NODE, lambda: ([], [], []))

        self._rooms = dict()

        self._main = self.xmpp | idiokit.map(self._map)
        self._muc = None

    def _map(self, elements):
        for element in elements.with_attrs("from"):
            sender = JID(element.get_attr("from"))
            outputs = self._rooms.get(sender.bare(), None)
            if not outputs:
                continue

            for output in outputs:
                output.send(element)

            for presence in element.named("presence").with_attrs(type="unavailable"):
                if presence.children("x", USER_NS).children("status").with_attrs(code="110"):
                    for output in outputs:
                        output.throw(StopIteration())
                    self._rooms.pop(sender.bare())

    @idiokit.stream
    def _test_muc(self, domain):
        info = yield self.xmpp.disco.info(domain)
        if MUC_NS in info.features:
            for identity in info.identities:
                if identity.category == "conference" and identity.type == "text":
                    idiokit.stop(domain)
        raise MUCError("{0!r} is not a multi-user chat service".format(domain))

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
    def get_full_room_jid(self, room):
        if "@" in str(room):
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
        jid = yield self.get_full_room_jid(room)
        if nick is None:
            nick = self.xmpp.jid.node
        jid = JID(jid.node, jid.domain, nick)

        output = idiokit.map(lambda x: (x,))
        idiokit.pipe(self._main.fork(), output)
        self._rooms.setdefault(jid.bare(), set()).add(output)
        try:
            while True:
                try:
                    jid, participants = yield join_room(jid, self.xmpp, output, password, history)
                except MUCError as me:
                    if (me.type, me.condition) != ("cancel", "conflict"):
                        raise
                    jid = JID(jid.node, jid.domain, nick + "-" + gen_random())
                else:
                    break
        except:
            outputs = self._rooms.get(jid.bare(), set())
            outputs.discard(output)
            if not outputs:
                self._rooms.pop(jid.bare(), None)
            output.throw()
            raise
        else:
            idiokit.stop(MUCRoom(jid, self.xmpp, output, participants))
