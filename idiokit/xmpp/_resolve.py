from __future__ import absolute_import

from .. import idiokit, dns

DEFAULT_XMPP_PORT = 5222


@idiokit.stream
def _resolve_host(host, port):
    results = yield dns.host_lookup(host)
    idiokit.stop([(family, ip, port) for (family, ip) in results])


@idiokit.stream
def resolve(domain, forced_host=None, forced_port=None):
    if forced_host is not None:
        port = DEFAULT_XMPP_PORT if forced_port is None else forced_port
        results = yield _resolve_host(forced_host, port)
        idiokit.stop(results)

    try:
        srv_records = yield dns.srv("_xmpp-client._tcp." + domain)
    except (dns.ResponseError, dns.DNSTimeout):
        srv_records = []

    if not srv_records:
        port = DEFAULT_XMPP_PORT if forced_port is None else forced_port
        results = yield _resolve_host(domain, port)
        idiokit.stop(results)

    ordered_results = []
    for srv_record in dns.ordered_srv_records(srv_records):
        port = srv_record.port if forced_port is None else forced_port
        results = yield _resolve_host(srv_record.target, port)
        ordered_results.extend(results)
    idiokit.stop(ordered_results)
