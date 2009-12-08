import re
import xml.parsers.expat
from xml.sax.saxutils import escape, quoteattr

class Query(object):
    def __init__(self, *elements):
        self.elements = elements

    def named(self, *args, **keys):
        elements = list()
        for element in self.elements:
            elements.extend(element.named(*args, **keys))
        return Query(*elements)        

    def children(self, *args, **keys):
        elements = list()
        for element in self.elements:
            elements.extend(element.children(*args, **keys))
        return Query(*elements)

    def with_attrs(self, *args, **keys):
        elements = list()
        for element in self.elements:
            elements.extend(element.with_attrs(*args, **keys))
        return Query(*elements)        

    def __len__(self):
        return len(self.elements)

    def __iter__(self):
        return iter(self.elements)

    def __nonzero__(self):
        return len(self.elements) > 0

def namespace_split(name):
    split = name.rsplit(":", 1)
    if len(split) == 1:
        return "xmlns", split[-1]
    return "xmlns:"+split[0], split[1]

class Element(object):
    @property
    def ns(self):
        return self.ns_attrs.get(self._ns_name, None)

    def __init__(self, name, **keys):
        self._children = list()

        self._original_name = name
        self._ns_name, self.name = namespace_split(name)

        self.attrs = dict()
        self.ns_attrs = dict()
        self.text = ""
        self.tail = ""

        for key, value in keys.iteritems():
            self.set_attr(key, value)

    def named(self, name=None, ns=None):
        if name is not None and self.name != name:
            return Query()
        if ns is not None and self.ns != ns:
            return Query()
        return self

    def _reparent(self, ns_attrs):
        ns_attrs = dict(ns_attrs)
        ns_attrs.update([item for item in self.attrs.items()
                         if item[0].startswith("xmlns")])
        for child in self._children:
            child._reparent(ns_attrs)
        self.ns_attrs = ns_attrs

    def add(self, *children):
        for child in children:            
            child._reparent(self.ns_attrs)
        self._children.extend(children)

    def children(self, *args, **keys):
        children = list()
        for child in self._children:
            children.extend(child.named(*args, **keys))
        return Query(*children)
        
    def with_attrs(self, *args, **keys):
        for key in args:
            key = key.lower()
            if key not in self.attrs:
                return Query()
        for key, value in keys.iteritems():
            key = key.lower()
            other = self.attrs.get(key, None)
            if other != value:
                return Query()
        return self

    def has_attrs(self, *args, **keys):
        return self.with_attrs(*args, **keys).__nonzero__()

    def get_attr(self, key, default=None):
        return self.attrs.get(key, default)

    def set_attr(self, key, value, _inherited=False):
        if not _inherited:
            key = unicode(key.lower())
            value = unicode(value)
            self.attrs[key] = value

        if _inherited or key.startswith("xmlns"):
            self.ns_attrs[key] = value
            for child in self._children:
                child.set_attr(key, value, True)

    def __iter__(self):
        yield self

    def __nonzero__(self):
        return True

    def __len__(self):
        return 1

    def _serialize_open(self):
        bites = list()

        bites.append("<%s" % self._original_name)
        for key, value in self.attrs.iteritems():
            bites.append(" %s=%s" % (key, quoteattr(value)))
        bites.append(">")

        return bites

    def serialize_open(self):
        return "".join(self._serialize_open()).encode("utf-8")

    def _serialize_close(self):
        return "</%s>" % self._original_name

    def serialize_close(self):
        return self._serialize_close().encode("utf-8")

    def _serialize(self):
        bites = list(self._serialize_open())
        if self.text:
            bites.append(escape(self.text))
        for child in self._children:
            bites.extend(child._serialize())
        bites.append(self._serialize_close())
        if self.tail:
            bites.append(escape(self.tail))
            
        return bites

    def serialize(self):
        data = "".join(self._serialize())
        return data.encode("utf-8")

class ElementParser(object):
    def __init__(self):
        self.parser = xml.parsers.expat.ParserCreate("utf-8")
        self.parser.StartElementHandler = self.start_element
        self.parser.EndElementHandler = self.end_element
        self.parser.CharacterDataHandler = self.char_data

        self.stack = list()
        self.collected = list()
        
    def start_element(self, name, attrs):
        element = Element(name)
        for key, value in attrs.iteritems():
            element.set_attr(key, value)

        if self.stack:
            self.stack[-1].add(element)
        self.stack.append(element)

    def end_element(self, name):
        current = self.stack.pop()
        if len(self.stack) != 1:
            return
        last = self.stack[-1]._children.pop()
        assert current is last
        self.collected.append(current)

    def char_data(self, data):
        current = self.stack[-1]
        if len(self.stack) == 1:
            return
        children = current._children
        if not children:
            current.text += data
        else:
            children[-1].tail += data

    def feed(self, data):
        self.parser.Parse(data)
        collected = Query(*self.collected)
        self.collected = list()
        return collected

import unittest

def is_valid_xml_data(data):
    try:
        xml.parsers.expat.ParserCreate("utf-8").Parse(data)
    except xml.parsers.expat.ExpatError:
        return False
    return True

class TestEncoding(unittest.TestCase):
    def test_escape(self):
        element = Element("name")
        element.text = "<&>"
        assert is_valid_xml_data(element.serialize())
    
    def test_ignore_illegal_chars(self):
        illegal_ranges = [(0x0, 0x9), (0xb, 0xd), (0xe, 0x20),
                          (0xd800, 0xe000), (0xfffe, 0x10000)]

        for start, end in illegal_ranges:
            for value in xrange(start, end):
                element = Element("name")
                element.text = unichr(value)
                assert is_valid_xml_data(element.serialize())

        element = Element("name")
        element.text = u"\ud800\ud800"
        assert is_valid_xml_data(element.serialize())

    def test_legal_wide_unicode_chars(self):
        element = Element("name")
        element.text = u"\U00100000"
        assert is_valid_xml_data(element.serialize())

        element = Element("name")
        element.text = u"\ud800\U00100000"
        assert is_valid_xml_data(element.serialize())

class TestElementNamespaces(unittest.TestCase):
    def test_default_ns(self):
        element = Element("name", xmlns="default_ns")
        element.set_attr("xmlns:other", "other_ns")

        assert element.name == "name"
        assert element.ns == "default_ns"

    def test_non_default_ns(self):
        element = Element("other:name", xmlns="default_ns")
        element.set_attr("xmlns:other", "other_ns")

        assert element.name == "name"
        assert element.ns == "other_ns"

    def test_default_ns_inheritance(self):
        parent = Element("parent", xmlns="default_ns")
        child = Element("child")
        parent.add(child)

        assert child.name == "child"
        assert child.ns == "default_ns"

    def test_non_default_ns_inheritance(self):
        parent = Element("parent", xmlns="default_ns")
        parent.set_attr("xmlns:other", "other_ns")

        child = Element("other:child")
        parent.add(child)

        assert child.name == "child"
        assert child.ns == "other_ns"

    def test_default_ns_inheritance_vs_gc(self):
        import gc

        parent = Element("parent", xmlns="default_ns")
        child = Element("child")
        parent.add(child)

        del parent
        gc.collect()

        assert child.ns == "default_ns"
        assert not child.has_attrs("xmlns")

if __name__ == "__main__":
    unittest.main()
