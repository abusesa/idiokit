import re

from . import idiokit, socket, ssl


class IRCError(Exception):
    pass


class IRCParser(object):
    def __init__(self):
        self.buffer = ""

    def feed(self, data=""):
        lines = re.split("\r?\n", self.buffer + data)
        self.buffer = lines.pop()

        for line in lines:
            if "\x00" in line:
                raise IRCError("NUL not allowed in messages")
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
            yield nick[:9 - len(suffix)] + suffix

    for nick in nicks:
        for i in range(1000000):
            suffix = str(i)
            yield nick[:9 - len(suffix)] + suffix


@idiokit.stream
def _init_ssl(sock, require_cert, ca_certs, identity):
    sock = yield ssl.wrap_socket(sock,
                                 require_cert=require_cert,
                                 ca_certs=ca_certs)
    if require_cert:
        cert = yield sock.getpeercert()
        ssl.match_hostname(cert, identity)
    idiokit.stop(sock)


@idiokit.stream
def connect(host, port, nick, password=None,
            ssl=False, ssl_verify_cert=True, ssl_ca_certs=None):
    parser = IRCParser()

    sock = socket.Socket()
    yield sock.connect((host, port))
    if ssl:
        sock = yield _init_ssl(sock, ssl_verify_cert, ssl_ca_certs, host)

    nicks = mutations(nick)
    if password is not None:
        yield sock.sendall(format_message("PASS", password))
    yield sock.sendall(format_message("NICK", nicks.next()))
    yield sock.sendall(format_message("USER", nick, nick, "-", nick))

    while True:
        data = yield sock.recv(4096)
        if not data:
            raise IRCError("connection lost")

        for prefix, command, params in parser.feed(data):
            if command == "PING":
                yield sock.sendall(format_message("PONG", *params))
                continue

            if command == "001":
                idiokit.stop(IRC(_main(sock, parser), nick))

            if command == "433":
                for nick in nicks:
                    yield sock.sendall(format_message("NICK", nick))
                    break
                else:
                    raise NickAlreadyInUse("".join(params[-1:]))
                continue

            if ERROR_REX.match(command):
                raise IRCError("".join(params[-1:]))


@idiokit.stream
def _main(sock, parser):
    @idiokit.stream
    def _input():
        while True:
            msg = yield idiokit.next()
            yield sock.sendall(format_message(*msg))

    @idiokit.stream
    def _output():
        data = ""

        while True:
            for prefix, command, params in parser.feed(data):
                if command == "PING":
                    yield sock.sendall(format_message("PONG", *params))
                yield idiokit.send(prefix, command, params)

            data = yield sock.recv(4096)
            if not data:
                raise IRCError("connection lost")

    try:
        yield _input() | _output()
    finally:
        yield sock.close()


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
