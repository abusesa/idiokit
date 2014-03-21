from __future__ import absolute_import

import socket
from .. import idiokit, dns

DEFAULT_XMPP_PORT = 5222


@idiokit.stream
def _resolve_host(host, port):
    for family in [socket.AF_INET, socket.AF_INET6]:
        try:
            socket.inet_pton(family, host)
        except socket.error:
            continue

        yield idiokit.send(family, host, port)
        idiokit.stop(1)

    a = yield dns.a(host)
    for ip in a:
        yield idiokit.send(socket.AF_INET, ip, port)

    aaaa = yield dns.aaaa(host)
    for ip in aaaa:
        yield idiokit.send(socket.AF_INET6, ip, port)

    idiokit.stop(len(a) + len(aaaa))


@idiokit.stream
def resolve(domain, forced_host=None, forced_port=None):
    if forced_host is not None:
        port = DEFAULT_XMPP_PORT if forced_port is None else forced_port
        yield _resolve_host(forced_host, port)
        return

    try:
        srv_records = yield dns.srv("_xmpp-client._tcp." + domain)
    except dns.ResponseError:
        srv_records = []

    srv_count = 0
    for srv_record in dns.ordered_srv_records(srv_records):
        port = srv_record.port if forced_port is None else forced_port
        srv_count += yield _resolve_host(srv_record.target, port)

    if srv_count == 0:
        port = DEFAULT_XMPP_PORT if forced_port is None else forced_port
        yield _resolve_host(domain, port)
