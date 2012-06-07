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
    add_package(builder, 'package', 'x86', co_name='checkout')
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
    add_package(builder, 'package', 'x86', co_name='checkout')
"""

BUILD_DESC_WITH_BRANCH = """\
# A very simple build description, with a checkout pinned to a revision
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
                touch('01.py', BUILD_DESC.format(build_name=build_name))
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

        builds_rev_1 = captured_muddle(['query', 'checkout-id', 'builds']).strip()
        checkout_rev_1 = captured_muddle(['query', 'checkout-id', 'checkout']).strip()

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
            with Directory('checkout'):
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
    print 'checkout/'
    print '  ',checkout_rev_1
    print '  ',checkout_rev_2
    print '  ',checkout_rev_3

    # Second build tree
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

        def check_revision(checkout, revision_wanted):
            actual_revision = captured_muddle(['query', 'checkout-id', checkout]).strip()
            if actual_revision != revision_wanted:
                raise GiveUp('Checkout checkout has revision %s, expected %s'%(
                    actual_revision, revision_wanted))

        check_revision('checkout', checkout_rev_2)

        # If we attempt to pull in the checkout, that should fail because
        # we are already at the requested revision
        text = captured_muddle(['pull', 'checkout'], error_fails=False).strip()
        if not text.endswith('the checkout past the specified revision.'):
            raise GiveUp('Expected muddle pull to fail trying to go "past" revision:\n%s'%text)

        # Merging should behave just the same
        text = captured_muddle(['merge', 'checkout'], error_fails=False).strip()
        if not text.endswith('the checkout past the specified revision.'):
            raise GiveUp('Expected muddle pull to fail trying to go "past" revision:\n%s'%text)

        # What if we're at a different revision?
        # All muddle can really do is go to the revision specified in the
        # build description...
        with Directory(d.join('src', 'checkout')):
            git('checkout %s'%checkout_rev_1)
            muddle(['pull'])
            check_revision('checkout', checkout_rev_2)

            git('checkout %s'%checkout_rev_1)
            muddle(['merge'])
            check_revision('checkout', checkout_rev_2)

        # What if we try to do work on a specified revision
        # (and, in git terms, at a detached HEAD)
        with Directory(d.join('src', 'checkout')):
            append('Makefile.muddle', '# Additional comment number 3\n')
            git('commit -a -m "Add comment number 3"')
            # We're not on a branch, so that commit is likely to get lost,
            # so we'd better allow the user ways of being told that
            # - muddle status should say something
            rc, text = captured_muddle2(['status'])
            if 'Since this checkout has a detached HEAD' not in text:
                raise GiveUp('Expected to be told checkout is in detached'
                             ' HEAD state, instead got:\n%s'%text)
            # And trying to push should fail
            rc, text = captured_muddle2(['push'])
            text = text.strip()
            if 'This checkout is in "detached HEAD" state' not in text:
                raise GiveUp('Expected to be told checkout is in detached'
                             ' HEAD state, instead got:\n%s'%text)

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
            with Directory('checkout'):
                git('checkout -b %s'%checkout_branch)
                muddle(['status'])
                muddle(['push'])


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

    #
    # After some discussion with Richard:
    #
    # 1. The .muddle/BuildDescription file should *not* store the revision id
    #    or branch for the build description. As Richard says, the original
    #    two files *aren't* describing the build description (as such), they're
    #    remembering the defaults that were set up for use in other checkouts,
    #    which are established relative to the "muddle init".
    #
    # 2. However, it might be useful to have -branch and -revision arguments
    #    to "muddle init" so that one doesn't have to:
    #
    #       * muddle init
    #       * cd src/builds
    #       * git checkout <branch-name>
    #
    #    if one does want a particular branch/revision id of the build
    #    description.
    #
    # 3. Richard also suggests that it would be useful to use the branch
    #    of the build description ("live", taken from the .git/ setup, not
    #    from a file in .muddle) as the default branch for *all* checkouts.
    #    This would help with a situation where one wants to move *all* of a
    #    build to a particular branch - for instance, v1.0-maintenance.
    #
    #    So one might do::
    #
    #       muddle init <vcs>+<repo> <desc> -branch v1.0-maintenance
    #
    #    and that would check out that branch of everything.
    #
    # 4. To make it easier to *create* a new branch like that in everything,
    #    then, it may also help to have a "muddle branch" command, so one
    #    can do::
    #
    #       $ muddle branch <branch-name> _all
    #
    #    Perhaps it should act like "git checkout -b" and move to the right
    #    branch as well. (Should it be a variant of "muddle checkout" then?
    #    - no, that's probably confusing and too git specific). Except that
    #    we're saying that the branch of the build description wins. But it's
    #    a pain to have to "cd src/builds; git checkout <branch-name>". So it
    #    probably should do the checkout as well, assuming the common usage is
    #    for _all.
    #
    # 5. All muddle VCS operations should thus check whether they are
    #    consistent with the current state, and if not (in a bad way)
    #    complain helpfully and stop.
    #
    # 6. Richard would like to keep "muddle merge" for at least simple
    #    (fast forward) merging of many checkouts - using muddle pull
    #    for this is less than obvious, and he asserts people would not
    #    guess. I think *full* merging would be a bad thing for it to do.
    #    Maybe it should write things it was not willing to merge to a
    #    .muddle/_need_merging file (or some other better name), and say
    #    it has done so.
    #
    # 7. I should look up "git sparse checkout", but that's for other reasons.
    #


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
