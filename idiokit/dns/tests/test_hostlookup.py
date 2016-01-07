import idiokit
import unittest
import tempfile
from socket import AF_INET, AF_INET6

from .. import _hostlookup
from .. import _dns


class HostLookupTests(unittest.TestCase):
    def setUp(self):
        self._hosts = tempfile.NamedTemporaryFile()
        self._hosts.writelines([
            "198.51.100.126 ipv4.idiokit.example\n",
            "2001:DB8::cafe ipv6.idiokit.example\n"
        ])
        self._hosts.flush()

    def tearDown(self):
        self._hosts.close()

    def _host_lookup(self, lookup):
        hl = _hostlookup.HostLookup(hosts_file=self._hosts.name)
        return idiokit.main_loop(hl.host_lookup(lookup))

    def test_ipv4_host_lookup_with_ip(self):
        self.assertEqual(
            [(AF_INET, "198.51.100.126")],
            self._host_lookup("198.51.100.126")
        )

    def test_ipv4_host_lookup_with_name(self):
        self.assertEqual(
            [(AF_INET, "198.51.100.126")],
            self._host_lookup("ipv4.idiokit.example")
        )

    def test_ipv6_host_lookup_with_ip(self):
        self.assertEqual(
            [(AF_INET6, "2001:db8::cafe")],
            self._host_lookup("2001:DB8::cafe")
        )

    def test_ipv6_host_lookup_with_name(self):
        self.assertEqual(
            [(AF_INET6, "2001:db8::cafe")],
            self._host_lookup("ipv6.idiokit.example")
        )

    def test_ipv6_host_lookup_with_unknown_name(self):
        self.assertRaises(_dns.ResponseError, self._host_lookup, "notfound.idiokit.example")
