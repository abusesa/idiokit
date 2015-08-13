from __future__ import absolute_import

import re
import urllib


def normpath(path, root_path="/", unquote=True):
    """
    >>> normpath("a/../b")
    '/b'

    >>> normpath(".")
    '/'

    >>> normpath("a/../../b")
    Traceback (most recent call last):
        ...
    ValueError

    >>> normpath("..", root_path="/x")
    Traceback (most recent call last):
        ...
    ValueError
    """

    if unquote:
        path = urllib.unquote(path)

    pieces = []
    for piece in path.split("/"):
        if piece in ("", "."):
            pass
        elif piece == "..":
            try:
                pieces.pop()
            except IndexError:
                raise ValueError()
        else:
            pieces.append(piece)

    result = root_path + "/" + "/".join(pieces)
    if path.endswith("/"):
        result += "/"
    return urllib.quote(re.sub("/+", "/", result))
