import copy
import pickle
import unittest
import warnings

from ..jid import JID, JIDError


class TestJID(unittest.TestCase):
    def test_7bit_ascii_byte_strings_should_be_converted_to_unicode(self):
        self.assertEqual(JID("node@domain/resource"), JID(u"node@domain/resource"))

    def test_non_7bit_ascii_byte_strings_should_cause_UnicodeDecodeErrors(self):
        self.assertRaises(UnicodeDecodeError, JID, "\xe4@domain/resource")

    def test_instances_should_be_copyable(self):
        jid = JID("a", "b", "c")
        assert copy.copy(jid) == jid

    def test_instances_should_be_deepcopyable(self):
        jid = JID("a", "b", "c")
        assert copy.deepcopy(jid) == jid

    def test_instances_should_be_picklable_and_unpicklable(self):
        jid = JID("a", "b", "c")
        assert pickle.loads(pickle.dumps(jid)) == jid

    def test_caching_should_recycle_JID_instances(self):
        assert JID("a", "b") is JID("a", "b")

    def test_caching_should_not_warn_about_str_unicode_mismatch(self):
        # Regression test: Creating a JID sometimes caused an UnicodeWarning to
        # be printed. The reason could be tracked back to JID instance caching
        # by repeating the following steps:
        #   1. Create a JID from an unicode string containing a non-ascii
        #   character.
        #   2. Try to create a JID from a byte string that both
        #     * contains a character outside of the 7-bit ascii range
        #     * has the same hash() value as the unicode string from step 1.
        # The cache dict ended up trying to compare these two incompatible
        # strings, hence the UnicodeWarning.

        class ZeroHashUnicode(unicode):
            def __hash__(self):
                return 0

        class ZeroHashBytes(str):
            def __hash__(self):
                return 0

        JID(ZeroHashUnicode(u"\xe4@domain.example"))

        with warnings.catch_warnings():
            warnings.simplefilter("error", UnicodeWarning)
            try:
                self.assertRaises(ValueError, JID, ZeroHashBytes("\xe4@domain.example"))
            except UnicodeWarning:
                self.fail("UnicodeWarning raised")

    def test_instances_should_support_conversion_to_unicode_strings(self):
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
