#! /usr/bin/env python
"""Test "muddle distribute" support

Our test build structure is::

        <top>
                subdomain1
                        subdomain3
                subdomain2
"""

import os
import shutil
import string
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

from muddled.utils import GiveUp, normalise_dir, LabelType, LabelTag, DirTypeDict
from muddled.utils import Directory, NewDirectory, TransientDirectory
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
    co_label = Label(LabelType.Checkout, 'second_co')
    repo = Repository.from_url('git', 'file://{repo}/main/second_co')
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

    builder.invocation.add_default_role(role)
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
    builder.invocation.add_default_role(role)
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

def main(args):

    if args:
        print __doc__
        raise GiveUp('Unexpected arguments %s'%' '.join(args))

    # Working in a local transient directory seems to work OK
    # although if it's anyone other than me they might prefer
    # somewhere in $TMPDIR...
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    #with TransientDirectory(root_dir):     # XXX
    with NewDirectory(root_dir):

        banner('MAKE REPOSITORIES')
        make_repos_with_subdomain(root_dir)

        with NewDirectory('build') as d:
            banner('CHECK REPOSITORIES OUT')
            checkout_build_descriptions(root_dir, d)
            muddle(['checkout', '_all'])
            check_checkout_files(d)

            banner('TESTING DISTRIBUTE')
            target_dir = os.path.join(root_dir, 'target')
            muddle(['distribute', target_dir])


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
