from __future__ import absolute_import

import os
import re
import urllib
import httplib
import urlparse
import mimetypes
import posixpath
from cStringIO import StringIO

from ... import idiokit
from . import utils


class FileSystem(object):
    def __init__(self, root_path):
        self._abs_root = os.path.abspath(root_path)

    def _sanitize_path(self, path):
        path = utils.normpath(path, "/")
        if re.search(r"[^\w\-_\./]", path):
            raise ValueError("forbidden characters in path")

        split_path = path.split("/")[1:]
        return os.path.abspath(os.path.join(self._abs_root, *split_path))

    def check_path(self, path):
        try:
            return self._sanitize_path(path)
        except ValueError:
            return False

    def isfile(self, path):
        return os.path.isfile(self._sanitize_path(path))

    def isdir(self, path):
        return os.path.isdir(self._sanitize_path(path))

    def open(self, path):
        return open(self._sanitize_path(path), "rb")


class BakedFileSystem(object):
    def __init__(self, data):
        self._data = data

    def _get(self, path):
        path = posixpath.abspath(os.path.join("/", path))
        pieces = path.split("/")[1:]
        if pieces and pieces[-1] == "":
            pieces.pop()

        current = self._data
        for piece in pieces:
            if isinstance(current, str):
                raise IOError()

            current = current.get(piece, None)
            if current is None:
                raise IOError()
        return current

    def check_path(self, path):
        return True

    def isfile(self, path):
        try:
            return isinstance(self._get(path), str)
        except IOError:
            return False

    def isdir(self, path):
        try:
            return isinstance(self._get(path), dict)
        except IOError:
            return False

    def open(self, path):
        data = self._get(path)
        if isinstance(data, dict):
            raise IOError()
        return StringIO(data)


def filehandler(filesystem, index=None):
    @idiokit.stream
    def send_file(response, path):
        headers = {}

        content_type, content_encoding = mimetypes.guess_type(path)
        if content_type is not None:
            headers["content-type"] = content_type
        if content_encoding is not None:
            headers["content-encoding"] = content_encoding

        try:
            f = filesystem.open(path)
        except IOError:
            yield response.write_status(code=httplib.NOT_FOUND)
            return

        try:
            yield response.write_headers(headers)
            while True:
                data = f.read(4096)
                if not data:
                    break
                yield response.write(data)
        finally:
            f.close()

    @idiokit.stream
    def _filehandler(addr, request, response):
        try:
            path = utils.normpath(urlparse.urlparse(request.uri).path)
            path = urllib.unquote(path)
        except ValueError:
            yield response.write_status(code=httplib.NOT_FOUND)
            return

        if filesystem.isfile(path):
            yield send_file(response, path)
        elif filesystem.isdir(path) and path == "/" and index is not None:
            yield send_file(response, utils.normpath("/" + index))
        else:
            yield response.write_status(code=httplib.NOT_FOUND)

    return _filehandler
