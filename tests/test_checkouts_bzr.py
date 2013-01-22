#! /usr/bin/env python
"""Test checkout support for bzr.

    $ ./test_checkouts_bzr.py [-keep]

With -keep, do not delete the 'transient' directory used for the tests.

Bazaar must be installed.
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
from muddled.utils import Directory, NewDirectory, TransientDirectory

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

CHECKOUT_BUILD_LEVELS = """ \
# Test build for testing checkouts into directories at different levels
# Does not test 'repo_rel', since git does not support cloning a "bit" of a
# repository. Testing that will have to wait for subversion testing (!).

import muddled.checkouts.simple
import muddled.checkouts.twolevel
import muddled.checkouts.multilevel

def describe_to(builder):
    builder.build_name = 'checkout_test'

    # checkout1
    # Simple, <repo>/<checkout> -> src/<checkout>
    muddled.checkouts.simple.relative(builder,
                                      co_name='checkout1')

    # checkout2
    # twolevel, <repo>/twolevel/<checkout> -> src/twolevel/<checkout>
    muddled.checkouts.twolevel.relative(builder,
                                        co_dir='twolevel',
                                        co_name='checkout2')

    # checkout3
    # Multilevel, <repo>/multilevel/inner/<checkout> -> src/multilevel/inner/<checkout>
    muddled.checkouts.multilevel.relative(builder,
                                          co_dir='multilevel/inner/checkout3',
                                          co_name='alice')
"""

def test_bzr_simple_build():
    """Bootstrap a muddle build tree.
    """
    root_dir = normalise_dir(os.getcwd())

    with NewDirectory('repo'):
        for name in ('builds', 'versions'):
            with NewDirectory(name):
                bzr('init')

        print 'Repositories are:', ' '.join(os.listdir('.'))

    root_repo = 'file://' + os.path.join(root_dir, 'repo')
    with NewDirectory('test_build1'):
        banner('Bootstrapping simple build')
        muddle(['bootstrap', 'bzr+%s'%root_repo, 'test_build'])
        cat('src/builds/01.py')

        with Directory('versions'):
            touch('fred.stamp',
                  '# A comment\n# Another comment\n')
            bzr('add fred.stamp')
            bzr('commit -m "New stamp file"')
            bzr('push %s/versions'%root_repo)

        with Directory('src/builds'):
            bzr('commit -m "New build"')
            bzr('push %s/builds'%root_repo)

        banner('Stamping simple build')
        muddle(['reparent', 'builds'])  # Not sure why we need to do this
        muddle(['stamp', 'version'])
        with Directory('versions'):
            bzr('add test_build.stamp')
            bzr('commit -m "A proper stamp file"')
            cat('test_build.stamp')

        # We should be able to use muddle to push the stamp file
        muddle(['stamp', 'push'])

    # We should be able to check everything out from the repository
    with NewDirectory('test_build2'):
        banner('Building from init')
        muddle(['init', 'bzr+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout','_all'])

    # We should be able to recreate our state from the stamp file...
    with NewDirectory('test_build3'):
        banner('Unstamping simple build')
        muddle(['unstamp', 'bzr+%s'%root_repo, 'versions/test_build.stamp'])

def setup_bzr_checkout_repositories():
    """Set up our testing repositories in the current directory.
    """
    banner('Setting up checkout repos')
    with NewDirectory('repo'):
        # The standards
        for name in ('builds', 'versions'):
            with NewDirectory(name):
                bzr('init')

        # Single level checkouts
        with NewDirectory('checkout1'):
            bzr('init')

        # Two-level checkouts
        with NewDirectory('twolevel'):
            with NewDirectory('checkout2'):
                bzr('init')

        # Multilevel checkouts
        with NewDirectory('multilevel'):
            with NewDirectory('inner'):
                with NewDirectory('checkout3'):
                    bzr('init')

def setup_new_build(root_repo, name):
    with NewDirectory('test_build1'):
        banner('Bootstrapping checkout build')
        muddle(['bootstrap', 'bzr+%s'%root_repo, 'test_build'])
        cat('src/builds/01.py')

        banner('Setting up src/')
        with Directory('src'):
            with Directory('builds'):
                touch('01.py', CHECKOUT_BUILD_LEVELS)
                bzr('add 01.py')
                bzr('commit -m "New build"')
                bzr('push %s/builds'%root_repo)

            with NewDirectory('checkout1'):
                touch('Makefile.muddle', MUDDLE_MAKEFILE)
                bzr('init')
                bzr('add Makefile.muddle')
                bzr('commit -m "Add muddle makefile"')
                bzr('push %s/checkout1'%root_repo)
                muddle(['assert', 'checkout:checkout1/checked_out'])

            with NewDirectory('twolevel'):
                with NewDirectory('checkout2'):
                    touch('Makefile.muddle', MUDDLE_MAKEFILE)
                    bzr('init')
                    bzr('add Makefile.muddle')
                    bzr('commit -m "Add muddle makefile"')
                    bzr('push %s/twolevel/checkout2'%root_repo)
                    muddle(['assert', 'checkout:checkout2/checked_out'])

            with NewDirectory('multilevel'):
                with NewDirectory('inner'):
                    with NewDirectory('checkout3'):
                        touch('Makefile.muddle', MUDDLE_MAKEFILE)
                        bzr('init')
                        bzr('add Makefile.muddle')
                        bzr('commit -m "Add muddle makefile"')
                        bzr('push %s/multilevel/inner/checkout3'%root_repo)
                        muddle(['assert', 'checkout:alice/checked_out'])


def test_bzr_checkout_build():
    """Test single, twolevel and multilevel checkouts.

    Relies on setup_bzr_checkout_repositories() having been called.
    """
    root_dir = normalise_dir(os.getcwd())
    root_repo = 'file://' + os.path.join(root_dir, 'repo')
    setup_new_build(root_repo, 'test_build1')

    with Directory('test_build1'):
        banner('Stamping checkout build')
        muddle(['reparent', '_all'])  # Probably need to do this?
        muddle(['stamp', 'version'])
        with Directory('versions'):
            bzr('add checkout_test.stamp')
            bzr('commit -m "A stamp file"')
            bzr('push %s/versions'%root_repo)
            cat('checkout_test.stamp')

        # We should be able to use muddle to push the stamp file
        muddle(['stamp', 'push'])

    # We should be able to check everything out from the repository
    with NewDirectory('test_build2'):
        banner('Building checkout build from init')
        muddle(['init', 'bzr+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout','_all'])

        check_files(['src/builds/01.py',
                     'src/checkout1/Makefile.muddle',
                     'src/twolevel/checkout2/Makefile.muddle',
                     'src/multilevel/inner/checkout3/Makefile.muddle',
                     ])

    # We should be able to recreate our state from the stamp file...
    with NewDirectory('test_build3'):
        banner('Unstamping checkout build')
        muddle(['unstamp', 'bzr+%s'%root_repo, 'versions/checkout_test.stamp'])

        check_files(['src/builds/01.py',
                     'versions/checkout_test.stamp',
                     'src/checkout1/Makefile.muddle',
                     'src/twolevel/checkout2/Makefile.muddle',
                     'src/multilevel/inner/checkout3/Makefile.muddle',
                     ])

def test_bzr_muddle_patch():
    """Test the workings of the muddle_patch program against bzr

    Relies upon test_bzr_checkout_build() having been called.
    """
    root_dir = normalise_dir(os.getcwd())

    banner('Making changes in build1')
    with Directory('test_build1'):
        with Directory('src/checkout1'):
            touch('empty.c')      # empty
            touch('program1.c','// This is very dull C file 1\n')
            touch('program2.c','// This is very dull C file 2\n')
            touch('Makefile.muddle',
                  '# This is our makefile reduced to a single line\n')
            bzr('add empty.c program1.c program2.c')
            bzr('commit -m "Add program1|2.c, empty.c, shrink our Makefile"')
            bzr('push')
            bzr('rm program2.c')
            touch('Makefile.muddle',
                  '# This is our makefile\n# Now with two lines\n')
            bzr('commit -m "Delete program2.c, change our Makefile"')
            bzr('push')

        with Directory('src/twolevel/checkout2'):
            touch('program.c','// This is very dull C file\n')
            bzr('add program.c')
            bzr('commit -m "Add program.c"')
            bzr('push')

        with Directory('src/multilevel/inner/checkout3'):
            touch('program.c','// This is very dull C file\n')
            bzr('add program.c')
            bzr('commit -m "Add program.c"')
            bzr('push')

    banner('TEMPORARY: MAKE VERSION STAMP FOR BUILD 1')
    with Directory('test_build1'):
        muddle(['stamp', 'version'])

    banner('Generating patches between build1 (altered, near) and build3 (unaltered, far)')
    # test_build2 doesn't have a stamp file...
    with Directory('test_build1'):
        shell('%s write - ../test_build3/versions/checkout_test.stamp'
              ' ../patch_dir'%MUDDLE_PATCH_COMMAND)

    shell('ls patch_dir')

    banner('Applying patches to build3')
    with Directory('test_build3'):
        shell('%s read ../patch_dir'%MUDDLE_PATCH_COMMAND)

    with Directory('test_build3/src/checkout1'):
        banner('Checking we have the expected files present...')
        check_specific_files_in_this_dir(['Makefile.muddle', 'program1.c', '.bzr'])
        # We'd *like* empty.c to be there as well, but at the moment
        # it won't be...

        banner('Committing the changes in checkout1')
        bzr('add')
        bzr('commit -m "Changes from muddle_patch"')

    with Directory('test_build3/src/twolevel/checkout2'):
        check_specific_files_in_this_dir(['Makefile.muddle',
                                          'program.c', '.bzr'])
        banner('Committing the changes in checkout2')
        bzr('add')
        bzr('commit -m "Changes from muddle_patch"')

    with Directory('test_build3/src/multilevel/inner/checkout3'):
        check_specific_files_in_this_dir(['Makefile.muddle',
                                          'program.c', '.bzr'])
        banner('Committing the changes in checkout3')
        bzr('add')
        bzr('commit -m "Changes from muddle_patch"')

def test_just_pulled():
    root_dir = normalise_dir(os.getcwd())
    root_repo = 'file://' + os.path.join(root_dir, 'repo')

    # Set up our repositories
    setup_bzr_checkout_repositories()
    setup_new_build(root_repo, 'build_0')

    root_repo = 'file://' + os.path.join(root_dir, 'repo')

    banner('Build A')
    with NewDirectory('build_A'):
        muddle(['init', 'bzr+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout', '_all'])

    banner('Build B')
    with NewDirectory('build_B'):
        muddle(['init', 'bzr+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout', '_all'])

    banner('Change Build A')
    with Directory('build_A'):
        with Directory('src'):
            with Directory('builds'):
                append('01.py', '# Just a comment\n')
                bzr('commit -m "A simple change"')
                muddle(['push'])
            with Directory('twolevel'):
                with Directory('checkout2'):
                    append('Makefile.muddle', '# Just a comment\n')
                    bzr('commit -m "A simple change"')
                    muddle(['push'])

    banner('Pull into Build B')
    with Directory('build_B') as d:
        _just_pulled_file = os.path.join(d.where, '.muddle', '_just_pulled')
        if os.path.exists(_just_pulled_file):
            raise GiveUp('%s exists when it should not'%_just_pulled_file)
        muddle(['pull', '_all'])
        if not same_content(_just_pulled_file,
                            'checkout:builds/checked_out\n'
                            'checkout:checkout2/checked_out\n'):
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
            banner('TEST SIMPLE BUILD (BZR)')
            test_bzr_simple_build()

        with NewDirectory('checkout'):
            banner('TEST CHECKOUT BUILD (BZR)')
            setup_bzr_checkout_repositories()
            test_bzr_checkout_build()
            banner('TEST MUDDLE PATCH (BZR)')
            test_bzr_muddle_patch()

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
