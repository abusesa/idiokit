import xml.parsers.expat
from xml.sax.saxutils import escape as _escape, quoteattr as _quoteattr


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
_quoteattr_cache = dict()
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

    __slots__ = [
        "_full_name", "_ns_name", "_name",
        "text", "tail",
        "_children", "_attrs"
    ]

    def __init__(self, _name, _text=u"", _tail=u"", **keys):
        self._full_name = _name
        self._ns_name, self._name = namespace_split(_name)
        self.text = _text
        self.tail = _tail

        self._children = None
        self._attrs = dict()
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
        key = unicode(key)
        value = unicode(value)
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
        collected = Elements(*self.collected)
        self.collected = list()
        return collected
