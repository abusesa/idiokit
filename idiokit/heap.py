class HeapError(Exception):
    pass


class Heap(object):
    def __init__(self, iterable=()):
        self._heap = []

        for value in iterable:
            self.push(value)

    def _get(self, node):
        if not self._heap:
            raise HeapError("empty heap")

        if node is None:
            return self._heap[0]

        if len(self._heap) <= node._index or self._heap[node._index] is not node:
            raise HeapError("node not in the heap")

        return node

    def push(self, value):
        node = _Node(len(self._heap), value)
        self._heap.append(node)
        _up(self._heap, node)
        return node

    def peek(self, node=None):
        return self._get(node)._value

    def pop(self, node=None):
        node = self._get(node)

        last = self._heap.pop()
        if last is not node:
            self._heap[node._index] = last
            last._index = node._index
            _down(self._heap, last)
            _up(self._heap, last)
        return node._value

    def head(self):
        return self._get(None)

    def __len__(self):
        return len(self._heap)


class _Node(object):
    __slots__ = "_index", "_value"

    def __init__(self, index, value):
        self._index = index
        self._value = value


def _swap(array, left, right):
    array[left._index] = right
    array[right._index] = left
    left._index, right._index = right._index, left._index


def _up(array, node):
    while node._index > 0:
        parent = array[(node._index - 1) // 2]
        if parent._value <= node._value:
            break
        _swap(array, node, parent)


def _down(array, node):
    length = len(array)

    while True:
        smallest = node

        left_index = 2 * node._index + 1
        if left_index < length:
            left = array[left_index]
            if left._value < smallest._value:
                smallest = left

        right_index = left_index + 1
        if right_index < length:
            right = array[right_index]
            if right._value < smallest._value:
                smallest = right

        if node is smallest:
            break

        _swap(array, node, smallest)
