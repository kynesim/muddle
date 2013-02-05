#! /usr/bin/env python
"""Test checkout support for svn.

    $ ./test_checkouts_svn.py [-keep]

With -keep, do not delete the 'transient' directory used for the tests.

Subversion must be installed.
"""

import os
import shutil
import subprocess
import sys
import traceback

from support_for_tests import *

try:
    import muddled.cmdline
except ImportError:
    # Try one level up
    sys.path.insert(0, get_parent_dir(__file__))
    import muddled.cmdline

from muddled.utils import GiveUp, normalise_dir
from muddled.withdir import Directory, NewDirectory, TransientDirectory

MUDDLE_MAKEFILE = """\
# Trivial muddle makefile
all:
\t@echo Make all for $(MUDDLE_LABEL)

config:
\t@echo Make configure for $(MUDDLE_LABEL)

install:
\t@echo Make install for $(MUDDLE_LABEL)

clean:
\t@echo Make clean for $(MUDDLE_LABEL)

distclean:
\t@echo Make distclean for $(MUDDLE_LABEL)

.PHONY: all config install clean distclean
"""

CHECKOUT_BUILD_SVN_REVISIONS = """ \
# Test build for testing checkouts at a particular revision
# This version is specific to subversion

import muddled.checkouts.simple

def describe_to(builder):
    builder.build_name = 'checkout_test'

    muddled.checkouts.simple.relative(builder,
                                      co_name='checkout1',
                                      rev='2')
"""

CHECKOUT_BUILD_SVN_NO_REVISIONS = """ \
# Test build for testing checkouts at a particular revision
# This version is specific to subversion

import muddled.checkouts.simple

def describe_to(builder):
    builder.build_name = 'checkout_test'

    muddled.checkouts.simple.relative(builder,
                                      co_name='checkout1')
"""

def test_svn_simple_build():
    """Bootstrap a muddle build tree.
    """
    root_dir = normalise_dir(os.getcwd())

    with NewDirectory('repo'):
        for name in ('main', 'versions'):
            shell('svnadmin create %s'%name)

        print 'Repositories are:', ' '.join(os.listdir('.'))

    root_repo = 'file://' + os.path.join(root_dir, 'repo', 'main')
    versions_repo = 'file://' + os.path.join(root_dir, 'repo', 'versions')
    with NewDirectory('test_build1'):
        banner('Bootstrapping simple build')
        muddle(['bootstrap', 'svn+%s'%root_repo, 'test_build'])
        cat('src/builds/01.py')

        # But, of course, we don't keep the versions/ directory in the same
        # repository (lest things get very confused)
        touch('.muddle/VersionsRepository', 'svn+%s\n'%versions_repo)
        with Directory('versions'):
            touch('fred.stamp',
                  '# A comment\n# Another comment\n')
            svn('import . %s -m "Initial import"'%versions_repo)

        # Is the next really the best we can do?
        shell('rm -rf versions')
        svn('checkout %s'%versions_repo)

        with Directory('src'):
            with Directory('builds'):
                svn('import . %s/builds -m "Initial import"'%root_repo)

            # Is the next really the best we can do?
            shell('rm -rf builds')
            svn('checkout %s/builds'%root_repo)

        banner('Stamping simple build')
        muddle(['stamp', 'version'])
        with Directory('versions'):
            svn('commit -m "A proper stamp file"')
            cat('test_build.stamp')

    # We should be able to check everything out from the repository
    with NewDirectory('test_build2'):
        banner('Building from init')
        muddle(['init', 'svn+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout','_all'])

    # We should be able to recreate our state from the stamp file...
    with NewDirectory('test_build3'):
        banner('Unstamping simple build')
        # Note that we do not ask for 'versions/test_build.stamp', since
        # our repository corresponds to this versions/ directory as a whole...
        muddle(['unstamp', 'svn+%s'%versions_repo, 'test_build.stamp'])

def test_svn_revisions_build():
    """Test a build tree where a checkout has a specific revision

    Doing 'muddle pull' or 'muddle merge' in such a directory should
    not update it.
    """
    root_dir = normalise_dir(os.getcwd())

    with NewDirectory('repo'):
        shell('svnadmin create main')

    root_repo = 'file://' + os.path.join(root_dir, 'repo', 'main')
    with NewDirectory('test_build1'):
        banner('Bootstrapping SVN revisions build')
        muddle(['bootstrap', 'svn+%s'%root_repo, 'test_build'])

        with Directory('src'):
            with Directory('builds'):
                touch('01.py', CHECKOUT_BUILD_SVN_REVISIONS)
                svn('import . %s/builds -m "Initial import"'%root_repo)

            # Is the next really the best we can do?
            shell('rm -rf builds')
            svn('checkout %s/builds'%root_repo)

            with TransientDirectory('checkout1'):
                touch('Makefile.muddle','# A comment\n')
                svn('import . %s/checkout1 -m "Initial import"'%root_repo)
            svn('checkout %s/checkout1'%root_repo)

            with Directory('checkout1'):
                touch('Makefile.muddle','# A different comment\n')
                svn('commit -m "Second version of Makefile.muddle"')
                shell('svnversion')

            with Directory('checkout1'):
                touch('Makefile.muddle','# Yet another different comment\n')
                svn('commit -m "Third version of Makefile.muddle"')
                shell('svnversion')

    # We should be able to check everything out from the repository
    with NewDirectory('test_build2'):
        banner('Building from init')
        muddle(['init', 'svn+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout','_all'])

        with Directory('src'):
            with Directory('checkout1'):
                revno = get_stdout('svnversion').strip()
                if revno != '2':
                    raise GiveUp('Revision number for checkout1 is %s, not 2'%revno)
                muddle(['pull'])
                revno = get_stdout('svnversion').strip()
                if revno != '2':
                    raise GiveUp('Revision number for checkout1 is %s, not 2 (after pull)'%revno)
                muddle(['merge'])
                revno = get_stdout('svnversion').strip()
                if revno != '2':
                    raise GiveUp('Revision number for checkout1 is %s, not 2 (after merge)'%revno)

            # But if we remove the restriction on revision number
            with Directory('builds'):
                touch('01.py', CHECKOUT_BUILD_SVN_NO_REVISIONS)
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')

            with Directory('checkout1'):
                muddle(['pull'])
                revno = get_stdout('svnversion').strip()
                if revno != '4':
                    raise GiveUp('Revision number for checkout1 is %s, not 4 (after pull)'%revno)

def test_just_pulled():
    root_dir = normalise_dir(os.getcwd())

    # Set up our repository
    with NewDirectory('repo'):
        shell('svnadmin create main')

    root_repo = 'file://' + os.path.join(root_dir, 'repo', 'main')
    banner('Repository')
    with NewDirectory('build_0'):
        muddle(['bootstrap', 'svn+%s'%root_repo, 'test_build'])
        with Directory('src'):
            with Directory('builds'):
                touch('01.py', CHECKOUT_BUILD_SVN_NO_REVISIONS)
                svn('import . %s/builds -m "Initial import"'%root_repo)

            with TransientDirectory('checkout1'):
                touch('Makefile.muddle','# A comment\n')
                svn('import . %s/checkout1 -m "Initial import"'%root_repo)

    banner('Build A')
    with NewDirectory('build_A'):
        muddle(['init', 'svn+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout', '_all'])

    banner('Build B')
    with NewDirectory('build_B'):
        muddle(['init', 'svn+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout', '_all'])

    banner('Change Build A')
    with Directory('build_A'):
        with Directory('src'):
            with Directory('builds'):
                append('01.py', '# Just a comment\n')
                svn('commit -m "A simple change"')
                muddle(['push'])
            with Directory('checkout1'):
                append('Makefile.muddle', '# Just a comment\n')
                svn('commit -m "A simple change"')
                muddle(['push'])

    banner('Pull into Build B')
    with Directory('build_B') as d:
        _just_pulled_file = os.path.join(d.where, '.muddle', '_just_pulled')
        if os.path.exists(_just_pulled_file):
            raise GiveUp('%s exists when it should not'%_just_pulled_file)
        muddle(['pull', '_all'])
        if not same_content(_just_pulled_file,
                            'checkout:builds/checked_out\n'
                            'checkout:checkout1/checked_out\n'):
            raise GiveUp('%s does not contain expected labels:\n%s'%(
                _just_pulled_file,open(_just_pulled_file).readlines()))
        muddle(['pull', '_all'])
        if not same_content(_just_pulled_file, ''):
            raise GiveUp('%s should be empty, but is not'%_just_pulled_file)

def main(args):

    keep = False
    if args:
        if len(args) == 1 and args[0] == '-keep':
            keep = True
        else:
            print __doc__
            return

    # Choose a place to work, rather hackily
    #root_dir = os.path.join('/tmp','muddle_tests')
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with TransientDirectory(root_dir, keep_on_error=True, keep_anyway=keep) as root_d:
        with NewDirectory('simple'):
            banner('TEST SIMPLE BUILD (SUBVERSION)')
            test_svn_simple_build()

        with NewDirectory('checkout'):
            banner('TEST BUILD WITH REVISION (SUBVERSION)')
            test_svn_revisions_build()

        with NewDirectory('just_pulled'):
            banner('TEST _JUST_PULLED')
            test_just_pulled()

if __name__ == '__main__':
    args = sys.argv[1:]
    try:
        main(args)
        print '\nGREEN light\n'
    except Exception as e:
        print
        traceback.print_exc()
        print '\nRED light\n'
        sys.exit(1)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
