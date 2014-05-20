#! /usr/bin/env python
"""Test domain support, and anything that might be affected by it.

    $ ./test_domains.py [-keep]

With -keep, do not delete the 'transient' directory used for the tests.

We're working with a structure as follows:

    <toplevel>
        <subdomain1>
            <subdomain3>
        <subdomain2>
            <subdomain3>
            <subdomain4>
"""

import os
import shutil
import string
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

from muddled.utils import GiveUp, normalise_dir, LabelType, DirTypeDict
from muddled.withdir import Directory, NewDirectory, TransientDirectory
from muddled.depend import Label, label_list_to_string

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

# TODO: also run tests where some of the lower level labels (both checkouts
# and packages, at least) are unified, in various ways.

TOPLEVEL_BUILD_DESC = """ \
# A build description that includes two subdomains

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
# A build description that includes two subdomains

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

    include_domain(builder,
                   domain_name = "subdomain4",
                   domain_repo = "git+file://{repo}/subdomain4",
                   domain_desc = "builds/01.py")

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role = role,
                                   rel = "", dest = "",
                                   domain = None)

    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub3',
                                 domain='subdomain3')
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub4',
                                 domain='subdomain4')

    builder.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

SUBDOMAIN3_BUILD_DESC = """ \
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

SUBDOMAIN4_BUILD_DESC = """ \
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

# Extra build description fragments for testing label unification
# 1. Unification from main through subdomain 1 into subdomain 3
UNIFY_1_MAIN_TWOJUMP = """\

    builder.unify_labels(Label.from_string('checkout:first_co/checked_out'),
                         Label.from_string('checkout:(subdomain1)first_co/checked_out'))
"""
# Remember, in subdomain 1, *its* first_co checkout does not get marked with a
# domain name
UNIFY_1_SUB1_TWOJUMP = """\
    builder.unify_labels(Label.from_string('checkout:(subdomain3)first_co/checked_out'),
                         Label.from_string('checkout:first_co/checked_out'))
"""

# 2. Unification from subdomain 2 into subdomain 3 (not matched by subdomain 1)
UNIFY_2_SUB2_BELOW = """\
    builder.unify_labels(Label.from_string('checkout:(subdomain3)main_co/checked_out'),
                         Label.from_string('checkout:main_co/checked_out'))
"""

# 3. Unification between subdomain 2 and subdomain 4, but backwards
UNIFY_3_SUB2_BACKWARDS = """\
    builder.unify_labels(Label.from_string('checkout:first_co/checked_out')
                         Label.from_string('checkout:(subdomain4)first_co/checked_out'))
"""

# 4. Unification from main into subdomain 4
UNIFY_4_MAIN_SKIP = """\
    builder.unify_labels(Label.from_string('checkout:(subdomain4)main_co/checked_out'),
                         Label.from_string('checkout:main_co/checked_out'))
"""

# 1. Unifying packages - this is more complicated because the deployments depend
#    upon things like package:(subdomain1)*{x86}/postinstalled and so we're
#    dealing with wildcards for the first time
UNIFY_5_MAIN_PACKAGES = """\

    builder.unify_labels(Label.from_string('package:(subdomain1)second_pkg{x86}/postinstalled'),
                         Label.from_string('package:second_pkg{x86}/postinstalled'))
"""


def muddle_stdout(text):
    """Expand a format string ('text') containing {muddle} and run it.
    """
    return get_stdout(text.format(muddle=MUDDLE_BINARY), False)

def check_cmd(command, expected='', unsure=False):
    """Check we get the expected output from 'muddle -n <command>'

    * If 'expected' is given, then it is a string of the expected labels
      separated by spaces
    * If 'unsure' is true, then 'expected' is ignored, and we expect
      the result of the command to be:

        'Not sure what you want to <command>'

      and an error code.
    """
    retcode, result = run2('{muddle} -n {cmd}'.format(muddle=MUDDLE_BINARY,
                                                      cmd=command))
    result = result.strip()
    lines = result.split('\n  ')

    if unsure:
        command_words = command.split(' ')
        wanted = 'Not sure what you want to {cmd}'.format(cmd=command_words[0])
        line0 = lines[0].strip()
        if retcode:
            if line0 == wanted:
                return
            else:
                raise GiveUp('Wanted "{0}" but got "{1}" and'
                             ' retcode {2}'.format(wanted, line0, retcode))
        else:
            raise GiveUp('Expecting failure and "{0}",'
                         ' got "{1}"'.format(wanted, line0))
    elif retcode:
        raise GiveUp('Command failed with retcode {0},'
                     ' got unexpected {1}'.format(retcode, result))

    lines = lines[1:]               # Drop the "explanation"
    #map(string.strip, lines)
    got = ' '.join(lines)
    if got != expected:
        raise GiveUp('Expected "{0}", got "{1}"'.format(expected, got))

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

def make_repos_with_subdomain(root_dir):
    """Create git repositories for our subdomain tests.
    """
    repo = os.path.join(root_dir, 'repo')
    with NewDirectory('repo'):
        with NewDirectory('main'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, TOPLEVEL_BUILD_DESC.format(repo=repo))
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'main0', 'main')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')
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
        with NewDirectory('subdomain4'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN4_BUILD_DESC)
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'subdomain4', 'subdomain4')
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
                 d.join('domains', 'subdomain2', 'domains', 'subdomain3', 'src', 'builds', '01.py'),
                 d.join('domains', 'subdomain2', 'domains', 'subdomain4', 'src', 'builds', '01.py'),
                ])

def checkout_all(d):
    muddle(['checkout', '_all'])
    check_checkout_files(d)

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

    with Directory(d.join('domains', 'subdomain2', 'domains', 'subdomain3', 'src')) as s:
        check_src_files('subdomain3.c')
    with Directory(d.join('domains', 'subdomain1', 'domains', 'subdomain3')):
        check_dot_muddle(is_subdomain=True)

    with Directory(d.join('domains', 'subdomain2', 'domains', 'subdomain4', 'src')) as s:
        check_src_files('subdomain4.c')
    with Directory(d.join('domains', 'subdomain2', 'domains', 'subdomain4')):
        check_dot_muddle(is_subdomain=True)

def assert_bare_muddle(path, label_strs):
    """A "muddle -n" in 'path' should build 'labels'...

    'labels' is a list of label strings.
    """
    labels = map(Label.from_string, label_strs)
    labels.sort()

    print 'labels:', labels

    with Directory(path):
        build = get_stdout('{muddle} -n'.format(muddle=MUDDLE_BINARY), False)
        build = build.strip()

        print '"muddle -n" said', build

        want_start = 'Asked to buildlabel:'

        if not build.startswith(want_start):
            raise GiveUp('Expected string starting with "{0}",'
                         ' got "{1}"'.format(want_start, build))

        build_lines = build.split('\n')
        build_lines = build_lines[1:]
        build_lines = map(string.strip, build_lines)
        build_labels = map(Label.from_string, build_lines)
        build_labels.sort()

        if len(labels) != len(build_labels):
            raise GiveUp('Expected {0} targets, got {1}\n'
                    '  want {2}\n'
                    '   got {3}'.format(len(labels), len(build_labels),
                        label_list_to_string(labels), label_list_to_string(build_labels)))

        for given, found in zip(labels, build_labels):
            if not given.just_match(found):
                raise GiveUp('Target {0} does not match {1}\n'
                        '  want {2}\n'
                        '   got {3}'.format(given, found,
                            label_list_to_string(labels), label_list_to_string(build_labels)))

def assert_where_is_buildlabel(path, expect_what, expect_label=None, expect_domain=None,
                               expect_package=None, is_build_desc=False, too_complex=False):
    """Check that we get the expected response for this location

    1. From 'muddle where'
    2. From 'muddle -n xxx', where 'xxx' depends on where we are, and the
       "expected result" involves the given label.

    Does *not* do stage 2 if expect_label is None - this is too complex for
    automated calculation.

    'expect_what', 'expect_domain' and 'expect_package' are what we expect
    "muddle where -detail" to give us back.

    For 'Checkout' locations, 'expect_package' is what we expect "muddle -n" to
    give us back (this can't be directly deduced from the "location" label).

    If 'is_build_desc' is true, then we know not to check for the result
    of "muddle -n", as there is no equivalent package to build.

    If 'too_complex' is true, then the "muddle -n" commands (either sort) are
    going to return something too complex for us (typically, more than one
    label), so don't do that.
    """
    with Directory(path):
        print '1. in directory', path
        where = get_stdout('{muddle} where -detail'.format(muddle=MUDDLE_BINARY), False)
        where = where.strip()
        print '2. "muddle where" says', where
        what_str, where_label_str, domain = where.split(' ')

        if what_str != expect_what:
            raise GiveUp('Expected {0}, got {1}'.format(expect_what, what_str))
        if where_label_str != str(expect_label):    # to allow for None
            raise GiveUp('Expected {0}, got {1}'.format(expect_label, where_label_str))
        if domain != str(expect_domain):            # to allow for None
            raise GiveUp('Expected {0}, got {1}'.format(expect_domain, domain))

        dir_type = DirTypeDict[what_str]

        if where_label_str == 'None':
            # There was no label there - nowt to do
            return

        where_label = Label.from_string(where_label_str)
        expect_label = Label.from_string(expect_label)
        if expect_package:
            package_label = Label.from_string(expect_package)
        else:
            package_label = None

        if where_label.type == LabelType.Checkout:
            verb = 'checkout'
        elif where_label.type == LabelType.Package:
            verb = 'build'
        elif where_label.type == LabelType.Deployment:
            verb = 'deploy'
        else:
            raise GiveUp('Unexpected label type in label {0}'.format(where_label))

        if too_complex:
            print 'C. OK (build description)'
            return

        print '3. Trying "muddle -n {verb}"'.format(verb=verb)

        build1 = get_stdout('{muddle} -n {verb}'.format(muddle=MUDDLE_BINARY,
            verb=verb), False)
        build1 = build1.strip()

        print '4. which said', build1

        build1_lines = build1.split('\n')[1:]
        map(string.strip, build1_lines)
        if len(build1_lines) > 1:
            raise GiveUp('Got too many labels: {0}'.format(' '.join(build1_lines)))
        build1_label_str = build1_lines[0].strip()
        build1_label = Label.from_string(build1_label_str)

        # Remember, the expect_label and where_label are already known to be
        # the same, so we only need to check against one
        # Also, we expect the 'where' label to have a wildcarded tag, so let's
        # not worry about it...
        if not where_label.match_without_tag(build1_label):
            raise GiveUp('"muddle where -detail" says "{0}", but "muddle -n {1}" says '
                         '"{2}"'.format(where, verb, build1))

        if is_build_desc:
            print 'X. OK (build description)'
            return

        print '5. Trying "muddle -n"'

        build2 = get_stdout('{muddle} -n'.format(muddle=MUDDLE_BINARY), False)
        build2 = build2.strip()
        build2_words = build2.split(' ')

        print '6. which said', build2

        build2_lines = build2.split('\n')[1:]
        map(string.strip, build2_lines)
        if len(build2_lines) > 1:
            raise GiveUp('Got too many labels: {0}'.format(' '.join(build2_lines)))
        build2_label_str = build2_lines[0].strip()
        build2_label = Label.from_string(build2_label_str)

        if verb == 'checkout':
            if expect_package != build2_label_str:
                raise GiveUp('"muddle -n" says "{0}", but we expected "{1}"'.format(build2,
                    expect_package))
        else:
            if not build1_label.just_match(build2_label):
                raise GiveUp('"muddle -n" says "{0}", but "muddle -n {1}" says'
                             ' "{2}"'.format(build1, verb, build2))

        print '7. OK'

def check_buildlabel(d):
    """Check 'muddle where' and 'muddle -n buildlabel' agree.
    """
    # TODO
    # Of course, at top level we have a special case if we give no args
    # - test that later on...
    #
    # Specifically:
    #
    # 1. If we are at Root, build all deployments and all default roles for
    #    the top-level build. DONE
    #
    # 2. If we are at DomainRoot, and know our subdomain, build all deployments
    #    *in our build tree* within that domain - i.e., deployment:(xxx)/*/deployed
    #    and also all packages in that domain - i.e., package:(xxx)/*{*}/postinstalled
    #    (firstly because we don't know what the subdomain's default deployments and
    #    roles are, but mostly because we don't actually care, as we really only
    #    want to build those things which our main build needs)
    #
    # 3. If we are at DomainRoot, but not yet in a subdomain, then all the things
    #    we would build for each of those subdomains (see (2) above)
    #
    # Also, if we are in deploy/everything, shouldn't our returned label be
    # deplyoment:everything/*, rather than None?

    assert_where_is_buildlabel(d.where, 'Root')
    # We want to build the default deployments and the default roles
    # for this top level build
    assert_bare_muddle(d.where, ['deployment:everything/deployed',
                                 'package:first_pkg{x86}/postinstalled',
                                 'package:main_pkg{x86}/postinstalled',
                                 'package:second_pkg{x86}/postinstalled'])

    assert_where_is_buildlabel(d.join('src'), 'Checkout')
    # TODO: should build all checkouts below here

    assert_where_is_buildlabel(d.join('src', 'builds'), 'Checkout', 'checkout:builds/*',
            is_build_desc=True)
    assert_where_is_buildlabel(d.join('src', 'main_co'), 'Checkout', 'checkout:main_co/*',
            expect_package='package:main_pkg{x86}/postinstalled')

    assert_where_is_buildlabel(d.join('obj'), 'Object')
    # obj/main_pkg will give us back two labels, one for each role that main_pkg
    # is in. We can't express that here, so let's not check it (we do check it
    # elsewhere)
    assert_where_is_buildlabel(d.join('obj', 'main_pkg'), 'Object', 'package:main_pkg{*}/*',
            too_complex=True)
    assert_where_is_buildlabel(d.join('obj', 'main_pkg', 'x86'), 'Object', 'package:main_pkg{x86}/*')

    assert_where_is_buildlabel(d.join('install'), 'Install')
    # TODO: what should this do? (??build all packages?? or do as it does
    # now, which is nothing??)

    assert_where_is_buildlabel(d.join('install', 'x86'), 'Install', 'package:*{x86}/*',
            too_complex=True)

    assert_where_is_buildlabel(d.join('deploy'), 'Deployed')
    # TODO: Should build all deployments?

    assert_where_is_buildlabel(d.join('deploy', 'everything'), 'Deployed', 'deployment:everything/*')
    # TODO: Should find label deployment:everything/deployed, and build it

    with Directory('domains') as dom:
        assert_where_is_buildlabel(dom.where, 'DomainRoot')
        # TODO: Arguably, should build all subdomains below here...

        with Directory('subdomain1') as sub:
            assert_where_is_buildlabel(sub.where, 'DomainRoot', None, 'subdomain1')
            # TODO: should build all deployments and default roles in subdomain1
            # that are in the build tree

            assert_where_is_buildlabel(sub.join('src'), 'Checkout', None, 'subdomain1')
            # TODO: should build all checkouts below here

            assert_where_is_buildlabel(sub.join('src', 'builds'),
                    'Checkout', 'checkout:(subdomain1)builds/*', 'subdomain1',
                    is_build_desc=True)
            assert_where_is_buildlabel(sub.join('src', 'main_co'),
                    'Checkout', 'checkout:(subdomain1)main_co/*', 'subdomain1',
                    expect_package='package:(subdomain1)main_pkg{x86}/postinstalled')

            assert_where_is_buildlabel(sub.join('obj'), 'Object', None, 'subdomain1')
            # This one counts as "too complex" because all of the wildcards get
            # expanded, so it's more difficult to compare the label
            # XXX Probably I should fix that
            assert_where_is_buildlabel(sub.join('obj', 'main_pkg'),
                    'Object', 'package:(subdomain1)main_pkg{*}/*', 'subdomain1',
                    too_complex=True)
            assert_where_is_buildlabel(sub.join('obj', 'main_pkg', 'x86'),
                    'Object', 'package:(subdomain1)main_pkg{x86}/*', 'subdomain1')

            assert_where_is_buildlabel(sub.join('install'), 'Install', None, 'subdomain1')
            # This is similarly "too complex"
            # XXX same comment...
            assert_where_is_buildlabel(sub.join('install', 'x86'),
                    'Install', 'package:(subdomain1)*{x86}/*', 'subdomain1',
                    too_complex=True)

            assert_where_is_buildlabel(sub.join('deploy'), 'Deployed', None, 'subdomain1')
            assert_where_is_buildlabel(sub.join('deploy', 'everything'),
                    'Deployed', 'deployment:(subdomain1)everything/*', 'subdomain1')

    with Directory('domains'):
        with Directory('subdomain1'):
            with Directory('domains') as dom:
                # A domain root within subdomain1 (not subdomain1's domain root)
                assert_where_is_buildlabel(dom.where,
                        'DomainRoot', None, 'subdomain1')
                # TODO: should build all deployments and default roles in subdomain3
                # that are in the build tree
                with Directory('subdomain3') as sub:
                    assert_where_is_buildlabel(sub.where,
                            'DomainRoot', None, 'subdomain1(subdomain3)')

                    assert_where_is_buildlabel(sub.join('src'),
                            'Checkout', None, 'subdomain1(subdomain3)')
                    # TODO: should build all checkouts below here

                    assert_where_is_buildlabel(sub.join('src', 'builds'),
                            'Checkout', 'checkout:(subdomain1(subdomain3))builds/*',
                            'subdomain1(subdomain3)',
                            is_build_desc=True)
                    assert_where_is_buildlabel(sub.join('src', 'main_co'),
                            'Checkout', 'checkout:(subdomain1(subdomain3))main_co/*',
                            'subdomain1(subdomain3)',
                            expect_package='package:(subdomain1(subdomain3))main_pkg{x86}/postinstalled')

                    assert_where_is_buildlabel(sub.join('obj'),
                            'Object', None, 'subdomain1(subdomain3)')
                    # XXX another "too complex"
                    assert_where_is_buildlabel(sub.join('obj', 'main_pkg'),
                            'Object', 'package:(subdomain1(subdomain3))main_pkg{*}/*',
                            'subdomain1(subdomain3)', too_complex=True)
                    assert_where_is_buildlabel(sub.join('obj', 'main_pkg', 'x86'),
                            'Object', 'package:(subdomain1(subdomain3))main_pkg{x86}/*',
                            'subdomain1(subdomain3)')

                    assert_where_is_buildlabel(sub.join('install'),
                            'Install', None, 'subdomain1(subdomain3)')
                    # XXX too many labels back, because of expanding wildcards
                    assert_where_is_buildlabel(sub.join('install', 'x86'),
                            'Install', 'package:(subdomain1(subdomain3))*{x86}/*',
                            'subdomain1(subdomain3)', too_complex=True)

                    assert_where_is_buildlabel(sub.join('deploy'),
                            'Deployed', None, 'subdomain1(subdomain3)')
                    assert_where_is_buildlabel(sub.join('deploy', 'everything'),
                            'Deployed', 'deployment:(subdomain1(subdomain3))everything/*',
                            'subdomain1(subdomain3)')

    with Directory('domains'):
        with Directory('subdomain2'):
            with Directory('domains') as dom:
                assert_where_is_buildlabel(dom.where, 'DomainRoot', None, 'subdomain2')
                # TODO: Arguably, should build all subdomains below here...
                # ...in which case it should find subdomain3 and subdomain4

def check_some_specifics():

        # Remember, main_co is used by packages main_pkg{x86} and
        # main_pkg{arm}, but role 'arm' is not a default role

        check_cmd('unimport main_co', 'checkout:main_co/checked_out')
        check_cmd('unimport package:main_pkg', 'checkout:main_co/checked_out')
        # Some commands give us what we deserve...
        check_cmd('unimport deployment:everything', 'checkout:first_co/checked_out checkout:main_co/checked_out checkout:second_co/checked_out checkout:(subdomain1)first_co/checked_out checkout:(subdomain1)main_co/checked_out checkout:(subdomain1)second_co/checked_out checkout:(subdomain1(subdomain3))first_co/checked_out checkout:(subdomain1(subdomain3))main_co/checked_out checkout:(subdomain1(subdomain3))second_co/checked_out checkout:(subdomain2)first_co/checked_out checkout:(subdomain2)main_co/checked_out checkout:(subdomain2)second_co/checked_out checkout:(subdomain2(subdomain3))first_co/checked_out checkout:(subdomain2(subdomain3))main_co/checked_out checkout:(subdomain2(subdomain3))second_co/checked_out checkout:(subdomain2(subdomain4))first_co/checked_out checkout:(subdomain2(subdomain4))main_co/checked_out checkout:(subdomain2(subdomain4))second_co/checked_out')

        # Note we don't get role {arm}
        check_cmd('build checkout:main_co', 'package:main_pkg{x86}/postinstalled')
        check_cmd('build main_pkg', 'package:main_pkg{x86}/postinstalled')
        check_cmd('build deployment:everything', 'package:first_pkg{x86}/postinstalled package:main_pkg{x86}/postinstalled package:second_pkg{x86}/postinstalled package:(subdomain1)first_pkg{x86}/postinstalled package:(subdomain1)main_pkg{x86}/postinstalled package:(subdomain1)second_pkg{x86}/postinstalled package:(subdomain1(subdomain3))first_pkg{x86}/postinstalled package:(subdomain1(subdomain3))main_pkg{x86}/postinstalled package:(subdomain1(subdomain3))second_pkg{x86}/postinstalled package:(subdomain2)first_pkg{x86}/postinstalled package:(subdomain2)main_pkg{x86}/postinstalled package:(subdomain2)second_pkg{x86}/postinstalled package:(subdomain2(subdomain3))first_pkg{x86}/postinstalled package:(subdomain2(subdomain3))main_pkg{x86}/postinstalled package:(subdomain2(subdomain3))second_pkg{x86}/postinstalled package:(subdomain2(subdomain4))first_pkg{x86}/postinstalled package:(subdomain2(subdomain4))main_pkg{x86}/postinstalled package:(subdomain2(subdomain4))second_pkg{x86}/postinstalled')

        check_cmd('deploy checkout:main_co', 'deployment:everything/deployed')
        check_cmd('deploy package:main_pkg', 'deployment:everything/deployed')
        check_cmd('deploy everything', 'deployment:everything/deployed')

        # Check we get the tags we expect
        check_cmd('unimport main_co/pulled', 'checkout:main_co/checked_out')
        check_cmd('build main_pkg/configured', 'package:main_pkg{x86}/postinstalled')
        check_cmd('deploy everything/instructionsapplied', 'deployment:everything/deployed')

        # Check some location defaults
        check_cmd('unimport', unsure=True)
        check_cmd('build', unsure=True)
        check_cmd('deploy', unsure=True)

        with Directory('src'):
            check_cmd('unimport', 'checkout:builds/checked_out checkout:first_co/checked_out checkout:main_co/checked_out checkout:second_co/checked_out')
            check_cmd('build', 'package:first_pkg{x86}/postinstalled package:main_pkg{x86}/postinstalled package:second_pkg{x86}/postinstalled')
            check_cmd('deploy', 'deployment:everything/deployed')

            with Directory('main_co'):
                check_cmd('unimport', 'checkout:main_co/checked_out')
                check_cmd('build', 'package:main_pkg{x86}/postinstalled')
                check_cmd('deploy', 'deployment:everything/deployed')

        with Directory('obj'):
            check_cmd('unimport', unsure=True)
            check_cmd('build', unsure=True)
            check_cmd('deploy', unsure=True)
            with Directory('main_pkg'):
                check_cmd('unimport', 'checkout:main_co/checked_out')
                # We get all roles for this package, which makes sense if you
                # look at "muddle where" returning a package:<name>{*}/postinstalled
                # label in this directory - {*} expands to all roles, not just
                # the default roles
                check_cmd('build', 'package:main_pkg{arm}/postinstalled package:main_pkg{x86}/postinstalled')
                check_cmd('deploy', 'deployment:everything/deployed')
                with Directory('x86'):
                    check_cmd('unimport', 'checkout:main_co/checked_out')
                    check_cmd('build', 'package:main_pkg{x86}/postinstalled')
                    check_cmd('deploy', 'deployment:everything/deployed')

        with Directory('install'):
            check_cmd('unimport', unsure=True)
            check_cmd('build', unsure=True)
            check_cmd('deploy', unsure=True)
            with Directory('x86'):
                check_cmd('unimport', 'checkout:first_co/checked_out checkout:main_co/checked_out checkout:second_co/checked_out')
                check_cmd('build', 'package:first_pkg{x86}/postinstalled package:main_pkg{x86}/postinstalled package:second_pkg{x86}/postinstalled')
                check_cmd('deploy', 'deployment:everything/deployed')

        with Directory('deploy'):
            check_cmd('unimport', unsure=True)
            check_cmd('build', '', unsure=True)
            check_cmd('deploy', unsure=True)
            with Directory('everything'):
                check_cmd('unimport', 'checkout:first_co/checked_out checkout:main_co/checked_out checkout:second_co/checked_out checkout:(subdomain1)first_co/checked_out checkout:(subdomain1)main_co/checked_out checkout:(subdomain1)second_co/checked_out checkout:(subdomain1(subdomain3))first_co/checked_out checkout:(subdomain1(subdomain3))main_co/checked_out checkout:(subdomain1(subdomain3))second_co/checked_out checkout:(subdomain2)first_co/checked_out checkout:(subdomain2)main_co/checked_out checkout:(subdomain2)second_co/checked_out checkout:(subdomain2(subdomain3))first_co/checked_out checkout:(subdomain2(subdomain3))main_co/checked_out checkout:(subdomain2(subdomain3))second_co/checked_out checkout:(subdomain2(subdomain4))first_co/checked_out checkout:(subdomain2(subdomain4))main_co/checked_out checkout:(subdomain2(subdomain4))second_co/checked_out')
                check_cmd('build', 'package:first_pkg{x86}/postinstalled package:main_pkg{x86}/postinstalled package:second_pkg{x86}/postinstalled package:(subdomain1)first_pkg{x86}/postinstalled package:(subdomain1)main_pkg{x86}/postinstalled package:(subdomain1)second_pkg{x86}/postinstalled package:(subdomain1(subdomain3))first_pkg{x86}/postinstalled package:(subdomain1(subdomain3))main_pkg{x86}/postinstalled package:(subdomain1(subdomain3))second_pkg{x86}/postinstalled package:(subdomain2)first_pkg{x86}/postinstalled package:(subdomain2)main_pkg{x86}/postinstalled package:(subdomain2)second_pkg{x86}/postinstalled package:(subdomain2(subdomain3))first_pkg{x86}/postinstalled package:(subdomain2(subdomain3))main_pkg{x86}/postinstalled package:(subdomain2(subdomain3))second_pkg{x86}/postinstalled package:(subdomain2(subdomain4))first_pkg{x86}/postinstalled package:(subdomain2(subdomain4))main_pkg{x86}/postinstalled package:(subdomain2(subdomain4))second_pkg{x86}/postinstalled')
                check_cmd('deploy', 'deployment:everything/deployed')

        with Directory('domains'):
            check_cmd('unimport', unsure=True)
            check_cmd('build', unsure=True)
            check_cmd('deploy', unsure=True)
            with Directory('subdomain1'):
                check_cmd('unimport', unsure=True)
                check_cmd('build', unsure=True)
                check_cmd('deploy', unsure=True)
                with Directory('src'):
                    check_cmd('unimport', 'checkout:(subdomain1)builds/checked_out checkout:(subdomain1)first_co/checked_out checkout:(subdomain1)main_co/checked_out checkout:(subdomain1)second_co/checked_out')
                    check_cmd('build', 'package:(subdomain1)first_pkg{x86}/postinstalled package:(subdomain1)main_pkg{x86}/postinstalled package:(subdomain1)second_pkg{x86}/postinstalled')
                    # NB: we get all the deployments that use this checkout...
                    check_cmd('deploy', 'deployment:everything/deployed deployment:(subdomain1)everything/deployed')

def build():
    muddle([])

def check_files_after_build(d):
    def check_built_tags(t, pkg):
        check_files([t.join('package', pkg, 'x86-built'),
                     t.join('package', pkg, 'x86-configured'),
                     t.join('package', pkg, 'x86-installed'),
                     t.join('package', pkg, 'x86-postinstalled'),
                     t.join('package', pkg, 'x86-preconfig')])

    def check_built_and_deployed_tags(d):
        with Directory(d.join('.muddle', 'tags')) as t:
            check_built_tags(t, 'main_pkg')
            check_built_tags(t, 'first_pkg')
            check_built_tags(t, 'second_pkg')
            check_files([t.join('deployment', 'everything', 'deployed')])

    def check_files_in(d, files):
        mapped = map(d.join, files)
        check_files(mapped)

    # Everything we checked out should still be checked out
    check_checkout_files(d)

    # Built and deployed tags
    check_built_and_deployed_tags(d)

    # Top level
    with Directory('deploy'):
        with Directory('everything') as e:
            check_files_in(e, ['first', 'second', 'main0'])
            with Directory('sub1') as s1:
                check_files_in(s1, ['first', 'second', 'subdomain1'])
                with Directory('sub3') as s3:
                    check_files_in(s3, ['first', 'second', 'subdomain3'])
            with Directory('sub2') as s2:
                check_files_in(s2, ['first', 'second', 'subdomain2'])
                with Directory('sub3') as s3:
                    check_files_in(s3, ['first', 'second', 'subdomain3'])
                with Directory('sub4') as s4:
                    check_files_in(s4, ['first', 'second', 'subdomain4'])
    with Directory('obj') as o:
        check_files([o.join('first_pkg', 'x86', 'first'),
                     o.join('main_pkg', 'x86', 'main0'),
                     o.join('second_pkg', 'x86', 'second')])
    with Directory('install'):
        with Directory('x86') as x:
            check_files_in(x, ['first', 'second', 'main0'])
    with Directory('.muddle'):
        with Directory('tags') as t:
            check_files([t.join('package', 'main_pkg', 'x86-built'),
                         t.join('package', 'main_pkg', 'x86-configured'),
                         t.join('package', 'main_pkg', 'x86-installed'),
                         t.join('package', 'main_pkg', 'x86-postinstalled'),
                         t.join('package', 'main_pkg', 'x86-preconfig'),
                         t.join('deployment', 'everything', 'deployed'),
                        ])

    with Directory('domains'):
        with Directory('subdomain1') as s1:
            check_built_and_deployed_tags(s1)
            with Directory('deploy'):
                with Directory('everything') as e:
                    check_files_in(e, ['first', 'second', 'subdomain1'])
                    with Directory('sub3') as s3:
                        check_files_in(s3, ['first', 'second', 'subdomain3'])
            with Directory('obj') as o:
                check_files([o.join('first_pkg', 'x86', 'first'),
                             o.join('main_pkg', 'x86', 'subdomain1'),
                             o.join('second_pkg', 'x86', 'second')])
            with Directory('install'):
                with Directory('x86') as x:
                    check_files_in(x, ['first', 'second', 'subdomain1'])
            with Directory('domains'):
                with Directory('subdomain3') as s3:
                    check_built_and_deployed_tags(s3)
                    with Directory('deploy'):
                        with Directory('everything') as e:
                            check_files_in(e, ['first', 'second', 'subdomain3'])
                    with Directory('obj') as o:
                        check_files([o.join('first_pkg', 'x86', 'first'),
                                     o.join('main_pkg', 'x86', 'subdomain3'),
                                     o.join('second_pkg', 'x86', 'second')])
                    with Directory('install'):
                        with Directory('x86') as x:
                            check_files_in(x, ['first', 'second', 'subdomain3'])

    with Directory('domains'):
        with Directory('subdomain2') as s2:
            check_built_and_deployed_tags(s2)
            with Directory('deploy'):
                with Directory('everything') as e:
                    check_files_in(e, ['first', 'second', 'subdomain2'])
                    with Directory('sub3') as s3:
                        check_files_in(s3, ['first', 'second', 'subdomain3'])
                    with Directory('sub4') as s4:
                        check_files_in(s4, ['first', 'second', 'subdomain4'])
            with Directory('obj') as o:
                check_files([o.join('first_pkg', 'x86', 'first'),
                             o.join('main_pkg', 'x86', 'subdomain2'),
                             o.join('second_pkg', 'x86', 'second')])
            with Directory('install'):
                with Directory('x86') as x:
                    check_files_in(x, ['first', 'second', 'subdomain2'])
            with Directory('domains'):
                with Directory('subdomain3') as s3:
                    check_built_and_deployed_tags(s3)
                    with Directory('deploy'):
                        with Directory('everything') as e:
                            check_files_in(e, ['first', 'second', 'subdomain3'])
                    with Directory('obj') as o:
                        check_files([o.join('first_pkg', 'x86', 'first'),
                                     o.join('main_pkg', 'x86', 'subdomain3'),
                                     o.join('second_pkg', 'x86', 'second')])
                    with Directory('install'):
                        with Directory('x86') as x:
                            check_files_in(x, ['first', 'second', 'subdomain3'])
                with Directory('subdomain4') as s4:
                    check_built_and_deployed_tags(s4)
                    with Directory('deploy'):
                        with Directory('everything') as e:
                            check_files_in(e, ['first', 'second', 'subdomain4'])
                    with Directory('obj') as o:
                        check_files([o.join('first_pkg', 'x86', 'first'),
                                     o.join('main_pkg', 'x86', 'subdomain4'),
                                     o.join('second_pkg', 'x86', 'second')])
                    with Directory('install'):
                        with Directory('x86') as x:
                            check_files_in(x, ['first', 'second', 'subdomain4'])

def check_programs_after_build(d):
    """And running the programs gives the expected result
    """

    def check_result(d, path, progname):
        fullpath = d.join(*path)
        fullname = d.join(fullpath, progname)
        result = get_stdout(fullname)
        if result != 'Program {0}\n'.format(progname):
            raise GiveUp('Program {0} printed out "{1}"'.format(fullpath, result))

    with Directory(d.join('deploy', 'everything')) as e:
        check_result(e, [],     'main0')
        check_result(e, [],     'first')
        check_result(e, [],     'second')
        check_result(e, ['sub1'], 'subdomain1')
        check_result(e, ['sub1'], 'first')
        check_result(e, ['sub1'], 'second')
        check_result(e, ['sub2'], 'subdomain2')
        check_result(e, ['sub2'], 'first')
        check_result(e, ['sub2'], 'second')
        check_result(e, ['sub1', 'sub3'], 'subdomain3')
        check_result(e, ['sub1', 'sub3'], 'first')
        check_result(e, ['sub1', 'sub3'], 'second')
        check_result(e, ['sub2', 'sub3'], 'subdomain3')
        check_result(e, ['sub2', 'sub3'], 'first')
        check_result(e, ['sub2', 'sub3'], 'second')
        check_result(e, ['sub2', 'sub4'], 'subdomain4')
        check_result(e, ['sub2', 'sub4'], 'first')
        check_result(e, ['sub2', 'sub4'], 'second')

def check_same_all():
    """Check that 'muddle -n XXX _all is the same everywhere.

    (well, we don't actually check EVERYWHERE - we prune a bit to save time)
    """

    def all_same(arg, dirname, fnames):
        for name in ('.muddle', '.git',
                     'subdomain2', 'sub2',
                     'first_co', 'second_co',
                     'first_pkg', 'second_pkg'):
            if name in fnames:
                fnames.remove(name)
        with Directory(dirname): #, show_pushd=False):
            check_cmd('unimport _all',
                       ('checkout:builds/checked_out '
                        'checkout:first_co/checked_out '
                        'checkout:main_co/checked_out '
                        'checkout:second_co/checked_out '
                        'checkout:(subdomain1)builds/checked_out '
                        'checkout:(subdomain1)first_co/checked_out '
                        'checkout:(subdomain1)main_co/checked_out '
                        'checkout:(subdomain1)second_co/checked_out '
                        'checkout:(subdomain1(subdomain3))builds/checked_out '
                        'checkout:(subdomain1(subdomain3))first_co/checked_out '
                        'checkout:(subdomain1(subdomain3))main_co/checked_out '
                        'checkout:(subdomain1(subdomain3))second_co/checked_out '
                        'checkout:(subdomain2)builds/checked_out '
                        'checkout:(subdomain2)first_co/checked_out '
                        'checkout:(subdomain2)main_co/checked_out '
                        'checkout:(subdomain2)second_co/checked_out '
                        'checkout:(subdomain2(subdomain3))builds/checked_out '
                        'checkout:(subdomain2(subdomain3))first_co/checked_out '
                        'checkout:(subdomain2(subdomain3))main_co/checked_out '
                        'checkout:(subdomain2(subdomain3))second_co/checked_out '
                        'checkout:(subdomain2(subdomain4))builds/checked_out '
                        'checkout:(subdomain2(subdomain4))first_co/checked_out '
                        'checkout:(subdomain2(subdomain4))main_co/checked_out '
                        'checkout:(subdomain2(subdomain4))second_co/checked_out'))

            check_cmd('build _all',
                       ('package:first_pkg{x86}/postinstalled '
                        'package:main_pkg{x86}/postinstalled '
                        'package:second_pkg{x86}/postinstalled '
                        'package:(subdomain1)first_pkg{x86}/postinstalled '
                        'package:(subdomain1)main_pkg{x86}/postinstalled '
                        'package:(subdomain1)second_pkg{x86}/postinstalled '
                        'package:(subdomain1(subdomain3))first_pkg{x86}/postinstalled '
                        'package:(subdomain1(subdomain3))main_pkg{x86}/postinstalled '
                        'package:(subdomain1(subdomain3))second_pkg{x86}/postinstalled '
                        'package:(subdomain2)first_pkg{x86}/postinstalled '
                        'package:(subdomain2)main_pkg{x86}/postinstalled '
                        'package:(subdomain2)second_pkg{x86}/postinstalled '
                        'package:(subdomain2(subdomain3))first_pkg{x86}/postinstalled '
                        'package:(subdomain2(subdomain3))main_pkg{x86}/postinstalled '
                        'package:(subdomain2(subdomain3))second_pkg{x86}/postinstalled '
                        'package:(subdomain2(subdomain4))first_pkg{x86}/postinstalled '
                        'package:(subdomain2(subdomain4))main_pkg{x86}/postinstalled '
                        'package:(subdomain2(subdomain4))second_pkg{x86}/postinstalled'))

            check_cmd('cleandeploy _all',
                       ('deployment:everything/deployed '
                        'deployment:(subdomain1)everything/deployed '
                        'deployment:(subdomain1(subdomain3))everything/deployed '
                        'deployment:(subdomain2)everything/deployed '
                        'deployment:(subdomain2(subdomain3))everything/deployed '
                        'deployment:(subdomain2(subdomain4))everything/deployed'))

    os.path.walk('build', all_same, None)

def test_label_unification_1(root_dir, d):
    # Let's start with baby steps...

    # Only checkout subdomain1, which has a single subdomain in it
    repo = os.path.join(root_dir, 'repo')
    muddle(['init', 'git+file://{repo}/subdomain1'.format(repo=repo), 'builds/01.py'])

    append(d.join('src', 'builds', '01.py'),
           """
    builder.unify_labels(Label.from_string('checkout:second_co/checked_out'),
                         Label.from_string('checkout:(subdomain3)second_co/checked_out'))

""")

    # Then remove the .pyc file, because Python probably won't realise
    # that this new 01.py is later than the previous version
    os.remove(d.join('src', 'builds', '01.pyc'))

    # Check it all worked
    text = muddle_stdout("{muddle} query needed-by package:second_pkg{{x86}}/preconfig")
    lines = text.split('\n')
    if 'checkout:(subdomain3)second_co/checked_out' not in lines:
        raise GiveUp('Unification [1] failed:\n{0}'.format(text))

    text = muddle_stdout("{muddle} query needed-by 'package:(subdomain3)second_pkg{{x86}}/preconfig'")
    lines = text.split('\n')
    if 'checkout:(subdomain3)second_co/checked_out' not in lines:
        raise GiveUp('Unification [2] failed:\n{0}'.format(text))

def test_label_unification(root_dir, d):
    banner('CHECKOUT BUILD DESCRIPTIONS')
    checkout_build_descriptions(root_dir, d)

    banner('AMEND BUILD DESCRIPTIONS')

    # =========================================================================
    # Before...
    text = muddle_stdout("{muddle} query needed-by 'package:first_pkg{{x86}}/preconfig'")
    lines = text.split('\n')
    if 'checkout:first_co/checked_out' not in lines:
        raise GiveUp('Pre UNIFY_1_MAIN_TWOJUMP/1 check failed:\n{0}'.format(text))

    text = muddle_stdout("{muddle} query needed-by 'package:(subdomain1)first_pkg{{x86}}/preconfig'")
    lines = text.split('\n')
    if 'checkout:(subdomain1)first_co/checked_out' not in lines:
        raise GiveUp('Pre UNIFY_1_MAIN_TWOJUMP/2 check failed:\n{0}'.format(text))

    build_description = d.join('src','builds','01.py')
    append(d.join(build_description), UNIFY_1_MAIN_TWOJUMP)
    # Then remove the .pyc file, because Python probably won't realise
    # that this new 01.py is later than the previous version (the mtime
    # of our modified file is probably within the same second as the mtime
    # of the original file)
    os.remove(build_description+'c')

    # After...
    text = muddle_stdout("{muddle} query needed-by 'package:first_pkg{{x86}}/preconfig'")
    lines = text.split('\n')
    if 'checkout:(subdomain1)first_co/checked_out' not in lines or \
       'checkout:first_co/checked_out' in lines:
        raise GiveUp('Unification UNIFY_1_MAIN_TWOJUMP/1 failed:\n{0}'.format(text))

    text = muddle_stdout("{muddle} query needed-by 'package:(subdomain1)first_pkg{{x86}}/preconfig'")
    lines = text.split('\n')
    if 'checkout:(subdomain1)first_co/checked_out' not in lines:
        raise GiveUp('Unification check UNIFY_1_MAIN_TWOJUMP/2 failed:\n{0}'.format(text))

    # =========================================================================
    # Before...
    text = muddle_stdout("{muddle} query needed-by 'package:(subdomain1(subdomain3))first_pkg{{x86}}/preconfig'")
    lines = text.split('\n')
    if 'checkout:(subdomain1(subdomain3))first_co/checked_out' not in lines:
        raise GiveUp('Pre UNIFY_1_SUB1_TWOJUMP check failed:\n{0}'.format(text))
    build_description = d.join('domains', 'subdomain1', 'src', 'builds','01.py')
    append(build_description, UNIFY_1_SUB1_TWOJUMP)
    os.remove(build_description+'c')

    # After...
    text = muddle_stdout("{muddle} query needed-by 'package:(subdomain1(subdomain3))first_pkg{{x86}}/preconfig'")
    lines = text.split('\n')
    if 'checkout:(subdomain1)first_co/checked_out' not in lines or \
       'checkout:(subdomain1(subdomain3)first_co/checked_out' in lines:
        raise GiveUp('Post UNIFY_1_SUB1_TWOJUMP failed:\n{0}'.format(text))

    # And our earlier checks should still be true
    text = muddle_stdout("{muddle} query needed-by 'package:first_pkg{{x86}}/preconfig'")
    lines = text.split('\n')
    if 'checkout:(subdomain1)first_co/checked_out' not in lines or \
       'checkout:first_co/checked_out' in lines:
        raise GiveUp('Unification UNIFY_1_MAIN_TWOJUMP/1 failed:\n{0}'.format(text))

    text = muddle_stdout("{muddle} query needed-by 'package:(subdomain1)first_pkg{{x86}}/preconfig'")
    lines = text.split('\n')
    if 'checkout:(subdomain1)first_co/checked_out' not in lines:
        raise GiveUp('Unification check UNIFY_1_MAIN_TWOJUMP/2 failed:\n{0}'.format(text))
    # =========================================================================
    #append(d.join('domains', 'subdomain2', 'src','builds','01.py'), UNIFY_2_SUB2_BELOW)

    #append(d.join('domains', 'subdomain2', 'src','builds','01.py'), UNIFY_3_SUB2_BACKWARDS)

    #append(d.join('src','builds','01.py'), UNIFY_4_MAIN_SKIP)

    #build_description = d.join('src','builds','01.py')
    #append(build_description, UNIFY_5_MAIN_PACKAGES)
    #os.remove(build_description+'c')

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

    with TransientDirectory(root_dir, keep_on_error=True, keep_anyway=keep) as root_d:
        banner('MAKE REPOSITORIES')
        make_repos_with_subdomain(root_dir)

        with NewDirectory('build') as d:
            banner('CHECK REPOSITORIES OUT')
            checkout_build_descriptions(root_dir, d)
            checkout_all(d)

            banner('BUILD')
            build()

            if True:
                check_files_after_build(d)
                check_programs_after_build(d)

                banner('CHECK WHERE AND BUILD AGREE')
                check_buildlabel(d)

                banner('CHECK _all IS THE SAME EVERYWHERE')
                check_same_all()

            banner('CHECK SOME SPECIFICS')
            check_some_specifics()

        banner('TESTING LABEL UNIFICATION')

        # This one I know works...
        with TransientDirectory('build2', keep_on_error=True) as d:
            test_label_unification_1(root_dir, d)

        with NewDirectory('build2') as d:
            test_label_unification(root_dir, d)
            #banner('CHECKOUT BUILD DESCRIPTIONS')
            #checkout_build_descriptions(root_dir, d)

            #banner('AMEND BUILD DESCRIPTIONS')

            #append(d.join('src','builds','01.py'), UNIFY_1_MAIN_NORMAL)

            #append(d.join('src','builds','01.py'), UNIFY_2_MAIN_TWOJUMP)
            #append(d.join('domains', 'subdomain1', 'src','builds','01.py'), UNIFY_2_SUB1_TWOJUMP)

            #append(d.join('domains', 'subdomain2', 'src','builds','01.py'), UNIFY_3_SUB2_BELOW)

            #append(d.join('domains', 'subdomain2', 'src','builds','01.py'), UNIFY_4_SUB2_BACKWARDS)

            #append(d.join('src','builds','01.py'), UNIFY_5_MAIN_SKIP)


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
