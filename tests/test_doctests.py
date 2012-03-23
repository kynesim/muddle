#! /usr/bin/env python
"""Run any doctests in the muddled package.
"""

import doctest
import os

import support_for_tests
from muddled.utils import Directory

def main():
    total_tests = 0
    total_failures = 0
    with Directory(support_for_tests.PARENT_DIR):    # hopefully, muddled is herein
        for dirpath, dirnames, filenames in os.walk('muddled'):
            for name in filenames:
                base, ext = os.path.splitext(name)
                if ext != '.py':
                    continue
                path = os.path.join(dirpath, base)
                relpath = os.path.relpath(path, support_for_tests.PARENT_DIR)
                words = relpath.split(os.sep)
                module = '.'.join(words)

                environment = {}
                try:
                    exec 'import %s; thing=%s'%(module, module) in environment
                except AttributeError:
                    pass
                except ImportError as e:
                    print 'ImportError: %s'%e
                    break

                failures, tests = doctest.testmod(environment['thing'])

                if tests:
                    testword = "test"
                    if tests != 1: testword = "tests"
                    failword = "failure"
                    if failures != 1: failword = "failures"
                    print
                    print "File %s: %d %s, %d %s"%(path,
                            tests,'test' if tests==1 else 'tests',
                            failures, 'failure' if failures==1 else 'failures')
                    print
                    total_tests += tests
                    total_failures += failures
    print 'Found %d %s, %d %s'%(total_tests, 'test' if total_tests==1 else 'tests',
            total_failures, 'failure' if total_failures==1 else 'failures')

if __name__ == "__main__":
    main()
