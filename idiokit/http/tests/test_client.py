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


class TestClient(unittest.TestCase):
    def test_http_unix_adapter(self):
        @idiokit.stream
        def main(test_string):
            s = socket.Socket(socket.AF_UNIX)
            try:
                tmpdir = tempfile.mkdtemp()
                try:
                    path = os.path.join(tmpdir, "socket")
                    yield s.bind(path)
                    yield s.listen(1)
                    result = yield serve(test_string, s) | connect(path)
                finally:
                    shutil.rmtree(tmpdir)
            finally:
                yield s.close()
            idiokit.stop(result)

        @idiokit.stream
        def connect(path):
            client = Client()
            client.mount("http+unix://", HTTPUnixAdapter())
            request = yield client.request("GET", "http+unix://" + urllib.quote(path, ""))
            response = yield request.finish()

            result = ""
            while True:
                data = yield response.read(1024)
                if not data:
                    break
                result += data
            idiokit.stop(result)

        self.assertEqual("this is a test", idiokit.main_loop(main("this is a test")))
