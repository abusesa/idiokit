# Module for XMPP JID processing as defined in on RFC 3920
# (http://www.ietf.org/rfc/rfc3920.txt) And RFC 3454
# (http://www.ietf.org/rfc/rfc3454.txt).
# 
# This module was originally written using both the above RFCs and the
# xmppstringprep module of the pyxmpp package
# (http://pyxmpp.jajcus.net/) as a reference.

import re
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
                       frozenset(u"\"&'/:<>").__contains__]
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
def prep_unicode_jid(jid):
    match = JID_REX.match(jid)
    if not match:
        raise JIDError("not a valid JID")

    node, domain, resource = match.groups()
    node = prep_node(node)
    domain = prep_domain(domain)
    resource = prep_resource(resource)

    return node, domain, resource

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
    except UnicodeError, ue:
        raise JIDError("not an intenationalized label: %s" % ue)
    labels = map(idna.ToUnicode, labels)
    domain = ".".join(labels)

    return check_length("domain", domain)

class JID(object):
    cache = dict()

    def __init__(self, jid):
        if not isinstance(jid, unicode):
            jid = unicode(jid)
        if jid not in self.cache:
            self.cache[jid] = prep_unicode_jid(jid)
        self.node, self.domain, self.resource = self.cache[jid]

    def bare(self):
        jid = self.domain
        if self.node is not None:
            jid = self.node + "@" + jid
        return JID(jid)

    def __eq__(self, other):
        if not isinstance(other, JID):
            return NotImplemented
        return unicode(self) == unicode(other)

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
            jid = self.node + u"@" + jid
        if self.resource is not None:
            jid = jid + "/" + self.resource

        return jid

import unittest

class TestJID(unittest.TestCase):
    def test_basic(self):
        jid_string = u"node@domain/resource"
        assert unicode(JID(jid_string)) == jid_string

    def test_eq_and_neq(self):
        jid1 = JID(u"n1@d1/r1")
        jid2 = JID(u"n2@d2/r2")

        assert jid1 == jid1
        assert jid2 == jid2
        assert jid1 != jid2

class TestDomain(unittest.TestCase):
    def test_invalid(self):
        self.assertRaises(JIDError, JID, "")
        self.assertRaises(JIDError, JID, ".")
        self.assertRaises(JIDError, JID, "root.")
        self.assertRaises(JIDError, JID, ".sub")
        self.assertRaises(JIDError, JID, u"\xe4"*63)

    def test_length(self):
        self.assertRaises(JIDError, JID, ".".join([u"\xe4"]*1024))

if __name__ == "__main__":
    unittest.main()
