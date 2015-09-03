import doctest

from .. import httpversion


def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(httpversion))
    return tests
