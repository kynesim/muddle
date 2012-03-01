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

import muddled
import muddled.pkgs.make
import muddled.deployments.collect as collect

from muddled.depend import checkout, package
from muddled.repository import Repository, add_upstream_repo

def add_package(builder, name, role, co_name=None):
    if not co_name:
        co_name = name
    muddled.pkgs.make.medium(builder, name, [role], co_name)

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    add_package(builder, 'package1',  role, 'repo1')

    # Add an upstream repository
    # I'm using the build description repository as a base:
    root_repo = builder.build_desc_repo
    # but it would have been just as sensible to use that for 'repo1'
    repo1_1 = root_repo.copy_with_changes('repo1.1')

    repo1 = builder.invocation.db.get_checkout_repo(checkout('repo1'))
    add_upstream_repo(builder, repo1, repo1_1, ('wombat', 'rhubarb'))

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role=role,
                                   rel="", dest="",
                                   domain=None)

    builder.invocation.add_default_role(role) # The 'arm' role is *not* a default role
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
                make_build_desc(d.where, BUILD_DESC.format(repo=repo))

            new_repo('program1', 'repo1')
            new_repo('program1', 'repo1.1')
            new_repo('program1', 'repo1.2')

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
