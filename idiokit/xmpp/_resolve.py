from __future__ import absolute_import

from .. import idiokit, dns

DEFAULT_XMPP_PORT = 5222


@idiokit.stream
def _add_port(port):
    while True:
        family, ip = yield idiokit.next()
        yield idiokit.send(family, ip, port)


def _resolve_host(host, port):
    return dns.host_lookup(host) | _add_port(port)


@idiokit.stream
def resolve(domain, forced_host=None, forced_port=None):
    if forced_host is not None:
        port = DEFAULT_XMPP_PORT if forced_port is None else forced_port
        yield _resolve_host(forced_host, port)
        return

    try:
        srv_records = yield dns.srv("_xmpp-client._tcp." + domain)
    except (dns.ResponseError, dns.DNSTimeout):
        srv_records = []

    if not srv_records:
        port = DEFAULT_XMPP_PORT if forced_port is None else forced_port
        yield _resolve_host(domain, port)
        return

    for srv_record in dns.ordered_srv_records(srv_records):
        port = srv_record.port if forced_port is None else forced_port
        yield _resolve_host(srv_record.target, port)
