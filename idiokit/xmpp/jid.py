# Module for XMPP JID processing as defined in on RFC 3920
# (http://www.ietf.org/rfc/rfc3920.txt) And RFC 3454
# (http://www.ietf.org/rfc/rfc3454.txt).
#
# This module was originally written using both the above RFCs and the
# xmppstringprep module of the pyxmpp package
# (http://pyxmpp.jajcus.net/) as well as the
# twisted.words.protocols.jabber.xmpp_stringprep module of Twisted
# (http://twistedmatrix.com/) as a reference.

import re
import threading
from stringprep import *
from unicodedata import ucd_3_2_0 as unicodedata
from encodings import idna

class JIDError(Exception):
    pass

def check_prohibited_and_unassigned(chars, prohibited_tables):
    for pos, ch in enumerate(chars):
        if any(table(ch) for table in prohibited_tables):
            raise JIDError("prohibited character %r at index %d" % (ch, pos))
        if in_table_a1(ch):
            raise JIDError("unassigned characted %r at index %d" % (ch, pos))

def check_bidirectional(chars):
    # RFC 3454: If a string contains any RandALCat character, the
    # string MUST NOT contain any LCat character.
    if not any(in_table_d1(ch) for ch in chars):
        return
    if any(in_table_d2(ch) for ch in chars):
        raise JIDError("string contains RandALCat and LCat characters")

    # RFC 3454: If a string contains any RandALCat character, a
    # RandALCat character MUST be the first character of the string,
    # and a RandALCat character MUST be the last character of the
    # string.
    if not (in_table_d1(chars[0]) and in_table_d1(chars[-1])):
        raise JIDError("string must start and end with RandALCat characters")

NODEPREP_PROHIBITED = [in_table_c11,
                       in_table_c12,
                       in_table_c21,
                       in_table_c22,
                       in_table_c3,
                       in_table_c4,
                       in_table_c5,
                       in_table_c6,
                       in_table_c7,
                       in_table_c8,
                       in_table_c9,
                       frozenset(u"\"&'/:<>@").__contains__]
def nodeprep(string):
    string = u"".join(map_table_b2(ch) for ch in string if not in_table_b1(ch))
    string = unicodedata.normalize("NFKC", string)
    check_prohibited_and_unassigned(string, NODEPREP_PROHIBITED)
    check_bidirectional(string)
    return string

RESOURCEPREP_PROHIBITED = [in_table_c12,
                           in_table_c21,
                           in_table_c22,
                           in_table_c3,
                           in_table_c4,
                           in_table_c5,
                           in_table_c6,
                           in_table_c7,
                           in_table_c8,
                           in_table_c9]
def resourceprep(string):
    string = u"".join(ch for ch in string if not in_table_b1(ch))
    string = unicodedata.normalize("NFKC", string)
    check_prohibited_and_unassigned(string, RESOURCEPREP_PROHIBITED)
    check_bidirectional(string)
    return string

JID_REX = re.compile("^(?:(.*?)@)?([^\.\/]+(?:\.[^\.\/]+)*)(?:/(.*))?$", re.U)
def split_jid(jid):
    match = JID_REX.match(jid)
    if not match:
        raise JIDError("not a valid JID")
    return match.groups()

def check_length(identifier, value):
    if len(value) > 1023:
        raise JIDError("%s identifier too long" % identifier)
    return value

def prep_node(node):
    if not node:
        return None
    node = nodeprep(node)
    return check_length("node", node)

def prep_resource(resource):
    if not resource:
        return None
    resource = resourceprep(resource)
    return check_length("resource", resource)

def prep_domain(domain):
    labels = domain.split(".")
    try:
        labels = map(idna.nameprep, labels)
        labels = map(idna.ToASCII, labels)
    except UnicodeError as ue:
        raise JIDError("not an internationalized label: %s" % ue)
    labels = map(idna.ToUnicode, labels)
    domain = ".".join(labels)

    return check_length("domain", domain)

def unicodify(item):
    if item is None:
        return None
    return unicode(item)

class JID(object):
    cache = dict()
    cache_size = 2**14
    cache_lock = threading.Lock()

    __slots__ = "_node", "_domain", "_resource"

    node = property(lambda x: x._node)
    domain = property(lambda x: x._domain)
    resource = property(lambda x: x._resource)

    def __new__(cls, node=None, domain=None, resource=None):
        with cls.cache_lock:
            cache_key = node, domain, resource
            if cache_key in cls.cache:
                return cls.cache[cache_key]

        if node is None and domain is None:
            raise JIDError("either a full JID or at least a domain expected")
        elif domain is None:
            if resource is not None:
                raise JIDError("resource not expected with a full JID")
            node, domain, resource = split_jid(unicodify(node))
        else:
            node, domain, resource = map(unicodify, (node, domain, resource))

        obj = super(JID, cls).__new__(cls)
        obj._node = prep_node(node)
        obj._domain = prep_domain(domain)
        obj._resource = prep_resource(resource)

        with cls.cache_lock:
            if len(cls.cache) >= cls.cache_size:
                cls.cache.clear()
            cls.cache[cache_key] = obj

        return obj

    def bare(self):
        return JID(self.node, self.domain)

    def __reduce__(self):
        return JID, (self.node, self.domain, self.resource)

    def __eq__(self, other):
        if not isinstance(other, JID):
            return NotImplemented
        return self is other or unicode(self) == unicode(other)

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __hash__(self):
        return hash(unicode(self))

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, repr(unicode(self)))

    def __unicode__(self):
        jid = self.domain

        if self.node is not None:
            jid = self.node + "@" + jid
        if self.resource is not None:
            jid = jid + "/" + self.resource

        return jid

import unittest

class TestJID(unittest.TestCase):
    def test_copy(self):
        import copy

        jid = JID("a", "b", "c")
        assert copy.copy(jid) == jid
        assert copy.deepcopy(jid) == jid

    def test_pickling(self):
        import pickle

        jid = JID("a", "b", "c")
        assert pickle.loads(pickle.dumps(jid)) == jid

    def test_caching(self):
        assert JID("a", "b") is JID("a", "b")

    def test_unicode(self):
        jid_string = "node@domain/resource"
        assert unicode(JID(jid_string)) == jid_string

    def test_read_only_attributes(self):
        jid = JID("a", "b", "c")
        self.assertRaises(AttributeError, setattr, jid, "node", "x")
        self.assertRaises(AttributeError, setattr, jid, "domain", "y")
        self.assertRaises(AttributeError, setattr, jid, "resource", "z")

    def test_eq_and_neq(self):
        assert JID("a@b/c") == JID("a@b/c")
        assert JID("a", "b", "c") == JID("a", "b", "c")
        assert JID("a@b/c") == JID("a", "b", "c")

        assert JID("x", "y", "z") != JID("a", "b", "c")
        assert JID("x@y/z") != JID("a", "b", "c")
        assert JID("x", "y", "z") != JID("a@b/c")
        assert JID("x@y/z") != JID("a@b/c")

    def test_invalid_domain(self):
        self.assertRaises(JIDError, JID, "")
        self.assertRaises(JIDError, JID, ".")
        self.assertRaises(JIDError, JID, "root.")
        self.assertRaises(JIDError, JID, ".sub")
        self.assertRaises(JIDError, JID, u"\xe4"*63)

        self.assertRaises(JIDError, JID, ".".join([u"\xe4"]*1024))

    def test_invalid_node(self):
        self.assertRaises(JIDError, JID, "@", "domain", "resource")

if __name__ == "__main__":
    unittest.main()
