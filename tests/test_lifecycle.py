#! /usr/bin/env python
"""Test simple project lifecycle

    $ ./test_lifecycle_git.py  [-keep]

Git and bzr must be installed.

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
from muddled.withdir import Directory, NewDirectory, TransientDirectory, \
        NewCountedDirectory

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

MULTIPLEX_BUILD_DESC = """\
# A simple build description with a variety of checkouts
import os

import muddled.pkgs.make

from muddled.depend import checkout
from muddled.version_control import checkout_from_repo
from muddled.repository import Repository

def add_package(builder, pkg_name, role, co_name=None, branch=None, revision=None):
    base_repo = builder.build_desc_repo
    if co_name is None:
        co_name = pkg_name
    # Don't follow the branch/revision of the build description
    repo = base_repo.copy_with_changes(co_name, branch=branch, revision=revision)
    checkout_from_repo(builder, checkout(co_name), repo)
    muddled.pkgs.make.simple(builder, pkg_name, role, co_name)

def add_bzr_package(builder, pkg_name, role, co_name=None, revision=None, no_follow=False):
    base_repo = builder.build_desc_repo
    if co_name is None:
        co_name = pkg_name
    repo = Repository('bzr', base_repo.base_url, co_name, revision=revision)
    checkout_from_repo(builder, checkout(co_name), repo)
    muddled.pkgs.make.simple(builder, pkg_name, role, co_name)
    if no_follow:
        builder.db.set_checkout_vcs_option(checkout(co_name), 'no_follow', True)

def describe_to(builder):
    builder.build_name = '{build_name}'
    add_package(builder, 'package1', 'x86', co_name='co1')
    add_package(builder, 'package2', 'x86', co_name='co.branch1', branch='branch1')
    add_package(builder, 'package3', 'x86', co_name='co.fred', revision='fred')
    # This is naughty - the branch and revision are incompatible
    # Current muddle will choose to believe the revision
    add_package(builder, 'package4', 'x86', co_name='co.branch1.fred', branch='branch1', revision='fred')
"""

BZR_CO_NO_REVISION = """\
    add_bzr_package(builder, 'package5', 'x86', co_name='co.bzr')
"""

BZR_CO_WITH_REVISION = """\
    # Bazaar does not support our idea of branching, so if the build
    # description asks for us to "follow" it, we need to stop that by
    # specifying an explicit revision
    add_bzr_package(builder, 'package5', 'x86', co_name='co.bzr', revision='3')
"""

BZR_CO_NO_FOLLOW = """\
    add_bzr_package(builder, 'package5', 'x86', co_name='co.bzr', no_follow=True)
"""

CO6_WHICH_HAS_NO_BRANCH_FOLLOW = """\
    add_package(builder, 'package6', 'x86', co_name='co6')
"""

EMPTY_BUILD_DESC = '# Nothing here\ndef describe_to(builder):\n  pass\n'
EMPTY_README_TEXT = 'An empty README file.\n'
EMPTY_C_FILE = '// Nothing to see here\n'

FOLLOW_LINE = '\n    builder.follow_build_desc_branch = True\n'

BUILD_NAME = 'test-build'

NO_BZR_BUILD_DESC = MULTIPLEX_BUILD_DESC.format(build_name=BUILD_NAME)

NONFOLLOW_BUILD_DESC = NO_BZR_BUILD_DESC + \
                       BZR_CO_NO_REVISION

FOLLOW_BUILD_DESC = NO_BZR_BUILD_DESC + \
                    BZR_CO_WITH_REVISION + \
                    FOLLOW_LINE

def create_multiplex_repo(build_name):
    """Creates repositories for checkouts 'builds', 'co1' .. 'co.branch1.fred'

    Assumes that we are already in an appropriate directory.

    Returns the path to the 'src' directory, which is the repo_root to use.
    """


    muddle(['bootstrap', 'git+file:///nowhere', 'test-build'])
    with Directory('src') as src:
        with Directory('builds') as builds:
            # Remove the .pyc file, because Python probably won't realise
            # that our new 01.py is/are later than the previous version
            os.remove('01.pyc')
            touch('01.py', EMPTY_BUILD_DESC)
            git('commit -a -m "Empty-ish build description"')
            # ---- branch0
            git('checkout -b branch0')
            touch('01.py', NO_BZR_BUILD_DESC)
            git('commit -a -m "More interesting build description"')
            # ---- branch1
            git('checkout -b branch1')
            touch('01.py', NONFOLLOW_BUILD_DESC)
            git('commit -a -m "More interesting build description"')
            # ---- branch.follow
            git('checkout -b branch.follow')
            touch('01.py', FOLLOW_BUILD_DESC)
            git('commit -a -m "A following build description"')
        with NewDirectory('co1'):
            touch('Makefile.muddle', MUDDLE_MAKEFILE)
            git('init')
            git('add Makefile.muddle')
            git('commit Makefile.muddle -m "A checkout needs a makefile"')
            # ---- branch1
            git('checkout -b branch1')
            touch('README.txt', EMPTY_README_TEXT)
            git('add README.txt')
            git('commit -m "And a README"')
            # ---- branch.follow
            git('checkout -b branch.follow')
            touch('program1.c', EMPTY_C_FILE)
            git('add program1.c')
            git('commit -m "And a program"')
        with NewDirectory('co.branch1'):
            touch('Makefile.muddle', MUDDLE_MAKEFILE)
            git('init')
            git('add Makefile.muddle')
            git('commit Makefile.muddle -m "A checkout needs a makefile"')
            # ---- branch1
            git('checkout -b branch1')
            touch('README.txt', EMPTY_README_TEXT)
            git('add README.txt')
            git('commit -m "And a README"')
            # ---- branch.follow
            git('checkout -b branch.follow')
            touch('program2.c', EMPTY_C_FILE)
            git('add program2.c')
            git('commit -m "And a program"')
        with NewDirectory('co.fred'):
            touch('Makefile.muddle', MUDDLE_MAKEFILE)
            git('init')
            git('add Makefile.muddle')
            git('commit Makefile.muddle -m "A checkout needs a makefile"')
            # ---- branch1
            git('checkout -b branch1')
            touch('README.txt', EMPTY_README_TEXT)
            git('add README.txt')
            git('commit -m "And a README"')
            # ---- branch.follow
            git('checkout -b branch.follow')
            touch('program3.c', EMPTY_C_FILE)
            git('add program3.c')
            git('commit -m "And a program"')
            # --- tag fred
            git('tag fred')
        with NewDirectory('co.branch1.fred'):
            touch('Makefile.muddle', MUDDLE_MAKEFILE)
            git('init')
            git('add Makefile.muddle')
            git('commit Makefile.muddle -m "A checkout needs a makefile"')
            # ---- branch1
            git('checkout -b branch1')
            touch('README.txt', EMPTY_README_TEXT)
            git('add README.txt')
            git('commit -m "And a README"')
            # ---- branch.follow
            git('checkout -b branch.follow')
            touch('program4.c', EMPTY_C_FILE)
            git('add program4.c')
            git('commit -m "And a program"')
            # --- tag fred
            git('tag fred')
        with NewDirectory('co.bzr'):
            # -- revision 1
            touch('Makefile.muddle', MUDDLE_MAKEFILE)
            bzr('init')
            bzr('add Makefile.muddle')
            bzr('commit Makefile.muddle -m "A checkout needs a makefile"')
            # -- revision 2
            touch('README.txt', EMPTY_README_TEXT)
            bzr('add README.txt')
            bzr('commit README.txt -m "And a README"')
            # -- revision 3
            touch('program5.c', EMPTY_C_FILE)
            bzr('add program5.c')
            bzr('commit program5.c -m "And a program"')
        with NewDirectory('co6'):
            touch('Makefile.muddle', MUDDLE_MAKEFILE)
            git('init')
            git('add Makefile.muddle')
            git('commit Makefile.muddle -m "A checkout needs a makefile"')
            # ---- branch1
            git('checkout -b branch1')
            touch('README.txt', EMPTY_README_TEXT)
            git('add README.txt')
            git('commit -m "And a README"')
            # --- but we don't have a branch.follow
    repo = src.where
    return repo


def check_revision(checkout, revision_wanted):
    actual_revision = captured_muddle(['query', 'checkout-id', checkout]).strip()
    if actual_revision != revision_wanted:
        raise GiveUp('Checkout co1 has revision %s, expected %s'%(
            actual_revision, revision_wanted))

def get_branch(dir):
    with Directory(dir):
        retcode, out = run2('git symbolic-ref -q HEAD')
        print out
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
    retcode, out = run2('git symbolic-ref -q HEAD')
    if retcode == 0:
        # HEAD is a symbolic reference - so not detached
        return False
    elif retcode == 1:
        # HEAD is not a symbolic reference, but a detached HEAD
        return True
    else:
        raise GiveUp('Error running "git symbolic-ref -q HEAD" to detect detached HEAD')


def test_init_with_branch(root_d):
    """Test muddle init:

    * without a branch name
    * with a branch name, but not following the build description
    * with a branch name, and following the build description
    """

    with NewCountedDirectory('init.branch.repo') as d:
        repo = create_multiplex_repo('test-build')

    with NewCountedDirectory('init.with.no.branch'):
        muddle(['init', 'git+file://' + repo, 'builds/01.py'])
        muddle(['checkout', '_all'])
        with Directory('src'):
            with Directory('builds'):
                check_file_v_text('01.py', EMPTY_BUILD_DESC)
            # And our empty build description should not have checked any
            # of our checkouts out
            for name in ('co1', 'co.branch1', 'co.fred', 'co.branch1.fred'):
                if os.path.isdir(name):
                    raise GiveUp('Unexpectedly found "%s" directory'%name)

    with NewCountedDirectory('init.with.branch1.no.follow'):
        muddle(['init', '-branch', 'branch1', 'git+file://' + repo, 'builds/01.py'])
        muddle(['checkout', '_all'])
        with Directory('src'):
            with Directory('builds'):
                check_file_v_text('01.py', NONFOLLOW_BUILD_DESC)
            # The build description did not ask us to follow it
            with Directory('co1'):
                # -- root
                check_specific_files_in_this_dir(['.git', 'Makefile.muddle'])
                check_file_v_text('Makefile.muddle', MUDDLE_MAKEFILE)
            with Directory('co.branch1'):
                # -- branch1
                check_specific_files_in_this_dir(['.git', 'Makefile.muddle', 'README.txt'])
                check_file_v_text('Makefile.muddle', MUDDLE_MAKEFILE)
                check_file_v_text('README.txt', EMPTY_README_TEXT)
            with Directory('co.fred'):
                # Revision 'fred' == tag on branch 'branch.follow'
                check_specific_files_in_this_dir(['.git', 'Makefile.muddle', 'README.txt', 'program3.c'])
                check_file_v_text('Makefile.muddle', MUDDLE_MAKEFILE)
                check_file_v_text('README.txt', EMPTY_README_TEXT)
                check_file_v_text('program3.c', EMPTY_C_FILE)
                # If we attempt to 'muddle pull' in the checkout, that should
                # fail because we are already at the requested revision
                # (even though that revision was specified as a tag)
                text = captured_muddle(['pull', 'co.fred'], error_fails=False).strip()
                if not text.endswith('checkout past the specified revision.'):
                    raise GiveUp('Expected muddle pull to fail trying to go "past" revision:\n%s'%text)
            with Directory('co.branch1.fred'):
                # Revision 'fred' and branch 'branch1' - the revision wins
                # -- fred
                check_specific_files_in_this_dir(['.git', 'Makefile.muddle', 'README.txt', 'program4.c'])
                check_file_v_text('Makefile.muddle', MUDDLE_MAKEFILE)
                check_file_v_text('README.txt', EMPTY_README_TEXT)
                check_file_v_text('program4.c', EMPTY_C_FILE)
                # If we attempt to 'muddle pull' in the checkout, that should
                # fail because we are already at the requested revision
                # (even though that revision was specified as a tag)
                text = captured_muddle(['pull', 'co.fred'], error_fails=False).strip()
                if not text.endswith('checkout past the specified revision.'):
                    raise GiveUp('Expected muddle pull to fail trying to go "past" revision:\n%s'%text)
            with Directory('co.bzr'):
                # Since this is using bzr, we always get HEAD
                check_specific_files_in_this_dir(['.bzr', 'Makefile.muddle', 'README.txt', 'program5.c'])
                check_file_v_text('Makefile.muddle', MUDDLE_MAKEFILE)
                check_file_v_text('README.txt', EMPTY_README_TEXT)
                check_file_v_text('program5.c', EMPTY_C_FILE)

    with NewCountedDirectory('init.branch.with.branch1.follow'):
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

    with NewCountedDirectory('init.branch.with.branch1.bzr.follow.error'):
        muddle(['init', '-branch', 'branch.follow', 'git+file://' + repo, 'builds/01.py'])
        # Now let us make the build description erroneous, by changing it so
        # that the Bazaar checkout is also required to follow the build
        # description
        with Directory('src'):
            with Directory('builds'):
                touch('01.py', NONFOLLOW_BUILD_DESC +
                               FOLLOW_LINE)
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')
        # And our checkout all should now fail...
        retcode, text = captured_muddle2(['checkout', '_all'])
        if retcode != 1:
            raise GiveUp('Expected retcode 1 from "muddle checkout _all", got %d'%retcode)
        check_text_endswith(text, """\
The build description wants checkouts to follow branch 'branch.follow',
but checkout co.bzr uses VCS Bazaar for which we do not support branching.
The build description should specify a revision for checkout co.bzr,
or specify the 'no_follow' option.
""")

    with NewCountedDirectory('init.branch.with.branch1.bzr.no_follow.option'):
        muddle(['init', '-branch', 'branch.follow', 'git+file://' + repo, 'builds/01.py'])
        # Now let us make a build description in which our Bazaar checkout
        # specifically says it should not follow the build description
        with Directory('src'):
            with Directory('builds'):
                touch('01.py', NO_BZR_BUILD_DESC +
                               BZR_CO_NO_FOLLOW +
                               FOLLOW_LINE)
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')
        # And our checkout _all should now be OK...
        muddle(['checkout', '_all'])

    with NewCountedDirectory('init.branch.with.branch1.nobranch.follow.error') as d:
        muddle(['init', '-branch', 'branch.follow', 'git+file://' + repo, 'builds/01.py'])
        # Now let us make the build description erroneous, by changing it so
        # that we have co6, which does not have branch branch.follow
        # description
        with Directory('src'):
            with Directory('builds'):
                touch('01.py', FOLLOW_BUILD_DESC +
                               CO6_WHICH_HAS_NO_BRANCH_FOLLOW)
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')
        # And our checkout all should now fail...
        retcode, text = captured_muddle2(['checkout', '_all'])
        if retcode != 1:
            raise GiveUp('Expected retcode 1 from "muddle checkout _all", got %d'%retcode)
        # The error text we get isn't particularly friendly, but should do
        check_text_endswith(text, """\
Cloning into 'co6'...
fatal: Remote branch branch.follow not found in upstream origin
fatal: The remote end hung up unexpectedly

Failure checking out checkout:co6/checked_out in {where}/src:
Command 'git clone -b branch.follow file://{repo}/co6 co6' failed with retcode 128
""".format(where=d.where, repo=repo))


def test_branch_tree(root_d):
    """Test doing "muddle branch-tree".
    """

    with NewCountedDirectory('branch-tree.repo') as d:
        repo = create_multiplex_repo('test-build')

    with Directory(repo):
        with Directory('co.fred'):
            co_fred_revision = captured_muddle(['query', 'checkout-id']).strip()
        with Directory('co.branch1.fred'):
            co_branch1_fred_revision = captured_muddle(['query', 'checkout-id']).strip()

    with NewCountedDirectory('branch-tree.branch'):
        muddle(['init', '-branch', 'branch0', 'git+file://' + repo, 'builds/01.py'])
        muddle(['checkout', '_all'])

        # Our checkouts should be as in the build description
        check_branch('src/builds', 'branch0')
        check_branch('src/co1', 'master')
        check_branch('src/co.branch1', 'branch1')
        check_revision('co.fred', co_fred_revision)
        check_revision('co.branch1.fred', co_branch1_fred_revision)
        # This branch of the build description doesn't have co.bzr

        retcode, text = captured_muddle2(['branch-tree', 'test-v0.1'])
        if retcode != 1:
            raise GiveUp("Expected 'muddle branch-tree test-v0.1 to fail with"
                         " retcode 1, got %d"%retcode)
        check_text_endswith(text, """\
Unable to branch-tree to test-v0.1, because:
  checkout:co.branch1.fred/checked_out explicitly specifies revision "fred" in the build description
  checkout:co.branch1/checked_out explicitly specifies branch "branch1" in the build description
  checkout:co.fred/checked_out explicitly specifies revision "fred" in the build description
""")

        # OK, force it
        muddle(['branch-tree', '-f', 'test-v0.1'])

        # And those checkouts without explicit branch/revision should now be
        # branched
        check_branch('src/builds', 'test-v0.1')
        check_branch('src/co1', 'test-v0.1')
        check_branch('src/co.branch1', 'branch1')
        check_revision('co.fred', co_fred_revision)
        check_revision('co.branch1.fred', co_branch1_fred_revision)

        # But if we sync...
        muddle(['sync', '_all'])
        # We should undo that...
        check_branch('src/builds', 'branch0')
        check_branch('src/co1', 'master')
        check_branch('src/co.branch1', 'branch1')
        check_revision('co.fred', co_fred_revision)
        check_revision('co.branch1.fred', co_branch1_fred_revision)

        # Try again
        muddle(['branch-tree', '-f', 'test-v0.1'])

        check_branch('src/builds', 'test-v0.1')
        check_branch('src/co1', 'test-v0.1')
        check_branch('src/co.branch1', 'branch1')
        check_revision('co.fred', co_fred_revision)
        check_revision('co.branch1.fred', co_branch1_fred_revision)

        # Now amend the build description so things follow it
        with Directory('src'):
            with Directory('builds'):
                touch('01.py', NO_BZR_BUILD_DESC +
                               FOLLOW_LINE)
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')

        muddle(['sync', '-v', '_all'])

        # And this time, things should follow the build description if they're
        # allowed to
        check_branch('src/builds', 'test-v0.1')
        check_branch('src/co1', 'test-v0.1')
        check_branch('src/co.branch1', 'branch1')
        check_revision('co.fred', co_fred_revision)
        check_revision('co.branch1.fred', co_branch1_fred_revision)

        # If we make amendments to the checkouts that are "following", can
        # we push them?
        with Directory('src'):
            with Directory('builds'):
                append('01.py', '# This should make no difference\n')
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')
                git('commit -a -m "Add a comment at the end"')
                muddle(['push'])
            with Directory('co1'):
                append('Makefile.muddle', '# This should make no difference\n')
                git('commit -a -m "Add a comment at the end"')
                muddle(['push'])

    # Let's see if that took
    with NewCountedDirectory('branch-tree.cloned'):
        muddle(['init', '-branch', 'test-v0.1', 'git+file://' + repo, 'builds/01.py'])
        muddle(['checkout', '_all'])

        check_branch('src/builds', 'test-v0.1')
        check_branch('src/co1', 'test-v0.1')
        check_branch('src/co.branch1', 'branch1')
        check_revision('co.fred', co_fred_revision)
        check_revision('co.branch1.fred', co_branch1_fred_revision)

        with Directory('src'):
            with Directory('builds'):
                with open('01.py') as fd:
                    text = fd.read()
                check_text_endswith(text, '# This should make no difference\n')
            with Directory('co1'):
                with open('Makefile.muddle') as fd:
                    text = fd.read()
                check_text_endswith(text, '# This should make no difference\n')

    # And another variation
    with NewCountedDirectory('branch-tree.cloned'):
        muddle(['init', '-branch', 'branch.follow', 'git+file://' + repo, 'builds/01.py'])
        muddle(['checkout', '_all'])

        check_branch('src/builds', 'branch.follow')
        check_branch('src/co1', 'branch.follow')
        check_branch('src/co.branch1', 'branch1')
        check_revision('co.fred', co_fred_revision)
        check_revision('co.branch1.fred', co_branch1_fred_revision)

        muddle(['branch-tree', '-f', 'test-v0.1'])

        with Directory('src'):
            with Directory('builds'):
                with open('01.py') as fd:
                    text = fd.read()
                check_text_endswith(text, '# This should make no difference\n')
            with Directory('co1'):
                with open('Makefile.muddle') as fd:
                    text = fd.read()
                check_text_endswith(text, '# This should make no difference\n')

def test_lifecycle(root_d):
    """A linear sequence of plausible actions...
    """

    # Repositories
    with NewCountedDirectory('repos') as d0:
        with NewDirectory('builds'):
            git('init --bare')
        with NewDirectory('co1'):
            git('init --bare')
        with NewDirectory('versions'):
            git('init --bare')

        repo_url = 'git+file://%s'%d0.where

    build_name = 'TestBuild'

    # First build tree
    with NewCountedDirectory('build1') as d1:
        muddle(['bootstrap', repo_url, build_name])
        with Directory('src'):
            with Directory('builds'):
                os.remove('01.py')
                os.remove('01.pyc')
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
            check_specific_files_in_this_dir(['.git', 'TestBuild.stamp'])
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

        # Find out what branches we are working with
        text = captured_muddle(['query', 'checkout-branches'])
        lines = text.splitlines()
        lines = lines[3:]       # ignore the header lines
        check_text_lines_v_lines(lines,
                ["builds master <none> <not following>",
                 "co1 master <none> <not following>"],
                fold_whitespace=True)

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
    with NewCountedDirectory('build2') as d2:
        muddle(['init', repo_url, 'builds/01.py'])
        # But we want to specify the revision for our source checkout
        with Directory(d2.join('src', 'builds')):
            # Note we don't need to specify ALL of the SHA1 string, we can
            # just specify some non-ambiguous subset...
            touch('01.py',
                    BUILD_DESC_WITH_REVISION.format(revision=checkout_rev_2[:8],
                                                  build_name=build_name))
            # Then remove the .pyc file, because Python probably won't realise
            # that this new 01.py is later than the previous version
            os.remove('01.pyc')
        muddle(['checkout', '_all'])

        check_revision('co1', checkout_rev_2)

        # If we attempt to 'muddle pull' in the checkout, that should fail
        # because we are already at the requested revision
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
        with Directory(d2.join('src', 'co1')):
            git('checkout %s'%checkout_rev_1)
            muddle(['pull'])
            check_revision('co1', checkout_rev_2)

            git('checkout %s'%checkout_rev_1)
            muddle(['merge'])
            check_revision('co1', checkout_rev_2)

        # What if we try to do work on that specified revision
        # (and, in git terms, at a detached HEAD)
        with Directory(d2.join('src', 'co1')):
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
                os.remove('01.pyc')
            with Directory('co1'):
                git('checkout -b %s'%checkout_branch)
                muddle(['status'])
                muddle(['push'])

        check_revision('co1', checkout_rev_4)

        # Find out what branches we are working with
        text = captured_muddle(['query', 'checkout-branches'])
        lines = text.splitlines()
        lines = lines[3:]       # ignore the header lines
        check_text_lines_v_lines(lines,
                ["builds master <none> <not following>",
                 "co1 this-is-a-branch this-is-a-branch <not following>"],
                fold_whitespace=True)

        # What happens if we specify a revision on a branch?
        # First, choose the revision before the branch
        with Directory('src'):
            with Directory('builds'):
                touch('01.py',
                      BUILD_DESC_WITH_REVISION.format(revision=checkout_rev_3,
                                                      build_name=build_name))
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')
            with Directory('co1'):
                muddle(['status'])
                # Doing 'muddle pull' is the obvious way to get us back to
                # the right revision
                muddle(['pull'])
                check_revision('co1', checkout_rev_3)
                # Because we specified an exact revision, we should be detached
                if not is_detached_head():
                    raise GiveUp('Expected to have a detached HEAD')

        # Find out what branches we are working with
        text = captured_muddle(['query', 'checkout-branches'])
        lines = text.splitlines()
        lines = lines[3:]       # ignore the header lines
        check_text_lines_v_lines(lines,
                ["builds master <none> <not following>",
                 "co1 <none> <none> <not following>"],
                fold_whitespace=True)

        # Then the revision after the branch
        with Directory('src'):
            with Directory('builds'):
                touch('01.py',
                      BUILD_DESC_WITH_REVISION.format(revision=checkout_rev_4,
                                                      build_name=build_name))
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')
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

        # Find out what branches we are working with
        text = captured_muddle(['query', 'checkout-branches'])
        lines = text.splitlines()
        lines = lines[3:]       # ignore the header lines
        check_text_lines_v_lines(lines,
                ["builds master <none> <not following>",
                 "co1 this-is-a-branch <none> <not following>"],
                fold_whitespace=True)

    # Third build tree, investigating use of "muddle branch-tree"
    with NewCountedDirectory('build3') as d3:
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

        # Doing a "mudddle sync" on the checkout should put it back to the
        # master branch, as that's what is (implicitly) asked for in the
        # build description. It shouldn't affect the build description.
        muddle(['sync', 'co1'])
        check_branch('src/builds', 'test-v0.1')
        check_branch('src/co1', 'master')

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

        # Find out what branches we are working with
        text = captured_muddle(['query', 'checkout-branches'])
        lines = text.splitlines()
        lines = lines[3:]       # ignore the header lines
        check_text_lines_v_lines(lines,
                ["builds test-v0.1 <none> <it's own>",
                 "co1 test-v0.1 <none> test-v0.1"], 
                fold_whitespace=True)

    # And a variant like the documentation
    with NewCountedDirectory('build4') as d4:
        muddle(['init', repo_url, 'builds/01.py'])
        muddle(['checkout', '_all'])

        # And change it
        muddle(['branch-tree', 'Widget-v0.1-maintenance'])
        with Directory('src'):
            with Directory('builds'):
                append('01.py', '    builder.follow_build_desc_branch = True\n')
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')

        muddle(['runin', '_all_checkouts', 'git commit -a -m "Create maintenance branch"'])
        muddle(['push', '_all'])

        # Find out what branches we are working with
        text = captured_muddle(['query', 'checkout-branches'])
        lines = text.splitlines()
        lines = lines[3:]       # ignore the header lines
        check_text_lines_v_lines(lines,
                ["builds Widget-v0.1-maintenance <none> <it's own>",
                 "co1 Widget-v0.1-maintenance <none> Widget-v0.1-maintenance"],
                fold_whitespace=True)

        muddle(['stamp', 'version'])
        with Directory('versions'):
            check_specific_files_in_this_dir(['.git', 'TestBuild.Widget-v0.1-maintenance.stamp'])

    with NewCountedDirectory('build4a') as d4a:
        muddle(['unstamp', d4.join('versions', 'TestBuild.Widget-v0.1-maintenance.stamp')])

        # Check we're working with the expected branches
        text = captured_muddle(['query', 'checkout-branches'])
        lines = text.splitlines()
        lines = lines[3:]       # ignore the header lines
        check_text_lines_v_lines(lines,
                ["builds Widget-v0.1-maintenance Widget-v0.1-maintenance <it's own>",
                 "co1 Widget-v0.1-maintenance <none> Widget-v0.1-maintenance"],
                fold_whitespace=True)

        muddle(['stamp', 'version'])
        with Directory('versions'):
            check_specific_files_in_this_dir(['.git', 'TestBuild.Widget-v0.1-maintenance.stamp'])

        # And that stamp file should be identical to the one we had before
        # (if we ignore the first few lines with the timestamp comments)
        with open(d4.join('versions', 'TestBuild.Widget-v0.1-maintenance.stamp')) as fd:
            that = fd.readlines()
        with open(os.path.join('versions', 'TestBuild.Widget-v0.1-maintenance.stamp')) as fd:
            this = fd.readlines()
        check_text_lines_v_lines(actual_lines=this[3:],
                                 wanted_lines=that[3:])

    with NewCountedDirectory('build5') as d5:
        muddle(['init', '-branch', 'Widget-v0.1-maintenance', repo_url, 'builds/01.py'])
        muddle(['checkout', '_all'])

        # Find out what branches we are working with
        text = captured_muddle(['query', 'checkout-branches'])
        lines = text.splitlines()
        lines = lines[3:]       # ignore the header lines
        check_text_lines_v_lines(lines,
                ["builds Widget-v0.1-maintenance Widget-v0.1-maintenance <it's own>",
                 "co1 Widget-v0.1-maintenance <none> Widget-v0.1-maintenance"],
                fold_whitespace=True)

        muddle(['stamp', 'version'])
        with Directory('versions'):
            check_specific_files_in_this_dir(['.git', 'TestBuild.Widget-v0.1-maintenance.stamp'])

        # And that stamp file should also be identical to the one we had before
        # (if we ignore the first few lines with the timestamp comments)
        with open(d4.join('versions', 'TestBuild.Widget-v0.1-maintenance.stamp')) as fd:
            that = fd.readlines()
        with open(os.path.join('versions', 'TestBuild.Widget-v0.1-maintenance.stamp')) as fd:
            this = fd.readlines()
        check_text_lines_v_lines(actual_lines=this[3:],
                                 wanted_lines=that[3:])

        # Now let's push a change
        with Directory('src'):
            with Directory('co1'):
                append('Makefile.muddle', '# This, this is not a change\n')
                git('commit Makefile.muddle -m "But a small thing"')
                muddle(['push'])

        co1_revision_id = captured_muddle(['query', 'checkout-id', 'co1']).strip()

    # And pull it elsewhere
    with Directory(d4a.join('src', 'co1')):
        old_revision_id = captured_muddle(['query', 'checkout-id']).strip()
        muddle(['pull'])
        new_revision_id = captured_muddle(['query', 'checkout-id']).strip()

        if old_revision_id == new_revision_id:
            raise GiveUp('Pull did nothing')

        if new_revision_id != co1_revision_id:
            raise GiveUp('Result of pull was unexpected\n'
                         'got: %s\nnot: %s'%(new_revision_id, co1_revision_id))

    # And let's be really awkward...
    with Directory(d4.join('src', 'co1')):
        git('checkout master')
        rv, text = run2('git branch')
        check_text_v_lines(text,
                           ['  Widget-v0.1-maintenance',
                            '* master'])
        old_revision_id = captured_muddle(['query', 'checkout-id']).strip()

        # We're fondly expecting "muddle pull" to put us back onto the
        # "following" branch
        muddle(['pull'])

        rv, text = run2('git branch')
        check_text_v_lines(text,
                           ['* Widget-v0.1-maintenance',
                            '  master'])
        new_revision_id = captured_muddle(['query', 'checkout-id']).strip()

        if old_revision_id == new_revision_id:
            raise GiveUp('Pull did nothing')

        if new_revision_id != co1_revision_id:
            raise GiveUp('Result of pull was unexpected\n'
                         'got: %s\nnot: %s'%(new_revision_id, co1_revision_id))


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

        banner('TEST BRANCH-TREE')
        test_branch_tree(root_d)

        banner('TEST LIFECYCLE')
        test_lifecycle(root_d)

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
