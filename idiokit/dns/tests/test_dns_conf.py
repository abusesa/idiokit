import unittest
import tempfile

from .. import _conf


class HostsFileTests(unittest.TestCase):
    _hosts = None

    def setUp(self):
        self._hosts = tempfile.NamedTemporaryFile()
        self._hosts.writelines(
            ["# Comments are ignored\n",
             "198.51.100.1 # This line should be ignored\n"
             "256.256.256.256 invalid-ip # Invalid IP should be ignored\n",
             "\n",
             "  198.51.100.126    IPv4.documentation.net.example   \n",
             "# Hosts file can have tab separator also\n",
             "2001:DB8::cafe \t IPv6.documentation.net.example\n",
             ]
        )
        self._hosts.flush()

    def tearDown(self):
        if self._hosts:
            self._hosts.close()

    def test_hosts_ipv4_to_names(self):
        hosts = _conf.hosts(path=self._hosts.name).load()
        for name in hosts.ip_to_names("198.51.100.126"):
            self.assertEqual(name, "ipv4.documentation.net.example")
            return
        self.assertTrue(False)

    def test_hosts_ipv6_to_names(self):
        hosts = _conf.hosts(path=self._hosts.name).load()
        for name in hosts.ip_to_names("2001:DB8::cafe"):
            self.assertEqual(name, "ipv6.documentation.net.example")
            return
        self.assertTrue(False)

    def test_hosts_name_to_ipv4(self):
        hosts = _conf.hosts(path=self._hosts.name).load()
        for ip in hosts.name_to_ips("ipv4.documentation.net.EXAMPLE"):
            self.assertEqual(ip, "198.51.100.126")
            return
        self.assertTrue(False)

    def test_hosts_name_to_ipv6(self):
        hosts = _conf.hosts(path=self._hosts.name).load()
        for ip in hosts.name_to_ips("ipv6.documentation.net.EXAMPLE"):
            self.assertEqual(ip, "2001:db8::cafe")
            return
        self.assertTrue(False)

    def test_hosts_invalid_ipv4_to_names(self):
        hosts = _conf.hosts(path=self._hosts.name).load()
        self.assertRaises(ValueError, hosts.ip_to_names, "256.256.256.256")

    def test_hosts_invalid_ipv6_to_names(self):
        hosts = _conf.hosts(path=self._hosts.name).load()
        self.assertRaises(ValueError, hosts.ip_to_names, "2001:db8::gg")
