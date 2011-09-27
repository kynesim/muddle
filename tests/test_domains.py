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

def main(args):

    if not args or len(args) > 1:
        print __doc__
        return

    print 'args:', args


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
