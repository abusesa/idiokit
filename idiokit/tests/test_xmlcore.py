import unittest
import xml.parsers.expat

from .. import xmlcore


def is_valid_xml_data(data):
    try:
        xml.parsers.expat.ParserCreate("utf-8").Parse(data)
    except xml.parsers.expat.ExpatError:
        return False
    return True


class TestElementParser(unittest.TestCase):
    def test_text_inside_an_element_should_become_the_text_of_the_element(self):
        parser = xmlcore.ElementParser()
        for a in parser.feed("<root><a><b>test</b></a>"):
            self.assertEqual(a.name, u"a")
            self.assertEqual(a.text, u"")
            self.assertEqual(a.tail, u"")

            children = list(a.children())
            self.assertEqual(len(children), 1)

            self.assertEqual(children[0].name, u"b")
            self.assertEqual(children[0].text, u"test")
            self.assertEqual(children[0].tail, u"")

    def test_text_before_the_first_child_element_should_be_the_text_of_the_parent(self):
        parser = xmlcore.ElementParser()
        for a in parser.feed("<root><a>test<b /></a>"):
            self.assertEqual(a.name, u"a")
            self.assertEqual(a.text, u"test")
            self.assertEqual(a.tail, u"")

            children = list(a.children())
            self.assertEqual(len(children), 1)

            self.assertEqual(children[0].name, u"b")
            self.assertEqual(children[0].text, u"")
            self.assertEqual(children[0].tail, u"")

    def test_text_after_the_last_child_element_should_be_the_tail_of_the_child_element(self):
        parser = xmlcore.ElementParser()
        for a in parser.feed("<root><a><b />test</a>"):
            self.assertEqual(a.name, u"a")
            self.assertEqual(a.text, u"")
            self.assertEqual(a.tail, u"")
            self.assertEqual(len(a.children()), 1)

            children = list(a.children())
            self.assertEqual(len(children), 1)

            self.assertEqual(children[0].name, u"b")
            self.assertEqual(children[0].text, u"")
            self.assertEqual(children[0].tail, u"test")

    def test_text_between_two_child_elements_should_be_the_tail_of_the_first_child_element(self):
        parser = xmlcore.ElementParser()

        for a in parser.feed("<root><a><b />test<c /></a>"):
            self.assertEqual(a.text, u"")
            self.assertEqual(a.tail, u"")

            children = list(a.children())
            self.assertEqual(len(children), 2)

            self.assertEqual(children[0].name, u"b")
            self.assertEqual(children[0].text, u"")
            self.assertEqual(children[0].tail, u"test")

            self.assertEqual(children[1].name, u"c")
            self.assertEqual(children[1].text, u"")
            self.assertEqual(children[1].tail, u"")


class TestCharacterSet(unittest.TestCase):
    NON_XML_RANGES = [(0x0, 0x9), (0xb, 0xd), (0xe, 0x20), (0xd800, 0xe000), (0xfffe, 0x10000)]
    NON_XML_STRINGS = [unichr(x) for start, end in NON_XML_RANGES for x in xrange(start, end)]
    NON_XML_STRINGS += [u"\ud800\ud800", u"\ud800\U00100000"]

    def test_raise_on_non_xml_chars_in_text(self):
        for x in self.NON_XML_STRINGS:
            element = xmlcore.Element("name")
            self.assertRaises(ValueError, setattr, element, "text", x)

    def test_accept_wide_unicode_chars_in_text(self):
        element = xmlcore.Element("name")
        element.text = u"\U00100000"
        assert is_valid_xml_data(element.serialize())

        element = xmlcore.Element("name")
        element.text = u"\udbc0\udc00"
        assert is_valid_xml_data(element.serialize())

    def test_raise_on_non_xml_chars_in_tail(self):
        for x in self.NON_XML_STRINGS:
            element = xmlcore.Element("name")
            self.assertRaises(ValueError, setattr, element, "tail", x)

    def test_accept_wide_unicode_chars_in_tail(self):
        element = xmlcore.Element("name")

        wide = xmlcore.Element("inner")
        wide.tail = u"\U00100000"
        element.add(wide)

        surrogate = xmlcore.Element("surrogate")
        surrogate.tail = u"\udbc0\udc00"
        element.add(surrogate)

        assert is_valid_xml_data(element.serialize())

    def test_raise_on_non_xml_chars_in_name(self):
        for x in self.NON_XML_STRINGS:
            self.assertRaises(ValueError, xmlcore.Element, x)

    def test_raise_on_non_xml_chars_in_attr_key(self):
        for x in self.NON_XML_STRINGS:
            element = xmlcore.Element("name")
            self.assertRaises(ValueError, element.set_attr, x, "value")

    def test_raise_on_non_xml_chars_in_attr_value(self):
        for x in self.NON_XML_STRINGS:
            element = xmlcore.Element("name")
            self.assertRaises(ValueError, element.set_attr, "key", x)


class TestEncoding(unittest.TestCase):
    def test_escape(self):
        element = xmlcore.Element("name")
        element.text = "<&>"
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
