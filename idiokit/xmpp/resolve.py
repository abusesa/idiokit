from __future__ import absolute_import

import socket
from subprocess import Popen, PIPE

DEFAULT_XMPP_PORT = 5222
DEFAULT_XMPP_SERVICE = "xmpp-client"

class Resolver(object):
    _resolvers = list()

    def __init__(self, forced_host=None, forced_port=None):
        self.host = forced_host
        self.port = forced_port

    def resolve(self, domain):
        if self.host is not None:
            if self.port is None:
                port = DEFAULT_XMPP_PORT
            else:
                port = self.port

            for result in getaddrinfo(self.host, port):
                yield result
            return

        if self.port is None:
            port_or_service = DEFAULT_XMPP_SERVICE
        else:
            port_or_service = self.port

        for resolver in self._resolvers:
            got_anything = False

            for result in resolver(domain, port_or_service):
                got_anything = True
                yield result

            if got_anything:
                return

        if self.port is None:
            for result in getaddrinfo(domain, DEFAULT_XMPP_PORT):
                yield result

def getaddrinfo(host_or_domain, port_or_service):
    try:
        for result in socket.getaddrinfo(host_or_domain,
                                         port_or_service,
                                         socket.AF_INET,
                                         socket.SOCK_STREAM,
                                         socket.IPPROTO_TCP):
            yield result
    except socket.gaierror:
        return
Resolver._resolvers.append(getaddrinfo)

def dig(domain, service):
    command = "dig", "+short", "srv", "_%s._tcp.%s" % (service, domain)
    try:
        popen = Popen(command, stdout=PIPE, stdin=PIPE, stderr=PIPE)
        lines = popen.communicate()[0].splitlines()
    except OSError:
        return

    results = list()
    for line in lines:
        try:
            priority, _, port, host = line.split()
            port = int(port)
            priority = int(priority)
        except ValueError:
            continue
        results.append((priority, host, port))

    for _, host, port in sorted(results):
        for result in getaddrinfo(host, port):
            yield result
Resolver._resolvers.append(dig)
