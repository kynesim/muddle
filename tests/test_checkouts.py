#! /usr/bin/env python
"""Test checkout support.

Give a single argument (one of 'git', 'bzr' or 'svn') to do tests for a
particular version control system. That VCS must be installed on the
machine you are running this on. For example::

    $ ./test_checkouts.py git

Give a set of commands starting with 'muddle' to run a muddle command,
just as if you were running the muddle command line program itself. For
example::

    $ ./test_checkouts.py muddle help query

The normal variants on 'help', '-help', etc. will probably work to
give this text...
"""

import os
import shutil
import subprocess
import sys
import traceback

from test_support import *

try:
    import muddled.cmdline
except ImportError:
    # Try one level up
    sys.path.insert(0, get_parent_file(__file__))
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
            svn('add test_build.stamp')
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

    Doing 'muddle fetch' or 'muddle merge' in such a directory should
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
                muddle(['fetch'])
                revno = get_stdout('svnversion').strip()
                if revno != '2':
                    raise GiveUp('Revision number for checkout1 is %s, not 2 (after fetch)'%revno)
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
                muddle(['fetch'])
                revno = get_stdout('svnversion').strip()
                if revno != '4':
                    raise GiveUp('Revision number for checkout1 is %s, not 4 (after fetch)'%revno)

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

def test_git_checkout_build():
    """Test single, twolevel and multilevel checkouts.

    Relies on setup_git_checkout_repositories() having been called.
    """
    root_dir = normalise_dir(os.getcwd())

    root_repo = 'file://' + os.path.join(root_dir, 'repo')
    with NewDirectory('test_build1'):
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

def test_bzr_checkout_build():
    """Test single, twolevel and multilevel checkouts.

    Relies on setup_bzr_checkout_repositories() having been called.
    """
    root_dir = normalise_dir(os.getcwd())

    root_repo = 'file://' + os.path.join(root_dir, 'repo')
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

def main(args):

    if not args or len(args) > 1:
        print __doc__
        return

    vcs = args[0]

    # Choose a place to work, rather hackily
    #root_dir = os.path.join('/tmp','muddle_tests')
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    if vcs == 'git':
        with TransientDirectory(root_dir, keep_on_error=True):
            banner('TEST SIMPLE BUILD (GIT)')
            test_git_simple_build()

        with TransientDirectory(root_dir, keep_on_error=True):
            banner('TEST CHECKOUT BUILD (GIT)')
            setup_git_checkout_repositories()
            test_git_checkout_build()
            banner('TEST MUDDLE PATCH (GIT)')
            test_git_muddle_patch()

    elif vcs == 'svn':
        with TransientDirectory(root_dir, keep_on_error=True):
            banner('TEST SIMPLE BUILD (SUBVERSION)')
            test_svn_simple_build()
        with TransientDirectory(root_dir, keep_on_error=True):
            banner('TEST BUILD WITH REVISION (SUBVERSION)')
            test_svn_revisions_build()

    elif vcs == 'bzr':
        with TransientDirectory(root_dir, keep_on_error=True):
            banner('TEST SIMPLE BUILD (BZR)')
            test_bzr_simple_build()

        with TransientDirectory(root_dir, keep_on_error=True):
            banner('TEST CHECKOUT BUILD (BZR)')
            setup_bzr_checkout_repositories()
            test_bzr_checkout_build()
            banner('TEST MUDDLE PATCH (BZR)')
            test_bzr_muddle_patch()

    elif vcs == 'test':
        pass

    else:
        print 'Unrecognised VCS %s'%vcs

if __name__ == '__main__':
    args = sys.argv[1:]
    if args and args[0] == 'muddle':
        # Pretend to be muddle the command line program
        # (but note we won't catch any exceptions)
        muddle(args[1:])
    else:
        try:
            main(args)
            print '\nGREEN light\n'
        except Exception as e:
            print
            traceback.print_exc()
            print '\nRED light\n'

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
