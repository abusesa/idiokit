import re

from . import idiokit, socket, ssl, timer


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
def _init_ssl(sock, require_cert, ca_certs, identity, timeout):
    sock = yield ssl.wrap_socket(
        sock,
        require_cert=require_cert,
        ca_certs=ca_certs,
        timeout=timeout
    )
    if require_cert:
        cert = yield sock.getpeercert()
        ssl.match_hostname(cert, identity)
    idiokit.stop(sock)


@idiokit.stream
def connect(
    host,
    port,
    nick,
    password=None,
    ssl=False,
    ssl_verify_cert=True,
    ssl_ca_certs=None,
    timeout=30.0
):
    parser = IRCParser()

    sock = socket.Socket()
    yield sock.connect((host, port), timeout=timeout)
    if ssl:
        sock = yield _init_ssl(sock, ssl_verify_cert, ssl_ca_certs, host, timeout=timeout)

    nicks = mutations(nick)
    if password is not None:
        yield sock.sendall(format_message("PASS", password), timeout=timeout)
    yield sock.sendall(format_message("NICK", nicks.next()), timeout=timeout)
    yield sock.sendall(format_message("USER", nick, nick, "-", nick), timeout=timeout)

    while True:
        data = yield sock.recv(4096, timeout=timeout)
        if not data:
            raise IRCError("connection lost")

        for prefix, command, params in parser.feed(data):
            if command == "PING":
                yield sock.sendall(format_message("PONG", *params), timeout=timeout)
                continue

            if command == "001":
                idiokit.stop(IRC(_main(sock, nick, parser, write_timeout=timeout), nick))

            if command == "433":
                for nick in nicks:
                    yield sock.sendall(format_message("NICK", nick), timeout=timeout)
                    break
                else:
                    raise NickAlreadyInUse("".join(params[-1:]))
                continue

            if ERROR_REX.match(command):
                raise IRCError("".join(params[-1:]))


@idiokit.stream
def _main(sock, nick, parser, ping_interval=10.0, write_timeout=30.0):
    @idiokit.stream
    def _input():
        while True:
            try:
                msg = yield timer.timeout(ping_interval, idiokit.next())
            except timer.Timeout:
                msg = ["PING", nick]
            yield sock.sendall(format_message(*msg), timeout=write_timeout)

    @idiokit.stream
    def _output(input_stream):
        data = ""

        while True:
            for prefix, command, params in parser.feed(data):
                if command == "PING":
                    input_stream.send("PONG", *params)
                yield idiokit.send(prefix, command, params)

            data = yield sock.recv(4096, timeout=None)
            if not data:
                raise IRCError("connection lost")

    try:
        input_stream = _input()
        yield input_stream | _output(input_stream)
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
