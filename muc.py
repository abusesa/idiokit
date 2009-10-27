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

def parse_participant_presence(elements, own_jid):
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
            participant = MUCParticipant(other_jid, affiliation, role, jid)
            return participant, codes
    return None

class ExitRoom(Exception):
    def __init__(self, reason=None):
        Exception.__init__(self)
        self.reason = reason

class MUCRoom(threado.GeneratorStream):
    def __init__(self, muc, xmpp, jid):
        threado.GeneratorStream.__init__(self)
        
        self.room_jid = JID(jid).bare()
        self.nick_jid = JID(jid)
        self.participants = list()

        self.muc = muc
        self.xmpp = xmpp
        self.stream = self.xmpp.stream()

    def send(self, *values):
        threado.GeneratorStream.send(self, values)

    def exit(self, reason=None):
        self.throw(ExitRoom(reason))

    def _exit(self, reason=None):
        if reason is None:
            self.xmpp.core.presence(to=self.room_jid, type="unavailable")
        else:
            status = Element("status")
            status.text = reason
            self.xmpp.core.presence(status, 
                                    to=self.room_jid, type="unavailable")

    def _join(self):
        attrs = dict()
        attrs["to"] = JID(self.nick_jid)

        x = Element("x", xmlns=MUC_NS)
        self.xmpp.core.presence(x, **attrs)

        for element in self.stream:
            parsed = parse_participant_presence(element, self.nick_jid)
            if parsed is None:
                continue

            participant, codes = parsed
            self.participants.append(participant)

            if participant.name == self.nick_jid or "110" in codes:
                nick_jid = participant.name
                break
        self.start()

    def run(self):
        try:
            while True:
                elements = yield self.inner, self.stream

                if self.inner.was_source:
                    attrs = dict(type="groupchat")
                    self.xmpp.core.message(self.room_jid, *elements, **attrs)
                    continue

                for element in elements.with_attrs("from"):
                    from_jid = JID(element.get_attr("from"))
                    if from_jid.bare() == self.room_jid:
                        self.inner.send(element)
        except ExitRoom, er:
            self._exit(er.reason)
        finally:
            self._exit()
            self.muc._exit_room(self)

class MUCParticipant(object):
    def __init__(self, name, affiliation, role, jid=None):
        self.name = name
        self.affiliation = affiliation
        self.role = role
        self.jid = jid

class MUC(object):
    def __init__(self, xmpp):
        self.xmpp = xmpp
        self.xmpp.disco.add_feature(MUC_NS)
        self.xmpp.disco.add_node(ROOMS_NODE, self._node_handler)
        self.rooms = set()

    def _node_handler(self):
        features = list()
        identities = [disco.DiscoIdentity("client", "bot")]
        items = [disco.DiscoItem(room.room_jid) for room in self.rooms]
        return features, identities, items

    def _exit_room(self, room):
        self.rooms.discard(room)

    def joined_rooms(self, jid):
        try:
            items = self.xmpp.disco.items(jid, node=ROOMS_NODE)
        except XMPPError:
            return
        return [item.jid for item in items]

    def join(self, room, nick=None):
        jid = JID(room)
        if jid.node is None:
            jid.node = jid.domain
            jid.domain = "conference." + self.xmpp.jid.domain
        if nick is not None:
            jid.resource = nick or "bot"

        info = self.xmpp.disco.info(jid.domain)
        if MUC_NS not in info.features:
            raise MUCError("'%s' is not a multi-user chat service" % jid.domain)
        if not any(x for x in info.identities if x.category == "conference"):
            raise MUCError("'%s' is not a multi-user chat service" % jid.domain)

        original_resource = jid.resource
        while True:
            room = MUCRoom(self, self.xmpp, jid)
            try:
                room._join()
            except MUCError, me:
                if (me.type, me.condition) != ("cancel", "conflict"):
                    raise
                jid.resource = original_resource + "-" + uuid.uuid4().hex[:8]
            else:
                self.rooms.add(room)
                return room
