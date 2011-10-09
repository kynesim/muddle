#! /usr/bin/env python
"""Test domain support, and anything that might be affected by it.
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

# You may recognise these example build descriptions from the documentation
SIMPLE_BUILD_DESC = """ \
# A simple build description

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep

def describe_to(builder):
    role = 'x86'

    muddled.checkouts.simple.relative(builder, "main_co")
    muddled.pkgs.make.simple(builder, "main_pkg", role, "main_co")

    # The 'main_dep' deployment is built from our single role, and goes
    # into deploy/main_dep.
    muddled.deployments.filedep.deploy(builder, "", "main_dep", [role])

    # If no role is specified, assume this one
    builder.invocation.add_default_role(role)
    # muddle at the top level will default to building this deployment
    builder.by_default_deploy("main_dep")
"""

MAIN_BUILD_DESC = """ \
# A build description that includes a subdomain

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect
from muddled.mechanics import include_domain

def describe_to(builder):
    # Checkout ..
    muddled.checkouts.simple.relative(builder, "main_co")
    muddled.pkgs.make.simple(builder, "main_pkg", "x86", "main_co")

    include_domain(builder,
                   domain_name = "subdomain1",
                   domain_repo = "git+file://{rootpath}/subdomain1",
                   domain_desc = "builds/01.py")

    collect.deploy(builder, "everything")
    collect.copy_from_role_install(builder, "everything",
                                   role = "x86",
                                   rel = "", dest = "",
                                   domain = None)
    collect.copy_from_role_install(builder, "everything",
                                   role = "x86",
                                   rel = "", dest = "usr",
                                   domain = "subdomain1")

    builder.invocation.add_default_role("x86")
    builder.by_default_deploy("everything")
"""

MAIN_C_SRC = """\
// Simple example C source code
#include <stdio.h>
int main(int argc, char **argv)
{{
    printf("Program {progname}\\n");
}}
"""

def make_repos_with_subdomain(rootpath):
    """Create git repositories for our subdomain tests.
    """
    with NewDirectory('repo'):
        with NewDirectory('main'):
            with NewDirectory('builds'):
                git('init')
                touch('01.py', MAIN_BUILD_DESC.format(rootpath=rootpath))
                git('add 01.py')
                git('commit -a -m "Commit main build desc"')
            with NewDirectory('main_co'):
                progname = 'main1'
                git('init')
                touch('{progname}.c'.format(progname=progname),
                        MAIN_C_SRC.format(progname=progname))
                touch('Makefile.muddle', MUDDLE_MAKEFILE.format(progname=progname))
                git('add {progname}.c Makefile.muddle'.format(progname=progname))
                git('commit -a -m "Commit main checkout 1"')
        with NewDirectory('subdomain1'):
            with NewDirectory('builds'):
                git('init')
                touch('01.py', SIMPLE_BUILD_DESC)
                git('add 01.py')
                git('commit -a -m "Commit subdomain1 build desc"')
            with NewDirectory('main_co'):
                progname = 'subdomain1'
                git('init')
                touch('{progname}.c'.format(progname=progname),
                        MAIN_C_SRC.format(progname=progname))
                touch('Makefile.muddle', MUDDLE_MAKEFILE.format(progname=progname))
                git('add {progname}.c Makefile.muddle'.format(progname=progname))
                git('commit -a -m "Commit subdomain 1 checkout 1"')

def check_repos_out(rootpath):

    with NewDirectory('build'):
        muddle(['init', 'git+file://{rootpath}/main'.format(rootpath=rootpath),
            'builds/01.py'])
        muddle([])

def main(args):

    if args:
        print __doc__
        raise GiveUp('Unexpected arguments %s'%' '.join(args))

    # Working in a local transient directory seems to work OK
    # although if it's anyone other than me they might prefer
    # somewhere in $TMPDIR...
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with NewDirectory(root_dir):
        rootpath = os.path.join(root_dir, 'repo')
        banner('MAKE REPOSITORIES')
        make_repos_with_subdomain(rootpath)

        banner('CHECK REPOSITORIES OUT')
        check_repos_out(rootpath)

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
