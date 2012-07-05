#! /usr/bin/env python
"""Run all the test scripts, one by one

Looks for executable files, starting with 'test_' and ending with '.py', in
the same directory as this script, and runs them.

With argument -short, ignores the BZR and SVN checkout tests (because they
are slower).

With argument -ignore <test>, ignore the test script <script>.
"""

import os
import sys

from stat import *

from support_for_tests import *

def run_tests(args):
    ignore = set()
    while args:
        word = args.pop(0)
        if word in ('-h', '-help', '--help'):
            print __doc__
            return
        elif word == '-short':
            ignore.add('test_checkouts_bzr.py')
            ignore.add('test_checkouts_svn.py')
        elif word == '-ignore':
            name = args.pop(0)
            ignore.add(name)

    this_dir = os.path.split(__file__)[0]
    os.chdir(this_dir)
    files = os.listdir('.')

    unrecognised = ignore.difference(files)

    if unrecognised:
        raise GiveUp('Asked to ignore %s, which do%s not exist'%(', '.join(unrecognised),
                                'es' if len(unrecognised)==1 else ''))

    for name in sorted(files):
        if not name.startswith('test_'):
            continue
        if not name.endswith('.py'):
            continue
        if name in ignore:
            continue
        if not os.stat(name).st_mode & S_IEXEC:
            continue

        print
        print '======== %s ========'%name
        print
        try:
            shell('./%s'%name)
        except ShellError as e:
            raise GiveUp('Test %s failed with return code %d'%(name, e.retcode))
        print
    print 'All tests succeeded'

if __name__ == '__main__':
    try:
        run_tests(sys.argv[1:])
    except GiveUp as e:
        print e
        sys.exit(1)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
