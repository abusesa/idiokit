from __future__ import absolute_import

import os
import re
import tempfile
import platform
import contextlib
import ssl as _ssl

from . import idiokit, select, socket, timer


class SSLError(socket.SocketError):
    pass


class SSLCertificateError(SSLError):
    pass


PROTOCOL_SSLv23 = _ssl.PROTOCOL_SSLv23
PROTOCOL_SSLv3 = _ssl.PROTOCOL_SSLv3
PROTOCOL_TLSv1 = _ssl.PROTOCOL_TLSv1


# A cert to make the ssl.wrap_socket to use the system CAs.
CERT_DATA = """
-----BEGIN CERTIFICATE-----
MIIFxzCCA6+gAwIBAgIJANrA5MxUQxeMMA0GCSqGSIb3DQEBBQUAMEsxSTBHBgNV
BAMUQC0mZ01sU1FaNCwmZD01bjF5J0cjMjZKKXc9RSlEaGZ6QlVVby9XLTI0Iip1
bSgvLnZnKGItYSEoTXloLSonVGcwHhcNMTEwNTE2MTIwNzA3WhcNODYwMTIyMTIw
NzA3WjBLMUkwRwYDVQQDFEAtJmdNbFNRWjQsJmQ9NW4xeSdHIzI2Sil3PUUpRGhm
ekJVVW8vVy0yNCIqdW0oLy52ZyhiLWEhKE15aC0qJ1RnMIICIjANBgkqhkiG9w0B
AQEFAAOCAg8AMIICCgKCAgEAxaciTX1BtGDO0CrKycc3uRtWdBVFIDyr4R9J6EQ8
TmJ6qprQqjK1gNpg72UHo7ivHgHYTe5m3qAs/lBCveSo7iwpe2WXiGH+bWxzGWC4
dyBf7tItBwE/gkj/dRclygm9V9zp4m0uFmrkaQitYePod31+7viDI7kZE0eqL966
+1BLCovbXbL9wIbiDcVLJabMYOjTqdshtJWY12OF0oekpJIcSkvfaUFxwuuLQXz4
BbMc1yvtN0h78L8uQdp2G5g3485CKR+t9Pd00h2CsMr251hTLCXoNSt5JsdddxAU
qYw8bfeA9ZTMH8v3vhKAi5r1wZ2ZzaOLb91KEk/UGFgy6zNVIeUPEmyRI8IquXx4
mczF7Q6hBbTZ09H8nPCM4eKOZv8imDZTXjFyanNODgrpG7G5GLMDbRcJIN6eprJu
GcJja9aFVVwwS56901ezGk1j9ujwZA0Dva/zkW6tf6rdDekOWUlvWwh51Nt8mxJ/
KiJCp2aobmSWKHG61IV0P+pVTpi1Qo4aTFYQg2XEGdIq2cWf/v8erjrSEV4/iUDi
p4FcreBmDOXpR3Y9zULxNCV1ttadvXE9GAJY1esWZqK8NhFxPg58Rh6rdqa6Eu8c
wEo06x4DE6FWgu2lyKYGdXAQPkrNE0oZIiVvHjUTS8WcWy5hqfEToHD5pVUV4Qtv
3c0CAwEAAaOBrTCBqjAdBgNVHQ4EFgQUUg1VmzwNUp521/sE1MiYgfycYk4wewYD
VR0jBHQwcoAUUg1VmzwNUp521/sE1MiYgfycYk6hT6RNMEsxSTBHBgNVBAMUQC0m
Z01sU1FaNCwmZD01bjF5J0cjMjZKKXc9RSlEaGZ6QlVVby9XLTI0Iip1bSgvLnZn
KGItYSEoTXloLSonVGeCCQDawOTMVEMXjDAMBgNVHRMEBTADAQH/MA0GCSqGSIb3
DQEBBQUAA4ICAQCOAlLDjLQEBpqPBPSxlpH+daLVp5y7Dl0HJld5+EKaAr2684xZ
vmqrW8bx/ii+uk8GzwTjEMioo0C1/NeusKCuhayUhmY1O25X/u8g0AwWV2tD+lxN
1y0fRW6vZQK45OFDaLymM1aAnoGXdcJLIfNKlP+knYPDkQGjQ3XkdLpnVrQpX2qm
qszsI2lClfLePy3u7/8eEBUH+j2IWerjxQ5yOV+/MQvPkw0Jt2LWmaAxHF+YbqWZ
drGW6JvVjhIMI7NXho1Y4QceGVOspyAS9qMlbCTgKoU/PZZLuqRuv7s75rehF8GO
EdNOhs9sbGDsqkmOMHkyLh5kvhfYuJbhk9dMgVy8GIs5QhY1ntk8LisRbiCfNsE4
rFlB4KqXn7dHu6LF/d1Rb7iGXRKDJc+SWpvTVCN0g7KktkWDPty5CwLCwIX8aoBm
I9v4wvZOlq1LoSEi9bs8KGi5PoDmpBF4R18T7qzrE5Z7HMvD8cccP2zEepSQnC+Z
HO9ICWDSY09Ahip73dCYbWwiwCvNbbp57nMTnN+8AHQlLiZ85IO1wmbEJ34gQRgR
6TU6z6yeMorMqcLRS0sEO5S4RduLGinaxkpHZ4uKnRt1SKTBXC0iB6uQ/pfhjVrv
O1m5HRRBQdjLoUrIsOby9i0rQyoEYE44YlUVgLbTKNL2zl+b+Sn/zg5Z+g==
-----END CERTIFICATE-----
"""


@contextlib.contextmanager
def _dummy_cert():
    fd, path = tempfile.mkstemp()
    try:
        index = 0
        while index < len(CERT_DATA):
            index += os.write(fd, CERT_DATA[index:])
        os.fsync(fd)

        yield path
    finally:
        os.close(fd)
        os.remove(path)


def _constant_cert(filename):
    @contextlib.contextmanager
    def _cert():
        yield filename
    return _cert


_distro = platform.linux_distribution(full_distribution_name=False)[0].lower()
if _distro == "ubuntu":
    _default_cert = _constant_cert("/etc/ssl/certs/ca-certificates.crt")
elif _distro == "centos":
    _default_cert = _constant_cert("/etc/pki/tls/certs/ca-bundle.crt")
else:
    _default_cert = _dummy_cert


@idiokit.stream
def _wrapped(ssl, timeout, func, *args, **keys):
    with socket.wrapped_socket_errors():
        for _, timeout in socket.countdown(timeout):
            try:
                result = func(*args, **keys)
            except _ssl.SSLError as err:
                if err.errno == _ssl.SSL_ERROR_WANT_READ:
                    yield select.select((ssl,), (), (), timeout)
                elif err.errno == _ssl.SSL_ERROR_WANT_WRITE:
                    yield select.select((), (ssl,), (), timeout)
                else:
                    raise SSLError(*err.args)
            else:
                idiokit.stop(result)


@idiokit.stream
def wrap_socket(sock,
                keyfile=None,
                certfile=None,
                server_side=False,
                ssl_version=None,
                require_cert=False,
                ca_certs=None,
                timeout=None):
    if ssl_version is None:
        ssl_version = PROTOCOL_SSLv23 if server_side else PROTOCOL_SSLv3

    keys = dict(
        keyfile=keyfile,
        certfile=certfile,
        server_side=server_side,
        cert_reqs=_ssl.CERT_REQUIRED if require_cert else _ssl.CERT_NONE,
        ssl_version=ssl_version,
        do_handshake_on_connect=False,
        suppress_ragged_eofs=True)

    if not require_cert or ca_certs is not None:
        cert = _constant_cert(ca_certs)
    else:
        cert = _default_cert

    with cert() as cert_file:
        ssl = _ssl.wrap_socket(sock._socket, ca_certs=cert_file, **keys)
        yield _wrapped(ssl, timeout, ssl.do_handshake)
    idiokit.stop(_SSLSocket(ssl))


class _SSLSocket(object):
    CHUNK_SIZE = 8 * 1024

    def __init__(self, ssl):
        self._ssl = ssl

    @idiokit.stream
    def getpeercert(self, binary_form=False):
        yield timer.sleep(0.0)
        idiokit.stop(self._ssl.getpeercert(binary_form))

    @idiokit.stream
    def recv(self, bufsize, flags=0, timeout=None):
        if flags != 0:
            raise ValueError("flags not supported by SSL sockets")

        if bufsize <= 0:
            yield timer.sleep(0.0)
            idiokit.stop("")

        result = yield _wrapped(self._ssl, timeout, self._ssl.read, bufsize)
        idiokit.stop(result)

    @idiokit.stream
    def send(self, data, flags=0, timeout=None):
        socket.check_sendable_type(data)
        if flags != 0:
            raise ValueError("flags not supported by SSL sockets")

        buf = buffer(data, 0, self.CHUNK_SIZE)
        result = yield _wrapped(self._ssl, timeout, self._ssl.write, buf)
        idiokit.stop(result)

    @idiokit.stream
    def sendall(self, data, flags=0, timeout=None):
        socket.check_sendable_type(data)
        if flags != 0:
            raise ValueError("flags not supported by SSL sockets")

        offset = 0
        length = len(data)

        for _, timeout in socket.countdown(timeout):
            buf = buffer(data, offset, self.CHUNK_SIZE)
            bytes = yield _wrapped(self._ssl, timeout, self._ssl.write, buf)

            offset += bytes
            if offset >= length:
                break

    def fileno(self):
        return self._ssl.fileno()


def identities(cert):
    """
    RFC2818: "If a subjectAltName extension of type dNSName is present,
    that MUST be used as the identity."

    >>> identities({
    ...     "subject": ((("commonName", "a"),),),
    ...     "subjectAltName": (("DNS", "x"),)
    ... })
    ['x']

    RFC2818: "Otherwise, the (most specific) Common Name field in the
    Subject field of the certificate MUST be used."

    >>> identities({
    ...     "subject": ((("commonName", "a"), ("commonName", "a.b")),)
    ... })
    ['a.b']

    RFC2818: "If more than one identity of a given type is present in
    the certificate (e.g., more than one dNSName name, a match in any one
    of the set is considered acceptable.)"

    >>> sorted(identities({
    ...     "subjectAltName": (("DNS", "x"), ("DNS", "x.y"))
    ... }))
    ['x', 'x.y']
    """

    alt_name = cert.get("subjectAltName", ())
    dns_names = [value for (key, value) in alt_name if key == "DNS"]
    if dns_names:
        return dns_names

    common_names = list()
    for fields in cert.get("subject", ()):
        common_names.extend(value for (key, value) in fields if key == "commonName")
    if common_names:
        return common_names[-1:]

    return []


def _match_part(pattern, part):
    rex_chars = list()
    for ch in pattern:
        if ch == "*":
            rex_chars.append(".*")
        else:
            rex_chars.append(re.escape(ch))
    rex_pattern = "".join(rex_chars)
    return re.match(rex_pattern, part, re.I) is not None


def _match_hostname(pattern, hostname):
    """
    >>> _match_hostname("a.b", "a.b")
    True
    >>> _match_hostname("*.b", "a.b")
    True
    >>> _match_hostname("a.*", "a.b")
    True
    >>> _match_hostname("a", "a.b")
    False
    >>> _match_hostname("a.b", "b")
    False
    """

    pattern_parts = pattern.split(".")
    hostname_parts = hostname.split(".")
    if len(pattern_parts) != len(hostname_parts):
        return False

    for pattern_part, hostname_part in zip(pattern_parts, hostname_parts):
        if not _match_part(pattern_part, hostname_part):
            return False
    return True


def match_hostname(cert, hostname):
    """
    >>> cert = {
    ...     "subject": ((("commonName", "a"),),),
    ...     "subjectAltName": (("DNS", "b"), ("DNS", "c"))
    ... }
    >>> match_hostname(cert, "b")
    >>> match_hostname(cert, "c")
    >>> match_hostname(cert, "a")
    Traceback (most recent call last):
    ...
    SSLCertificateError: hostname 'a' doesn't match 'b' or 'c'

    >>> cert = {
    ...     "subject": ((("commonName", "a"), ("commonName", "x")),)
    ... }
    >>> match_hostname(cert, "x")
    >>> match_hostname(cert, "a")
    Traceback (most recent call last):
    ...
    SSLCertificateError: hostname 'a' doesn't match 'x'

    >>> match_hostname({}, "x")
    Traceback (most recent call last):
    ...
    SSLCertificateError: certificate doesn't contain any hostname patterns
    """

    id_list = list(identities(cert))
    if not id_list:
        message = "certificate doesn't contain any hostname patterns"
        raise SSLCertificateError(message)

    for identity in id_list:
        if _match_hostname(identity, hostname):
            return

    if len(id_list) == 1:
        id_string = repr(id_list[0])
    else:
        id_string = ", ".join(map(repr, id_list[:-1]))
        id_string += " or " + repr(id_list[-1])
    message = "hostname {0!r} doesn't match {1}".format(hostname, id_string)
    raise SSLCertificateError(message)


if __name__ == "__main__":
    import doctest
    doctest.testmod()
