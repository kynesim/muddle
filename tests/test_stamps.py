#! /usr/bin/env python
"""Test stamp file support

    $ ./test_stamps.py [-keep]

With -keep, do not delete the 'transient' directory used for the tests.

Our test build structure is::

        <top>
                subdomain1
                        subdomain3
                subdomain2

NB: Uses both git and bazaar.
"""

import os
import shutil
import string
import subprocess
import sys
import tempfile
import traceback

from support_for_tests import *
try:
    import muddled.cmdline
except ImportError:
    # Try one level up
    sys.path.insert(0, get_parent_dir(__file__))
    import muddled.cmdline

from muddled.utils import GiveUp, normalise_dir, LabelType, LabelTag, DirTypeDict
from muddled.withdir import Directory, NewDirectory, TransientDirectory
from muddled.depend import Label, label_list_to_string
from muddled.version_stamp import VersionStamp

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

TOPLEVEL_BUILD_DESC = """ \
# A build description that includes two subdomains

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect
from muddled.mechanics import include_domain
from muddled.depend import Label
from muddled.utils import LabelType
from muddled.repository import Repository
from muddled.version_control import checkout_from_repo

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "main_pkg", [role], "main_co")
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")

    # So we can test stamping a Repository using a direct URL
    # Note this is a Bazaar repository
    co_label = Label(LabelType.Checkout, 'second_co')
    repo = Repository.from_url('bzr', 'file://{repo}/main/second_co')
    checkout_from_repo(builder, co_label, repo)
    muddled.pkgs.make.simple(builder, "second_pkg", role, "second_co")

    # A package in a different role (which we never actually build)
    muddled.pkgs.make.simple(builder, "main_pkg", 'arm', "main_co")

    include_domain(builder,
                   domain_name = "subdomain1",
                   domain_repo = "git+file://{repo}/subdomain1",
                   domain_desc = "builds/01.py")

    include_domain(builder,
                   domain_name = "subdomain2",
                   domain_repo = "git+file://{repo}/subdomain2",
                   domain_desc = "builds/01.py")

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role = role,
                                   rel = "", dest = "",
                                   domain = None)

    # And collect stuff from our subdomains
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub1',
                                 domain='subdomain1')
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub2',
                                 domain='subdomain2')

    # The 'arm' role is *not* a default role
    builder.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

SUBDOMAIN1_BUILD_DESC = """ \
# A build description that includes a subdomain

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect
from muddled.mechanics import include_domain
from muddled.depend import Label

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "main_pkg", [role], "main_co")
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role], "second_co")

    include_domain(builder,
                   domain_name = "subdomain3",
                   domain_repo = "git+file://{repo}/subdomain3",
                   domain_desc = "builds/01.py")

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role = role,
                                   rel = "", dest = "",
                                   domain = None)

    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # also the same
                                 rel='',
                                 dest='sub3',
                                 domain='subdomain3')

    builder.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

SUBDOMAIN2_BUILD_DESC = """ \
# A simple build description

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep
from muddled.depend import Label

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    muddled.pkgs.make.medium(builder, "main_pkg", [role], "main_co")
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role], "second_co")

    # The 'everything' deployment is built from our single role, and goes
    # into deploy/everything.
    muddled.deployments.filedep.deploy(builder, "", "everything", [role])

    # If no role is specified, assume this one
    builder.add_default_role(role)
    # muddle at the top level will default to building this deployment
    builder.by_default_deploy("everything")
"""

SUBDOMAIN3_BUILD_DESC = SUBDOMAIN2_BUILD_DESC

GITIGNORE = """\
*~
*.pyc
"""

MAIN_C_SRC = """\
// Simple example C source code
#include <stdio.h>
int main(int argc, char **argv)
{{
    printf("Program {progname}\\n");
    return 0;
}}
"""

OPTIONS_TEST  = """\
# Muddle stamp file
# Writen at 2012-01-29 17:55:40
#           2012-01-29 17:55:40 UTC

[STAMP]
version = 2

[ROOT]
repository = git+file:///Users/tibs/sw/m3/tests/transient/repo/main
description = builds/01.py
versions_repo = git+file:///Users/tibs/sw/m3/tests/transient/repo/main/versions

[CHECKOUT co_name]
co_label = checkout:co_name/checked_out
co_leaf = co_name
repo_vcs = git
repo_from_url_string = None
repo_base_url = file:///Users/tibs/sw/m3/tests/transient/repo
repo_name = second_co
repo_prefix_as_is = False
repo_revision = 388b51c67c56229e7253e727218392e7b6873ea9
option~Fred = int:99
option~BadFred = int:ThreadNeedle
option~Jim = bool:False
option~BadJim = bool:Immensity
option~Bill = str:Some sort of string
option~Aha~There = No colons here
option~AhaTwo = what:pardon
"""

def make_checkout_bare():
    """Use nasty trickery to turn our checkout bare...
    """
    # 1. Lose the working set
    files = os.listdir('.')
    for file in files:
        if file != '.git':
            os.remove(file)
    # 2. Move the contents of .git/ up one level, and delete the empty .git/
    files = os.listdir('.git')
    for file in files:
        os.rename(os.path.join('.git', file), file)
    os.rmdir('.git')
    # 3. Tell git what we've done
    git('config --bool core.bare true')

def make_build_desc(co_dir, file_content):
    """Take some of the repetition out of making build descriptions.
    """
    git('init')
    touch('01.py', file_content)
    git('add 01.py')
    git('commit -m "Commit build desc"')
    touch('.gitignore', GITIGNORE)
    git('add .gitignore')
    git('commit -m "Commit .gitignore"')

    make_checkout_bare()

def make_standard_checkout(co_dir, progname, desc):
    """Take some of the repetition out of making checkouts.
    """
    git('init')
    touch('{progname}.c'.format(progname=progname),
            MAIN_C_SRC.format(progname=progname))
    touch('Makefile.muddle', MUDDLE_MAKEFILE.format(progname=progname))
    git('add {progname}.c Makefile.muddle'.format(progname=progname))
    git('commit -a -m "Commit {desc} checkout {progname}"'.format(desc=desc,
        progname=progname))

    make_checkout_bare()

def make_bzr_standard_checkout(co_dir, progname, desc):
    """Create a bzr repository for our testing.
    """
    bzr('init')
    c = os.getcwd()
    print c
    d = tempfile.mkdtemp()
    try:
        with Directory(d):
            bzr('init')
            touch('{progname}.c'.format(progname=progname),
                    MAIN_C_SRC.format(progname=progname))
            touch('Makefile.muddle', MUDDLE_MAKEFILE.format(progname=progname))
            bzr('add {progname}.c Makefile.muddle'.format(progname=progname))
            bzr('commit -m "Commit {desc} checkout {progname}"'.format(desc=desc,
                progname=progname))
            bzr('push %s'%c)
    finally:
        shutil.rmtree(d)

def make_repos_with_subdomain(repo):
    """Create git repositories for our subdomain tests.
    """
    with NewDirectory('repo'):
        with NewDirectory('main'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, TOPLEVEL_BUILD_DESC.format(repo=repo))
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'main0', 'main')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_bzr_standard_checkout(d.where, 'second', 'second')
        with NewDirectory('subdomain1'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN1_BUILD_DESC.format(repo=repo))
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'subdomain1', 'subdomain1')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')
        with NewDirectory('subdomain2'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN2_BUILD_DESC.format(repo=repo))
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'subdomain2', 'subdomain2')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')
        with NewDirectory('subdomain3'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN3_BUILD_DESC)
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'subdomain3', 'subdomain3')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')

def checkout_build_descriptions(root_dir, d):

    repo = os.path.join(root_dir, 'repo')
    muddle(['init', 'git+file://{repo}/main'.format(repo=repo), 'builds/01.py'])

    check_files([d.join('src', 'builds', '01.py'),
                 d.join('domains', 'subdomain1', 'src', 'builds', '01.py'),
                 d.join('domains', 'subdomain1', 'domains', 'subdomain3', 'src', 'builds', '01.py'),
                 d.join('domains', 'subdomain2', 'src', 'builds', '01.py'),
                ])


def check_checkout_files(d):
    """Check we have all the files we should have after checkout

    'd' is the current Directory.
    """
    def check_dot_muddle(is_subdomain):
        with Directory('.muddle') as m:
            check_files([m.join('Description'),
                         m.join('RootRepository'),
                         m.join('VersionsRepository')])

            if is_subdomain:
                check_files([m.join('am_subdomain')])

            with Directory(m.join('tags', 'checkout')) as c:
                check_files([c.join('builds', 'checked_out'),
                             c.join('first_co', 'checked_out'),
                             c.join('main_co', 'checked_out'),
                             c.join('second_co', 'checked_out')])

    def check_src_files(main_c_file='main0.c'):
        check_files([s.join('builds', '01.py'),
                     s.join('main_co', 'Makefile.muddle'),
                     s.join('main_co', main_c_file),
                     s.join('first_co', 'Makefile.muddle'),
                     s.join('first_co', 'first.c'),
                     s.join('second_co', 'Makefile.muddle'),
                     s.join('second_co', 'second.c')])

    check_dot_muddle(is_subdomain=False)
    with Directory('src') as s:
        check_src_files('main0.c')

    with Directory(d.join('domains', 'subdomain1', 'src')) as s:
        check_src_files('subdomain1.c')
    with Directory(d.join('domains', 'subdomain1')):
        check_dot_muddle(is_subdomain=True)

    with Directory(d.join('domains', 'subdomain1', 'domains', 'subdomain3', 'src')) as s:
        check_src_files('subdomain3.c')
    with Directory(d.join('domains', 'subdomain1', 'domains', 'subdomain3')):
        check_dot_muddle(is_subdomain=True)

    with Directory(d.join('domains', 'subdomain2', 'src')) as s:
        check_src_files('subdomain2.c')
    with Directory(d.join('domains', 'subdomain2')):
        check_dot_muddle(is_subdomain=True)

def check_problem(got, starts):
    """We can't be bothered to check ALL of the string...
    """
    if not got.startswith(starts):
        raise GiveUp('Problem report does not start with what we expect\n'
                     'Got:    %s\n'
                     'Wanted: %s ...'%(got, starts))

def test_options():
    """Test we can read back options from a stamp file.
    """
    fname = 'test_options.stamp'
    touch(fname, OPTIONS_TEST)
    v = VersionStamp.from_file(fname)

    if len(v.problems) != 4:
        raise GiveUp('Expected 4 problems reading %s, got %d'%(fname, len(v.problems)))

    # Make the problem order deterministic
    v.problems.sort()

    check_problem(v.problems[0], "Cannot convert value to integer, for 'option~BadFred = int:ThreadNeedle'")
    check_problem(v.problems[1], "No datatype (no colon in value), for 'option~Aha~There = No colons here'")
    check_problem(v.problems[2], "Unrecognised datatype 'what' (not bool, int or str), for 'option~AhaTwo = what:pardon'")
    check_problem(v.problems[3], "Value is not True or False, for 'option~BadJim = bool:Immensity'")

    co_label = Label(LabelType.Checkout, 'co_name', None, LabelTag.CheckedOut)
    co_dir, co_leaf, repo = v.checkouts[co_label]
    options = v.options[co_label]

    expected_repo = 'file:///Users/tibs/sw/m3/tests/transient/repo/second_co'
    if co_dir is not None or co_leaf != 'co_name' or \
       str(repo) != expected_repo:
        raise GiveUp('Error in reading checkout back\n'
                     '  co_dir %s, expected None\n'
                     '  co_leaf %s, expected co_name\n'
                     '  repo     %s\n'
                     '  expected %s'%(co_dir, co_leaf, repo, expected_repo))

    if len(options) != 3 or \
            options['Jim'] != False or \
            options['Bill'] != 'Some sort of string' or \
            options['Fred'] != 99:
        raise GiveUp('Error in reading checkout options back\n'
                     "  expected {'Jim': False, 'Bill': 'Some sort of string', 'Fred': 99}\n"
                     '  got      %s'%options)

def capture_revisions():
    checkouts = captured_muddle(['query', 'checkouts'])
    checkouts = checkouts.strip()
    checkouts = checkouts.split('\n')

    revisions = {}
    for co in checkouts:
        id = captured_muddle(['query', 'checkout-id', co])
        id = id.strip()
        revisions[co] = id
    return revisions

def revisions_differ(old, new):
    """Finds all the differences (if any).

    Returns True if they are different.
    """
    keys = set(old.keys())
    keys.update(new.keys())
    maxlen = 0
    for k in keys:
        if len(k) > maxlen:
            maxlen = len(k)

    different = False
    for label in sorted(keys):
        if label not in old:
            print '%-*s: not in old'%(maxlen, label)
            different = True
        elif label not in new:
            print '%-*s: not in new'%(maxlen, label)
            different = True
        else:
            old_id = old[label]
            new_id = new[label]
            if old_id != new_id:
                print '%-*s: old=%s, new=%s'%(maxlen, label, old_id, new_id)
                different = True
    return different

def read_just_pulled():
    """Read the _just_pulled file, and return a set of label names.
    """
    with open('.muddle/_just_pulled') as fd:
        text = fd.read()
    label_strings = set()
    just_pulled = text.split('\n')
    for thing in just_pulled:
        if thing:
            label_strings.add(thing)
    return label_strings

def test_stamp_unstamp(root_dir):
    """Simple test of stamping and then unstamping

    Returns the path to the stamp file it creates
    """
    banner('TEST BASIC STAMP AND UNSTAMP')
    with NewDirectory('build') as d:
        banner('CHECK REPOSITORIES OUT', 2)
        checkout_build_descriptions(root_dir, d)
        muddle(['checkout', '_all'])
        check_checkout_files(d)

        banner('STAMP', 2)
        muddle(['stamp', 'version'])

        first_stamp = os.path.join(d.where, 'versions', '01.stamp')

    with NewDirectory('build2') as d2:
        banner('UNSTAMP', 2)
        muddle(['unstamp', os.path.join(d.where, 'versions', '01.stamp')])
        check_checkout_files(d2)

    return first_stamp

def test_stamp_is_current_working_set(first_stamp):
    """Check we are stamping the current working set
    """
    with NewDirectory('build3') as d2:
        banner('TESTING STAMP CURRENT WORKING SET')
        muddle(['unstamp', first_stamp])
        # So, we've selected specific revisions for all of our checkouts
        # and thus they are all in "detached HEAD" state
        revisions = capture_revisions()

        # XXX To be considered XXX
        # Here, we are deliberately making a change that we do not push to the
        # remote repository. Thus our stamp file will contain a revision id
        # that no-one else can make sense of. This may be a Bad Thing.
        # Indeed, if we try to do this with a bzr repository, our own code
        # in 'muddle query checkout-id' would use 'bzr missing' and notice that
        # the revision was not present at the far end, and give up with a
        # complaint at that point.

        with Directory('src'):
            with Directory('first_co'):
                append('Makefile.muddle', '\n# A comment\n')
                git('commit Makefile.muddle -m "Add a comment"')

        # Don't forget that ".strip()" to remove the trailing newline!
        first_co_rev2 = captured_muddle(['query', 'checkout-id', 'first_co']).strip()

        if first_co_rev2 == revisions['first_co']:
            raise GiveUp('The revision of first_co did not change')

        revisions['first_co'] = first_co_rev2

        muddle(['stamp', 'save', 'amended.stamp'])

        stamp = VersionStamp.from_file('amended.stamp')
        if len(stamp.checkouts) != len(revisions):
            raise GiveUp('Stamp file has %d checkouts, build tree %d'%(len(stamp.checkouts),
                                                                       len(revisions)))

        for co in stamp.checkouts:
            if co.domain:
                dom_plus_name = '(%s)%s'%(co.domain, co.name)
            else:
                dom_plus_name = co.name
            repo = stamp.checkouts[co][-1]      # ah, named tuples would be good here
            #print dom_plus_name
            #print '  S:',repo.revision
            #print '  D:',revisions[dom_plus_name]
            if repo.revision != revisions[dom_plus_name]:
                raise GiveUp('Checkout %s is revision %s in stamp file,'
                        ' %s on disk'%(dom_plus_name, repo.revision, revisions[dom_plus_name]))

def test_unstamp_update_identity_operation(repo, first_stamp):
    """Test the "unstamp -update" identity operation
    """
    banner('TESTING UNSTAMP -UPDATE -- TEST 1 (IDENTITY)')
    with NewDirectory('build4') as d2:
        muddle(['init', 'git+file://{repo}/main'.format(repo=repo), 'builds/01.py'])
        muddle(['checkout', '_all'])
        old_revisions = capture_revisions()
        # And check the "null" operation
        muddle(['unstamp', '-update', first_stamp])
        new_revisions = capture_revisions()
        if revisions_differ(old_revisions, new_revisions):
            raise GiveUp('Null update changed stuff!')
        else:
            print 'The tree was not changed by the "null" update'

def test_unstamp_update_2(repo, first_stamp):
    """Test the "unstamp -update" operation a bit more
    """
    banner('TESTING UNSTAMP -UPDATE -- TEST 2')
    with NewDirectory('build5') as d:
        muddle(['init', 'git+file://{repo}/main'.format(repo=repo), 'builds/01.py'])
        muddle(['checkout', '_all'])
        old_revisions = capture_revisions()

        # Make some amdendments and check them in
        with Directory('src'):
            with Directory('first_co'):
                append('Makefile.muddle', '\n# A comment\n')
                git('commit Makefile.muddle -m "Add a comment"')
                muddle(['push'])
            with Directory('second_co'):
                append('Makefile.muddle', '\n# A comment\n')
                bzr('commit Makefile.muddle -m "Add a comment"')
                muddle(['push'])

        with Directory('domains'):
            with Directory('subdomain1'):
                with Directory('src'):
                    with Directory('builds'):
                        append('01.py', '\n# A comment\n')
                        git('commit 01.py -m "Add a comment"')
                        muddle(['push'])

        new_revisions = capture_revisions()

        # Keep this state for later on
        muddle(['stamp', 'save', 'new_state.stamp'])

        # Revert to the original
        muddle(['unstamp', '-update', first_stamp])
        current_revisions = capture_revisions()
        if revisions_differ(current_revisions, old_revisions):
            raise GiveUp('Update back to original failed')

        # And back (forwards) again
        muddle(['unstamp', '-update', 'new_state.stamp'])
        current_revisions = capture_revisions()
        if revisions_differ(current_revisions, new_revisions):
            raise GiveUp('Update forward again failed')

        # One of the points of using "muddle pull" internally in the
        # "muddle unstamp -update" command is that we want our "just pulled"
        # list to be available. So check that.
        just_pulled = read_just_pulled()
        if just_pulled != set(['checkout:first_co/checked_out',
                               'checkout:second_co/checked_out',
                               'checkout:(subdomain1)builds/checked_out']):
            print 'Read _just_pulled as:'
            print just_pulled
            raise GiveUp('Just pulled list does not match')

def main(args):

    keep = False
    if args:
        if len(args) == 1 and args[0] == '-keep':
            keep = True
        else:
            print __doc__
            raise GiveUp('Unexpected arguments %s'%' '.join(args))

    # Working in a local transient directory seems to work OK
    # although if it's anyone other than me they might prefer
    # somewhere in $TMPDIR...
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))
    repo = os.path.join(root_dir, 'repo')

    with TransientDirectory(root_dir, keep_on_error=True, keep_anyway=keep) as root_d:

        banner('TESTING CHECKOUT OPTIONS')
        test_options()

        banner('MAKE REPOSITORIES')
        make_repos_with_subdomain(repo)

        first_stamp = test_stamp_unstamp(root_dir)

        test_stamp_is_current_working_set(first_stamp)

        test_unstamp_update_identity_operation(repo, first_stamp)

        test_unstamp_update_2(repo, first_stamp)


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
