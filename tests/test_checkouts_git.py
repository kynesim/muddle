#! /usr/bin/env python
"""Test checkout support for git.

    $ ./test_checkouts_git.py

Git must be installed.
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

def test_git_simple_build():
    """Bootstrap a muddle build tree.
    """
    root_dir = normalise_dir(os.getcwd())

    with NewDirectory('repo'):
        for name in ('builds', 'versions'):
            with NewDirectory(name):
                git('init --bare')

        print 'Repositories are:', ' '.join(os.listdir('.'))

    root_repo = 'file://' + os.path.join(root_dir, 'repo')
    with NewDirectory('test_build1'):
        banner('Bootstrapping simple build')
        muddle(['bootstrap', 'git+%s'%root_repo, 'test_build'])
        cat('src/builds/01.py')

        with Directory('versions'):
            touch('fred.stamp',
                  '# A comment\n# Another comment\n')
            git('add fred.stamp')
            git('commit -m "New stamp file"')
            # We have to associate it with a repository
            git('remote add origin %s/versions'%root_repo)
            git('push origin master')

        with Directory('src/builds'):
            git('commit -m "New build"')
            ##git('push %s/builds HEAD'%root_repo)
            # We can use the big blunt stick of 'reparent',
            # or we could use 'git remote add origin' directly
            # TODO: muddle bootstrap should have done this for us
            muddle(['reparent'])
            muddle(['push'])

        banner('Stamping simple build')
        muddle(['stamp', 'version'])
        with Directory('versions'):
            git('add test_build.stamp')
            git('commit -m "A proper stamp file"')
            cat('test_build.stamp')

        # We should be able to use muddle to push the stamp file
        muddle(['stamp', 'push'])

    # We should be able to check everything out from the repository
    with NewDirectory('test_build2'):
        banner('Building from init')
        muddle(['init', 'git+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout','_all'])

    # We should be able to recreate our state from the stamp file...
    with NewDirectory('test_build3'):
        banner('Unstamping simple build')
        muddle(['unstamp', 'git+%s'%root_repo, 'versions/test_build.stamp'])

def setup_git_checkout_repositories():
    """Set up our testing repositories in the current directory.
    """
    banner('Setting up checkout repos')
    with NewDirectory('repo'):
        # The standards
        for name in ('builds', 'versions'):
            with NewDirectory(name):
                git('init --bare')

        # Single level checkouts
        with NewDirectory('checkout1'):
            git('init --bare')

        # Two-level checkouts
        with NewDirectory('twolevel'):
            with NewDirectory('checkout2'):
                git('init --bare')

        # Multilevel checkouts
        with NewDirectory('multilevel'):
            with NewDirectory('inner'):
                with NewDirectory('checkout3'):
                    git('init --bare')

def setup_new_build(root_repo, name):
    with NewDirectory(name):
        banner('Bootstrapping checkout build')
        muddle(['bootstrap', 'git+%s'%root_repo, 'test_build'])
        cat('src/builds/01.py')

        banner('Setting up src/')
        with Directory('src'):
            with Directory('builds'):
                touch('01.py', CHECKOUT_BUILD_LEVELS)
                git('add 01.py')
                git('commit -m "New build"')
                git('push %s/builds HEAD'%root_repo)

            with NewDirectory('checkout1'):
                touch('Makefile.muddle', MUDDLE_MAKEFILE)
                git('init')
                git('add Makefile.muddle')
                git('commit -m "Add muddle makefile"')
                # Assert that this checkout *has* been checked out
                # (this also does a "muddle reparent" for us, setting
                # up our remote origin for pushing)
                muddle(['import'])
                # And thus we can now ask muddle to push for us
                # (although a plain "git push" would also work)
                muddle(['push'])

            with NewDirectory('twolevel'):
                with NewDirectory('checkout2'):
                    touch('Makefile.muddle', MUDDLE_MAKEFILE)
                    git('init')
                    git('add Makefile.muddle')
                    git('commit -m "Add muddle makefile"')
                    muddle(['import'])
                    # As was said in 'checkout1', we can "git push" if
                    # we prefer, once we've done import - although we do
                    # need to be specific about *what* we're pushing, this
                    # first time round
                    git('push origin master')

            with NewDirectory('multilevel'):
                with NewDirectory('inner'):
                    with NewDirectory('checkout3'):
                        touch('Makefile.muddle', MUDDLE_MAKEFILE)
                        git('init')
                        git('add Makefile.muddle')
                        git('commit -m "Add muddle makefile"')
                        # Or we can do a more complicated sequence of things
                        # Just assert checkout via its tagged label
                        muddle(['assert', 'checkout:alice/checked_out'])
                        # then reparent by hand
                        muddle(['reparent'])
                        # and now we can git push
                        git('push origin master')

def test_git_checkout_build():
    """Test single, twolevel and multilevel checkouts.

    Relies on setup_git_checkout_repositories() having been called.
    """
    root_dir = normalise_dir(os.getcwd())
    root_repo = 'file://' + os.path.join(root_dir, 'repo')
    setup_new_build(root_repo, 'test_build1')

    with Directory('test_build1'):
        banner('Stamping checkout build')
        muddle(['stamp', 'version'])
        with Directory('versions'):
            git('add checkout_test.stamp')
            git('commit -m "A stamp file"')
            # We have to associate it with a repository
            git('remote add origin %s/versions'%root_repo)
            git('push origin master')
            cat('checkout_test.stamp')

        # We should be able to use muddle to push the stamp file
        muddle(['stamp', 'push'])

    # We should be able to check everything out from the repository
    with NewDirectory('test_build2'):
        banner('Building checkout build from init')
        muddle(['init', 'git+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout','_all'])

        check_files(['src/builds/01.py',
                     'src/checkout1/Makefile.muddle',
                     'src/twolevel/checkout2/Makefile.muddle',
                     'src/multilevel/inner/checkout3/Makefile.muddle',
                     ])

    # We should be able to recreate our state from the stamp file...
    with NewDirectory('test_build3'):
        banner('Unstamping checkout build')
        muddle(['unstamp', 'git+%s'%root_repo, 'versions/checkout_test.stamp'])

        check_files(['src/builds/01.py',
                     'versions/checkout_test.stamp',
                     'src/checkout1/Makefile.muddle',
                     'src/twolevel/checkout2/Makefile.muddle',
                     'src/multilevel/inner/checkout3/Makefile.muddle',
                     ])

def test_git_muddle_patch():
    """Test the workings of the muddle_patch program against git

    Relies upon test_git_checkout_build() having been called.
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
            git('add empty.c program1.c program2.c Makefile.muddle')
            git('commit -m "Add program1|2.c, empty.c, shrink our Makefile"')
            muddle(['push'])  # muddle remembers the repository for us
            git('rm program2.c')
            touch('Makefile.muddle',
                  '# This is our makefile\n# Now with two lines\n')
            git('add Makefile.muddle')
            git('commit -m "Delete program2.c, change our Makefile"')
            muddle(['push'])  # muddle remembers the repository for us

        with Directory('src/twolevel/checkout2'):
            touch('program.c','// This is very dull C file\n')
            git('add program.c')
            git('commit -m "Add program.c"')
            muddle(['push'])  # muddle remembers the repository for us

        with Directory('src/multilevel/inner/checkout3'):
            touch('program.c','// This is very dull C file\n')
            git('add program.c')
            git('commit -m "Add program.c"')
            muddle(['push'])  # muddle remembers the repository for us

    banner('Generating patches between build1 (altered, near) and build3 (unaltered, far)')
    # test_build2 doesn't have a stamp file...
    with Directory('test_build1'):
        shell('%s write - ../test_build3/versions/checkout_test.stamp'
              ' ../patch_dir'%MUDDLE_PATCH_COMMAND)

    shell('ls patch_dir')

    banner('Applying patches to build3')
    with Directory('test_build3'):
        shell('%s read ../patch_dir'%MUDDLE_PATCH_COMMAND)

    with Directory('test_build1/src/checkout1'):
        git('rev-parse HEAD')
        git('rev-parse master')

    with Directory('test_build3/src/checkout1'):
        git('rev-parse HEAD')
        git('rev-parse master')
        banner('"git am" leaves our HEAD detached, so we should then do something like:')
        git('branch post-am-branch')    # to stop our HEAD being detached
        git('checkout master')          # assuming we were on master, of course
        git('merge post-am-branch')     # and we should now be where we want...
        git('rev-parse HEAD')
        git('rev-parse master')

    with Directory('test_build3/src/checkout1'):
        check_specific_files_in_this_dir(['Makefile.muddle', 'empty.c',
                                          'program1.c', '.git'])

    with Directory('test_build3/src/twolevel/checkout2'):
        check_specific_files_in_this_dir(['Makefile.muddle',
                                          'program.c', '.git'])

    with Directory('test_build3/src/multilevel/inner/checkout3'):
        check_specific_files_in_this_dir(['Makefile.muddle',
                                          'program.c', '.git'])

def test_just_pulled():
    root_dir = normalise_dir(os.getcwd())
    root_repo = 'file://' + os.path.join(root_dir, 'repo')

    # Set up our repositories
    setup_git_checkout_repositories()
    setup_new_build(root_repo, 'build_0')

    root_repo = 'file://' + os.path.join(root_dir, 'repo')

    banner('Build A')
    with NewDirectory('build_A'):
        muddle(['init', 'git+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout', '_all'])

    banner('Build B')
    with NewDirectory('build_B'):
        muddle(['init', 'git+%s'%root_repo, 'builds/01.py'])
        muddle(['checkout', '_all'])

    banner('Change Build A')
    with Directory('build_A'):
        with Directory('src'):
            with Directory('builds'):
                append('01.py', '# Just a comment\n')
                git('commit -a -m "A simple change"')
                muddle(['push'])
            with Directory('twolevel'):
                with Directory('checkout2'):
                    append('Makefile.muddle', '# Just a comment\n')
                    git('commit -a -m "A simple change"')
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

    if args:
        print __doc__
        return

    # Choose a place to work, rather hackily
    #root_dir = os.path.join('/tmp','muddle_tests')
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with TransientDirectory(root_dir, keep_on_error=True):
        banner('TEST SIMPLE BUILD (GIT)')
        test_git_simple_build()

    with TransientDirectory(root_dir, keep_on_error=True):
        banner('TEST CHECKOUT BUILD (GIT)')
        setup_git_checkout_repositories()
        test_git_checkout_build()
        banner('TEST MUDDLE PATCH (GIT)')
        test_git_muddle_patch()

    with TransientDirectory(root_dir, keep_on_error=True):
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
