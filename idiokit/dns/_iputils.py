from __future__ import absolute_import

import socket


def parse_ip(ip):
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            data = socket.inet_pton(family, ip)
        except socket.error:
            pass
        else:
            return family, socket.inet_ntop(family, data)
    return ValueError("{0!r} is not a valid IPv4/6 address".format(ip))


def reverse_ipv4(string):
    """
    >>> reverse_ipv4("192.0.2.1")
    '1.2.0.192'

    >>> reverse_ipv4("256.0.0.0")
    Traceback (most recent call last):
        ...
    ValueError: '256.0.0.0' is not a valid IPv4 address

    >>> reverse_ipv4("test")
    Traceback (most recent call last):
        ...
    ValueError: 'test' is not a valid IPv4 address
    """

    try:
        data = socket.inet_pton(socket.AF_INET, string)
    except socket.error:
        raise ValueError("{0!r} is not a valid IPv4 address".format(string))

    return ".".join(str(ord(x)) for x in reversed(data))


def reverse_ipv6(string):
    """
    >>> reverse_ipv6("2001:db8::1234:5678")
    '8.7.6.5.4.3.2.1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2'

    >>> reverse_ipv6("2001:db8::12345")
    Traceback (most recent call last):
        ...
    ValueError: '2001:db8::12345' is not a valid IPv6 address

    >>> reverse_ipv6("test")
    Traceback (most recent call last):
        ...
    ValueError: 'test' is not a valid IPv6 address
    """

    try:
        data = socket.inet_pton(socket.AF_INET6, string)
    except socket.error:
        raise ValueError("{0!r} is not a valid IPv6 address".format(string))

    nibbles = []
    for ch in reversed(data):
        num = ord(ch)
        nibbles.append("{0:x}.{1:x}".format(num & 0xf, num >> 4))

    return ".".join(nibbles)
