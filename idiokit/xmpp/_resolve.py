from __future__ import absolute_import

from .. import idiokit, dns

DEFAULT_XMPP_PORT = 5222


@idiokit.stream
def _add_port_and_count(port):
    count = 0

    while True:
        try:
            family, ip = yield idiokit.next()
        except StopIteration:
            idiokit.stop(count)

        yield idiokit.send(family, ip, port)
        count += 1


def _resolve_host(host, port):
    return dns.host_lookup(host) | _add_port_and_count(port)


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
