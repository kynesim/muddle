#! /usr/bin/env python
"""Test tree branching against upstream repositories and subdomains

    $ ./test_lifecycle2.py [-keep]

With -keep, do not delete the 'transient' directory used for the tests.
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

from muddled.depend import Label
from muddled.licenses import standard_licenses
from muddled.repository import Repository
from muddled.withdir import Directory, NewDirectory, TransientDirectory, NewCountedDirectory
from muddled.utils import GiveUp, MuddleBug, normalise_dir, LabelType, LabelTag
from muddled.version_control import VersionControlHandler, checkout_from_repo
from muddled.db import Database, CheckoutData

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
# A build description for testing upstream repositories and subdomains
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
    add_upstream_repo(builder, repo1, repo1_1, ['rhubarb'])
    add_upstream_repo(builder, repo1, repo1_2, ['wombat'])
    add_upstream_repo(builder, repo1, repo1_3, ['platypus'])

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

    builder.add_default_role(role)
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
    builder.add_default_role(role)
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
    builder.add_default_role(role)
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
    builder.add_default_role(role)
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

            with NewDirectory('repo1') as d:
                make_standard_checkout(d.where, 'program1', 'first program')

            # Several very similar repositories
            other_repo_names = ('repo1.1', 'repo1.2', 'repo1.3')
            for repo_name in other_repo_names:
                with NewDirectory(repo_name):
                    git('init --bare')

                repo_url = os.path.join(repo, 'main', repo_name)
                with Directory('repo1'):
                    git('remote add %s %s'%(repo_name, repo_url))
                    git('push %s master'%repo_name)

        with NewDirectory('subdomain1'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN1_BUILD_DESC.format(repo=repo))

        with NewDirectory('subdomain2'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN2_BUILD_DESC.format(repo=repo))

        with NewDirectory('subdomain3'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN3_BUILD_DESC.format(repo=repo))



def check_exception(testing, fn, args, exception=GiveUp, startswith=None, endswith=None):
    """Check we get the right sort of exception.
    """
    if not startswith and not endswith:
        raise ValueError('ERROR TESTING: need startswith or endswith')

    print testing
    ok = False
    try:
        fn(*args)
    except exception as e:
        if startswith:
            if str(e).startswith(startswith):
                ok = True
            else:
                raise GiveUp('Unexpected %s exception: %s\n'
                             '  (does not start with %r)'%(e.__class__.__name__,
                                 e, startswith))
        if endswith:
            if str(e).endswith(endswith):
                ok = True
            else:
                raise GiveUp('Unexpected %s exception: %s\n'
                             '  (does not end with %r)'%(e.__class__.__name__,
                                 e, endswith))
    if ok:
        print 'Fails OK'
    else:
        if startswith:
            raise GiveUp('Did not get an exception, so not starting %r'%startswith)
        else:
            raise GiveUp('Did not get an exception, so not ending %r'%endswith)


def test_using_upstreams(root_dir):
    err, text = captured_muddle2(['query', 'upstream-repos', 'co_label1'])
    check_text(text, "\nThere is no checkout data (repository) registered for label checkout:co_label1/checked_out\n")
    assert err == 1
    text = captured_muddle(['query', 'upstream-repos', 'co_repo1'])
    check_text(text, """\
Repository('git', 'file://{root_dir}/repo/main', 'repo1') used by checkout:co_repo1/checked_out
    Repository('git', 'file://{root_dir}/repo/main', 'repo1.1')  rhubarb
    Repository('git', 'file://{root_dir}/repo/main', 'repo1.2', push=False)  wombat
    Repository('git', 'file://{root_dir}/repo/main', 'repo1.3', pull=False)  platypus
""".format(root_dir=root_dir))

    err, text = captured_muddle2(['pull-upstream', 'package:package1', 'builds', '-u', 'platypus'])
    assert err == 1
    check_text(text, """\

Nowhere to pull checkout:builds/checked_out from

Pulling checkout:co_repo1/checked_out from file://{root_dir}/repo/main/repo1.3 (platypus)

Failure pulling checkout:co_repo1/checked_out in src/co_repo1:
  file://{root_dir}/repo/main/repo1.3 does not allow "pull"
""".format(root_dir=root_dir))

    err, text = captured_muddle2(['push-upstream', 'package:package1', 'builds', '-u', 'wombat', 'wombat'])
    assert err == 1
    check_text(text, """\

Nowhere to push checkout:builds/checked_out to

Pushing checkout:co_repo1/checked_out to file://{root_dir}/repo/main/repo1.2 (wombat)

Failure pushing checkout:co_repo1/checked_out in src/co_repo1:
  file://{root_dir}/repo/main/repo1.2 does not allow "push"
""".format(root_dir=root_dir))

    err, text = captured_muddle2(['-n', 'pull-upstream', 'package:package1', 'builds', '-u', 'rhubarb', 'wombat'])
    assert err == 0
    check_text(text, """\
Asked to pull-upstream:
  checkout:builds/checked_out
  checkout:co_repo1/checked_out
for: rhubarb, wombat
Nowhere to pull checkout:builds/checked_out from
Would pull checkout:co_repo1/checked_out from file://{root_dir}/repo/main/repo1.1 (rhubarb)
Would pull checkout:co_repo1/checked_out from file://{root_dir}/repo/main/repo1.2 (wombat)
""".format(root_dir=root_dir))

    with Directory('src'):
        with Directory('co_repo1'):
            # None of that should have changed where *origin* points
            text = get_stdout('git remote show origin')
            check_text(text, """\
* remote origin
  Fetch URL: file://{root_dir}/repo/main/repo1
  Push  URL: file://{root_dir}/repo/main/repo1
  HEAD branch: master
  Remote branch:
    master tracked
  Local branch configured for 'git pull':
    master merges with remote master
  Local ref configured for 'git push':
    master pushes to master (up to date)
""".format(root_dir=root_dir))

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

    with TransientDirectory(root_dir, keep_on_error=True, keep_anyway=keep) as root:

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

        banner('CHECK USING UPSTREAMS')
        with Directory(d.where):
            test_using_upstreams(root_dir)

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
