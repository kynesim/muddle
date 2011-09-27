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

config:
\t@echo Make configure for $(MUDDLE_LABEL)

install:
\t@echo Make install for $(MUDDLE_LABEL)

clean:
\t@echo Make clean for $(MUDDLE_LABEL)

distclean:
\t@echo Make distclean for $(MUDDLE_LABEL)

.PHONY: all config install clean distclean
"""

# You may recognise these example build descriptions from the documentation
SUBDOMAIN_BUILD = """ \
# An example of how to build a cpio archive as a
# deployment - e.g. for a Linux initrd.

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple

def describe_to(builder):
    # Checkout ..
    muddled.checkouts.simple.relative(builder, "cpio_co")
    muddled.pkgs.make.simple(builder, "pkg_cpio", "x86", "cpio_co")
    muddled.deployments.cpio.deploy(builder, "my_archive.cpio",
                                    {"x86": "/"},
                                    "cpio_dep", [ "x86" ])

    builder.invocation.add_default_role("x86")
    builder.by_default_deploy("cpio_dep")
"""

MAIN_BUILD = """ \
# An example of building with a subdomain

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect
from muddled.mechanics import include_domain

def describe_to(builder):
    # Checkout ..
    muddled.checkouts.simple.relative(builder, "cpio_co")
    muddled.pkgs.make.simple(builder, "pkg_cpio", "x86", "cpio_co")

    include_domain(builder,
                   domain_name = "b",
                   domain_repo = "svn+http://muddle.googlecode.com/svn/trunk/muddle/examples/b",
                   domain_desc = "builds/01.py")

    collect.deploy(builder, "everything")
    collect.copy_from_role_install(builder, "everything",
                                   role = "x86",
                                   rel = "", dest = "",
                                   domain = None)
    collect.copy_from_role_install(builder, "everything",
                                   role = "x86",
                                   rel = "", dest = "usr",
                                   domain = "b")

    builder.invocation.add_default_role("x86")
    builder.by_default_deploy("everything")
"""

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

    with TransientDirectory(root_dir, keep_on_error=True):
        banner('SIMPLE SUBDOMAIN')
        test_simple_subdomain()

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
