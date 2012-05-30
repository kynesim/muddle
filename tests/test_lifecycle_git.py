#! /usr/bin/env python
"""Test simple project lifecycle in git

    $ ./test_lifecycle_git.py

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
    sys.path.insert(0, get_parent_file(__file__))
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

DEVT_BUILD = """\
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
    add_package(builder, 'package', 'x86', co_name='checkout')
"""

def test_git_lifecycle(root_d):
    """A linear sequence of plausible actions...
    """

    # Repositories
    with NewDirectory(root_d.join('repos')) as d:
        with NewDirectory(d.join('builds')):
            git('init --bare')
        with NewDirectory(d.join('checkout')):
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
                touch('01.py', DEVT_BUILD.format(build_name=build_name))
                git('add 01.py')  # Because we changed it since the last 'git add'
                git('commit -m "First commit of build description"')
                muddle(['push'])
            with NewDirectory('checkout'):
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

        muddle(['query', 'checkout-id', 'builds'])
        muddle(['query', 'checkout-id', 'checkout'])

    # Still to do: add a couple more revisions to each of the two checkouts,
    # and remember all the revision ids for later. Call the revisions of
    # checkout checkout A, B and C
    #
    # So, things I intend to test:
    #
    # 1. That we can make some changes and push them
    # 2. That we can add a build description that uses the revision id B
    #    found above for checkout checkout
    # 3. That I can "muddle init" a build using that new, revision specific
    #    build tree
    # 4. That doing so does not natter on about detached HEAD (and preferably
    #    does not *have* a detached head)
    # 5. That if I do a "muddle pull" and am already at the specified revision
    #    it tells me that I can't do it because I am already at the specififed
    #    revision
    # 6. That if I do change the revision id in the build description to A
    #    and do a "muddle pull" it tells me I'm trying to go backwards in
    #    time. I *think* the correct thing to happen then is that either
    #    "muddle pull" reverts to the earlier revision (which is confusing),
    #    or I use "muddle reparent" to go to the correct revision (in which
    #    case the message from "muddle pull" should tell me this is what to
    #    do). I suspect this is the better solution, as "muddle reparent" means
    #    "sort out our VCS situation to make sense".
    # 7. That I can do a sequence something like:
    #
    #        * git checkout -b newbranch
    #        * edit the build description to reflect the branch (and not the
    #          revision id any more)
    #        * muddle push
    #
    # 8. That I can set the build description to revision C (and not the
    #    branch) and do (muddle reparent or whatever) and go to revision C.
    # 9. That I can use git itself to go to branch A, and then "muddle pull",
    #    and it *will* take me to revision C
    # 10. That I can start with a different (new) build, and edit the build
    #     description to request that branch, and then a "muddle pull" and/or
    #     "muddle reparent" will take me to that branch.
    #
    # Oh, and that I can't "muddle push" if I'm at or behind the specified
    # revision, and that I can't "muddle push" if I'm not on the specified
    # branch, and so on.
    #
    # I then want a way to be able to do this for the build description as
    # well. This requires doing something about issue 145. My current thinking
    # is that we should support .muddle/Description and .muddle/RootRepository
    # as they are as legacy, but either:
    #
    # 1. If they start with a name in square brackets, treat them as "INI"
    #    style files, containing information similar to that held for stamp
    #    files. The Description would contain the co_dir and co_name for the
    #    build description, and the RootRepository would contain all the
    #    Repository class information.
    #
    # or (and I prefer this second option):
    #
    # 2. In new build trees, have a single file, .muddle/BuildDescription,
    #    which is identical in form to the [CHECKOUT] clause from a stamp
    #    file, but 'repo_revision' would not be specified unless the user
    #    actually specified a revision "by hand" for the builds checkout
    #    (stamp files, of course, always specify a revision).
    #
    #    So, for example:
    #
    #      [CHECKOUT builds]
    #      co_label = checkout:builds/checked_out
    #      co_leaf = builds
    #      repo_vcs = git
    #      repo_from_url_string = None
    #      repo_base_url = file:///Users/tibs/sw/m3/tests/transient/repos
    #      repo_name = builds
    #      repo_prefix_as_is = False
    #
    # "muddle init" would then allow the current way of specifying things,
    # corresponding to:
    #
    #    muddle init <vcs>+<repository_url>  <co_name>/<build_desc>
    #
    # (which gets turned into Repository(<vcs>, <repository_url>, <co_name>))
    # but we would also allow a different form of command line which allows
    # closer control of the Repository created, and allows the "local" co_dir
    # and co_name to be specified independently (so like a call of
    #
    #   muddled.version_control.checkout_from_repo(builder, co_label, repo, co_dir, co_leaf)
    #
    # So parts we might want to specify are:
    #
    # * vcs
    #
    # * co_name (in the above call, co_label.name - we don't need to worry
    #   about domains because by definition we're working at the top level)
    # * co_dir
    # * co_leaf
    # * either:
    #
    #   * repo_from_url_string - i.e., a single URL indicating all of the
    #     repository location in one go
    #
    # * or:
    #
    #   * repo_base_url
    #   * repo_name
    #   * repo_prefix
    #   * repo_prefix_as_is (!)
    #   * repo_suffix
    #   * repo_inner_path
    #   * repo_handler      (?)
    #   * repo_revision
    #   * repo_branch
    #
    # NB: whilst the <vcs> and <repository_url> are inherited as defaults by
    # other checkouts, I don't think any build description branch or revision
    # should be. If the user *does* want to do that, I think they need to do
    # it "by hand" in the build description, by interrogating the build
    # descriptions Repository instance.
    #
    # I *think* we should say that we always retain the current command line
    # as the default, and it corresponds (in fact) to:
    #
    #    muddle init <vcs>+<repo_base_url> [<co_dir>/]<co_leaf>/<build_desc>
    #
    # and that:
    #
    # * the third argument specifies where the build description is under
    #   'src/', in the build tree as checked out, which is what the user
    #   expects
    #
    # and that:
    #
    # * <co_name> defaults to <co_leaf>, use '-co_name <name>' to change it
    #   if necessary
    # * <repo_name> defaults to <co_name>, use '-repo_name <name>' to change
    #   it if necessary (nb: I think it should default to <co_name>, not to
    #   <co_leaf>)
    # * <repo_prefix> defaults to <co_dir>, if that is given
    #
    # and so on.
    #
    # I think we also need to allow switches to come freely anywhere in the
    # command line after "muddle init".
    #
    # It's not entirely clear to me how the user would specify a
    # repo_from_string_url on the command line - perhaps just a free standing
    # switch of that name, which causes the <url> in <vcs>+<url> to be treated
    # differently.
    #
    # Similar changes (as appropriate) would be needed to "muddle bootstrap".


def main(args):

    if args:
        print __doc__
        return

    # Choose a place to work, rather hackily
    #root_dir = os.path.join('/tmp','muddle_tests')
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with TransientDirectory(root_dir, keep_on_error=True) as root_d:
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

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
