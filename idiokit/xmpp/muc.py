from __future__ import absolute_import

import sys
import random
import string

from .. import idiokit
from ..xmlcore import Element, Query
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

class MUCRoom(idiokit.Stream):
    def __init__(self, jid, muc, output, participants):
        idiokit.Stream.__init__(self)

        self.jid = JID(jid)
        self.participants = participants

        self._muc = muc
        self._xmpp = muc.xmpp
        self._proxied = self._handle_input() | output | self._handle_output()

    def pipe_left(self, *args, **keys):
        return self._proxied.pipe_left(*args, **keys)

    def pipe_right(self, *args, **keys):
        return self._proxied.pipe_right(*args, **keys)

    def head(self, *args, **keys):
        return self._proxied.head(*args, **keys)

    def result(self, *args, **keys):
        return self._proxied.result(*args, **keys)

    @idiokit.stream
    def _handle_input(self):
        bare_jid = self.jid.bare()

        while True:
            elements = yield idiokit.next()
            attrs = dict(type="groupchat")
            yield self._xmpp.core.message(bare_jid, *elements, **attrs)

    @idiokit.stream
    def _handle_output(self):
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

        idiokit.pipe(self.xmpp, self._handler())

    @idiokit.stream
    def _handler(self):
        try:
            while True:
                elements = yield idiokit.next()

                for element in elements:
                    bare = JID(element.get_attr("from")).bare()
                    for output in self.rooms.get(bare, set()):
                        output.send(element)
        except:
            exc_info = sys.exc_info()

            for bare, rooms in self.rooms.iteritems():
                for room in rooms:
                    room.stream.throw(*exc_info)

            self.rooms.clear()

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
    def join(self, room, nick=None, password=None, history=False):
        jid = JID(room)
        if jid.resource is not None:
            raise MUCError("illegal room JID (contains a resource)")
        if jid.node is None:
            jid = JID(room + "@conference." + self.xmpp.jid.domain)

        if nick is None:
            nick = self.xmpp.jid.node
        jid = JID(jid.node, jid.domain, nick)

        info = yield self.xmpp.disco.info(jid.domain)
        if MUC_NS not in info.features:
            raise MUCError("'%s' is not a multi-user chat service" % jid.domain)
        if not any(x for x in info.identities if x.category == "conference"):
            raise MUCError("'%s' is not a multi-user chat service" % jid.domain)

        output = channel()
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
                    jid = JID(jid.node, jid.domain, nick + "-" + gen_random())
                else:
                    break
        except:
            exc_type, exc_value, exc_tb = sys.exc_info()

            outputs = self.rooms.get(jid.bare(), set())
            outputs.discard(output)
            if not outputs:
                self.rooms.pop(jid.bare(), None)

            yield output.signal(idiokit.Signal)

            raise exc_type, exc_value, exc_tb
        else:
            idiokit.stop(MUCRoom(jid, self, output, participants))
