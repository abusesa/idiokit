import idiokit
from idiokit.xmpp import connect as xmpp_connect
from idiokit.irc import connect as irc_connect
from idiokit.xmpp.jid import JID
from idiokit.xmlcore import Element


def guess_encoding(text):
    if isinstance(text, unicode):
        return text

    for encoding in ["ascii", "utf-8"]:
        try:
            return text.decode(encoding)
        except UnicodeDecodeError:
            pass
    return text.decode("latin-1", "replace")


@idiokit.stream
def xmpp_to_irc(own_jid, channel, encoding="latin-1"):
    while True:
        elements = yield idiokit.next()

        for message in elements.named("message").with_attrs("from"):
            sender = JID(message.get_attr("from"))
            if sender == own_jid:
                continue
            if sender.resource is None:
                continue

            for body in message.children("body"):
                for line in body.text.splitlines():
                    text = "<{0}> {1}".format(sender.resource, line)
                    yield idiokit.send("PRIVMSG", channel, text.encode(encoding))


@idiokit.stream
def irc_to_xmpp(channel):
    while True:
        prefix, command, params = yield idiokit.next()
        if command != "PRIVMSG":
            continue
        if not params or params[0] != channel:
            continue

        sender = prefix.split("@", 1)[0].split("!", 1)[0]
        text = "<{0}> {1}".format(guess_encoding(sender), guess_encoding(params[-1]))

        body = Element("body")
        body.text = text
        yield idiokit.send(body)


@idiokit.stream
def main(bot_name,
         irc_server, irc_port, irc_ssl, irc_channel,
         xmpp_jid, xmpp_password, xmpp_channel):

    irc = yield irc_connect(irc_server, irc_port, bot_name, ssl=irc_ssl)
    yield irc.join(irc_channel)

    xmpp = yield xmpp_connect(xmpp_jid, xmpp_password)
    room = yield xmpp.muc.join(xmpp_channel, irc.nick)

    yield (room
           | xmpp_to_irc(room.jid, irc_channel)
           | irc
           | irc_to_xmpp(irc_channel)
           | room)


if __name__ == "__main__":
    import getpass

    username = raw_input("Username: ")
    password = getpass.getpass()

    idiokit.main_loop(main("echobot",
                           "irc.example.com", 6667, False, "#echobot",
                           username, password, "room@conference.example.com"))
