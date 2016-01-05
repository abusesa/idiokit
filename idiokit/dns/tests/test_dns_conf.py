import unittest
import tempfile

from .. import _conf


class HostsFileTests(unittest.TestCase):
    def setUp(self):
        missing = tempfile.NamedTemporaryFile()
        self._missing_file = missing.name
        missing.close()  # Close deletes the file

        self._empty_file = tempfile.NamedTemporaryFile()
        self._empty_file.flush()

        # Make sure empty and missing files are not same
        self.assertNotEqual(self._empty_file.name, self._missing_file)

        self._hosts = tempfile.NamedTemporaryFile()
        self._hosts.writelines(
            ["# Comments are ignored\n",
             "198.51.100.1 # This line should be ignored\n"
             "256.256.256.256 invalid-ip # Invalid IP should be ignored\n",
             "\n",
             "  198.51.100.126    IPv4.documentation.net.example   \n",
             "# Hosts file can have tab separator also\n",
             "2001:DB8::cafe \t IPv6.documentation.net.example\n",
             "198.51.100.0 incomplete.last.line.net.example"
             ]
        )
        self._hosts.flush()

    def tearDown(self):
        if self._empty_file:
            self._empty_file.close()

        if self._hosts:
            self._hosts.close()

    def test_hosts_missing_file(self):
        hosts = _conf.hosts(path=self._missing_file).load()
        self.assertEqual(hosts._ips, {})
        self.assertEqual(hosts._names, {})

    def test_hosts_empty_file(self):
        hosts = _conf.hosts(path=self._empty_file.name).load()
        self.assertEqual(hosts._ips, {})
        self.assertEqual(hosts._names, {})

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

    def test_hosts_incomplete_last_line(self):
        hosts = _conf.hosts(path=self._hosts.name).load()
        for ip in hosts.name_to_ips("incomplete.last.line.net.example"):
            self.assertEqual(ip, "198.51.100.0")
        for name in hosts.ip_to_names("198.51.100.0"):
            self.assertEqual(name, "incomplete.last.line.net.example")
            return
        self.assertTrue(False)

    def test_hosts_invalid_ipv4_to_names(self):
        hosts = _conf.hosts(path=self._hosts.name).load()
        self.assertRaises(ValueError, hosts.ip_to_names, "256.256.256.256")

    def test_hosts_invalid_ipv6_to_names(self):
        hosts = _conf.hosts(path=self._hosts.name).load()
        self.assertRaises(ValueError, hosts.ip_to_names, "2001:db8::gg")


class ResolvConfFileTests(unittest.TestCase):
    def setUp(self):
        missing = tempfile.NamedTemporaryFile()
        self._missing_file = missing.name
        missing.close()  # Close deletes the file

        self._empty_file = tempfile.NamedTemporaryFile()
        self._empty_file.flush()

        # Make sure empty and missing files are not same
        self.assertNotEqual(self._empty_file.name, self._missing_file)

        self._resolv_conf = tempfile.NamedTemporaryFile()
        self._resolv_conf.writelines(
            ["# Comments are ignored\n",
             "; This comment also ignored\n",
             "this-is-ignored-also\n",
             "domain idiokit.test.example\n",
             "nameserver 192.0.2.11\n",
             "nameserver 2001:DB8:CAFE::11\n",
             "nameserver 2001:db8:cafe::11\n",
             "nameserver dns1.idiokit.test.example\n",
             ]
        )
        self._resolv_conf.flush()

    def tearDown(self):
        if self._empty_file:
            self._empty_file.close()

        if self._resolv_conf:
            self._resolv_conf.close()

    def test_resolv_conf_missing_file(self):
        rc = _conf.resolv_conf(path=self._missing_file).load()
        self.assertEqual(rc._servers, ())

    def test_resolv_conf_empty_file(self):
        rc = _conf.resolv_conf(path=self._empty_file.name).load()
        self.assertEqual(rc._servers, ())

    def test_resolv_conf_servers(self):
        rc = _conf.resolv_conf(path=self._resolv_conf.name).load()
        self.assertEqual(
            rc.servers,
            (('192.0.2.11', 53), ('2001:db8:cafe::11', 53))
        )
