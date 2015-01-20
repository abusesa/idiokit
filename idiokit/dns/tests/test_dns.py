import doctest
import unittest

from .. import _dns


def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(_dns))
    return tests


class UnpackNameTests(unittest.TestCase):
    def test_unpack_valid(self):
        self.assertEqual(_dns.unpack_name("\x00"), ("", 1))
        self.assertEqual(_dns.unpack_name("\x01a\x01b\x01c\x00"), ("a.b.c", 7))
        self.assertEqual(_dns.unpack_name("\x01a\x01b\x01c\x00", offset=2), ("b.c", 7))
        self.assertEqual(_dns.unpack_name("\x01a\x01b\x01c\x00\xc0\x00", offset=7), ("a.b.c", 9))

    def test_invalid_octets(self):
        """
        Raise MessageError when an octet that should be either start a label
        (two highest bits 00) or a pointer (two highest bits 11) has its two
        highest bits set to 01 or 10 instead.
        """

        self.assertRaises(_dns.MessageError, _dns.unpack_name, "\x00\x40\x00", offset=1)
        self.assertRaises(_dns.MessageError, _dns.unpack_name, "\x00\x70\x00", offset=1)

    def test_max_name_length(self):
        """
        A packed name (labels + label lengths) must be at most 255 octets in total.
        The last null octet also consumes the octet budget, whereas pointers do not.
        """

        # 254 octets of label data and the corresponding unpacked label
        octets_254 = "\x02aa" + ("\x01a" * 125) + "\x00"
        label_254 = ".".join(["aa"] + ["a"] * 125)

        # 255 octets of label data and the corresponding unpacked label
        octets_255 = ("\x01a" * 127) + "\x00"
        label_255 = ".".join(["a"] * 127)

        # 256 octets of label data
        octets_256 = "\x02aa" + ("\x01a" * 126) + "\x00"

        # 305 octets of label data that runs over the octet budget
        # in the middle of the last label
        octets_300 = ("\x01a" * 120) + ("\x3f" + "a" * 63) + "\x00"

        self.assertEqual(_dns.unpack_name(octets_254), (label_254, 254))
        self.assertEqual(_dns.unpack_name(octets_255), (label_255, 255))
        self.assertRaises(_dns.MessageError, _dns.unpack_name, octets_256)
        self.assertRaises(_dns.MessageError, _dns.unpack_name, octets_300)

        # Check neither octets in the pointers do not consume the octet budget
        self.assertEqual(
            _dns.unpack_name(octets_254 + "\xc0\x00", offset=len(octets_254)),
            (label_254, 256)
        )
        self.assertEqual(
            _dns.unpack_name(octets_255 + "\xc0\x00", offset=len(octets_255)),
            (label_255, 257)
        )
        self.assertRaises(
            _dns.MessageError,
            _dns.unpack_name,
            octets_256 + "\xc0\x00",
            offset=len(octets_256)
        )

    def test_truncated_data(self):
        self.assertRaises(_dns.NotEnoughData, _dns.unpack_name, "")
        self.assertRaises(_dns.NotEnoughData, _dns.unpack_name, "\x02")
        self.assertRaises(_dns.NotEnoughData, _dns.unpack_name, "\x02a")
        self.assertRaises(_dns.NotEnoughData, _dns.unpack_name, "\x02aa")
        self.assertRaises(_dns.NotEnoughData, _dns.unpack_name, "\x02aa\x00", offset=4)

    def test_pointer_outside_data(self):
        # Point to offset=255 in a 2 byte chunk of data.
        self.assertRaises(_dns.NotEnoughData, _dns.unpack_name, "\xc0\xff")

    def test_pointer_loop(self):
        self.assertRaises(_dns.MessageError, _dns.unpack_name, "\xc0\x00")
