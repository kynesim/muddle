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
\t@echo Make all for $(MUDDLE_LABEL)
\t$(CC) $(MUDDLE_SRC)/{progname}.c -o $(MUDDLE_OBJ)/{progname}

config:
\t@echo Make configure for $(MUDDLE_LABEL)

install:
\t@echo Make install for $(MUDDLE_LABEL)
\tcp $(MUDDLE_OBJ)/{progname} $(MUDDLE_INSTALL)

clean:
\t@echo Make clean for $(MUDDLE_LABEL)

distclean:
\t@echo Make distclean for $(MUDDLE_LABEL)

.PHONY: all config install clean distclean
"""

# You may recognise these example build descriptions from the documentation
SUBDOMAIN_BUILD_DESC = """ \
# A simple subdomain

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple

def describe_to(builder):
    # Checkout ..
    muddled.checkouts.simple.relative(builder, "subdomain1_co1")
    muddled.pkgs.make.simple(builder, "main", "x86", "main_co1")
    muddled.deployments.cpio.deploy(builder, "my_archive.cpio",
                                    {"x86": "/"},
                                    "main_dep", [ "x86" ])

    builder.invocation.add_default_role("x86")
    builder.by_default_deploy("main_dep")
"""

MAIN_BUILD_DESC = """ \
# An example of building with a subdomain

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect
from muddled.mechanics import include_domain

def describe_to(builder):
    # Checkout ..
    muddled.checkouts.simple.relative(builder, "main_co1")
    muddled.pkgs.make.simple(builder, "main", "x86", "main_co1")

    include_domain(builder,
                   domain_name = "subdomain1",
                   domain_repo = "git+file://{rootpath}/subdomain1/builds",
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
{
    printf("Program %s\n", argv[0]);
}
"""

def make_repos_with_subdomain(this_dir):
    """Create git repositories for our subdomain tests.
    """
    rootpath = os.path.join(this_dir, 'repo')
    with NewDirectory('repo'):
        with NewDirectory('main'):
            with NewDirectory('builds'):
                git('init')
                touch('01.py', MAIN_BUILD_DESC.format(rootpath=rootpath))
                git('add 01.py')
                git('commit -a -m "Commit main build desc"')
            with NewDirectory('main_co1'):
                progname = 'main1'
                git('init')
                touch('{progname}.c'.format(progname=progname), MAIN_C_SRC)
                touch('Makefile.muddle', MUDDLE_MAKEFILE.format(progname=progname))
                git('add {progname}.c Makefile.muddle'.format(progname=progname))
                git('commit -a -m "Commit main checkout 1"')
        with NewDirectory('subdomain1'):
            with NewDirectory('builds'):
                git('init')
                touch('01.py', SUBDOMAIN_BUILD_DESC)
                git('add 01.py')
                git('commit -a -m "Commit subdomain1 build desc"')
            with NewDirectory('main_co1'):
                progname = 'subdomain1'
                git('init')
                touch('{progname}.c'.format(progname=progname), MAIN_C_SRC)
                touch('Makefile.muddle', MUDDLE_MAKEFILE.format(progname=progname))
                git('add {progname}.c Makefile.muddle'.format(progname=progname))
                git('commit -a -m "Commit subdomain 1 checkout 1"')


def test_simple_subdomain():
    """Bootstrap a muddle build tree.
    """

    # We're not going to make any attempt to have a real repository
    # but we will "pretend" to use bzr, so I don't accidentally write
    # code that tracks up to find the muddle .git directory, and alter
    # that (muddle import, I'm looking at you...)
    root_repo = 'bzr+ssh://tibs@somewhere.over.the.rainbow/repository/'
    with NewDirectory('test_build1'):
        banner('Bootstrapping subdomain build')

        # We need to create the subdomain first, because if we run
        # 'muddle' with the top level build description in place,
        # and muddle doesn't think we've got the subdomain, it will
        # try to obey the top level build description and check the
        # subdomain out. And that won't work (in various ways)
        with NewDirectory('domains'):
            with NewDirectory('b'):
                # We don't need to say "boostrap -subdomain" because
                # we aren't yet within a build tree
                muddle(['bootstrap', root_repo, 'test_subdomain_build'])

                with Directory('src/builds'):
                    os.remove('01.py')
                    touch('01.py', SUBDOMAIN_BUILD)

                with NewDirectory('src/cpio_co'):
                    touch('Makefile.muddle', MUDDLE_MAKEFILE)

        # And now we can safely create our top level build
        muddle(['bootstrap', root_repo, 'test_build'])

        with Directory('src/builds'):
            os.remove('01.py')
            touch('01.py', MAIN_BUILD)

        with NewDirectory('src/cpio_co'):
            touch('Makefile.muddle', MUDDLE_MAKEFILE)

        # Pretend we've actually checked out our checkouts
        # This one is actually a subtle test that we can specify
        # subdomains in checkouts at the command line
        muddle(['import', '(b)cpio_co'])
        muddle(['import', 'cpio_co'])

def main(args):

    if args:
        print __doc__
        raise GiveUp('Unexpected arguments %s'%' '.join(args))

    # Working in a local transient directory seems to work OK
    # although if it's anyone other than me they might prefer
    # somewhere in $TMPDIR...
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    if False:
        with TransientDirectory(root_dir, keep_on_error=True):
            banner('SIMPLE SUBDOMAIN')
            test_simple_subdomain()
    else:
        # Initial testing of our tests
        with NewDirectory(root_dir):
            banner('REPOSITORIES WITH SUBDOMAIN')
            make_repos_with_subdomain(root_dir)

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
