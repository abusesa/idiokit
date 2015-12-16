import re
import sys
import xml.parsers.expat
from xml.sax.saxutils import escape as _escape, quoteattr as _quoteattr


if sys.maxunicode <= 65535:
    _NON_XML_SAFE = re.compile(ur"^(?:[\ud800-\udbff][\udc00-\udfff]|[\u0009\u000a\u000d\u0020-\ud7ff\uE000-\uFFFD])*$", re.U)
else:
    _NON_XML_SAFE = re.compile(ur"^(?:[\U00010000-\U0010FFFF]|[\ud800-\udbff][\udc00-\udfff]|[\u0009\u000a\u000d\u0020-\ud7ff\uE000-\uFFFD])*$", re.U)


def is_xml_safe(string):
    r"""
    Return True when the string contains only characters inside
    the XML 1.0 character range, False otherwise.

    >>> is_xml_safe("test")
    True

    >>> is_xml_safe("\x00")
    False
    """

    return bool(_NON_XML_SAFE.match(string))


class _XMLSafeUnicode(object):
    r"""
    A marker class that asserts to _to_xml_safe_unicode(...) that the contained
    unicode value is XML safe and does not need to be checked.

    >>> _to_xml_safe_unicode(_XMLSafeUnicode(u"test"))
    u'test'

    This class is an internal optimization (to allow ElementParser to skip
    redundant checks when creating Element instances) and should not be
    used nor referenced outside of this module.
    """

    __slots__ = ["value"]

    def __init__(self, value):
        self.value = value


def _to_xml_safe_unicode(string):
    r"""
    Coerce the argument string into a unicode object that contains
    only characters inside the XML 1.0 range.

    >>> _to_xml_safe_unicode(u"unicode string")
    u'unicode string'
    >>> _to_xml_safe_unicode("byte string")
    u'byte string'

    Raise an UnicodeDecodeError when the argument is not a
    unicode object and can not be decoded into one using the
    ASCII encoding.

    >>> _to_xml_safe_unicode("\xe4")
    Traceback (most recent call last):
        ...
    UnicodeDecodeError: ...

    Raise a ValueError when the argument contains characters
    outside the XML 1.0 character range.

    >>> _to_xml_safe_unicode("\x00")
    Traceback (most recent call last):
        ...
    ValueError: string contains non-XML safe characters
    """

    if isinstance(string, _XMLSafeUnicode):
        return string.value

    string = unicode(string)
    if not is_xml_safe(string):
        raise ValueError("string contains non-XML safe characters")

    return string


class Elements(object):
    __slots__ = ["_elements"]

    def __init__(self, *elements):
        element_list = list()
        for element in elements:
            element_list.extend(element)
        self._elements = tuple(element_list)

    def named(self, *args, **keys):
        elements = (x.named(*args, **keys) for x in self._elements)
        return Elements(*elements)

    def children(self, *args, **keys):
        elements = (x.children(*args, **keys) for x in self._elements)
        return Elements(*elements)

    def with_attrs(self, *args, **keys):
        elements = (x.with_attrs(*args, **keys) for x in self._elements)
        return Elements(*elements)

    def __len__(self):
        return len(self._elements)

    def __iter__(self):
        return iter(self._elements)

    def __nonzero__(self):
        return not not self._elements


def namespace_split(name):
    if ":" not in name:
        return "xmlns", name
    split = name.rsplit(":", 1)
    return "xmlns:" + split[0], split[1]


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
_quoteattr_cache = {}
_quoteattr_cache_size = 0
_quoteattr_cache_max_size = 2 ** 16


def escape(text):
    escaped = _escape(text)
    if len(escaped) - len(text) > 12 and "]]>" not in text:
        return "<![CDATA[" + text + "]]>"
    return escaped


class Element(object):
    @property
    def name(self):
        return self._name

    @property
    def ns(self):
        attrs = self._attrs
        ns_name = self._ns_name

        while attrs is not None:
            if ns_name in attrs:
                return attrs[ns_name]
            attrs = attrs.get(None, None)
        return None

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = _to_xml_safe_unicode(value)

    @property
    def tail(self):
        return self._tail

    @tail.setter
    def tail(self, value):
        self._tail = _to_xml_safe_unicode(value)

    __slots__ = [
        "_full_name",
        "_ns_name",
        "_name",
        "_text",
        "_tail",
        "_children",
        "_attrs"
    ]

    def __init__(self, _name, _text=u"", _tail=u"", **keys):
        _name = _to_xml_safe_unicode(_name)
        _text = _to_xml_safe_unicode(_text)
        _tail = _to_xml_safe_unicode(_tail)

        self._full_name = _name
        self._ns_name, self._name = namespace_split(_name)
        self._text = _text
        self._tail = _tail

        self._children = None
        self._attrs = {}
        for key, value in keys.iteritems():
            self.set_attr(key, value)

    def named(self, name=None, ns=None):
        if name is not None and self.name != name:
            return Elements()
        if ns is not None and self.ns != ns:
            return Elements()
        return self

    def add(self, *children):
        children = Elements(*children)
        for child in children:
            child._attrs[None] = self._attrs
        if self._children is None:
            self._children = list()
        self._children.extend(children)

    def children(self, *args, **keys):
        children = list()
        for child in (self._children or ()):
            children.extend(child.named(*args, **keys))
        return Elements(*children)

    def with_attrs(self, *args, **keys):
        for key in args:
            if key not in self._attrs:
                return Elements()

        for key, value in keys.iteritems():
            if value is None and key not in self._attrs:
                return

            other = self._attrs.get(key, None)
            if value is None and other is not None:
                return Elements()
            if value is not None and other != value:
                return Elements()
        return self

    def get_attr(self, key, default=None):
        if key not in self._attrs:
            return default
        return self._attrs[key]

    def set_attr(self, key, value):
        key = _to_xml_safe_unicode(key)
        value = _to_xml_safe_unicode(value)
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
        return "".join(bites).encode("utf-8")

    def _serialize_close(self, append):
        append("</" + self._full_name + ">")

    def serialize_close(self):
        bites = list()
        self._serialize_close(bites.append)
        return "".join(bites).encode("utf-8")

    def _serialize(self, append):
        if not (self.text or self._children):
            self._serialize_open(append, close=True)
        else:
            self._serialize_open(append, close=False)
            if self.text:
                append(escape(self.text))
            for child in (self._children or ()):
                child._serialize(append)
            self._serialize_close(append)

        if self.tail:
            append(escape(self.tail))

    def serialize(self, encoding=None):
        bites = list()
        self._serialize(bites.append)
        return u"".join(bites).encode("utf-8")


class ElementParser(object):
    def __init__(self):
        self._parser = xml.parsers.expat.ParserCreate("utf-8")
        self._parser.StartElementHandler = self.start_element
        self._parser.EndElementHandler = self.end_element
        self._parser.CharacterDataHandler = self.char_data

        self._text = []
        self._stack = []
        self._collected = []

    def _flush_text(self):
        if not self._text:
            return
        text = _XMLSafeUnicode(u"".join(self._text))
        self._text[:] = []

        assert self._stack
        current = self._stack[-1]
        children = current._children
        if children:
            children[-1].tail = text
        else:
            current.text = text

    def start_element(self, name, attrs):
        self._flush_text()

        element = Element(_XMLSafeUnicode(name))
        for key, value in attrs.iteritems():
            element.set_attr(_XMLSafeUnicode(key), _XMLSafeUnicode(value))

        if self._stack:
            self._stack[-1].add(element)
        self._stack.append(element)

    def end_element(self, name):
        self._flush_text()

        current = self._stack.pop()
        if len(self._stack) == 1:
            last = self._stack[-1]._children.pop()
            assert current is last
            self._collected.append(current)

    def char_data(self, data):
        if len(self._stack) > 1:
            self._text.append(data)

    def feed(self, data):
        self._parser.Parse(data)
        collected = Elements(*self._collected)
        self._collected = list()
        return collected
