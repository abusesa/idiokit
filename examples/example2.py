from xmpp import connect, Element
from irc import IRC
from jid import JID
from util import guess_encoding
import threado

@threado.stream
def xmpp_to_irc(inner, own_jid, channel, encoding="latin-1"):
    while True:
        elements = yield inner

        for message in elements.named("message").with_attrs("from"):
            sender = JID(message.get_attr("from"))
            if sender == own_jid:
                continue
            if sender.resource is None:
                continue

            for body in message.children("body"):
                text = "<%s> %s" % (sender.resource, body.text)
                inner.send("PRIVMSG", channel, text.encode(encoding))

@threado.stream
def irc_to_xmpp(inner, channel):
    while True:
        prefix, command, params = yield inner
        if command != "PRIVMSG":
            continue
        if not params or params[0] != channel:
            continue

        sender = prefix.split("@", 1)[0].split("!", 1)[0]
        text = "<%s> %s" % (guess_encoding(sender), guess_encoding(params[-1]))

        body = Element("body")
        body.text = text
        inner.send(body)

@threado.stream
def main(inner, bot_name, 
         irc_server, irc_port, irc_ssl, irc_channel,
         xmpp_jid, xmpp_password, xmpp_channel):

    irc = IRC(irc_server, irc_port, irc_ssl)
    nick = yield inner.sub(irc.connect(bot_name))
    irc.join(irc_channel)

    xmpp = yield inner.sub(connect(xmpp_jid, xmpp_password))
    room = yield inner.sub(xmpp.muc.join(xmpp_channel, nick))

    yield inner.sub(room 
                    | xmpp_to_irc(room.nick_jid, irc_channel)
                    | irc
                    | irc_to_xmpp(irc_channel)
                    | room)

if __name__ == "__main__":
    import getpass

    username = raw_input("Username: ")
    password = getpass.getpass()

    threado.run(main("echobot", 
                     "irc.example.com", 6667, False, "#echobot",
                     username, password, "room@conference.example.com"))
