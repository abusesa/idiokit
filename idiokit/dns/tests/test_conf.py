import os
import shutil
import unittest
import tempfile
import contextlib

from .. import _conf


@contextlib.contextmanager
def tmpdir():
    path = tempfile.mkdtemp()
    try:
        yield path
    finally:
        shutil.rmtree(path)


@contextlib.contextmanager
def tmpfile(*lines):
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.writelines(lines)
        tmp.flush()
        yield tmp.name


class HostsFileTests(unittest.TestCase):
    lines = [
        "# Comments are ignored\n",
        "198.51.100.1 # This line should be ignored\n"
        "256.256.256.256 invalid-ip # Invalid IP should be ignored\n",
        "\n",
        "  198.51.100.126    IPv4.documentation.net.example   \n",
        "# Hosts file can have tab separator also\n",
        "2001:DB8::cafe \t IPv6.documentation.net.example\n",
        "198.51.100.0 incomplete.last.line.net.example"
    ]

    def test_hosts_missing_file(self):
        with tmpdir() as path:
            filepath = os.path.join(path, "does-not-exist")
            hosts = _conf.hosts(path=filepath).load()

        self.assertEqual(hosts.ips, ())
        self.assertEqual(hosts.names, ())

    def test_hosts_empty_file(self):
        with tmpfile() as empty:
            hosts = _conf.hosts(path=empty).load()

        self.assertEqual(hosts.ips, ())
        self.assertEqual(hosts.names, ())

    def test_hosts_ipv4_to_names(self):
        with tmpfile(*self.lines) as filename:
            hosts = _conf.hosts(path=filename).load()

        self.assertEqual(
            list(hosts.ip_to_names("198.51.100.126")),
            ["ipv4.documentation.net.example"]
        )

    def test_hosts_ipv6_to_names(self):
        with tmpfile(*self.lines) as filename:
            hosts = _conf.hosts(path=filename).load()

        self.assertEqual(
            list(hosts.ip_to_names("2001:DB8::cafe")),
            ["ipv6.documentation.net.example"]
        )

    def test_hosts_name_to_ipv4(self):
        with tmpfile(*self.lines) as filename:
            hosts = _conf.hosts(path=filename).load()

        self.assertEqual(
            list(hosts.name_to_ips("ipv4.documentation.net.EXAMPLE")),
            ["198.51.100.126"]
        )

    def test_hosts_name_to_ipv6(self):
        with tmpfile(*self.lines) as filename:
            hosts = _conf.hosts(path=filename).load()

        self.assertEqual(
            list(hosts.name_to_ips("ipv6.documentation.net.EXAMPLE")),
            ["2001:db8::cafe"]
        )

    def test_hosts_incomplete_last_line(self):
        with tmpfile(*self.lines) as filename:
            hosts = _conf.hosts(path=filename).load()

        self.assertEqual(
            list(hosts.name_to_ips("incomplete.last.line.net.example")),
            ["198.51.100.0"]
        )
        self.assertEqual(
            list(hosts.ip_to_names("198.51.100.0")),
            ["incomplete.last.line.net.example"]
        )

    def test_hosts_invalid_ipv4_to_names(self):
        with tmpfile(*self.lines) as filename:
            hosts = _conf.hosts(path=filename).load()
        self.assertRaises(ValueError, hosts.ip_to_names, "256.256.256.256")

    def test_hosts_invalid_ipv6_to_names(self):
        with tmpfile(*self.lines) as filename:
            hosts = _conf.hosts(path=filename).load()
        self.assertRaises(ValueError, hosts.ip_to_names, "2001:db8::gg")


class ResolvConfFileTests(unittest.TestCase):
    def test_resolv_conf_missing_file(self):
        with tmpdir() as path:
            filepath = os.path.join(path, "does-not-exist")
            rc = _conf.resolv_conf(path=filepath).load()

        self.assertEqual(rc.servers, ())

    def test_resolv_conf_empty_file(self):
        with tmpfile() as empty:
            rc = _conf.resolv_conf(path=empty).load()

        self.assertEqual(rc.servers, ())

    def test_resolv_conf_servers(self):
        with tmpfile(
            "# Comments are ignored\n",
            "; This comment also ignored\n",
            "this-is-ignored-also\n",
            "domain idiokit.test.example\n",
            "nameserver 192.0.2.11\n",
            "nameserver 2001:DB8:CAFE::11\n",
            "nameserver 2001:db8:cafe::11\n",
            "nameserver dns1.idiokit.test.example\n",
        ) as filename:
            rc = _conf.resolv_conf(path=filename).load()

        self.assertEqual(
            rc.servers,
            (('192.0.2.11', 53), ('2001:db8:cafe::11', 53))
        )
