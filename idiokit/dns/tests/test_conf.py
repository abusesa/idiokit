import doctest

from .. import _conf


def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(_conf))
    return tests
