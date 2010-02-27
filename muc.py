import threado
import disco
import uuid
from xmlcore import Element, Query
from core import STANZA_NS, XMPPError
from jid import JID

MUC_NS = "http://jabber.org/protocol/muc"
USER_NS = MUC_NS + "#user"
ROOMS_NODE = "http://jabber.org/protocol/muc#rooms"

class MUCError(XMPPError):
    pass

def gen_random():
    return uuid.uuid4().hex[:8]

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

class MUCRoom(threado.GeneratorStream):
    def __init__(self, muc, xmpp, stream, jid):
        threado.GeneratorStream.__init__(self, fast=True)
        
        self.room_jid = JID(jid).bare()
        self.nick_jid = JID(jid)
        self.exit_done = threado.Channel()
        self.participants = list()

        self.muc = muc
        self.xmpp = xmpp
        self.stream = stream

    @threado.stream_fast
    def _join(inner, self, password=None, history=False):
        x = Element("x", xmlns=MUC_NS)
        if password is not None:
            password_element = Element("password")
            password_element.text = password
            x.add(password_element)
        if not history:
            history_element = Element("history", maxstanzas="0")
            x.add(history_element)
        self.xmpp.core.presence(x, to=JID(self.nick_jid))

        while True:
            yield inner, self.stream
            list(inner)

            for element in self.stream:
                parsed = parse_presence(element, self.nick_jid)
                if parsed is None:
                    continue

                participant, codes = parsed
                self.participants.append(participant)

                if participant.name == self.nick_jid or "110" in codes:
                    nick_jid = participant.name
                    self.start()
                    return

    @threado.stream
    def exit(inner, self, reason=None):
        if reason is not None:
            status = Element("status")
            status.text = reason
            self.xmpp.core.presence(status, to=self.nick_jid, type="unavailable")
        else:
            self.xmpp.core.presence(to=self.nick_jid, type="unavailable")

        yield self.exit_done

    def run(self):
        exit_sent = False

        try:
            while True:
                yield self.inner, self.stream

                try:
                    for elements in self.inner:
                        if exit_sent:
                            continue
                        if elements is None:
                            elements = list()
                        attrs = dict(type="groupchat")
                        self.xmpp.core.message(self.room_jid, *elements, **attrs)
                        continue
                except threado.Finished:
                    if not exit_sent:
                        self.exit()
                        exit_send = True
                except:
                    if not exit_sent:
                        self.exit()
                        exit_send = True
                    raise

                for elements in self.stream:
                    for element in elements.with_attrs("from"):
                        from_jid = JID(element.get_attr("from"))
                        if from_jid.bare() != self.room_jid:
                            continue

                        self.inner.send(element)

                        for presence in element.named("presence"):
                            if presence.get_attr("type", None) != "unavailable":
                                continue
                            if from_jid == self.nick_jid:
                                return
                            for x in presence.children("x", USER_NS):
                                if x.children("status").with_attrs("code", "110"):
                                    return
        finally:
            self.muc._exit_room(self)
            self.exit_done.finish()

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
        self.xmpp.disco.add_node(ROOMS_NODE, self._node_handler)
        self.rooms = dict()
        self.xmpp.add_listener(self._handler)

    def _handler(self, success, value):
        if success:
            bare = JID(value.get_attr("from")).bare()
            for room in self.rooms.get(bare, set()):
                room.stream.send(value)
        else:
            for bare, rooms in self.rooms.iteritems():
                for room in rooms:
                    room.stream.throw(*value)
            self.rooms.clear()

    def _node_handler(self):
        features = list()
        identities = [disco.DiscoIdentity("client", "bot")]
        items = [disco.DiscoItem(room) for room in self.rooms]
        return features, identities, items

    def _exit_room(self, room):
        rooms = self.rooms.get(room.room_jid.bare(), set())
        rooms.discard(room)
        if not rooms:
            self.rooms.pop(room.room_jid.bare(), None)

    @threado.stream
    def joined_rooms(inner, self, jid):
        try:
            items = yield inner.sub(self.xmpp.disco.items(jid, node=ROOMS_NODE))
        except XMPPError:
            inner.finish()
        inner.finish([item.jid for item in items])

    @threado.stream
    def join(inner, self, room, nick=None, password=None, history=False):
        jid = JID(room)
        if jid.resource is not None:
            raise MUCError("illegal room JID (contains a resource)")
        if jid.node is None:
            jid = JID(room + "@conference." + self.xmpp.jid.domain)
        jid = JID(jid.node, jid.domain, nick or gen_random())

        info = yield inner.sub(self.xmpp.disco.info(jid.domain))
        if MUC_NS not in info.features:
            raise MUCError("'%s' is not a multi-user chat service" % jid.domain)
        if not any(x for x in info.identities if x.category == "conference"):
            raise MUCError("'%s' is not a multi-user chat service" % jid.domain)

        resource = jid.resource
        while True:
            stream = threado.Channel()
            room = MUCRoom(self, self.xmpp, stream, jid)
            self.rooms.setdefault(jid.bare(), set()).add(room)
            try:
                yield inner.sub(room._join(password=password, history=history))
            except MUCError, me:
                if (me.type, me.condition) != ("cancel", "conflict"):
                    raise
                jid = JID(jid.node, jid.domain, resource + "-" + gen_random())
            else:
                inner.finish(room)
