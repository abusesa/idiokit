import re
import collections


class HTTPVersion(collections.namedtuple("HTTPVersion", ["major", "minor"])):
    """
    A class for representing HTTP protocol versions.

    >>> version = HTTPVersion(1, 0)
    >>> version.major
    1
    >>> version.minor
    0

    Instances of this class are immutable.

    >>> HTTPVersion(1, 1).major = 2
    Traceback (most recent call last):
        ...
    AttributeError: can't set attribute

    Instances can be compared, the comparison logic being the same
    as between two (x, y) tuples.

    >>> HTTPVersion(1, 1) == HTTPVersion(1, 1)
    True
    >>> HTTPVersion(1, 2) == HTTPVersion(1, 1)
    False
    >>> HTTPVersion(1, 1) > HTTPVersion(1, 0)
    True

    In fact, as a convenience, instances can be compared with regular
    tuples.

    >>> (1, 2) > HTTPVersion(1, 1) > (1, 0)
    True
    """

    __slots__ = ()

    @classmethod
    def from_string(cls, string):
        """
        Return a HTTPVersion object parsed from a string.

        >>> HTTPVersion.from_string("HTTP/1.0")
        HTTPVersion(major=1, minor=0)

        The parsing is based in RFC 2616 section 3.1, i.e. strings
        of general form 'HTTP/x.y' where x and y are 1-n digit
        numbers standing for the major and minor HTTP versions,
        respectively.

        Or as RFC 2616 section 3.1 notes:
        > Note that the major and minor numbers MUST be treated as
        > separate integers and that each MAY be incremented higher
        > than a single digit.

        >>> HTTPVersion.from_string("HTTP/12.13")
        HTTPVersion(major=12, minor=13)

        Further:
        > Leading zeros MUST be ignored by recipients [...]

        >>> HTTPVersion.from_string("HTTP/001.000")
        HTTPVersion(major=1, minor=0)

        Raise a ValueError for strings that do not conform to the
        specification.

        >>> HTTPVersion.from_string("obviously wrong")
        Traceback (most recent call last):
            ...
        ValueError: invalid HTTP version string

        >>> HTTPVersion.from_string("http/1.1")
        Traceback (most recent call last):
            ...
        ValueError: invalid HTTP version string

        >>> HTTPVersion.from_string(" HTTP/1.1 ")
        Traceback (most recent call last):
            ...
        ValueError: invalid HTTP version string
        """

        match = re.match("^HTTP/(\d+)\.(\d+)$", string)
        if match is None:
            raise ValueError("invalid HTTP version string")

        major, minor = map(int, match.groups())
        return cls(major, minor)

    def __str__(self):
        """
        >>> str(HTTP10)
        'HTTP/1.0'

        >>> unicode(HTTP11)
        u'HTTP/1.1'

        >>> format(HTTPVersion(1, 2))
        'HTTP/1.2'
        """

        return "HTTP/{0.major}.{0.minor}".format(self)


HTTP10 = HTTPVersion(1, 0)
HTTP11 = HTTPVersion(1, 1)
