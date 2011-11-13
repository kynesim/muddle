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
from muddled.depend import Label

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

def assert_where_is_buildlabel(path, expect_what, expect_label=None, expect_domain=None):
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
        else:
            where_label = Label.from_string(where_label_str)

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
        build1_words = build1.split(' ')

        print '4. which said', build1

        if verb != 'checkout':      # Since we've already checked it out...
            print '5. Trying "muddle -n"'

            build2 = get_stdout('{muddle} -n'.format(muddle=MUDDLE_BINARY), False)
            build2 = build2.strip()
            build2_words = build2.split(' ')

            print '6. which said', build1

            if build1_words[-1] != build2_words[-1]:
                raise GiveUp('"muddle" says "{0}, but "muddle {1}" says'
                             ' "{2}"'.format(build1, verb, build2))

        build_label_str = build1_words[-1]
        build_label = Label.from_string(build_label_str)

        print '7. So comparing', build_label_str, 'and', where_label_str

        # We expect the 'where' label to have a wildcarded tag, so let's
        # not worry about it...
        if not where_label.match_without_tag(build_label):
            raise GiveUp('"muddle where" says "{0}", but "muddle {1}" says '
                         '"{2}"'.format(where, verb, build))

        print '8. OK'

def check_buildlabel():
    """Check 'muddle where' and 'muddle -n buildlabel' agree.
    """
    # Of course, at top level we have a special case if we give no args
    # - test that later on...
    #
    # Specifically:
    #
    # 1. If we are at Root, build all deployments and all default roles for
    #    the top-level build
    # 2. If we are at DomainRoot, but have no subdomain, then ???
    # 3. If we are at DomainRoot, and know our subdomain, build all deployments
    #    and default roles for that subdomain(?)
    #
    # Also, if we are in deploy/everything, shouldn't our returned label be
    # deplyoment:everything/*, rather than None?

    with Directory('build') as d:
        assert_where_is_buildlabel(d.where, 'Root')
        assert_where_is_buildlabel(d.join('src'), 'Checkout')
        assert_where_is_buildlabel(d.join('src', 'builds'), 'Checkout', 'checkout:builds/*')
        assert_where_is_buildlabel(d.join('src', 'main_co'), 'Checkout', 'checkout:main_co/*')

        assert_where_is_buildlabel(d.join('obj'), 'Object')
        assert_where_is_buildlabel(d.join('obj', 'main_pkg'), 'Object', 'package:main_pkg{*}/*')
        assert_where_is_buildlabel(d.join('obj', 'main_pkg', 'x86'), 'Object', 'package:main_pkg{x86}/*')

        assert_where_is_buildlabel(d.join('install'), 'Install')
        assert_where_is_buildlabel(d.join('install', 'x86'), 'Install', 'package:*{x86}/*')

        assert_where_is_buildlabel(d.join('deploy'), 'Deployed')
        assert_where_is_buildlabel(d.join('deploy', 'everything'), 'Deployed')

    with Directory('build') as d:
        with Directory('domains') as dom:
            assert_where_is_buildlabel(dom.where, 'DomainRoot')
            with Directory('subdomain1') as sub:
                assert_where_is_buildlabel(sub.where, 'DomainRoot', None, 'subdomain1')
                assert_where_is_buildlabel(sub.join('src'), 'Checkout', None, 'subdomain1')
                assert_where_is_buildlabel(sub.join('src', 'builds'),
                        'Checkout', 'checkout:(subdomain1)builds/*', 'subdomain1')
                assert_where_is_buildlabel(sub.join('src', 'main_co'),
                        'Checkout', 'checkout:(subdomain1)main_co/*', 'subdomain1')

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
                    with Directory('subdomain3') as sub:
                        assert_where_is_buildlabel(sub.where,
                                'DomainRoot', None, 'subdomain1(subdomain3)')
                        assert_where_is_buildlabel(sub.join('src'),
                                'Checkout', None, 'subdomain1(subdomain3)')
                        assert_where_is_buildlabel(sub.join('src', 'builds'),
                                'Checkout', 'checkout:(subdomain1(subdomain3))builds/*',
                                'subdomain1(subdomain3)')
                        assert_where_is_buildlabel(sub.join('src', 'main_co'),
                                'Checkout', 'checkout:(subdomain1(subdomain3))main_co/*',
                                'subdomain1(subdomain3)')

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

def main(args):

    if args:
        print __doc__
        raise GiveUp('Unexpected arguments %s'%' '.join(args))

    # Working in a local transient directory seems to work OK
    # although if it's anyone other than me they might prefer
    # somewhere in $TMPDIR...
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with NewDirectory(root_dir):
        banner('MAKE REPOSITORIES')
        make_repos_with_subdomain(root_dir)

        banner('CHECK REPOSITORIES OUT')
        check_repos_out(root_dir)

        banner('BUILD')
        build(root_dir)
        check_files_after_build(root_dir)
        check_programs_after_build(root_dir)

        banner('CHECK WHERE AND BUILD AGREE')
        check_buildlabel()

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
