from __future__ import absolute_import

import doctest

from .. import utils


def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(utils))
    return tests
