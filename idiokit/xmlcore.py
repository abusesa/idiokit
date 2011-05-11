import codecs
import xml.parsers.expat
from xml.sax.saxutils import escape as _escape, quoteattr as _quoteattr

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

_utf8encoder = codecs.getencoder("utf-8")
def _encode(string):
    return _utf8encoder(string)[0]

_utf8decoder = codecs.getdecoder("utf-8")
def _decode(string):
    return _utf8decoder(string)[0]    

def namespace_split(name):
    if ":" not in name:
        return "xmlns", name
    split = name.rsplit(":", 1)
    return "xmlns:"+split[0], split[1]

_quoteattr_cache = dict()
_quoteattr_cache_size = 0
_quoteattr_cache_max_size = 2**16
def quoteattr(attr):
    global _quoteattr_cache_size

    value = _quoteattr_cache.get(attr, None)
    if value is not None:
        return value

    value = _quoteattr(attr)
    length = len(value) if attr is value else len(value) + len(attr)
    if length >= _quoteattr_cache_max_size:
        return value

    if _quoteattr_cache_max_size - _quoteattr_cache_size < length:
        _quoteattr_cache_size = 0
        _quoteattr_cache.clear()
    _quoteattr_cache[attr] = value
    _quoteattr_cache_size += length
    return value

def escape(text):
    escaped = _escape(text)
    if len(escaped) - len(text) > 12 and "]]>" not in text:
        return "<![CDATA[" + text + "]]>"
    return escaped

class _Element(object):
    @property
    def name(self):
        return _decode(self._name)

    @property
    def ns(self):
        attrs = self._attrs
        ns_name = self._ns_name
        
        while attrs is not None:
            if ns_name in attrs:
                return _decode(attrs[ns_name])
            attrs = attrs.get(None, None)
        return None

    def _get_text(self):
        return _decode(self._text)
    def _set_text(self, text):
        self._text = _encode(text)
    text = property(_get_text, _set_text)

    def _get_tail(self):
        return _decode(self._tail)
    def _set_tail(self, tail):
        self._tail = _encode(tail)
    tail = property(_get_tail, _set_tail)

    def __init__(self, _name, _text="", _tail="", **keys):
        _name = _encode(_name)
        _text = _encode(_text)
        _tail = _encode(_tail)

        self._full_name = _name
        self._ns_name, self._name = namespace_split(_name)
        self._text = _text
        self._tail = _tail

        self._children = None
        self._attrs = dict()
        for key, value in keys.iteritems():
            self.set_attr(key, value)

    def named(self, name=None, ns=None):
        if name is not None and self.name != name:
            return Query()
        if ns is not None and self.ns != ns:
            return Query()
        return self

    def add(self, *children):
        for child in children:
            child._attrs[None] = self._attrs
        if self._children is None:
            self._children = list()
        self._children.extend(children)

    def children(self, *args, **keys):
        children = list()
        for child in (self._children or ()):
            children.extend(child.named(*args, **keys))
        return Query(*children)

    def with_attrs(self, *args, **keys):
        for key in args:
            key = _encode(key.lower())
            if key not in self._attrs:
                return Query()

        for key, value in keys.iteritems():
            key = _encode(key.lower())
            if value is None and key not in self._attrs:
                return 

            other = self._attrs.get(key, None)
            if value is None and other is not None:
                return Query()
            if value is not None and other != _encode(value):
                return Query()
        return self

    def get_attr(self, key, default=None):
        key = _encode(key.lower())
        if key not in self._attrs:
            return default
        return _decode(self._attrs[key])

    def set_attr(self, key, value):
        key = _encode(unicode(key.lower()))
        value = _encode(unicode(value))
        self._attrs[key] = value

    def __iter__(self):
        yield self

    def __nonzero__(self):
        return True

    def __len__(self):
        return 1

    def _serialize_open(self, append, close=False):
        append("<" + self._full_name)
        for key, value in self._attrs.iteritems():
            if key is None:
                continue
            append(" " + key + "=" + quoteattr(value))

        if close:
            append("/>")
        else:
            append(">")

    def serialize_open(self):
        bites = list()
        self._serialize_open(bites.append)
        return "".join(bites)

    def _serialize_close(self, append):
        append("</" + self._full_name + ">")

    def serialize_close(self):
        bites = list()
        self._serialize_close(bites.append)
        return "".join(bites)

    def _serialize(self, append):
        if not (self._text or self._children):
            self._serialize_open(append, close=True)
        else:
            self._serialize_open(append, close=False)
            if self._text:
                append(escape(self._text))
            for child in (self._children or ()):
                child._serialize(append)
            self._serialize_close(append)

        if self._tail:
            append(escape(self._tail))

    def serialize(self):
        bites = list()
        self._serialize(bites.append)
        return "".join(bites)

_example = _Element("_example")
class Element(_Element):
    __slots__ = tuple(_example.__dict__)

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
        assert not child.with_attrs("xmlns")

if __name__ == "__main__":
    unittest.main()
