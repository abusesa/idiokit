from __future__ import absolute_import

import re
import socket
import numbers
import subprocess

from . import idiokit, select, timer


class ResolverError(Exception):
    pass


class ResolverTimeout(ResolverError):
    pass


class _Dig(object):
    type_rex = re.compile("^[a-z0-9=]+$", re.I)

    @classmethod
    def escape_name(self, string):
        r"""
        Return a DNS name suitably escaped for dig.

        >>> _Dig.escape_name("example.com")
        '\\101\\120\\097\\109\\112\\108\\101.\\099\\111\\109'

        >>> _Dig.escape_name("example.com; ls -la")
        '\\101\\120\\097\\109\\112\\108\\101.\\099\\111\\109\\059\\032\\108\\115\\032\\045\\108\\097'

        >>> _Dig.escape_name("-m")
        '\\045\\109'

        >>> _Dig.escape_name("+tcp")
        '\\043\\116\\099\\112'
        """

        parts = []
        for part in string.split("."):
            parts.append("".join("\\{0:03d}".format(ord(ch)) for ch in part))
        return ".".join(parts)

    @idiokit.stream
    def dig(self, type, name, tcp="auto", dns_servers=(), ignore_errors=True):
        if not self.type_rex.match(type):
            raise ValueError("unknown query type " + repr(type))

        cmd = ["dig"]
        for server in dns_servers:
            cmd += ["@" + server]

        if not tcp:
            cmd.append("+notcp")
        elif tcp != "auto":
            cmd.append("+tcp")
        cmd += ["+noall", "+answer", "-t", type, "-q", self.escape_name(name)]

        dig = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True)

        answers = []
        pending = set([dig.stdout, dig.stderr])
        try:
            while True:
                while True:
                    readable, _, _ = yield select.select(pending, [], [])

                    if dig.stderr in readable:
                        line = dig.stderr.readline()
                        if not line:
                            pending.remove(dig.stderr)

                    if dig.stdout in readable:
                        break

                answer = dig.stdout.readline()
                if not answer:
                    break

                _, ttl, cls, typ, rest = answer.rstrip().split(None, 4)
                try:
                    ttl = int(ttl)
                except ValueError:
                    continue
                answers.append((ttl, cls.lower(), typ.lower(), rest.rstrip()))
        finally:
            dig.kill()
            retcode = dig.wait()

        if retcode == 0:
            idiokit.stop(answers)
        if ignore_errors:
            idiokit.stop([])
        raise ResolverError("dig exited with return value {0}".format(retcode))


def _is_ip(string):
    """
    Return whether the given string is a valid IPv4 or IPv6 address.

    >>> _is_ip("127.0.0.1")
    True
    >>> _is_ip("::1")
    True
    >>> _is_ip("x")
    False

    For convenience the function also accepts unicode values. Only
    those that can be ASCII encoded will be tested though.

    >>> _is_ip(u"127.0.0.1")
    True
    >>> _is_ip(u"::1")
    True
    >>> _is_ip(u"\xe4")
    False

    Other types are right out.

    >>> _is_ip(object())
    False
    """

    if not isinstance(string, basestring):
        return False

    if isinstance(string, unicode):
        try:
            string = string.encode("ascii")
        except ValueError:
            return False

    for _type in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(_type, string)
        except socket.error:
            continue
        return True
    return False


class Resolver(object):
    # Shared dig wrapper instance used by all resolvers.
    _dig = _Dig()

    def __init__(
            self,
            tcp="auto",
            tries=3,
            timeout=5.0,
            dns_servers=[]):
        """
        The nameservers used for resolving can either be set when the resolver
        gets initialized or later by setting the 'dns_server' attribute.

        >>> resolver = Resolver(dns_servers=["127.0.0.1", "::1"])  # upon initialization

        >>> resolver = Resolver()
        >>> resolver.dns_servers = ["127.0.0.1", "::1"]  # after initialization

        Either way the current nameserver listing can be read from the 'dns_server'
        attribute. The listing is returned as an immutable tuple.

        >>> resolver.dns_servers
        ('127.0.0.1', '::1')

        When 'dns_servers' is empty (as it is by default) the running environment's
        default nameserver selection will be used.

        >>> resolver = Resolver()
        >>> resolver.dns_servers
        ()

        Server listings should contain only IPv4 and IPv6 address strings. Other values
        raise an error.

        >>> resolver = Resolver(dns_servers=["x"])
        Traceback (most recent call last):
            ...
        ValueError: invalid DNS server address 'x'

        >>> resolver.dns_servers = ["x"]
        Traceback (most recent call last):
            ...
        ValueError: invalid DNS server address 'x'

        Resolver's 'tcp' attribute can either be True (use only TCP queries),
        False (use only UDP) or "auto" (do what you got to do). As with
        other attributes it can be set upon initialization and set and queried
        upon initialization. The default value is "auto".

        >>> resolver = Resolver()
        >>> resolver.tcp
        'auto'
        >>> resolver.tcp = True
        >>> resolver.tcp
        True

        Attribute 'tries' defines how many times each query will be tried
        before giving up. How many seconds each try is allowed take is determined
        by the attribute 'timeout'.

        >>> resolver = Resolver()
        >>> resolver.tries  # try 3 times by default
        3
        >>> resolver.timeout  # each try can take at most 5 seconds by default
        5.0

        Together these two values tell how long one resolve may take. If all
        tries have timed out a ResolverTimeout will be raised. Thus the following
        resolver raises ResolverTimeout if 0.2 seconds pass with no success:

        >>> resolver = Resolver(tries=2, timeout=0.1)

        'tries' should be an integral >= 1 and 'timeout' should be a real >= 0.0.

        >>> resolver.tries = -1
        Traceback (most recent call last):
            ...
        ValueError: value for property 'tries' should be >= 1

        >>> resolver.tries = object()
        Traceback (most recent call last):
            ...
        TypeError: value for property 'tries' should be an integral number

        >>> resolver.timeout = -1
        Traceback (most recent call last):
            ...
        ValueError: timeout should be >= 0

        >>> resolver.timeout = object()
        Traceback (most recent call last):
            ...
        TypeError: timeout should be a real number
        """

        self.tcp = tcp
        self.tries = tries
        self.timeout = timeout
        self.dns_servers = dns_servers

    @property
    def tcp(self):
        return self._tcp

    @tcp.setter
    def tcp(self, tcp):
        if tcp not in (False, True, "auto"):
            raise ValueError("value for property 'tcp' should be True, False or \"auto\"")
        self._tcp = tcp

    @property
    def tries(self):
        return self._tries

    @tries.setter
    def tries(self, tries):
        if not isinstance(tries, numbers.Integral):
            raise TypeError("value for property 'tries' should be an integral number")
        if tries < 1:
            raise ValueError("value for property 'tries' should be >= 1")
        self._tries = tries

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, timeout):
        if not isinstance(timeout, numbers.Real):
            raise TypeError("timeout should be a real number")
        if timeout < 0:
            raise ValueError("timeout should be >= 0")
        self._timeout = timeout

    @property
    def dns_servers(self):
        return self._dns_servers

    @dns_servers.setter
    def dns_servers(self, dns_servers):
        servers = []
        for server in dns_servers:
            if not _is_ip(server):
                raise ValueError("invalid DNS server address " + repr(server))
            servers.append(server)
        self._dns_servers = tuple(servers)

    def a(self, name, **options):
        """
        Perform an A query and return a list of the results.
        """

        return self._resolve("a", name, **options)

    def aaaa(self, name, **options):
        """
        Perform an AAAA query and return a list of the results.
        """

        return self._resolve("aaaa", name, **options)

    def txt(self, name, **options):
        """
        Perform a TXT query and return a list of the results.
        """

        return self._resolve("txt", name, **options)

    @idiokit.stream
    def srv(self, name, **options):
        """
        Perform an SRV query and return a list of (host, port)
        pairs sorted by priority (highest priority first).
        """

        answers = yield self._resolve("srv", name, **options)

        results = []
        for answer in answers:
            try:
                priority, _, port, host = answer.split()
                port = int(port)
                priority = int(priority)
            except ValueError:
                continue
            results.append((priority, host, port))

        results.sort()
        idiokit.stop([(host, port) for (_, host, port) in results])

    @idiokit.stream
    def _resolve(self, type, name, **options):
        orig_options = {
            "tcp": self.tcp,
            "tries": self.tries,
            "timeout": self.timeout,
            "dns_servers": self.dns_servers
        }
        final_options = dict(orig_options)
        final_options.update(options)

        if orig_options != final_options:
            results = yield Resolver(**final_options)._resolve(type, name)
            idiokit.stop(results)

        for try_number in xrange(self.tries):
            dig = self._dig.dig(
                type, name,
                tcp=self.tcp,
                dns_servers=self.dns_servers)

            try:
                answers = yield timer.timeout(self.timeout, dig, throw=ResolverTimeout())
            except ResolverTimeout as error:
                continue

            results = []
            for _, _, result_type, value in answers:
                if result_type != type:
                    continue
                results.append(value)
            idiokit.stop(results)

        raise ResolverTimeout()


global_resolver = Resolver()

a = global_resolver.a
aaaa = global_resolver.aaaa
txt = global_resolver.txt
srv = global_resolver.srv

del global_resolver
