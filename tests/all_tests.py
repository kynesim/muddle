#! /usr/bin/env python
"""Run all the test scripts, one by one

Looks for executable files, starting with 'test_' and ending with '.py', in
the same directory as this script, and runs them.

With argument -short, ignores the BZR and SVN checkout tests (because they
are slower).

With argument -ignore <test>, ignore the test script <script>.

With argument -list, lists the tests it would have run.
"""

import os
import sys
import stat

from support_for_tests import *

def is_executable(thing):
    return os.stat(thing)[stat.ST_MODE] & stat.S_IXUSR

def onpath(name):
    path = os.environ['PATH']
    path = path.split(os.path.pathsep)
    for place in path:
        thing = os.path.join(place, name)
        if os.path.exists(thing) and is_executable(thing):
            return True
    return False

def check_prerequisites():
    problems = []
    for item in ('git', 'bzr', 'svn'):
        if not onpath(item):
            problems.append(item)
    if problems:
        raise GiveUp('Some prerequisites are not available:\n'
                     'The following are not on the PATH: %s'%', '.join(problems))

def run_tests(args):
    ignore = set()
    just_list = False
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
        elif word == '-list':
            just_list = True
        else:
            raise GiveUp('Unrecognised argument "%s"'%word)

    this_dir = os.path.split(__file__)[0]
    os.chdir(this_dir)
    files = os.listdir('.')

    unrecognised = ignore.difference(files)

    if unrecognised:
        raise GiveUp('Asked to ignore %s, which do%s not exist'%(', '.join(unrecognised),
                                'es' if len(unrecognised)==1 else ''))

    tests = []

    for name in sorted(files):
        if not name.startswith('test_'):
            continue
        if not name.endswith('.py'):
            continue
        if name in ignore:
            continue
        if not os.stat(name).st_mode & stat.S_IEXEC:
            continue

        if just_list:
            tests.append(name)
            continue

        print
        print '======== %s ========'%name
        print
        try:
            shell('./%s'%name)
        except ShellError as e:
            raise GiveUp('Test %s failed with return code %d'%(name, e.retcode))
        print

    if just_list:
        print 'The following tests would have been run:'
        for name in tests:
            print ' ', name
    else:
        print 'All tests succeeded'

    if (ignore):
        print '(NB: ignored %s)'%(', '.join(ignore))

if __name__ == '__main__':
    try:
        check_prerequisites()
        run_tests(sys.argv[1:])
    except GiveUp as e:
        print e
        sys.exit(1)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
