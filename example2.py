from xmpp import XMPP, Element
from irc import IRC
from jid import JID

def guess_encoding(text):
    if isinstance(text, unicode):
        return text

    for encoding in ["ascii", "utf-8", "latin-1"]:
        try:
            return text.decode(encoding)
        except UnicodeDecodeError:
            pass
    return text.decode("unicode-escape")

def room_message(room, irc, channel, elements, encoding="latin-1"):
    for message in elements.named("message").with_attrs("from"):
        if message.children("x", "jabber:x:delay"):
            continue
        if message.children("delay", "urn:xmpp:delay"):
            continue

        sender = JID(message.get_attr("from"))
        if sender == room.nick_jid:
            continue
        if sender.resource is None:
            continue

        for body in message.children("body").with_attrs(irc=None):
            text = "<%s> %s" % (sender.resource, body.text)
            irc.send("PRIVMSG", channel, text.encode(encoding))

def irc_message(channel, room, prefix, command, params):
    if command != "PRIVMSG":
        return
    if not params or params[0] != channel:
        return

    sender = prefix.split("@", 1)[0].split("!", 1)[0]

    body = Element("body")
    body.text = "<%s> %s" % (guess_encoding(sender), guess_encoding(params[-1]))
    room.message(body)

def main(bot_name, 
         irc_server, irc_port, irc_ssl, irc_channel,
         xmpp_jid, xmpp_password, xmpp_channel):

    irc = IRC(irc_server, irc_port, irc_ssl)
    nick = irc.connect(bot_name)
    irc.join(irc_channel)

    xmpp = XMPP(xmpp_jid, xmpp_password)
    xmpp.connect()
    room = xmpp.muc.join(xmpp_channel, nick)

    for item in room + irc:
        if room.was_source:
            room_message(room, irc, irc_channel, item)
        else:
            irc_message(irc_channel, room, *item)

if __name__ == "__main__":
    import getpass

    username = raw_input("Username: ")
    password = getpass.getpass()

    main("echobot", 
         "irc.example.com", 6667, False, "#echobot",
         username, password, "room@conference.example.com")
