from __future__ import absolute_import

import re

from . import idiokit, util, sockets

class IRCError(Exception):
    pass

class IRCParser(object):
    def __init__(self):
        self.line_buffer = util.LineBuffer()

    def feed(self, data=""):
        if "\x00" in data:
            raise IRCError("NUL not allowed in messages")

        for line in self.line_buffer.feed(data):
            if len(line) > 510:
                raise IRCError("too long message (over 512 bytes)")
            yield self.process_line(line)

    def process_line(self, line):
        if line.startswith(":"):
            bites = line.split(" ", 2)
            prefix = bites.pop(0)[1:]
        else:
            bites = line.split(" ", 1)
            prefix = None

        if len(bites) != 2:
            raise IRCError("invalid message")

        command, trailing = bites
        params = list()

        while trailing:
            if trailing.startswith(":"):
                params.append(trailing[1:])
                break

            bites = trailing.split(" ", 1)
            params.append(bites.pop(0))
            trailing = "".join(bites)

        return prefix, command, params

def format_message(command, *params):
    message = [command] + list(params[:-1]) + [":" + "".join(params[-1:])]
    return " ".join(message) + "\r\n"

ERROR_REX = re.compile("^(4|5)\d\d$")

class NickAlreadyInUse(IRCError):
    pass

def mutations(*nicks):
    for nick in nicks:
        yield nick

    for suffix in ["_", "-", "~", "^"]:
        for nick in nicks:
            yield nick[:9-len(suffix)] + suffix

    for nick in nicks:
        for i in range(1000000):
            suffix = str(i)
            yield nick[:9-len(suffix)] + suffix

@idiokit.stream
def connect(host, port, nick, password=None,
            ssl=False, ssl_verify_cert=True, ssl_ca_certs=None):
    parser = IRCParser()
    socket = sockets.Socket()

    yield socket.connect((host, port))

    if ssl:
        yield self.socket.ssl(verify_cert=self.ssl_verify_cert,
                              ca_certs=self.ssl_ca_certs)

    nicks = mutations(nick)
    if password is not None:
        yield socket.writeall(format_message("PASS", password))
    yield socket.writeall(format_message("NICK", nicks.next()))
    yield socket.writeall(format_message("USER", nick, nick, "-", nick))

    while True:
        data = yield socket.read(4096)

        for prefix, command, params in parser.feed(data):
            if command == "PING":
                yield socket.writeall(format_message("PONG", *params))
                continue

            if command == "001":
                idiokit.stop(IRC(_main(socket, parser), nick))

            if command == "433":
                for nick in nicks:
                    yield self.socket.writeall(format_message("NICK", nick))
                    break
                else:
                    raise NickAlreadyInUse("".join(params[-1:]))
                continue

                if ERROR_REX.match(command):
                    raise IRCError("".join(params[-1:]))

def _main(socket, parser):
    @idiokit.stream
    def _input():
        try:
            while True:
                msg = yield idiokit.next()
                yield socket.writeall(format_message(*msg))
        finally:
            yield socket.close()

    @idiokit.stream
    def _output():
        data = ""

        while True:
            for prefix, command, params in parser.feed(data):
                if command == "PING":
                    yield socket.writeall(format_message("PONG", *params))
                yield idiokit.send(prefix, command, params)

            data = yield socket.read(4096)

    return _input() | _output()

class IRC(idiokit.Proxy):
    def __init__(self, proxied, nick):
        idiokit.Proxy.__init__(self, proxied)

        self.nick = nick

    def set_nick(self, nick):
        return self.send("NICK", nick)

    def quit(self, message=None):
        if message is None:
            return self.send(("QUIT",))
        return self.send("QUIT", message)

    def join(self, channel, key=None):
        if key is None:
            return self.send("JOIN", channel)
        return self.send("JOIN", channel, key)
