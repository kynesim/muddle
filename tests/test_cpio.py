#! /usr/bin/env python
"""Test CPIO file support
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

from muddled.utils import GiveUp, normalise_dir, LabelType, DirTypeDict
from muddled.utils import Directory, NewDirectory, TransientDirectory
from muddled.depend import Label, label_list_to_string

TOPLEVEL_BUILD_DESC = """ \
# A simple build description

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.cpio as cpio

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role], "second_co")

    fw = cpio.create(builder, 'firmware.cpio', deployment)
    fw.copy_from_role(role, '', '/')
    fw.done()

    builder.by_default_deploy(deployment)
"""

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
\tif [ -e $(MUDDLE_SRC)/instructions.xml ]; then \
\t  $(MUDDLE_INSTRUCT)  $(MUDDLE_SRC)/instructions.xml; \
\tfi

clean:
\t@echo Make clean for '$(MUDDLE_LABEL)'

distclean:
\t@echo Make distclean for '$(MUDDLE_LABEL)'

.PHONY: all config install clean distclean
"""

INSTRUCTIONS = """\
<?xml version="1.0"?>

<!-- Filesystem for a Linux with busybox - the fiddly bits -->

<instructions>

  <!-- There's something to be said for making all files be owned by
       root (it makes the system look tidier), but on the other hand
       it involves changing *all* files -->
  <chown>
    <filespec>
      <root>/rootfs</root>
      <spec>.*</spec>
      <all-under />
    </filespec>
    <user>0</user>
    <group>0</group>
  </chown>

  <!-- Certain things *must* be set executable -->
  <chmod>
    <filespec>
    <root>/rootfs/etc/init.d</root>
      <spec>rcS</spec>
    </filespec>
    <mode>0755</mode>
  </chmod>

  <!-- Traditionally, this is the only device node we *need* -->
  <mknod>
    <name>rootfs/dev/console</name>
    <uid>0</uid>
    <gid>0</gid>
    <type>char</type>
    <major>5</major>
    <minor>1</minor>
    <mode>0600</mode>
  </mknod>

</instructions>
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

# List content of CPIO archive:
#
#       cpio -it -F <cpio-file>
#       cpio -itv -F <cpio-file>


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



def make_build_tree():
    with NewDirectory('build') as d:
        muddle(['bootstrap', 'git+file:///nowhere', 'cpio-test-build'])

        with Directory('src'):
            with Directory('builds'):
                touch('01.py', TOPLEVEL_BUILD_DESC)

            with NewDirectory('first_co'):
                git('init')
                touch('Makefile.muddle', MUDDLE_MAKEFILE.format(progname='program1'))
                touch('program1.c', MAIN_C_SRC.format(progname='program1'))
                touch('instructions.xml', INSTRUCTIONS)
                git('add Makefile.muddle program1.c instructions.xml')
                git('commit -m "A commit"')
                muddle(['import'])

            with NewDirectory('second_co'):
                git('init')
                touch('Makefile.muddle', MUDDLE_MAKEFILE.format(progname='program2'))
                touch('program2.c', MAIN_C_SRC.format(progname='program2'))
                git('add Makefile.muddle program2.c')
                git('commit -m "A commit"')
                muddle(['import'])

        muddle([])


def main(args):

    if args:
        print __doc__
        raise GiveUp('Unexpected arguments %s'%' '.join(args))

    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with TransientDirectory(root_dir, keep_on_error=True):
        banner('MAKE BUILD TREE')
        make_build_tree()



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
