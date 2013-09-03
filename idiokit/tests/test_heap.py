import unittest

from ..heap import Heap, HeapError


class HeapTests(unittest.TestCase):
    def test_pop(self):
        h = Heap([0, 1, 2, 3])
        assert h.pop() == 0
        assert h.pop() == 1
        assert h.pop() == 2
        assert h.pop() == 3
        self.assertRaises(HeapError, h.pop)

    def test_ordering_regression(self):
        heap = Heap()
        nodes = {}
        for i in [0, 5, 1, 6, 7, 2, 3, 8, 9, 10, 11, 4]:
            nodes[i] = heap.push(i)

        heap.pop(nodes[6])

        values = []
        while heap:
            values.append(heap.pop())
        self.assertEqual(values, sorted(values))
