from __future__ import with_statement, absolute_import

import re
import os
import shutil
import socket
import tempfile

# A cert to make the ssl.wrap_socket to use the system CAs.
WRAP_CERT = """
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

try:
    # Try to use the new ssl module included by default from Python
    # 2.6 onwards.
    import ssl
except ImportError:
    SSLError = socket.sslerror
    SSL_ERROR_WANT_WRITE = socket.SSL_ERROR_WANT_WRITE
    SSL_ERROR_WANT_READ = socket.SSL_ERROR_WANT_READ

    def wrap_socket(sock, verify_cert=True, ca_certs=None, identity=None):
        if verify_cert:
            raise SSLError("module 'ssl' required for certificate verification")
        return socket.ssl(sock)
else:
    SSLError = ssl.SSLError
    SSL_ERROR_WANT_WRITE = ssl.SSL_ERROR_WANT_WRITE
    SSL_ERROR_WANT_READ = ssl.SSL_ERROR_WANT_READ

    def _wrap_socket(sock, verify_cert, ca_certs):
        if not verify_cert:
            return ssl.wrap_socket(sock)

        if ca_certs is not None:
            return ssl.wrap_socket(sock,
                                   cert_reqs=ssl.CERT_REQUIRED,
                                   ca_certs=ca_certs)

        tempdir = tempfile.mkdtemp()
        try:
            filename = os.path.join(tempdir, "cert")
            with open(filename, "w+b") as temp:
                temp.write(WRAP_CERT)

            return ssl.wrap_socket(sock,
                                   cert_reqs=ssl.CERT_REQUIRED,
                                   ca_certs=filename)
        finally:
            shutil.rmtree(tempdir)

    def wrap_socket(sock, verify_cert=True, ca_certs=None, identity=None):
        wrapped = _wrap_socket(sock, verify_cert, ca_certs)
        if verify_cert and identity is not None:
            if not match_identity(wrapped.getpeercert(), identity):
                raise SSLError("failed certificate identity check")
        return wrapped

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
        common_names.extend([value for (key, value) in fields if key == "commonName"])
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

def _match_identity(pattern, identity):
    """
    >>> _match_identity("a.b", "a.b")
    True
    >>> _match_identity("*.b", "a.b")
    True
    >>> _match_identity("a.*", "a.b")
    True
    >>> _match_identity("a", "a.b")
    False
    >>> _match_identity("a.b", "b")
    False
    """

    pattern_parts = pattern.split(".")
    identity_parts = identity.split(".")
    if len(pattern_parts) != len(identity_parts):
        return False

    for pattern_part, identity_part in zip(pattern_parts, identity_parts):
        if not _match_part(pattern_part, identity_part):
            return False
    return True

def match_identity(cert, identity):
    """
    >>> cert = {
    ...     "subject": ((("commonName", "a"),),),
    ...     "subjectAltName": (("DNS", "b"), ("DNS", "c"))
    ... }
    >>> match_identity(cert, "b")
    True
    >>> match_identity(cert, "c")
    True
    >>> match_identity(cert, "a")
    False

    >>> cert = {
    ...     "subject": ((("commonName", "a"), ("commonName", "x")),)
    ... }
    >>> match_identity(cert, "a")
    False
    >>> match_identity(cert, "x")
    True
    """

    for pattern in identities(cert):
        if _match_identity(pattern, identity):
            return True
    return False
