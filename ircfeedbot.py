import threado
import re
import util
from xmpp import XMPP, Element
from irc import IRC

@threado.stream
def filter(inner, channel, nick):
    while True:
        prefix, command, params = yield inner

        if command != "PRIVMSG":
            continue
        if not params or params[0] != channel:
            continue

        sender = prefix.split("@", 1)[0].split("!", 1)[0]
        if sender == nick:
            inner.send(params[-1])

@threado.stream
def parse(inner):
    field_str = "([^\s=]+)='([^']*)'"
    data_rex = re.compile("^([^\s>]+)>\s*(("+ field_str +"\s*,?\s*)*)\s*$")
    field_rex = re.compile(field_str)

    while True:
        data = yield inner

        match = data_rex.match(data.strip())
        if not match:
            continue

        type = match.group(1)
        fields = dict()
        fields = field_rex.findall(match.group(2) or "")

        attrs = dict()
        for key, value in fields:
            key = util.guess_encoding(key)
            value = util.guess_encoding(value)
            attrs.setdefault(key.lower(), list()).append(value)
        inner.send(type.lower(), attrs)

@threado.stream
def convert(inner):
    while True:
        source, attrs = yield inner

        event = Element("event", xmlns="idiokit#event")
        fields = list()
        for key, values in attrs.items():
            for value in values:
                event.add(Element("attr", key=key, value=value))
                fields.append("%s=%s" % (key, value))

        body = Element("body")
        body.text = "%s: %s" % (source, ", ".join(fields))
        inner.send(body, event)

@threado.stream
def ignore(inner):
    while True:
        yield inner

def main():
    channel = "#example3"

    irc = IRC("irc.example.com", 6667, ssl=False)
    nick = irc.connect("ex3bot", password=None)
    irc.join(channel)

    xmpp = XMPP("username@example.com", "password")
    xmpp.connect()
    room = xmpp.muc.join("room@conference.example.com", nick)

    pipeline = (irc 
                | filter(channel, "feedbot") 
                | parse() 
                | convert() 
                | room 
                | ignore())
    for msg in pipeline: pass

if __name__ == "__main__":
    main()
