import doctest

from .. import _iputils


def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(_iputils))
    return tests
