# Module for XMPP JID processing as defined in on RFC 3920
# (http://www.ietf.org/rfc/rfc3920.txt) and RFC 3454
# (http://www.ietf.org/rfc/rfc3454.txt).
# 
# This module was originally written using both the above RFCs and the
# xmppstringprep module of the pyxmpp package
# (http://pyxmpp.jajcus.net/) as a reference.

import re
import stringprep
from unicodedata import ucd_3_2_0 as unicodedata
from encodings import idna

class JIDError(Exception):
    pass

def in_sets(*funcs):
    return lambda item: any(func(item) for func in funcs)

def mapping(*funcs):
    def _mapping(ch):
        for func in funcs:
            mapped = func(ch)
            if mapped is not None:
                return mapped
        return ch
    return _mapping

A1 = stringprep.in_table_a1
def B1(ch):
    if stringprep.in_table_b1(ch):
        return u""
    return None
B2 = stringprep.map_table_b2
C11 = stringprep.in_table_c11
C12 = stringprep.in_table_c12
C21 = stringprep.in_table_c21
C22 = stringprep.in_table_c22
C3 = stringprep.in_table_c3
C4 = stringprep.in_table_c4
C5 = stringprep.in_table_c5
C6 = stringprep.in_table_c6
C7 = stringprep.in_table_c7
C8 = stringprep.in_table_c8
C9 = stringprep.in_table_c9
D1 = stringprep.in_table_d1
D2 = stringprep.in_table_d2

def prep_func(mapping, prohibited, unassigned):
    def _prep_func(string):
        string = u"".join(mapping(ch) for ch in string)
        string = unicodedata.normalize("NFKC", string)

        for ch in string:
            if prohibited(ch):
                raise JIDError("prohibited character '%r'" % ch)
        for ch in string:
            if unassigned(ch):
                raise JIDError("unassigned character '%r'" % ch)

        has_ral = any(D1(ch) for ch in string)
        has_l = any(D2(ch) for ch in string)
        if has_ral and has_l:
            raise JIDError("both RAL an L bidirectional characters present")
        if string and has_ral and not (D1(string[0]) and D1(string[-1])):
            raise JIDError("first and last character must be RAL bidirectional")

        return string
    return _prep_func

nodeprep = prep_func(mapping(B1, B2),
                     in_sets(C11, C12, C21, C22, C3, C4, C5, C6, C7, C8, C9,
                             set(u"\"&'/:<>").__contains__),
                     mapping(A1))
resourceprep = prep_func(mapping(B1),
                         in_sets(C12, C21, C22, C3, C4, C5, C6, C7, C8, C9),
                         mapping(A1))

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
