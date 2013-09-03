import unittest

from ..jid import JID, JIDError


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
        self.assertRaises(JIDError, JID, u"\xe4" * 63)

        self.assertRaises(JIDError, JID, ".".join([u"\xe4"] * 1024))

    def test_invalid_node(self):
        self.assertRaises(JIDError, JID, "@", "domain", "resource")
