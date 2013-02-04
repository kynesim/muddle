#! /usr/bin/env python
"""Test simple project lifecycle in git

    $ ./test_lifecycle_git.py  [-keep]

Git must be installed.
If '-keep' is specified, then the 'transient/' directory will not be deleted.
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
\t@echo Make all for '$(MUDDLE_LABEL)'
\t$(CC) $(MUDDLE_SRC)/{progname}.c -o $(MUDDLE_OBJ)/{progname}

config:
\t@echo Make configure for '$(MUDDLE_LABEL)'

install:
\t@echo Make install for '$(MUDDLE_LABEL)'
\tcp $(MUDDLE_OBJ)/{progname} $(MUDDLE_INSTALL)

clean:
\t@echo Make clean for '$(MUDDLE_LABEL)'

distclean:
\t@echo Make distclean for '$(MUDDLE_LABEL)'

.PHONY: all config install clean distclean
"""

BUILD_DESC = """\
# A very simple build description
import os

import muddled.pkgs.make

from muddled.depend import checkout
from muddled.version_control import checkout_from_repo

def add_package(builder, pkg_name, role, co_name=None):
    if co_name is None:
        co_name = pkg_name
    root_repo = builder.build_desc_repo
    repo = root_repo.copy_with_changes(co_name)
    checkout_from_repo(builder, checkout(co_name), repo)
    muddled.pkgs.make.simple(builder, pkg_name, role, co_name)

def describe_to(builder):
    builder.build_name = '{build_name}'
    # A single checkout
    add_package(builder, 'package', 'x86', co_name='co1')
"""

BUILD_DESC_WITH_REVISION = """\
# A very simple build description, with a checkout pinned to a revision
import os

import muddled.pkgs.make

from muddled.depend import checkout
from muddled.version_control import checkout_from_repo

def add_package(builder, pkg_name, role, co_name=None):
    if co_name is None:
        co_name = pkg_name
    root_repo = builder.build_desc_repo
    repo = root_repo.copy_with_changes(co_name, revision='{revision}')
    checkout_from_repo(builder, checkout(co_name), repo)
    muddled.pkgs.make.simple(builder, pkg_name, role, co_name)

def describe_to(builder):
    builder.build_name = '{build_name}'
    # A single checkout
    add_package(builder, 'package', 'x86', co_name='co1')
"""

BUILD_DESC_WITH_BRANCH = """\
# A very simple build description, with a checkout pinned to a branch
import os

import muddled.pkgs.make

from muddled.depend import checkout
from muddled.version_control import checkout_from_repo

def add_package(builder, pkg_name, role, co_name=None):
    if co_name is None:
        co_name = pkg_name
    root_repo = builder.build_desc_repo
    repo = root_repo.copy_with_changes(co_name, branch='{branch}')
    checkout_from_repo(builder, checkout(co_name), repo)
    muddled.pkgs.make.simple(builder, pkg_name, role, co_name)

def describe_to(builder):
    builder.build_name = '{build_name}'
    # A single checkout
    add_package(builder, 'package', 'x86', co_name='co1')
"""

def check_revision(checkout, revision_wanted):
    actual_revision = captured_muddle(['query', 'checkout-id', checkout]).strip()
    if actual_revision != revision_wanted:
        raise GiveUp('Checkout co1 has revision %s, expected %s'%(
            actual_revision, revision_wanted))

def get_branch(dir):
    with Directory(dir):
        retcode, out = get_stdout2('git symbolic-ref -q HEAD')
        if retcode == 0:
            out = out.strip()
            if out.startswith('refs/heads'):
                return out[11:]
            else:
                return None
        elif retcode == 1:
            # HEAD is not a symbolic reference, but a detached HEAD
            return None
        else:
            raise GiveUp('Error running "git symbolic-ref -q HEAD" to determine current branch')

def check_branch(dir, branch_wanted):
    branch = get_branch(dir)
    if branch != branch_wanted:
        raise GiveUp('Checkout in %s has branch %s, expected %s'%(dir,
            branch, branch_wanted))

def is_detached_head():
    retcode, out = get_stdout2('git symbolic-ref -q HEAD')
    if retcode == 0:
        # HEAD is a symbolic reference - so not detached
        return False
    elif retcode == 1:
        # HEAD is not a symbolic reference, but a detached HEAD
        return True
    else:
        raise GiveUp('Error running "git symbolic-ref -q HEAD" to detect detached HEAD')


class NewBuildDirectory(NewDirectory):
    """A version of NewDirectory that prefixes a count to its directory names.
    """

    build_count = 0

    def __init__(self, name):
        NewBuildDirectory.build_count += 1
        name = '%02d.%s'%(NewBuildDirectory.build_count, name)
        super(NewBuildDirectory, self).__init__(name)


def test_init_with_branch(root_d):
    """Test doing a muddle init with a specified branch name.
    """

    EMPTY_BUILD_DESC = '# Nothing here\ndef describe_to(builder):\n  pass\n'
    EMPTY_README_TEXT = 'An empty README file.\n'
    EMPTY_C_FILE = '// Nothing to see here\n'

    SIMPLE_BUILD_DESC = BUILD_DESC.format(build_name='test-build')
    FOLLOW_BUILD_DESC = SIMPLE_BUILD_DESC + '\n    builder.follow_build_desc_branch = True\n'

    with NewBuildDirectory('init.branch.repo') as d:
        muddle(['bootstrap', 'git+file:///nowhere', 'test-build'])
        with Directory('src') as src:
            with Directory('builds') as builds:
                touch('01.py', EMPTY_BUILD_DESC)
                git('commit -a -m "Empty-ish build description"')
                git('checkout -b branch1')
                touch('01.py', SIMPLE_BUILD_DESC)
                git('commit -a -m "More interesting build description"')
                git('checkout -b branch.follow')
                touch('01.py', FOLLOW_BUILD_DESC)
                git('commit -a -m "A following build description"')
            with NewDirectory('co1'):
                touch('Makefile.muddle', MUDDLE_MAKEFILE)
                git('init')
                git('add Makefile.muddle')
                git('commit Makefile.muddle -m "A checkout needs a makefile"')
                git('checkout -b branch1')
                touch('README.txt', EMPTY_README_TEXT)
                git('add README.txt')
                git('commit -m "And a README"')
                git('checkout -b branch.follow')
                touch('program1.c', EMPTY_C_FILE)
                git('add program1.c')
                git('commit -m "And a program"')
        repo = src.where

    with NewBuildDirectory('init.implicit.master'):
        muddle(['init', 'git+file://' + repo, 'builds/01.py'])
        muddle(['checkout', '_all'])
        with Directory('src'):
            with Directory('builds'):
                check_file_v_text('01.py', EMPTY_BUILD_DESC)
            if os.path.isdir('co1'):
                raise GiveUp('Unexpectedly found "co1" directory')

    with NewBuildDirectory('init.explicit.branch1'):
        muddle(['init', '-branch', 'branch1', 'git+file://' + repo, 'builds/01.py'])
        muddle(['checkout', '_all'])
        with Directory('src'):
            with Directory('builds'):
                check_file_v_text('01.py', SIMPLE_BUILD_DESC)
            with Directory('co1'):
                # The build description did not ask us to follow it
                check_specific_files_in_this_dir(['.git', 'Makefile.muddle'])
                check_file_v_text('Makefile.muddle', MUDDLE_MAKEFILE)

    with NewBuildDirectory('init.branch.explicit.branch.follow'):
        muddle(['init', '-branch', 'branch.follow', 'git+file://' + repo, 'builds/01.py'])
        muddle(['checkout', '_all'])
        with Directory('src'):
            with Directory('builds'):
                check_file_v_text('01.py', FOLLOW_BUILD_DESC)
            with Directory('co1'):
                # The build description asked us to follow it
                check_specific_files_in_this_dir(['.git', 'Makefile.muddle', 'README.txt', 'program1.c'])
                check_file_v_text('Makefile.muddle', MUDDLE_MAKEFILE)
                check_file_v_text('README.txt', EMPTY_README_TEXT)
                check_file_v_text('program1.c', EMPTY_C_FILE)


def test_git_lifecycle(root_d):
    """A linear sequence of plausible actions...
    """

    # Repositories
    with NewDirectory(root_d.join('repos')) as d:
        with NewDirectory(d.join('builds')):
            git('init --bare')
        with NewDirectory(d.join('co1')):
            git('init --bare')
        with NewDirectory(d.join('versions')):
            git('init --bare')

        repo_url = 'git+file://%s'%d.where

    build_name = 'TestBuild'

    # First build tree
    with NewDirectory(root_d.join('build1')) as d:
        muddle(['bootstrap', repo_url, build_name])
        with Directory('src'):
            with Directory('builds'):
                os.remove('01.py')
                touch('01.py', BUILD_DESC.format(build_name=build_name))
                git('add 01.py')  # Because we changed it since the last 'git add'
                git('commit -m "First commit of build description"')
                muddle(['push'])
            with NewDirectory('co1'):
                touch('Makefile.muddle', MUDDLE_MAKEFILE)
                git('init')
                git('add Makefile.muddle')
                git('commit Makefile.muddle -m "A checkout needs a makefile"')
                muddle(['import'])
                muddle(['push'])

        muddle(['stamp', 'version'])
        with Directory('versions'):
            git('add TestBuild.stamp')
            git('commit -m "First stamp"')
            muddle(['stamp', 'push'])

        builds_rev_1 = captured_muddle(['query', 'checkout-id', 'builds']).strip()
        checkout_rev_1 = captured_muddle(['query', 'checkout-id', 'co1']).strip()

        # Add some more revisions, so we have something to work with
        with Directory('src'):
            with Directory('builds'):
                append('01.py', '# Additional comment number 1\n')
                git('add 01.py')
                git('commit -m "Add comment number 1"')
                builds_rev_2 = captured_muddle(['query', 'checkout-id']).strip()
                append('01.py', '# Additional comment number 2\n')
                git('commit -a -m "Add comment number 2"')
                builds_rev_3 = captured_muddle(['query', 'checkout-id']).strip()
                muddle(['push'])
            with Directory('co1'):
                append('Makefile.muddle', '# Additional comment number 1\n')
                git('add Makefile.muddle')
                git('commit -m "Add comment number 1"')
                checkout_rev_2 = captured_muddle(['query', 'checkout-id']).strip()
                append('Makefile.muddle', '# Additional comment number 2\n')
                git('commit -a -m "Add comment number 2"')
                checkout_rev_3 = captured_muddle(['query', 'checkout-id']).strip()
                muddle(['push'])

    print 'builds/'
    print '  ',builds_rev_1
    print '  ',builds_rev_2
    print '  ',builds_rev_3
    print 'co1/'
    print '  ',checkout_rev_1
    print '  ',checkout_rev_2
    print '  ',checkout_rev_3

    # Second build tree, where the build description gives a specific revision
    # for a checkout.
    with NewDirectory(root_d.join('build2')) as d:
        muddle(['init', repo_url, 'builds/01.py'])
        # But we want to specify the revision for our source checkout
        with Directory(d.join('src', 'builds')):
            touch('01.py',
                  BUILD_DESC_WITH_REVISION.format(revision=checkout_rev_2,
                                                  build_name=build_name))
            # Then remove the .pyc file, because Python probably won't realise
            # that this new 01.py is later than the previous version
            os.remove(d.join('src', 'builds', '01.pyc'))
        muddle(['checkout', '_all'])

        check_revision('co1', checkout_rev_2)

        # If we attempt to pull in the checkout, that should fail because
        # we are already at the requested revision
        text = captured_muddle(['pull', 'co1'], error_fails=False).strip()
        if not text.endswith('checkout past the specified revision.'):
            raise GiveUp('Expected muddle pull to fail trying to go "past" revision:\n%s'%text)

        # Merging should behave just the same
        text = captured_muddle(['merge', 'co1'], error_fails=False).strip()
        if not text.endswith('checkout past the specified revision.'):
            raise GiveUp('Expected muddle pull to fail trying to go "past" revision:\n%s'%text)

        # What if the checkout is at the wrong revision? (e.g., someone used
        # git explicitly to change it, or equally we changed the build description
        # itself).
        # All muddle can really do is go to the revision specified in the
        # build description...
        with Directory(d.join('src', 'co1')):
            git('checkout %s'%checkout_rev_1)
            muddle(['pull'])
            check_revision('co1', checkout_rev_2)

            git('checkout %s'%checkout_rev_1)
            muddle(['merge'])
            check_revision('co1', checkout_rev_2)

        # What if we try to do work on that specified revision
        # (and, in git terms, at a detached HEAD)
        with Directory(d.join('src', 'co1')):
            append('Makefile.muddle', '# Additional comment number 3\n')
            git('commit -a -m "Add comment number 3"')
            checkout_rev_4 = captured_muddle(['query', 'checkout-id']).strip()
            # We're not on a branch, so that commit is likely to get lost,
            # so we'd better allow the user ways of being told that
            # - muddle status should say something
            rc, text = captured_muddle2(['status'])
            if 'Note that this checkout has a detached HEAD' not in text:
                raise GiveUp('Expected to be told checkout is in detached'
                             ' HEAD state, instead got:\n%s'%text)
            # And trying to push should fail
            rc, text = captured_muddle2(['push'])
            text = text.strip()
            if 'This checkout is in "detached HEAD" state' not in text:
                raise GiveUp('Expected to be told checkout is in detached'
                             ' HEAD state, instead got:\n%s'%text)
        print 'co1/'
        print '  ',checkout_rev_1
        print '  ',checkout_rev_2
        print '  ',checkout_rev_3
        print '  ',checkout_rev_4

        # So fix that by using a branch
        checkout_branch = 'this-is-a-branch'
        with Directory('src'):
            with Directory('builds'):
                touch('01.py',
                      BUILD_DESC_WITH_BRANCH.format(branch=checkout_branch,
                                                    build_name=build_name))
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove(d.join('src', 'builds', '01.pyc'))
            with Directory('co1'):
                git('checkout -b %s'%checkout_branch)
                muddle(['status'])
                muddle(['push'])

        check_revision('co1', checkout_rev_4)

        # What happens if we specify a revision on a branch?
        # First, choose the revision before the branch
        with Directory('src'):
            with Directory('builds'):
                touch('01.py',
                      BUILD_DESC_WITH_REVISION.format(revision=checkout_rev_3,
                                                      build_name=build_name))
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove(d.join('src', 'builds', '01.pyc'))
            with Directory('co1'):
                muddle(['status'])
                # Doing 'muddle pull' is the obvious way to get us back to
                # the right revision
                muddle(['pull'])
                check_revision('co1', checkout_rev_3)
                # Because we specified an exact revision, we should be detached
                if not is_detached_head():
                    raise GiveUp('Expected to have a detached HEAD')

        # Then the revision after the branch
        with Directory('src'):
            with Directory('builds'):
                touch('01.py',
                      BUILD_DESC_WITH_REVISION.format(revision=checkout_rev_4,
                                                      build_name=build_name))
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove(d.join('src', 'builds', '01.pyc'))
            with Directory('co1'):
                # We're still on the old revision, and detached
                check_revision('co1', checkout_rev_3)
                # Because we specified an exact revision, we should be detached
                if not is_detached_head():
                    raise GiveUp('Expected to have a detached HEAD')
                rc, text = captured_muddle2(['status'])
                if 'Note that this checkout has a detached HEAD' not in text:
                    raise GiveUp('Expected to be told checkout is in detached'
                                 ' HEAD state, instead got:\n%s'%text)

                # Doing 'muddle pull' is the obvious way to get us back to
                # the right revision
                muddle(['pull'])
                check_revision('co1', checkout_rev_4)
                # Because we specified an exact revision, we should be detached
                if not is_detached_head():
                    raise GiveUp('Expected to have a detached HEAD')

                # But what if we go to "the same place" by a different means?
                git('checkout %s'%checkout_branch)
                muddle(['status'])
                # We're still at the requested revision
                check_revision('co1', checkout_rev_4)
                # But we're no longer a detached HEAD
                if is_detached_head():
                    raise GiveUp('Surprised to have a detached HEAD')
                # muddle pull shouldn't need to do anything...
                text = captured_muddle(['pull'], error_fails=False).strip()
                if not text.endswith('checkout past the specified revision.'):
                    raise GiveUp('Expected muddle pull to fail trying to go "past" revision:\n%s'%text)

    # Third build tree, investigating use of "muddle branch-tree"
    with NewDirectory(root_d.join('build3')) as d:
        muddle(['init', repo_url, 'builds/01.py'])
        muddle(['checkout', '_all'])

        # Check the branches of our checkouts
        check_branch('src/builds', 'master')
        check_branch('src/co1', 'master')

        # And change it
        muddle(['branch-tree', 'test-v0.1'])

        # Check the branches of our checkouts - since this isn't using muddle,
        # it should still show both at the new branch
        check_branch('src/builds', 'test-v0.1')
        check_branch('src/co1', 'test-v0.1')

        # XXX And what command *should* I use to go to the branch specified
        # XXX by the build description (explicitly or implicitly)? I don't
        # XXX particularly like using "muddle parent" for this, as it's
        # XXX really a bit beyond its original remit (and essentially
        # XXX unguessable).
        # Doing a "mudddle sync" on the checkout should put it back to the
        # master branch, as that's what is (implicitly) asked for in the
        # build description. It shouldn't affect the build description.
        muddle(['sync', 'co1'])
        check_branch('src/builds', 'test-v0.1')
        check_branch('src/co1', 'master')

        # XXX We have various things to mix and match:
        # XXX
        # XXX 1. build description says to follow itself or not
        # XXX 2. build description is on master or not
        # XXX
        # XXX a. checkout has its own explicit branch
        # XXX b. checkout does not specify an explicit branch
        # XXX
        # XXX i.   checkout starts on master
        # XXX ii.  checkout starts on branch <something-else>
        # XXX iii. checkout starts on <explicit-branch>

        # If we amend the build description, though:
        print 'Setting build description for "follow my branch"'
        with Directory('src'):
            with Directory('builds'):
                append('01.py', '    builder.follow_build_desc_branch = True\n')
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')
        # and sync again, our checkout should now follow the build
        # description's branch
        muddle(['sync', 'co1'])
        check_branch('src/builds', 'test-v0.1')
        check_branch('src/co1', 'test-v0.1')

        # Let's commit and push...
        with Directory('src'):
            with Directory('builds'):
                git('commit -a -m "Branched"')
                muddle(['push'])
            with Directory('co1'):
                # We hadn't changed any files in our checkout
                muddle(['push'])

        # ...also want to check what happens if we explicitly select
        # branch master of co1, by name, in the build description
        # - we should revert to master again.


    # XXX See lifecycle.txt for what we're trying to test.
    # XXX But note that text higher up may alter conclusions reached therein.
    # XXX Oh well.




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
        banner('TEST INIT WITH BRANCH')
        test_init_with_branch(root_d)


        banner('TEST LIFECYCLE (GIT)')
        test_git_lifecycle(root_d)

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
