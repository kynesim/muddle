#! /usr/bin/env python
"""Test upstream repository support in muddle
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
    sys.path.insert(0, get_parent_file(__file__))
    import muddled.cmdline

from muddled.utils import GiveUp, normalise_dir, LabelType, LabelTag
from muddled.utils import Directory, NewDirectory, TransientDirectory
from muddled.licenses import standard_licenses

class OurGiveUp(Exception):
    pass

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
# A build description for testing upstream repositories
import os

import muddled.pkgs.make
import muddled.deployments.collect as collect

from muddled.depend import checkout, package
from muddled.mechanics import include_domain
from muddled.repository import Repository, get_checkout_repo, add_upstream_repo
from muddled.version_control import checkout_from_repo

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # We're going to do this manually since we want the repository name
    # to be different than the checkout name (and because occasionally
    # it is nice to do things a new way)
    root_repo = builder.build_desc_repo
    repo1 = root_repo.copy_with_changes('repo1')
    co_label = checkout('co_repo1')
    checkout_from_repo(builder, co_label, repo1)
    muddled.pkgs.make.simple(builder, 'package1', role, co_label.name)

    # Add some upstream repositories
    repo1_1 = root_repo.copy_with_changes('repo1.1')
    repo1_2 = root_repo.copy_with_changes('repo1.2', push=False)
    repo1_3 = root_repo.copy_with_changes('repo1.3', pull=False)

    repo1 = get_checkout_repo(builder, checkout('co_repo1'))
    add_upstream_repo(builder, repo1, repo1_1, ('wombat', 'rhubarb'))
    add_upstream_repo(builder, repo1, repo1_2, ('wombat', 'insignificance'))
    add_upstream_repo(builder, repo1, repo1_3, ('platypus', 'rhubarb'))

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role=role, rel="", dest="", domain=None)

    # Some subdomains
    include_domain(builder,
                   domain_name = '{subdomain1}',
                   domain_repo = 'git+file://{repo}/{subdomain1}',
                   domain_desc = 'builds/01.py')
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='', dest='sub', domain='{subdomain1}')

    include_domain(builder,
                   domain_name = '{subdomain2}',
                   domain_repo = 'git+file://{repo}/{subdomain2}',
                   domain_desc = 'builds/01.py')
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='', dest='sub', domain='{subdomain2}')

    include_domain(builder,
                   domain_name = '{subdomain3}',
                   domain_repo = 'git+file://{repo}/{subdomain3}',
                   domain_desc = 'builds/01.py')
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='', dest='sub', domain='{subdomain3}')

    builder.invocation.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

SUBDOMAIN1_BUILD_DESC = """ \
# A subdomain build description

import os

import muddled.pkgs.make
import muddled.deployments.collect as collect

from muddled.depend import checkout, package
from muddled.repository import Repository
from muddled.version_control import checkout_from_repo

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # We use the same repository as a package and checkout in the top-level
    # build (clearly this is an obvious case for that top-level build to
    # unify somehow, but they have chosen not to do so)

    repo = Repository('git', 'file://{repo}/main', 'repo1')
    co_label = checkout('co_repo1')
    checkout_from_repo(builder, co_label, repo)
    muddled.pkgs.make.simple(builder, 'packageSub1', role, co_label.name)

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role=role, rel="", dest="", domain=None)
    builder.invocation.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

SUBDOMAIN2_BUILD_DESC = """ \
# A subdomain build description

import os

import muddled.pkgs.make
import muddled.deployments.collect as collect

from muddled.depend import checkout, package
from muddled.repository import Repository
from muddled.version_control import checkout_from_repo

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # We use a repository that is an upstream repository in the main build
    # Luckily, both we and the top-level build regard this as a repository
    # that can be pulled from and pushed to

    repo = Repository('git', 'file://{repo}/main', 'repo1.1')
    co_label = checkout('co_repo1.1')
    checkout_from_repo(builder, co_label, repo)
    muddled.pkgs.make.simple(builder, 'packageSub2', role, co_label.name)

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role=role, rel="", dest="", domain=None)
    builder.invocation.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

SUBDOMAIN3_BUILD_DESC = """ \
# A subdomain build description

import os

import muddled.pkgs.make
import muddled.deployments.collect as collect

from muddled.depend import checkout, package
from muddled.repository import Repository
from muddled.version_control import checkout_from_repo

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # We use a repository that is an upstream repository in the main build
    # Moreover, it's a repository that the top-level build believes it cannot
    # pull from, whereas we obviously believe we can

    repo = Repository('git', 'file://{repo}/main', 'repo1.3')
    co_label = checkout('co_repo1.3')
    checkout_from_repo(builder, co_label, repo)
    muddled.pkgs.make.simple(builder, 'packageSub3', role, co_label.name)

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role=role, rel="", dest="", domain=None)
    builder.invocation.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

SUBDOMAIN_OK_UPSTREAM_1_BUILD_DESC = """ \
# A subdomain build description that duplicates upstreams from its top-level

import os

import muddled.pkgs.make
import muddled.deployments.collect as collect

from muddled.depend import checkout, package
from muddled.repository import Repository, add_upstream_repo
from muddled.version_control import checkout_from_repo

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Match repository information from upstream
    # This should be OK since it's exactly the same

    repo = Repository('git', 'file://{repo}/main', 'repo1')
    co_label = checkout('co_repo1')
    checkout_from_repo(builder, co_label, repo)
    muddled.pkgs.make.simple(builder, 'packageSub3', role, co_label.name)

    repo1_1 = repo.copy_with_changes('repo1.1')
    repo1_2 = repo.copy_with_changes('repo1.2', push=False)
    repo1_3 = repo.copy_with_changes('repo1.3', pull=False)

    add_upstream_repo(builder, repo, repo1_1, ('wombat', 'rhubarb'))
    add_upstream_repo(builder, repo, repo1_2, ('wombat', 'insignificance'))
    add_upstream_repo(builder, repo, repo1_3, ('platypus', 'rhubarb'))

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role=role, rel="", dest="", domain=None)
    builder.invocation.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

SUBDOMAIN_OK_UPSTREAM_2_BUILD_DESC = """ \
# A subdomain build description that duplicates upstreams from its top-level

import os

import muddled.pkgs.make
import muddled.deployments.collect as collect

from muddled.depend import checkout, package
from muddled.repository import Repository, add_upstream_repo
from muddled.version_control import checkout_from_repo

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Match repository information from upstream
    # This should be OK since it's a subset

    repo = Repository('git', 'file://{repo}/main', 'repo1')
    co_label = checkout('co_repo1')
    checkout_from_repo(builder, co_label, repo)
    muddled.pkgs.make.simple(builder, 'packageSub3', role, co_label.name)

    repo1_1 = repo.copy_with_changes('repo1.1')
    repo1_2 = repo.copy_with_changes('repo1.2', push=False)

    add_upstream_repo(builder, repo, repo1_1, ('wombat', 'rhubarb'))
    add_upstream_repo(builder, repo, repo1_2, ('wombat', 'insignificance'))

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role=role, rel="", dest="", domain=None)
    builder.invocation.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

SUBDOMAIN_OK_UPSTREAM_3_BUILD_DESC = """ \
# A subdomain build description that duplicates upstreams from its top-level

import os

import muddled.pkgs.make
import muddled.deployments.collect as collect

from muddled.depend import checkout, package
from muddled.repository import Repository, add_upstream_repo
from muddled.version_control import checkout_from_repo

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Match repository information from upstream
    # This should be OK since it's a subset that introduces different names

    repo = Repository('git', 'file://{repo}/main', 'repo1')
    co_label = checkout('co_repo1')
    checkout_from_repo(builder, co_label, repo)
    muddled.pkgs.make.simple(builder, 'packageSub3', role, co_label.name)

    repo1_1 = repo.copy_with_changes('repo1.1')
    repo1_2 = repo.copy_with_changes('repo1.2', push=False)

    add_upstream_repo(builder, repo, repo1_1, ('wombat', 'rhubarb'))
    add_upstream_repo(builder, repo, repo1_2, ('platypus', 'manhattan'))

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role=role, rel="", dest="", domain=None)
    builder.invocation.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

SUBDOMAIN_BAD_UPSTREAM_1_BUILD_DESC = """ \
# A subdomain build description that clashes with upstreams from its top-level

import os

import muddled.pkgs.make
import muddled.deployments.collect as collect

from muddled.depend import checkout, package
from muddled.repository import Repository, add_upstream_repo
from muddled.version_control import checkout_from_repo

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Clash with repository information upstream

    repo = Repository('git', 'file://{repo}/main', 'repo1')
    co_label = checkout('co_repo1')
    checkout_from_repo(builder, co_label, repo)
    muddled.pkgs.make.simple(builder, 'packageSub3', role, co_label.name)

    repo1_X = repo.copy_with_changes('repo1.X')

    add_upstream_repo(builder, repo, repo1_X, ('wombat', 'rhubarb', 'fruitbat'))

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role=role, rel="", dest="", domain=None)
    builder.invocation.add_default_role(role)
    builder.by_default_deploy(deployment)
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

def make_repos(root_dir):
    """Create git repositories for our tests.
    """

    def new_repo(prog_name, repo_name):
        with NewDirectory(repo_name) as d:
            make_standard_checkout(d.where, prog_name, prog_name)

    repo = os.path.join(root_dir, 'repo')
    with NewDirectory('repo'):
        with NewDirectory('main'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, BUILD_DESC.format(repo=repo,
                                                           subdomain1='subdomain1',
                                                           subdomain2='subdomain2',
                                                           subdomain3='subdomain3'))
            with NewDirectory('builds_ok_upstream_1') as d:
                make_build_desc(d.where, BUILD_DESC.format(repo=repo,
                                                           subdomain1='subdomain_ok_upstream_1',
                                                           subdomain2='subdomain2',
                                                           subdomain3='subdomain3'))
            with NewDirectory('builds_ok_upstream_2') as d:
                make_build_desc(d.where, BUILD_DESC.format(repo=repo,
                                                           subdomain1='subdomain_ok_upstream_2',
                                                           subdomain2='subdomain2',
                                                           subdomain3='subdomain3'))
            with NewDirectory('builds_ok_upstream_3') as d:
                make_build_desc(d.where, BUILD_DESC.format(repo=repo,
                                                           subdomain1='subdomain_ok_upstream_3',
                                                           subdomain2='subdomain2',
                                                           subdomain3='subdomain3'))
            with NewDirectory('builds_bad_upstream_1') as d:
                make_build_desc(d.where, BUILD_DESC.format(repo=repo,
                                                           subdomain1='subdomain_bad_upstream_1',
                                                           subdomain2='subdomain2',
                                                           subdomain3='subdomain3'))

            # Several very similar repositories
            new_repo('program1', 'repo1')
            new_repo('program1', 'repo1.1')
            new_repo('program1', 'repo1.2')
            new_repo('program1', 'repo1.3')

        with NewDirectory('subdomain1'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN1_BUILD_DESC.format(repo=repo))

        with NewDirectory('subdomain2'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN2_BUILD_DESC.format(repo=repo))

        with NewDirectory('subdomain3'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN3_BUILD_DESC.format(repo=repo))

        with NewDirectory('subdomain_ok_upstream_1'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN_OK_UPSTREAM_1_BUILD_DESC.format(repo=repo))

        with NewDirectory('subdomain_ok_upstream_2'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN_OK_UPSTREAM_2_BUILD_DESC.format(repo=repo))

        with NewDirectory('subdomain_ok_upstream_3'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN_OK_UPSTREAM_3_BUILD_DESC.format(repo=repo))

        with NewDirectory('subdomain_bad_upstream_1'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN_BAD_UPSTREAM_1_BUILD_DESC.format(repo=repo))

def main(args):

    if args:
        print __doc__
        raise GiveUp('Unexpected arguments %s'%' '.join(args))

    # Working in a local transient directory seems to work OK
    # although if it's anyone other than me they might prefer
    # somewhere in $TMPDIR...
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    #with TransientDirectory(root_dir):     # XXX
    with NewDirectory(root_dir) as root:

        banner('MAKE REPOSITORIES')
        make_repos(root_dir)

        with NewDirectory('build') as d:
            banner('CHECK REPOSITORIES OUT')
            muddle(['init', 'git+file://{repo}/main'.format(repo=root.join('repo')),
                    'builds/01.py'])
            muddle(['checkout', '_all'])
            banner('BUILD')
            muddle([])
            banner('STAMP VERSION')
            muddle(['stamp', 'version'])

        with NewDirectory('builds_ok_upstream_1') as d:
            banner('CHECK REPOSITORIES OUT (OK UPSTREAM 1)')
            muddle(['init', 'git+file://{repo}/main'.format(repo=root.join('repo')),
                    'builds_ok_upstream_1/01.py'])

        with NewDirectory('builds_ok_upstream_2') as d:
            banner('CHECK REPOSITORIES OUT (OK UPSTREAM 2)')
            muddle(['init', 'git+file://{repo}/main'.format(repo=root.join('repo')),
                    'builds_ok_upstream_2/01.py'])

        with NewDirectory('builds_ok_upstream_3') as d:
            banner('CHECK REPOSITORIES OUT (OK UPSTREAM 3)')
            muddle(['init', 'git+file://{repo}/main'.format(repo=root.join('repo')),
                    'builds_ok_upstream_3/01.py'])

            upstream_text = captured_muddle(['query', 'upstream-repos'])
#            same_as(upstream_text, """\
#Repository('git', '{root_dir}/repo/main', 'repo1') used by checkout:co_repo1/* checkout:(subdomain_ok_upstream_3)co_repo1/*
#    Repository('git', '{root_dir}/repo/main', 'repo1.1')  rhubarb, wombat
#    Repository('git', '{root_dir}/repo/main', 'repo1.2', push=False)  insignificance, manhattan, platypus, wombat
#    Repository('git', '{root_dir}/repo/main', 'repo1.3', pull=False)  platypus, rhubarb
#""".format(root_dir=root_dir))

        with NewDirectory('builds_bad_upstream_1') as d:
            banner('CHECK REPOSITORIES OUT (BAD UPSTREAM 1)')
            muddle(['init', 'git+file://{repo}/main'.format(repo=root.join('repo')),
                    'builds_bad_upstream_1/01.py'])

if __name__ == '__main__':
    args = sys.argv[1:]
    try:
        main(args)
        print '\nGREEN light\n'
    except OurGiveUp as e:
        print
        print e
        print '\nRED light\n'
    except Exception as e:
        print
        traceback.print_exc()
        print '\nRED light\n'

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
