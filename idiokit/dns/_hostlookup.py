from .. import idiokit
from ._iputils import parse_ip
from ._conf import hosts
from ._dns import DNSError, a, aaaa


class HostLookup(object):
    _hosts = hosts()

    @idiokit.stream
    def _send_ips(self, ips):
        count = 0

        for ip in ips:
            try:
                family, ip = parse_ip(ip)
            except ValueError:
                continue
            yield idiokit.send(family, ip)
            count += 1

        idiokit.stop(count)

    @idiokit.stream
    def host_lookup(self, host, resolver=None):
        count = yield self._send_ips([host])
        if count > 0:
            return

        count = yield self._send_ips(self._hosts.load().name_to_ips(host))
        if count > 0:
            return

        error = None
        try:
            records = yield a(host, resolver)
        except DNSError as error:
            pass
        else:
            yield self._send_ips(records)

        try:
            records = yield aaaa(host, resolver)
        except DNSError:
            if error is not None:
                raise error
        else:
            yield self._send_ips(records)


host_lookup = HostLookup().host_lookup
