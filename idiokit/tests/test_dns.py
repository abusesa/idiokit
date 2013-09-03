import doctest

from .. import dns


def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(dns))
    return tests
