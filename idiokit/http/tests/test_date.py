import doctest

from .. import date


def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(date))
    return tests
