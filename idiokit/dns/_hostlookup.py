from .. import idiokit
from ._iputils import parse_ip
from ._conf import hosts
from ._dns import DNSError, a, aaaa


def _filter_ips(potential_ips):
    results = []
    for ip in potential_ips:
        try:
            family, ip = parse_ip(ip)
        except ValueError:
            continue
        else:
            results.append((family, ip))
    return results


class HostLookup(object):
    def __init__(self, hosts_file=None):
        if hosts_file:
            self._hosts = hosts(path=hosts_file)
        else:
            self._hosts = hosts()

    @idiokit.stream
    def host_lookup(self, host, resolver=None):
        results = _filter_ips([host])

        if not results:
            results = _filter_ips(self._hosts.load().name_to_ips(host))

        if not results:
            results = []
            error = None
            try:
                records = yield a(host, resolver)
            except DNSError as error:
                results = []
            else:
                results = _filter_ips(records)

            try:
                records = yield aaaa(host, resolver)
            except DNSError:
                if error is not None:
                    raise error
            else:
                results.extend(_filter_ips(records))

        idiokit.stop(results)


host_lookup = HostLookup().host_lookup
