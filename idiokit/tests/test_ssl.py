import os
import shutil
import inspect
import tempfile
import unittest
import contextlib
import socket as stdlib_socket

from .. import idiokit, socket, ssl


@contextlib.contextmanager
def tmpdir():
    path = tempfile.mkdtemp()
    try:
        yield path
    finally:
        shutil.rmtree(path)


class TestWrapSocket(unittest.TestCase):
    @idiokit.stream
    def _test_wrap_socket(self, client_conn, server_conn, require_cert=False):
        # Self-signed combined certfile/keyfile created using cfssl version
        # 1.2.0 with the following command:
        #   echo '{"key":{"algo":"rsa","size":2048}}' | cfssl selfsign idiokit.example -
        certdata = inspect.cleandoc("""
            -----BEGIN CERTIFICATE-----
            MIIDATCCAemgAwIBAgIICZaQBavdnb0wDQYJKoZIhvcNAQELBQAwADAeFw0xNjA0
            MDcxMzMzNDBaFw0xNjA3MDcxOTM4NDBaMAAwggEiMA0GCSqGSIb3DQEBAQUAA4IB
            DwAwggEKAoIBAQDLYuXhBLrkpgOE2QCtO5RzPo9hXu5c5oKxOF2ucHt/gEDDd8zv
            VkW680Q2J2p+yBDtrLojhQ83rLA5PXFP1neamafNY+mQ0kPAyVZaY+kDcjPVL0Ua
            mxJ2KX4bpcC6re58uoR4jmcrHzIfDaENHBnW2uxsO0nkZUBoAMYUxlk5kkaKxq3p
            OYoVxyNskd8emqZmzqeYq1+5FnbSXrjkbmmHRs7azpkYM558KdKH2teI3zghy19r
            jr2C9XIcHodDK+k1H8lW5ohMRNogl4g6kB6OiS/mCOPAO+JAjh1krA8yeDK1trh4
            wpZpPlJFVA2ien0a9mtcuSwE/KkNCDRzMsofAgMBAAGjfzB9MA4GA1UdDwEB/wQE
            AwIFoDAdBgNVHSUEFjAUBggrBgEFBQcDAQYIKwYBBQUHAwIwDAYDVR0TAQH/BAIw
            ADAdBgNVHQ4EFgQUzztWrdAkmIG7D6GTbAqCJ22Wd+0wHwYDVR0jBBgwFoAUzztW
            rdAkmIG7D6GTbAqCJ22Wd+0wDQYJKoZIhvcNAQELBQADggEBAHB+6zStVfMtLsFg
            dhBkTqJXPANeqn9P0KKwUg2KQBgk7e+uQDJMfmdE1coBtHAexsNf1ko6gcTzFQMk
            DmNbQBxKbb9lJaEaorzVVxg+PenEeRBcwYfw6Yf96tAR1txTr9ItEgTAfR1wkIy5
            a5IQOEmq3Vr9KAVqLJpg8IUXLKgS0gssAIUqO3T8pRInhflzBOEORCosOWbevkw0
            m5egn+oYhdaqZNE8OqKuq8hKGxWcIeGVGGvxvnuqmbjxbjBxIYirQoykOOZrOVFi
            gj+7ErT5noJSX39NHPmuNghaFxl6yjvR9kzx5fBsdQnb5F/1bDVjhjO8yvhPmZgY
            VUJkIrU=
            -----END CERTIFICATE-----
            -----BEGIN RSA PRIVATE KEY-----
            MIIEowIBAAKCAQEAy2Ll4QS65KYDhNkArTuUcz6PYV7uXOaCsThdrnB7f4BAw3fM
            71ZFuvNENidqfsgQ7ay6I4UPN6ywOT1xT9Z3mpmnzWPpkNJDwMlWWmPpA3Iz1S9F
            GpsSdil+G6XAuq3ufLqEeI5nKx8yHw2hDRwZ1trsbDtJ5GVAaADGFMZZOZJGisat
            6TmKFccjbJHfHpqmZs6nmKtfuRZ20l645G5ph0bO2s6ZGDOefCnSh9rXiN84Ictf
            a469gvVyHB6HQyvpNR/JVuaITETaIJeIOpAejokv5gjjwDviQI4dZKwPMngytba4
            eMKWaT5SRVQNonp9GvZrXLksBPypDQg0czLKHwIDAQABAoIBAHnIbDGCrY3/wheo
            AHm6NTeUfDInr7684ADR6XZsL+a2mxDwCSw+kl5RD8UFcQUdMtW+GW7vW59Qrex4
            WAMgPlm6K/oWG2L2JE+pvyU8see4WEUMmupFdJaAXdycMX0WbLkOzgeJ7Uiq0044
            0PiSnP5D9FESZzp1Tk14OSNzaTXIyWT0T2qPLuGxojP2io9S3D9g2bp6DItQQkAp
            rQmge45SoJYmTfdK3tZ5ryODDw7NLd2coiWg1TDmUZEAEA4vvdnbZkpeJONeOdvA
            ZqeTPND4UniTdVoJKfPpCs7OY7XjwtCrT21s9t3dV63FgG/wBuS2/0Bc5Z5rRYoV
            flGRO/ECgYEA494/W7ta8j+73UuUkozgFOX6OW/Jns5JoxP4RXdIElt8UloSrSUY
            gXES/3FdTgR4cK5GZr0pHhKu2JSqXZTCvBXo1WGm1+WCDHBlpWJL61fO7+uwPfFh
            +h3B6l07CXlOaPFCgge5pFR2EZ3JeSP6cKQFvq2HSLKu7EJGtQM8wZ0CgYEA5H7n
            gL03NrGS2TnkTBMH4EfscW0HcL77cqFe3NOZkOm0maU1Vq3BHNoUjo5Qo0ypf5T0
            zQlXyZHjgLsSMnyPA1WPswlTXoHM9ZLm8Kl3dcridxVoH0f6fF8pKAFQhK8o0Wxf
            BfdakTnfyvKvjfljoFmtBlllLUPDYn8JM+0Pm+sCgYAGW/x+reLi4d53VZWm5WGX
            k7eBBNqmoPEzKOqD3clYIc99aOAejut5KVOzZ1GITN2jn2l9kofkO/c/Oh7rD6zD
            nQTrd5c1bUVM3ZIopG6j+cZfsb8wa10lotD3nnR4VjdW/Gyzvk1zBZxp73Jg/B0Q
            KbOzV5pv7/SryUm54YY/jQKBgCfHE+QsjH0gArGAS4cW1QstWjMQyPfOt5VoFEyb
            JaO9m6wXv6ZcTz8HlAaRLeaPxP4p30gGdVro49MYPf2+A2OQNJj1aacNL7IcpcmF
            pv9Bl5Uli9/ONwQJyO9m8y52E8QJeq1eN00K5zO8deVgYgCbO+zcCSoNHul5tg9t
            GIeLAoGBAKRgQQe13L1eEFj3dONmjmx72k8NdJAMfdoAR+wwvPGVOnec+pXvZsl0
            Wmh4Xd4hVi04s4CARS0Zinke6PqhLNtQhWCDc3337qo5sFmtcpcWbV8agL+gtcdi
            HaKlqgMHCfSbjpJa8g1070yWBSdUMLPKcdjuEo2D4jr1vSiISHVR
            -----END RSA PRIVATE KEY-----
        """)

        @idiokit.stream
        def run_server(server_conn):
            with tempfile.NamedTemporaryFile() as certfile:
                certfile.write(certdata)
                certfile.flush()
                server = yield ssl.wrap_socket(
                    server_conn,
                    server_side=True,
                    certfile=certfile.name
                )

            yield server.sendall("Hello, World!")
            yield server.shutdown(socket.SHUT_RDWR)
            yield server.close()

        @idiokit.stream
        def run_client(client_conn):
            client = yield ssl.wrap_socket(
                client_conn,
                require_cert=require_cert
            )

            result = ""
            while True:
                data = yield client.recv(1024)
                if not data:
                    idiokit.stop(result)
                result += data
            idiokit.stop(result)

        result = yield run_server(server_conn) | run_client(client_conn)
        self.assertEqual(result, "Hello, World!")

    def test_wrapping_a_socket_should_work(self):
        @idiokit.stream
        def connect_client(socket_path):
            sock = socket.Socket(socket.AF_UNIX)
            yield sock.connect(socket_path)
            yield idiokit.send(sock)

        @idiokit.stream
        def connect_server(sock):
            conn, _ = yield sock.accept()
            client = yield idiokit.next()
            idiokit.stop(client, conn)

        @idiokit.stream
        def test():
            with tmpdir() as tmp:
                socket_path = os.path.join(tmp, "socket")

                server_sock = socket.Socket(socket.AF_UNIX)
                try:
                    yield server_sock.bind(socket_path)
                    yield server_sock.listen(1)
                    client_conn, server_conn = yield idiokit.pipe(
                        connect_client(socket_path),
                        connect_server(server_sock)
                    )
                finally:
                    yield server_sock.close()
            yield self._test_wrap_socket(client_conn, server_conn)
        idiokit.main_loop(test())

    def test_wrapping_a_socket_created_with_fromfd_should_work(self):
        left, right = socket.socketpair()
        idiokit.main_loop(self._test_wrap_socket(left, right))

    def test_wrapping_a_socket_created_with_socketpair_should_work(self):
        left, right = stdlib_socket.socketpair()
        idiokit.main_loop(self._test_wrap_socket(
            socket.fromfd(left.fileno(), left.family, left.type),
            socket.fromfd(right.fileno(), right.family, right.type)
        ))

    def test_should_check_certificates_when_require_cert_is_set(self):
        left, right = socket.socketpair()
        self.assertRaises(
            ssl.SSLError,
            idiokit.main_loop,
            self._test_wrap_socket(left, right, require_cert=True)
        )
