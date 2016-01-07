import os
import shutil
import urllib
import idiokit
import unittest
import tempfile
from idiokit import socket

from ..client import Client, HTTPUnixAdapter


@idiokit.stream
def serve(test_string, sock):
    conn, _ = yield sock.accept()
    try:
        request = ""
        while True:
            data = yield conn.recv(1024)
            if not data:
                raise RuntimeError("not enough data")

            request += data
            if "\r\n\r\n" in request:
                break

        yield conn.sendall("HTTP/1.0 200 OK\r\n")
        yield conn.sendall("\r\n")
        yield conn.sendall(test_string)
    finally:
        yield conn.close()


@idiokit.stream
def get(client, url):
    request = yield client.request("GET", url)
    response = yield request.finish()

    result = ""
    while True:
        data = yield response.read(1024)
        if not data:
            break
        result += data
    idiokit.stop(result)


class TestClient(unittest.TestCase):
    def test_http_client_user_agent(self):
        client = Client(user_agent="Test Agent")
        self.assertEqual(
            client.user_agent,
            "Test Agent idiokit/{0}".format(idiokit.__version__)
        )

    def test_http_adapter(self):
        @idiokit.stream
        def main(test_string, client):
            s = socket.Socket(socket.AF_INET)
            try:
                yield s.bind(("127.0.0.1", 0))
                yield s.listen(1)

                _, port = yield s.getsockname()
                result = yield serve(test_string, s) | get(client, "http://127.0.0.1:{0}/".format(port))
            finally:
                yield s.close()
            idiokit.stop(result)

        client = Client()
        self.assertEqual("this is a test", idiokit.main_loop(main("this is a test", client)))

    def test_http_unix_adapter(self):
        @idiokit.stream
        def main(test_string, client):
            s = socket.Socket(socket.AF_UNIX)
            try:
                tmpdir = tempfile.mkdtemp()
                try:
                    # Ensure that the path contains both upper and lower case
                    # characters to test case-sensitivity.
                    path = os.path.join(tmpdir, "socket.SOCKET")
                    url = "http+unix://{0}".format(urllib.quote(path, ""))

                    yield s.bind(path)
                    yield s.listen(1)
                    result = yield serve(test_string, s) | get(client, url)
                finally:
                    shutil.rmtree(tmpdir)
            finally:
                yield s.close()
            idiokit.stop(result)

        client = Client()
        client.mount("http+unix://", HTTPUnixAdapter())
        self.assertEqual("this is a test", idiokit.main_loop(main("this is a test", client)))
