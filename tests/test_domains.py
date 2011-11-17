#! /usr/bin/env python
"""Test domain support, and anything that might be affected by it.

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

from muddled.utils import GiveUp, normalise_dir, LabelType, DirTypeDict
from muddled.utils import Directory, NewDirectory, TransientDirectory
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

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "main_pkg", [role], "main_co")
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role], "second_co")

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

    builder.invocation.add_default_role(role)
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

    builder.invocation.add_default_role(role)
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

    builder.invocation.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

SUBDOMAIN3_BUILD_DESC = """ \
# A simple build description

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep

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
    builder.invocation.add_default_role(role)
    # muddle at the top level will default to building this deployment
    builder.by_default_deploy("everything")
"""

SUBDOMAIN4_BUILD_DESC = """ \
# A simple build description

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep

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
    builder.invocation.add_default_role(role)
    # muddle at the top level will default to building this deployment
    builder.by_default_deploy("everything")
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

def make_build_desc(co_dir, file_content):
    """Take some of the repetition out of making build descriptions.
    """
    git('init')
    touch('01.py', file_content)
    git('add 01.py')
    git('commit -a -m "Commit build desc"')

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
                make_standard_checkout(d.where, 'main1', 'main')
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

def check_repos_out(root_dir):

    repo = os.path.join(root_dir, 'repo')
    with NewDirectory('build') as d:
        muddle(['init', 'git+file://{repo}/main'.format(repo=repo), 'builds/01.py'])

        check_files([d.join('src', 'builds', '01.py'),
                     d.join('domains', 'subdomain1', 'src', 'builds', '01.py'),
                    ])

    with Directory('build') as d:
        muddle(['checkout'])
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

    def check_src_files(main_c_file='main1.c'):
        check_files([s.join('builds', '01.py'),
                     s.join('main_co', 'Makefile.muddle'),
                     s.join('main_co', main_c_file),
                     s.join('first_co', 'Makefile.muddle'),
                     s.join('first_co', 'first.c'),
                     s.join('second_co', 'Makefile.muddle'),
                     s.join('second_co', 'second.c')])

    check_dot_muddle(is_subdomain=False)
    with Directory('src') as s:
        check_src_files('main1.c')

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

        want_start = 'Asked to buildlabel: '

        if not build.startswith(want_start):
            raise GiveUp('Expected string starting with "{0}",'
                         ' got "{1}"'.format(want_start, build))

        build = build[len(want_start):]
        build_words = build.split(' ')
        build_labels = map(Label.from_string, build_words)
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
                               expect_package=None, is_build_desc=False):
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

    NB: If 'is_build_desc' is true, then we know not to check for the result
    of "muddle -n", as there is no equivalent package to build.
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

        print '3. Trying "muddle -n {verb}"'.format(verb=verb)

        build1 = get_stdout('{muddle} -n {verb}'.format(muddle=MUDDLE_BINARY,
            verb=verb), False)
        build1 = build1.strip()

        print '4. which said', build1

        build1_words = build1.split(' ')
        build1_label_str = build1_words[-1]
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

        build2_label_str = build2_words[-1]
        build2_label = Label.from_string(build2_label_str)

        # We expect the 'where' label to have a wildcarded tag, so let's
        # not worry about it...
        #if not where_label.match_without_tag(build2_label):
        #    raise GiveUp('"muddle where -detail" says "{0}", but "muddle -n"'
        #            ' says "{1}"'.format(where, build2))

        if verb == 'checkout':
            if expect_package != build2_label_str:
                raise GiveUp('"muddle -n" says "{0}, but we expected "{1}"'.format(build2,
                    expect_package))
        else:
            if not build1_label.just_match(build2_label):
                raise GiveUp('"muddle -n" says "{0}, but "muddle -n {1}" says'
                             ' "{2}"'.format(build1, verb, build2))

        print '7. OK'

def check_buildlabel():
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

    with Directory('build') as d:
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
        assert_where_is_buildlabel(d.join('obj', 'main_pkg'), 'Object', 'package:main_pkg{*}/*')
        assert_where_is_buildlabel(d.join('obj', 'main_pkg', 'x86'), 'Object', 'package:main_pkg{x86}/*')

        assert_where_is_buildlabel(d.join('install'), 'Install')
        # TODO: what should this do? (??build all packages?? or do as it does
        # now, which is nothing??)

        assert_where_is_buildlabel(d.join('install', 'x86'), 'Install', 'package:*{x86}/*')

        assert_where_is_buildlabel(d.join('deploy'), 'Deployed')
        # TODO: Should build all deployments?

        assert_where_is_buildlabel(d.join('deploy', 'everything'), 'Deployed')
        # TODO: Should find label deployment:everything/deployed, and build it

    with Directory('build') as d:
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
                assert_where_is_buildlabel(sub.join('obj', 'main_pkg'),
                        'Object', 'package:(subdomain1)main_pkg{*}/*', 'subdomain1')
                assert_where_is_buildlabel(sub.join('obj', 'main_pkg', 'x86'),
                        'Object', 'package:(subdomain1)main_pkg{x86}/*', 'subdomain1')

                assert_where_is_buildlabel(sub.join('install'), 'Install', None, 'subdomain1')
                assert_where_is_buildlabel(sub.join('install', 'x86'),
                        'Install', 'package:(subdomain1)*{x86}/*', 'subdomain1')

                assert_where_is_buildlabel(sub.join('deploy'), 'Deployed', None, 'subdomain1')
                assert_where_is_buildlabel(sub.join('deploy', 'everything'),
                        'Deployed', None, 'subdomain1')

    with Directory('build') as d:
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
                        assert_where_is_buildlabel(sub.join('obj', 'main_pkg'),
                                'Object', 'package:(subdomain1(subdomain3))main_pkg{*}/*',
                                'subdomain1(subdomain3)')
                        assert_where_is_buildlabel(sub.join('obj', 'main_pkg', 'x86'),
                                'Object', 'package:(subdomain1(subdomain3))main_pkg{x86}/*',
                                'subdomain1(subdomain3)')

                        assert_where_is_buildlabel(sub.join('install'),
                                'Install', None, 'subdomain1(subdomain3)')
                        assert_where_is_buildlabel(sub.join('install', 'x86'),
                                'Install', 'package:(subdomain1(subdomain3))*{x86}/*',
                                'subdomain1(subdomain3)')

                        assert_where_is_buildlabel(sub.join('deploy'),
                                'Deployed', None, 'subdomain1(subdomain3)')
                        assert_where_is_buildlabel(sub.join('deploy', 'everything'),
                                'Deployed', None, 'subdomain1(subdomain3)')

    with Directory('build'):
        with Directory('domains'):
            with Directory('subdomain2'):
                with Directory('domains') as dom:
                    assert_where_is_buildlabel(dom.where, 'DomainRoot', None, 'subdomain2')
                    # TODO: Arguably, should build all subdomains below here...
                    # ...in which case it should find subdomain3 and subdomain4

def build(root_dir):
    with Directory('build') as d:
        muddle([])

def check_files_after_build(root_dir):
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

    with Directory('build') as d:
        # Everything we checked out should still be checked out
        check_checkout_files(d)

        # Built and deployed tags
        check_built_and_deployed_tags(d)

        # Top level
        with Directory('deploy'):
            with Directory('everything') as e:
                check_files_in(e, ['first', 'second', 'main1'])
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
                         o.join('main_pkg', 'x86', 'main1'),
                         o.join('second_pkg', 'x86', 'second')])
        with Directory('install'):
            with Directory('x86') as x:
                check_files_in(x, ['first', 'second', 'main1'])
        with Directory('.muddle'):
            with Directory('tags') as t:
                check_files([t.join('package', 'main_pkg', 'x86-built'),
                             t.join('package', 'main_pkg', 'x86-configured'),
                             t.join('package', 'main_pkg', 'x86-installed'),
                             t.join('package', 'main_pkg', 'x86-postinstalled'),
                             t.join('package', 'main_pkg', 'x86-preconfig'),
                             t.join('deployment', 'everything', 'deployed'),
                            ])

    with Directory('build') as d:
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

    with Directory('build') as d:
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

def check_programs_after_build(root_dir):
    """And running the programs gives the expected result
    """

    def check_result(d, path, progname):
        fullpath = d.join(*path)
        fullname = d.join(fullpath, progname)
        result = get_stdout(fullname)
        if result != 'Program {0}\n'.format(progname):
            raise GiveUp('Program {0} printed out "{1}"'.format(fullpath, result))

    with Directory('build') as d:
        with Directory(d.join('deploy', 'everything')) as e:
            check_result(e, [],     'main1')
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

def check_same_all(root_dir):
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
            text = get_stdout('{muddle} -n unimport _all'.format(muddle=MUDDLE_BINARY), False)
            text = text.strip()
            text = text[len('Asked to unimport: '):]
            expected = ('checkout:builds/checked_out '
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
                        'checkout:(subdomain2(subdomain4))second_co/checked_out')
            if text != expected:
                print 'Expected', expected
                print 'Got     ', text
                raise GiveUp('"muddle -n unimport _all" gave unexpected results')

            text = get_stdout('{muddle} -n build _all'.format(muddle=MUDDLE_BINARY), False)
            text = text.strip()
            text = text[len('Asked to build: '):]
            expected = ('package:first_pkg{x86}/postinstalled '
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
                        'package:(subdomain2(subdomain4))second_pkg{x86}/postinstalled')
            if text != expected:
                print 'Expected', expected
                print 'Got     ', text
                raise GiveUp('"muddle -n build _all" gave unexpected results')

            text = get_stdout('{muddle} -n cleandeploy _all'.format(muddle=MUDDLE_BINARY), False)
            text = text.strip()
            text = text[len('Asked to cleandeploy: '):]
            expected = ('deployment:everything/deployed '
                        'deployment:(subdomain1)everything/deployed '
                        'deployment:(subdomain1(subdomain3))everything/deployed '
                        'deployment:(subdomain2)everything/deployed '
                        'deployment:(subdomain2(subdomain3))everything/deployed '
                        'deployment:(subdomain2(subdomain4))everything/deployed')
            if text != expected:
                print 'Expected', expected
                print 'Got     ', text
                raise GiveUp('"muddle -n cleandeploy _all" gave unexpected results')

    os.path.walk('build', all_same, None)

def main(args):

    if args:
        print __doc__
        raise GiveUp('Unexpected arguments %s'%' '.join(args))

    # Working in a local transient directory seems to work OK
    # although if it's anyone other than me they might prefer
    # somewhere in $TMPDIR...
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with NewDirectory(root_dir):    # XXX Eventually, should be TransientDirectory
        banner('MAKE REPOSITORIES')
        make_repos_with_subdomain(root_dir)

        banner('CHECK REPOSITORIES OUT')
        check_repos_out(root_dir)

        banner('BUILD')
        build(root_dir)
        if False:       # XXX
            check_files_after_build(root_dir)
            check_programs_after_build(root_dir)

        banner('CHECK WHERE AND BUILD AGREE')
        check_buildlabel()

        banner('CHECK _all IS THE SAME EVERYWHERE')
        check_same_all(root_dir)

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
