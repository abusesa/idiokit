from __future__ import with_statement, absolute_import

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

    def wrap_socket(sock, verify_cert=True, ca_certs=None):
        if verify_cert:
            raise SSLError("module 'ssl' required for certificate verification")
        return socket.ssl(sock)
else:
    SSLError = ssl.SSLError
    SSL_ERROR_WANT_WRITE = ssl.SSL_ERROR_WANT_WRITE
    SSL_ERROR_WANT_READ = ssl.SSL_ERROR_WANT_READ

    def wrap_socket(sock, verify_cert=True, ca_certs=None):
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
