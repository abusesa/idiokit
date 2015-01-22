from __future__ import absolute_import

import struct
import random
import inspect
import collections
import socket as _socket

from .. import idiokit, socket, timer
from ._iputils import parse_ip, reverse_ipv4, reverse_ipv6
from ._conf import resolv_conf


system_random = random.SystemRandom()


def gen_id():
    return system_random.randint(0, 65535)


class _ReprMixin(object):
    def __repr__(self):
        keys = []
        for key, value in inspect.getmembers(type(self)):
            if not isinstance(value, property):
                continue
            keys.append((value.fget.func_code.co_firstlineno, key))
        keys.sort()

        pieces = []
        for _, key in keys:
            value = getattr(self, key)
            pieces.append(key + "=" + repr(value))
        return self.__class__.__name__ + "(" + ", ".join(pieces) + ")"


class DNSError(Exception):
    pass


class DNSTimeout(DNSError):
    pass


class MessageError(DNSError):
    pass


class NotEnoughData(MessageError):
    def __init__(self, message="not enough data"):
        MessageError.__init__(self, message)


def unpack(_struct, data, offset=0):
    size = _struct.size
    if len(data) - offset < size:
        raise NotEnoughData()
    return _struct.unpack_from(data, offset), offset + size


DNS_PORT = 53

FLAGS_RA = 0b0000000010000000
FLAGS_RD = 0b0000000100000000
FLAGS_TC = 0b0000001000000000
FLAGS_AA = 0b0000010000000000
FLAGS_QR = 0b1000000000000000

MASK_OPCODE = 0b0111100000000000
MASK_RCODE = 0b0000000000001111

OPCODE_QUERY = 0
OPCODE_IQUERY = 1
OPCODE_STATUS = 2

RCODE_NO_ERROR = 0
RCODE_FORMAT_ERROR = 1
RCODE_SERVER_FAILURE = 2
RCODE_NAME_ERROR = 3
RCODE_NOT_IMPLEMENTED = 4
RCODE_REFUSED = 5

RCODE_STRINGS = {
    RCODE_NO_ERROR: "no error",
    RCODE_FORMAT_ERROR: "format error",
    RCODE_SERVER_FAILURE: "server failure",
    RCODE_NAME_ERROR: "name error",
    RCODE_NOT_IMPLEMENTED: "not implemented",
    RCODE_REFUSED: "refused"
}


class ResponseError(DNSError):
    def __init__(self, rcode, string=None):
        if string is None:
            string = RCODE_STRINGS.get(rcode, "rcode {0!r}".format(rcode))

        DNSError.__init__(self, string)

        self._rcode = rcode
        self._string = string

    @property
    def rcode(self):
        return self._rcode

    @property
    def string(self):
        return self._string


class Message(_ReprMixin):
    _struct = struct.Struct("!HHHHHH")

    @classmethod
    def unpack(cls, data, offset=0):
        (id, flags, qd_count, an_count, ns_count, ar_count), offset = unpack(cls._struct, data, offset)

        qr = bool(FLAGS_QR & flags)
        aa = bool(FLAGS_AA & flags)
        tc = bool(FLAGS_TC & flags)
        rd = bool(FLAGS_RD & flags)
        ra = bool(FLAGS_RA & flags)
        rcode = MASK_RCODE & flags
        opcode = (MASK_OPCODE & flags) >> 11

        qd_list = ()
        an_list = ()
        ns_list = ()
        ar_list = ()
        try:
            qd_list, offset = cls._unpack_n(Question, qd_count, data, offset)
            an_list, offset = cls._unpack_n(RR, an_count, data, offset)
            ns_list, offset = cls._unpack_n(RR, ns_count, data, offset)
            ar_list, offset = cls._unpack_n(RR, ar_count, data, offset)
        except NotEnoughData:
            if not tc:
                raise
            offset = len(data)
        return cls(id, not qr, opcode, aa, tc, rd, ra, rcode, qd_list, an_list, ns_list, ar_list), offset

    @classmethod
    def _unpack_n(cls, type_, count, data, offset):
        results = []
        for _ in xrange(count):
            result, offset = type_.unpack(data, offset)
            results.append(result)
        return results, offset

    def __init__(
            self,
            id=None,
            query=True,
            opcode=OPCODE_QUERY,
            authoritative_answer=False,
            truncated=False,
            recursion_desired=True,
            recursion_available=False,
            rcode=RCODE_NO_ERROR,
            questions=(),
            answers=(),
            authorities=(),
            additional=()):
        self._id = id if id is not None else gen_id()
        self._query = query
        self._opcode = opcode
        self._authoritative_answer = authoritative_answer
        self._truncated = truncated
        self._recursion_desired = recursion_desired
        self._recursion_available = recursion_available
        self._rcode = rcode
        self._questions = list(questions)
        self._answers = list(answers)
        self._authorities = list(authorities)
        self._additional = list(additional)

    @property
    def id(self):
        return self._id

    @property
    def query(self):
        return self._query

    @property
    def opcode(self):
        return self._opcode

    @property
    def authoritative_answer(self):
        return self._authoritative_answer

    @property
    def truncated(self):
        return self._truncated

    @property
    def recursion_desired(self):
        return self._recursion_desired

    @property
    def recursion_available(self):
        return self._recursion_available

    @property
    def rcode(self):
        return self._rcode

    @property
    def questions(self):
        return self._questions

    @property
    def answers(self):
        return self._answers

    @property
    def authorities(self):
        return self._authorities

    @property
    def additional(self):
        return self._additional

    def pack(self):
        flags = 0
        flags |= 0 if self._query else FLAGS_QR
        flags |= FLAGS_AA if self._authoritative_answer else 0
        flags |= FLAGS_TC if self._truncated else 0
        flags |= FLAGS_RD if self._recursion_desired else 0
        flags |= FLAGS_RA if self._recursion_available else 0
        flags |= (self._opcode << 11) & MASK_OPCODE
        flags |= self._rcode & MASK_RCODE

        qd_count = len(self._questions)
        an_count = len(self._answers)
        ns_count = len(self._authorities)
        ar_count = len(self._additional)

        pieces = [self._struct.pack(self._id, flags, qd_count, an_count, ns_count, ar_count)]
        for entry_list in (self._questions, self._answers, self._authorities, self._additional):
            for entry in entry_list:
                pieces.extend(entry.pack())
        return "".join(pieces)


CLASS_INET = 1
CLASS_CSNET = 2
CLASS_CHAOS = 3
CLASS_HESIOD = 4
CLASS_ANY = 255


class Question(_ReprMixin):
    _struct = struct.Struct("!HH")

    @classmethod
    def unpack(cls, data, offset=0):
        name, offset = unpack_name(data, offset)
        (qtype, qclass), offset = unpack(cls._struct, data, offset)
        return cls(name, qtype, qclass), offset

    def __init__(self, name, type, cls=CLASS_INET):
        self._name = name
        self._type = type
        self._cls = cls

    @property
    def name(self):
        return self._name

    @property
    def type(self):
        return self._type

    @property
    def cls(self):
        return self._cls

    def pack(self):
        return pack_name(self._name) + self._struct.pack(self._type, self._cls)


class RR(_ReprMixin):
    _struct = struct.Struct("!HHiH")
    _types = {}

    @classmethod
    def register_type(cls, type, code=None):
        if code is None:
            code = type.code
        cls._types[code] = type

    @classmethod
    def unpack(cls, data, offset=0):
        name, offset = unpack_name(data, offset)
        (type_, cls_, ttl, length), offset = unpack(cls._struct, data, offset)
        if len(data) - offset < length:
            raise NotEnoughData()

        data_cls = cls._types.get(type_, Raw)
        data = data_cls.unpack(data, offset, length)
        return cls(name, type_, cls_, ttl, data), offset + length

    def __init__(self, name, type, cls, ttl, data):
        self._name = name
        self._type = type
        self._cls = cls
        self._ttl = ttl
        self._data = data

    @property
    def name(self):
        return self._name

    @property
    def type(self):
        return self._type

    @property
    def cls(self):
        return self._cls

    @property
    def ttl(self):
        return self._ttl

    @property
    def data(self):
        return self._data

    def pack(self):
        name = pack_name(self._name)
        data = self._data.pack()
        return name + self._struct.pack(self._type, self._cls, self._ttl, len(data)) + data


class Raw(object):
    @classmethod
    def unpack(cls, data, offset=0, length=None):
        return cls(data, offset, length)

    def __init__(self, data, offset=0, length=None):
        if length is None:
            length = len(data) - offset
        self._data = buffer(data, offset, length)

    def pack(self):
        return str(self._data)


class A(_ReprMixin):
    code = 1

    @classmethod
    def unpack(cls, data, offset, length):
        if length != 4:
            raise MessageError("expected 4 bytes of RDATA, got {0}".format(length))
        ip = _socket.inet_ntop(_socket.AF_INET, data[offset:offset + length])
        return cls(ip)

    def __init__(self, ip):
        self._ip = ip

    @property
    def ip(self):
        return self._ip

    def pack(self):
        return _socket.inet_pton(_socket.AF_INET, self._ip)
RR.register_type(A)


class AAAA(_ReprMixin):
    code = 28

    @classmethod
    def unpack(cls, data, offset, length):
        if length != 16:
            raise MessageError("expected 16 bytes of RDATA, got {0}".format(length))
        ip = _socket.inet_ntop(_socket.AF_INET6, data[offset:offset + length])
        return cls(ip)

    def __init__(self, ip):
        self._ip = ip

    @property
    def ip(self):
        return self._ip

    def pack(self):
        return _socket.inet_pton(_socket.AF_INET6, self._ip)
RR.register_type(AAAA)


class TXT(_ReprMixin):
    code = 16

    @classmethod
    def unpack(cls, data, offset, length):
        end = offset + length
        strings = []

        while offset < end:
            amount = ord(data[offset])
            offset += 1

            if offset + amount > end:
                raise MessageError("a character string spans over the end of RDATA")

            strings.append(data[offset:offset + amount])
            offset += amount

        return cls(strings)

    def __init__(self, strings):
        self._strings = tuple(strings)

    @property
    def strings(self):
        return self._strings

    def pack(self):
        strings = []
        for string in self._strings:
            length = len(string)
            if length > 255:
                raise MessageError()

            strings.append(chr(length))
            strings.append(string)
        return "".join(strings)
RR.register_type(TXT)


class PTR(_ReprMixin):
    code = 12

    @classmethod
    def unpack(cls, data, offset, length):
        name, offset = unpack_name(data, offset)
        return cls(name)

    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name

    def pack(self):
        return pack_name(self._name)
RR.register_type(PTR)


class CNAME(_ReprMixin):
    code = 5

    @classmethod
    def unpack(cls, data, offset, length):
        name, offset = unpack_name(data, offset)
        return cls(name)

    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name

    def pack(self):
        return pack_name(self._name)
RR.register_type(CNAME)


class SRV(_ReprMixin):
    code = 33

    _struct = struct.Struct("!HHH")

    @classmethod
    def unpack(cls, data, offset, length):
        (priority, weight, port), offset = unpack(cls._struct, data, offset)
        target, offset = unpack_name(data, offset)
        return cls(priority, weight, port, target)

    def __init__(self, priority, weight, port, target):
        self._priority = priority
        self._weight = weight
        self._port = port
        self._target = target

    @property
    def priority(self):
        return self._priority

    @property
    def weight(self):
        return self._weight

    @property
    def port(self):
        return self._port

    @property
    def target(self):
        return self._target

    def pack(self):
        return self._struct.pack(self._priority, self._weight, self._port) + pack_name(self._target)
RR.register_type(SRV)


def pack_name(name):
    result = []
    for piece in name.split("."):
        result.append(chr(len(piece)))
        result.append(piece)
    result.append("\x00")
    return "".join(result)


def unpack_name(data, offset=0, max_octet_count=255):
    r"""
    Return a domain name unpacked from byte data and the offset
    where the unpacked name ends in the byte data.

    >>> unpack_name("\x01a\x01b\x01c\x00")
    ('a.b.c', 7)

    """

    labels = []
    length = len(data)

    jump_count = 0
    octet_count = 0
    real_offset = None

    while offset < length:
        byte = ord(data[offset])
        offset += 1

        hi_bits = (byte >> 6) & 0b11
        if hi_bits == 0b11:
            if jump_count == 0:
                real_offset = offset + 1

            jump_count += 1
            if jump_count >= length:
                raise MessageError("packed name contains a jump loop")

            if offset >= length:
                raise NotEnoughData("not enough data for name")
            offset = ((byte & 0x3f) << 8) + ord(data[offset])
        elif hi_bits == 0b00:
            octet_count += 1

            if byte != 0:
                labels.append(data[offset:offset + byte])
                offset += byte
                octet_count += byte

            if octet_count > max_octet_count:
                raise MessageError("name longer than {0} octets".format(max_octet_count))

            if byte == 0:
                if real_offset is None:
                    real_offset = offset
                return ".".join(labels), real_offset
        else:
            raise MessageError("invalid octet")

    raise NotEnoughData("not enough data for name")


def find_answers(msg, question):
    cnames = {}
    answers = {}
    for answer in msg.answers:
        if answer.type == CNAME.code:
            cnames[answer.name] = answer.data.name
        if answer.type == question.type:
            answers.setdefault(answer.name, []).append(answer)

    name = question.name
    for _ in xrange(len(cnames) + 1):
        results = answers.get(name, None)
        if results is not None:
            return name, results

        cname = cnames.get(name, None)
        if cname is None:
            return name, []

        name = cname

    raise DNSError("CNAME loop")


class Resolver(object):
    _resolv_conf = resolv_conf()

    @classmethod
    def _normalize_server(self, server):
        if isinstance(server, basestring):
            return (server, DNS_PORT)

        if not isinstance(server, collections.Sequence):
            raise TypeError("expected a host string or a (host, port) sequence, got {0!r}".format(server))
        if len(server) != 2:
            raise ValueError("sequence contains {0} items, expected 2".format(len(server)))
        return server

    def __init__(self, servers=None):
        if servers is None:
            servers = self._resolv_conf.load().servers
        else:
            servers = map(self._normalize_server, servers)

        self._servers = []
        self._timeout = 5.0
        self._tries = 3
        self._use_tcp = True

        for host, port in servers:
            self.append_server(host, port)

    def append_server(self, ip, port=DNS_PORT):
        family, ip = parse_ip(ip)
        self._servers.append((family, ip, port))

    def clear_servers(self):
        self._servers = []

    @idiokit.stream
    def query(self, name, type, cls=CLASS_INET):
        if not self._servers:
            raise DNSError("no DNS servers specified")

        if isinstance(name, unicode):
            name = str(name)
        question = Question(name, type, cls)

        for family, addr, port in self._servers:
            result = None

            for _ in xrange(self._tries):
                try:
                    result = yield timer.timeout(self._timeout, self._query_udp(question, family, addr, port))
                except timer.Timeout:
                    result = None
                else:
                    break

            if result is not None and result.truncated and self._use_tcp:
                try:
                    result = yield timer.timeout(self._timeout, self._query_tcp(question, family, addr, port))
                except timer.Timeout:
                    result = None

            if not result:
                continue

            cname, answers = find_answers(result, question)
            idiokit.stop(cname, answers, (addr, port))

        raise DNSTimeout("DNS query timed out")

    @idiokit.stream
    def _query_udp(self, question, family, server_addr, server_port):
        query = Message(questions=[question])
        sock = socket.Socket(family, socket.SOCK_DGRAM)
        try:
            # Trust the platform's ephemeral source port generation method
            # to adequately randomize the source port.
            yield sock.sendto(query.pack(), (server_addr, server_port))

            while True:
                data, addr = yield sock.recvfrom(512)
                if addr[0] != server_addr or addr[1] != server_port:
                    continue

                msg, _ = Message.unpack(data)
                if msg.query or msg.id != query.id or not self._question_matches(msg, question):
                    continue

                self._check_rcode(msg)
                idiokit.stop(msg)
        finally:
            yield sock.close()

    @idiokit.stream
    def _query_tcp(self, question, family, server_addr, server_port):
        query = Message(questions=[question])
        sock = socket.Socket(family, socket.SOCK_STREAM)
        try:
            yield sock.connect((server_addr, server_port))

            query_data = query.pack()
            yield sock.sendall(struct.pack("!H", len(query_data)) + query_data)

            len_data = yield self._recv_all(sock, 2)
            length, = struct.unpack("!H", len_data)

            msg_data = yield self._recv_all(sock, length)
            msg, _ = Message.unpack(msg_data)
            if msg.query or msg.id != query.id or not self._question_matches(msg, question):
                raise DNSError("unexpected message from server")

            self._check_rcode(msg)
            idiokit.stop(msg)
        finally:
            yield sock.close()

    @idiokit.stream
    def _recv_all(self, sock, amount):
        buf = []
        while amount > 0:
            data = yield sock.recv(amount)
            if not data:
                raise DNSError("server closed connection unexpectedly")
            buf.append(data)
            amount -= len(data)
        idiokit.stop("".join(buf))

    def _check_rcode(self, msg):
        if msg.rcode == RCODE_NO_ERROR:
            return
        raise ResponseError(msg.rcode)

    def _question_matches(self, msg, question):
        if len(msg.questions) != 1:
            return False

        other = msg.questions[0]
        return (
            other.name == question.name
            and other.type == question.type
            and other.cls == question.cls
        )


_global_resolver = None


def _get_resolver(resolver):
    global _global_resolver

    if resolver is not None:
        return resolver

    if _global_resolver is None:
        _global_resolver = Resolver()

    return _global_resolver


@idiokit.stream
def a(name, resolver=None):
    resolver = _get_resolver(resolver)
    _, answers, _ = yield resolver.query(name, A.code)
    idiokit.stop([x.data.ip for x in answers])


@idiokit.stream
def aaaa(name, resolver=None):
    resolver = _get_resolver(resolver)
    _, answers, _ = yield resolver.query(name, AAAA.code)
    idiokit.stop([x.data.ip for x in answers])


@idiokit.stream
def srv(name, resolver=None):
    resolver = _get_resolver(resolver)
    _, answers, _ = yield resolver.query(name, SRV.code)

    items = []
    for answer in answers:
        items.append(answer.data)
    idiokit.stop(items)


def ordered_srv_records(srv_records):
    # Implement server selection as described in RFC 2782.

    srv_records = tuple(srv_records)
    if len(srv_records) == 1 and srv_records[0].target == "":
        return

    priorities = dict()
    for srv in srv_records:
        priorities.setdefault(srv.priority, []).append((srv.weight, srv))

    for _, by_weight in sorted(priorities.iteritems()):
        total_weight = sum(weight for (weight, _) in by_weight)

        by_weight.sort()

        while by_weight:
            cumulative_weight = 0
            random_number = random.uniform(0, total_weight)

            for index, (weight, srv) in enumerate(by_weight):
                cumulative_weight += weight
                if cumulative_weight >= random_number:
                    break

            selected_weight, selected_srv = by_weight.pop(index)
            yield selected_srv
            total_weight -= selected_weight


@idiokit.stream
def txt(name, resolver=None):
    resolver = _get_resolver(resolver)
    _, answers, _ = yield resolver.query(name, TXT.code)
    idiokit.stop([x.data.strings for x in answers])


@idiokit.stream
def ptr(name, resolver=None):
    resolver = _get_resolver(resolver)
    _, answers, _ = yield resolver.query(name, PTR.code)
    idiokit.stop([x.data.name for x in answers])


@idiokit.stream
def cname(name, resolver=None):
    resolver = _get_resolver(resolver)
    _, answers, _ = yield resolver.query(name, CNAME.code)
    idiokit.stop([x.data.name for x in answers])


def reverse_lookup(ip, resolver=None):
    family, ip = parse_ip(ip)
    if family == _socket.AF_INET:
        name = reverse_ipv4(ip) + ".in-addr.arpa"
    else:
        name = reverse_ipv6(ip) + ".ip6.arpa"
    return ptr(name, resolver)
