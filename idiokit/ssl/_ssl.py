from __future__ import absolute_import

import os
import shutil
import tempfile

import ssl as _ssl

from .. import idiokit, select, socket, timer

class SSLError(socket.SocketError):
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

@idiokit.stream
def _wrapped(ssl, timeout, func, *args, **keys):
    with socket.wrapped_socket_errors():
        for _, timeout in socket.countdown(timeout):
            try:
                result = func(*args, **keys)
            except _ssl.SSLError as err:
                if err.args[0] == _ssl.SSL_ERROR_WANT_READ:
                    yield select.select((ssl,), (), (), timeout)
                elif err.args[0] == _ssl.SSL_ERROR_WANT_WRITE:
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
                ssl_version=PROTOCOL_SSLv23,
                require_cert=False,
                ca_certs=None,
                timeout=None):
    keys = dict(
        keyfile=keyfile,
        certfile=certfile,
        server_side=server_side,
        cert_reqs=_ssl.CERT_REQUIRED if require_cert else _ssl.CERT_NONE,
        ssl_version=ssl_version,
        do_handshake_on_connect=False,
        suppress_ragged_eofs=True)

    if not require_cert or ca_certs is not None:
        ssl = _ssl.wrap_socket(sock._socket, ca_certs=ca_certs, **keys)
        yield _wrapped(ssl, timeout, ssl.do_handshake)
    else:
        tempdir = tempfile.mkdtemp()
        try:
            filename = os.path.join(tempdir, "cert")
            with open(filename, "w+b") as temp:
                temp.write(CERT_DATA)
            ssl = _ssl.wrap_socket(sock._socket, ca_certs=filename, **keys)
            yield _wrapped(ssl, timeout, ssl.do_handshake)
        finally:
            shutil.rmtree(tempdir)
    idiokit.stop(_SSLSocket(ssl))

class _SSLSocket(object):
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
        result = yield _wrapped(self._ssl, timeout, self._ssl.read, bufsize)
        idiokit.stop(result)

    @idiokit.stream
    def send(self, data, flags=0, timeout=None):
        if flags != 0:
            raise ValueError("flags not supported by SSL sockets")
        result = yield _wrapped(self._ssl, timeout, self._ssl.write, data)
        idiokit.stop(result)

    @idiokit.stream
    def sendall(self, string, flags=0, timeout=None, chunk_size=1024):
        offset = 0
        length = len(string)

        for _, timeout in socket.countdown(timeout):
            chunk = string[offset:offset+chunk_size]

            bytes = yield self.send(chunk, flags, timeout)

            offset += bytes
            if offset >= length:
                break
