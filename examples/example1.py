import getpass
from idiokit import threado
from idiokit.xmpp import connect
from idiokit.jid import JID

@threado.stream
def main(inner):
    xmpp = yield inner.sub(connect(raw_input("Username: "), getpass.getpass()))
    room = yield inner.sub(xmpp.muc.join(raw_input("Channel: ")))

    while True:
        elements = yield inner, room
        if inner.was_source:
            continue

        for message in elements.named("message").with_attrs("from"):
            sender = JID(message.get_attr("from"))
            if sender == room.nick_jid:
                continue
            for body in message.children("body"):
                room.send(body)

if __name__ == "__main__":
    threado.run(main())
