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

from muddled.utils import GiveUp, normalise_dir, LabelType
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

        with Directory('.muddle') as m:
            check_files([m.join('Description'),
                         m.join('RootRepository'),
                         m.join('VersionsRepository')])
            with Directory(m.join('tags', 'checkout')) as c:
                check_files([c.join('builds', 'checked_out'),
                             c.join('first_co', 'checked_out'),
                             c.join('main_co', 'checked_out'),
                             c.join('second_co', 'checked_out')])
        with Directory('src') as s:
            check_files([s.join('builds', '01.py'),
                         s.join('main_co', 'Makefile.muddle'),
                         s.join('main_co', 'main1.c'),
                         s.join('first_co', 'Makefile.muddle'),
                         s.join('first_co', 'first.c'),
                         s.join('second_co', 'Makefile.muddle'),
                         s.join('second_co', 'second.c') ])

        with Directory(d.join('domains', 'subdomain1', 'src')) as s:
            check_files([s.join('builds', '01.py'),
                         s.join('main_co', 'Makefile.muddle'),
                         s.join('main_co', 'subdomain1.c'),
                         s.join('first_co', 'Makefile.muddle'),
                         s.join('first_co', 'first.c'),
                         s.join('second_co', 'Makefile.muddle'),
                         s.join('second_co', 'second.c')])
        with Directory(d.join('domains', 'subdomain1', '.muddle')) as m:
            check_files([m.join('Description'),
                         m.join('RootRepository'),
                         m.join('VersionsRepository'),
                         m.join('am_subdomain')])
            with Directory(m.join('tags', 'checkout')) as c:
                check_files([c.join('builds', 'checked_out'),
                             c.join('first_co', 'checked_out'),
                             c.join('main_co', 'checked_out'),
                             c.join('second_co', 'checked_out')])

        with Directory(d.join('domains', 'subdomain1', 'domains', 'subdomain3', 'src')) as s:
            check_files([s.join('builds', '01.py'),
                         s.join('main_co', 'Makefile.muddle'),
                         s.join('main_co', 'subdomain3.c'),
                         s.join('first_co', 'Makefile.muddle'),
                         s.join('first_co', 'first.c'),
                         s.join('second_co', 'Makefile.muddle'),
                         s.join('second_co', 'second.c'),
                        ])
        with Directory(d.join('domains', 'subdomain1', 'domains', 'subdomain3', '.muddle')) as m:
            check_files([m.join('Description'),
                         m.join('RootRepository'),
                         m.join('VersionsRepository'),
                         m.join('am_subdomain')])
            with Directory(m.join('tags', 'checkout')) as c:
                check_files([c.join('builds', 'checked_out'),
                             c.join('first_co', 'checked_out'),
                             c.join('main_co', 'checked_out'),
                             c.join('second_co', 'checked_out')])

        with Directory(d.join('domains', 'subdomain2', 'src')) as s:
            check_files([s.join('builds', '01.py'),
                         s.join('main_co', 'Makefile.muddle'),
                         s.join('main_co', 'subdomain2.c'),
                         s.join('first_co', 'Makefile.muddle'),
                         s.join('first_co', 'first.c'),
                         s.join('second_co', 'Makefile.muddle'),
                         s.join('second_co', 'second.c'),
                        ])

        with Directory(d.join('domains', 'subdomain2', '.muddle')) as m:
            check_files([m.join('Description'),
                         m.join('RootRepository'),
                         m.join('VersionsRepository'),
                         m.join('am_subdomain'),
                        ])
            with Directory(m.join('tags', 'checkout')) as c:
                check_files([c.join('builds', 'checked_out'),
                             c.join('first_co', 'checked_out'),
                             c.join('main_co', 'checked_out'),
                             c.join('second_co', 'checked_out')])

        with Directory(d.join('domains', 'subdomain2', 'domains', 'subdomain3', 'src')) as s:
            check_files([s.join('builds', '01.py'),
                         s.join('main_co', 'Makefile.muddle'),
                         s.join('main_co', 'subdomain3.c'),
                         s.join('first_co', 'Makefile.muddle'),
                         s.join('first_co', 'first.c'),
                         s.join('second_co', 'Makefile.muddle'),
                         s.join('second_co', 'second.c'),
                        ])
        with Directory(d.join('domains', 'subdomain1', 'domains', 'subdomain3', '.muddle')) as m:
            check_files([m.join('Description'),
                         m.join('RootRepository'),
                         m.join('VersionsRepository'),
                         m.join('am_subdomain')])
            with Directory(m.join('tags', 'checkout')) as c:
                check_files([c.join('builds', 'checked_out'),
                             c.join('first_co', 'checked_out'),
                             c.join('main_co', 'checked_out'),
                             c.join('second_co', 'checked_out')])

        with Directory(d.join('domains', 'subdomain2', 'domains', 'subdomain4', 'src')) as s:
            check_files([s.join('builds', '01.py'),
                         s.join('main_co', 'Makefile.muddle'),
                         s.join('main_co', 'subdomain4.c'),
                         s.join('first_co', 'Makefile.muddle'),
                         s.join('first_co', 'first.c'),
                         s.join('second_co', 'Makefile.muddle'),
                         s.join('second_co', 'second.c'),
                        ])
        with Directory(d.join('domains', 'subdomain2', 'domains', 'subdomain4', '.muddle')) as m:
            check_files([m.join('Description'),
                         m.join('RootRepository'),
                         m.join('VersionsRepository'),
                         m.join('am_subdomain')])
            with Directory(m.join('tags', 'checkout')) as c:
                check_files([c.join('builds', 'checked_out'),
                             c.join('first_co', 'checked_out'),
                             c.join('main_co', 'checked_out'),
                             c.join('second_co', 'checked_out')])

def assert_where_is_buildlabel(path):
    with Directory(path):
        print '1. in directory', path
        where = get_stdout('{muddle} where'.format(muddle=MUDDLE_BINARY), False)
        where = where.strip()
        print '2. "muddle where" says', where
        words = where.split(' ')
        try:
            where_label_str = words[-1]
            where_label = Label.from_string(where_label_str)
        except GiveUp:
            # There was no label there - nowt to do
            return

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

    with Directory('build') as d:
        assert_where_is_buildlabel(d.where)
        assert_where_is_buildlabel(d.join('src'))
        assert_where_is_buildlabel(d.join('src', 'builds'))
        assert_where_is_buildlabel(d.join('src', 'main_co'))

        assert_where_is_buildlabel(d.join('obj'))
        assert_where_is_buildlabel(d.join('obj', 'main_pkg'))
        assert_where_is_buildlabel(d.join('obj', 'main_pkg', 'x86'))

        assert_where_is_buildlabel(d.join('install'))
        assert_where_is_buildlabel(d.join('install', 'x86'))

        assert_where_is_buildlabel(d.join('deploy'))
        assert_where_is_buildlabel(d.join('deploy', 'everything'))

        with Directory(d.join('domains')) as dom:
            assert_where_is_buildlabel(d.where)
            with Directory(dom.join('subdomain1')) as sub:
                assert_where_is_buildlabel(sub.where)
                assert_where_is_buildlabel(sub.join('src'))
                assert_where_is_buildlabel(sub.join('src', 'builds'))
                assert_where_is_buildlabel(sub.join('src', 'main_co'))

                assert_where_is_buildlabel(sub.join('obj'))
                assert_where_is_buildlabel(sub.join('obj', 'main_pkg'))
                assert_where_is_buildlabel(sub.join('obj', 'main_pkg', 'x86'))

                assert_where_is_buildlabel(sub.join('install'))
                assert_where_is_buildlabel(sub.join('install', 'x86'))

def build(root_dir):

    with Directory('build') as d:
        muddle([])
        # Things get built in their subdomains, but we're deploying at top level
        check_files([d.join('obj', 'main_pkg', 'x86', 'main1'),
                     d.join('install', 'x86', 'main1'),
                     d.join('domains', 'subdomain1', 'obj', 'main_pkg', 'x86', 'subdomain1'),
                     d.join('domains', 'subdomain1', 'install', 'x86', 'subdomain1'),
                     d.join('deploy', 'everything', 'main1'),
                     d.join('deploy', 'everything', 'sub1', 'subdomain1'),
                    ])

        # The top level build has its own stuff
        with Directory(d.join('.muddle', 'tags')) as t:
            check_files([t.join('checkout', 'builds', 'checked_out'),
                         t.join('checkout', 'main_co', 'checked_out'),
                         t.join('package', 'main_pkg', 'x86-built'),
                         t.join('package', 'main_pkg', 'x86-configured'),
                         t.join('package', 'main_pkg', 'x86-installed'),
                         t.join('package', 'main_pkg', 'x86-postinstalled'),
                         t.join('package', 'main_pkg', 'x86-preconfig'),
                         t.join('deployment', 'everything', 'deployed'),
                        ])

        # The subdomain has its stuff
        with Directory(d.join('domains', 'subdomain1')) as subdomain:

            with Directory(subdomain.join('.muddle')) as m:
                check_files([m.join('am_subdomain')])
                with Directory(m.join('tags')) as t:
                    check_files([t.join('checkout', 'builds', 'checked_out'),
                                 t.join('checkout', 'main_co', 'checked_out'),
                                 t.join('package', 'main_pkg', 'x86-built'),
                                 t.join('package', 'main_pkg', 'x86-configured'),
                                 t.join('package', 'main_pkg', 'x86-installed'),
                                 t.join('package', 'main_pkg', 'x86-postinstalled'),
                                 t.join('package', 'main_pkg', 'x86-preconfig'),
                                ])

            check_nosuch_files([subdomain.join('deployment')])

        # And running the programs gives the expected result
        with Directory(d.join('deploy', 'everything')) as deploy:
            main1_result = get_stdout(deploy.join('main1'))
            if main1_result != 'Program main1\n':
                raise GiveUp('Program main1 printed out "{0}"'.format(main1_result))

            subdomain1_result = get_stdout(deploy.join('sub1', 'subdomain1'))
            if subdomain1_result != 'Program subdomain1\n':
                raise GiveUp('Program subdomain1 printed out "{0}"'.format(subdomain1_result))

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
