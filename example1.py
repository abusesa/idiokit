import getpass
from xmpp import XMPP
from jid import JID

xmpp = XMPP(raw_input("Username: "), getpass.getpass())
xmpp.connect()
room = xmpp.muc.join(raw_input("Channel: "), "echobot")

for elements in room:
    for message in elements.named("message").with_attrs("from"):
        if message.children("x", "jabber:x:delay"):
            continue
        if message.children("delay", "urn:xmpp:delay"):
            continue

        sender = JID(message.get_attr("from"))
        if sender == room.nick_jid:
            continue

        for body in message.children("body"):
            room.send(body)
