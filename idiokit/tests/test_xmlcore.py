import unittest
import xml.parsers.expat

from .. import xmlcore


def is_valid_xml_data(data):
    try:
        xml.parsers.expat.ParserCreate("utf-8").Parse(data)
    except xml.parsers.expat.ExpatError:
        return False
    return True


class TestEncoding(unittest.TestCase):
    def test_escape(self):
        element = xmlcore.Element("name")
        element.text = "<&>"
        assert is_valid_xml_data(element.serialize())

    def test_ignore_illegal_chars(self):
        illegal_ranges = [
            (0x0, 0x9),
            (0xb, 0xd),
            (0xe, 0x20),
            (0xd800, 0xe000),
            (0xfffe, 0x10000)
        ]

        for start, end in illegal_ranges:
            for value in xrange(start, end):
                element = xmlcore.Element("name")
                element.text = unichr(value)
                assert is_valid_xml_data(element.serialize())

        element = xmlcore.Element("name")
        element.text = u"\ud800\ud800"
        assert is_valid_xml_data(element.serialize())

    def test_legal_wide_unicode_chars(self):
        element = xmlcore.Element("name")
        element.text = u"\U00100000"
        assert is_valid_xml_data(element.serialize())

        element = xmlcore.Element("name")
        element.text = u"\ud800\U00100000"
        assert is_valid_xml_data(element.serialize())


class TestElementNamespaces(unittest.TestCase):
    def test_default_ns(self):
        element = xmlcore.Element("name", xmlns="default_ns")
        element.set_attr("xmlns:other", "other_ns")

        assert element.name == "name"
        assert element.ns == "default_ns"

    def test_non_default_ns(self):
        element = xmlcore.Element("other:name", xmlns="default_ns")
        element.set_attr("xmlns:other", "other_ns")

        assert element.name == "name"
        assert element.ns == "other_ns"

    def test_default_ns_inheritance(self):
        parent = xmlcore.Element("parent", xmlns="default_ns")
        child = xmlcore.Element("child")
        parent.add(child)

        assert child.name == "child"
        assert child.ns == "default_ns"

    def test_non_default_ns_inheritance(self):
        parent = xmlcore.Element("parent", xmlns="default_ns")
        parent.set_attr("xmlns:other", "other_ns")

        child = xmlcore.Element("other:child")
        parent.add(child)

        assert child.name == "child"
        assert child.ns == "other_ns"

    def test_default_ns_inheritance_vs_gc(self):
        import gc

        parent = xmlcore.Element("parent", xmlns="default_ns")
        child = xmlcore.Element("child")
        parent.add(child)

        del parent
        gc.collect()

        assert child.ns == "default_ns"
        assert not child.with_attrs("xmlns")
