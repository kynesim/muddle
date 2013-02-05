#! /usr/bin/env python
"""Test romfs deployment support
"""

import os
import shutil
import string
import subprocess
import sys
import getpass
import traceback
from itertools import izip, count

from support_for_tests import *
try:
    import muddled.cmdline
except ImportError:
    # Try one level up
    sys.path.insert(0, get_parent_dir(__file__))
    import muddled.cmdline

from muddled.utils import GiveUp, normalise_dir, LabelType, DirTypeDict
from muddled.withdir import Directory, NewDirectory, TransientDirectory
from muddled.depend import Label, label_list_to_string

DEPLOYMENT_BUILD_DESC_12 = """ \
# A simple build description using romfs deployment
# Taking binaries from role1 and then role2

import muddled
import muddled.pkgs.make
import muddled.deployments.romfs as romfs
import muddled.checkouts.simple

def describe_to(builder):
    role1 = 'role1'
    role2 = 'role2'
    deployment = 'everything'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "first_pkg", [role1], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role2], "second_co")

    romfs.deploy(builder, deployment, 'root.romfs')

    romfs.copy_from_checkout(builder, deployment, 'first_co',
                             'etc/init.d',
                             'etc/init.d')

    romfs.copy_from_package_obj(builder, deployment, 'first_pkg', role1,
                                '',
                                'objfiles')

    # These last will also default to obeying any instructions
    romfs.copy_from_role_install(builder, deployment, role1,
                                 'bin',
                                 'bin')
    romfs.copy_from_role_install(builder, deployment, role2,
                                 'bin',
                                 'bin')

    builder.by_default_deploy(deployment)
"""

MUDDLE_MAKEFILE1 = """\
# Trivial muddle makefile
all:
\t@echo Make all for '$(MUDDLE_LABEL)'
\t$(CC) $(MUDDLE_SRC)/{progname}.c -o $(MUDDLE_OBJ)/{progname}

config:
\t@echo Make configure for '$(MUDDLE_LABEL)'

install:
\t@echo Make install for '$(MUDDLE_LABEL)'
\tmkdir -p $(MUDDLE_INSTALL)/bin
\tcp $(MUDDLE_OBJ)/{progname} $(MUDDLE_INSTALL)/bin
\t$(MUDDLE_INSTRUCT)  $(MUDDLE_SRC)/instructions.xml; \
\tmkdir -p $(MUDDLE_INSTALL)/dev

clean:
\t@echo Make clean for '$(MUDDLE_LABEL)'

distclean:
\t@echo Make distclean for '$(MUDDLE_LABEL)'

.PHONY: all config install clean distclean
"""

MUDDLE_MAKEFILE2 = """\
# Trivial muddle makefile
all:
\t@echo Make all for '$(MUDDLE_LABEL)'
\t$(CC) $(MUDDLE_SRC)/{progname1}.c -o $(MUDDLE_OBJ)/{progname1}
\t$(CC) $(MUDDLE_SRC)/{progname2}.c -o $(MUDDLE_OBJ)/{progname2}

config:
\t@echo Make configure for '$(MUDDLE_LABEL)'

install:
\t@echo Make install for '$(MUDDLE_LABEL)'
\tmkdir -p $(MUDDLE_INSTALL)/bin
\tcp $(MUDDLE_OBJ)/{progname1} $(MUDDLE_INSTALL)/bin
\tcp $(MUDDLE_OBJ)/{progname2} $(MUDDLE_INSTALL)/bin

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
      <root>/</root>
      <spec>.*</spec>
      <all-under />
    </filespec>
    <user>0</user>
    <group>0</group>
  </chown>

  <!-- Certain things *must* be set executable -->
  <chmod>
    <filespec>
    <root>/etc/init.d</root>
      <spec>rcS</spec>
    </filespec>
    <mode>0755</mode>
  </chmod>

  <!-- Traditionally, this is the only device node we *need* -->
  <mknod>
    <name>dev/console</name>
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

def make_old_build_tree():
    """Make a build tree that does a romfs deployment, and use/test it
    """
    with NewDirectory('build.old') as d:
        muddle(['bootstrap', 'git+file:///nowhere', 'cpio-test-build'])

        with Directory('src'):
            with Directory('builds'):
                touch('01.py', DEPLOYMENT_BUILD_DESC_12)

            with NewDirectory('first_co'):
                git('init')
                touch('Makefile.muddle', MUDDLE_MAKEFILE1.format(progname='program1'))
                touch('program1.c', MAIN_C_SRC.format(progname='program1'))
                touch('instructions.xml', INSTRUCTIONS)
                os.makedirs('etc/init.d')
                touch('etc/init.d/rcS', '# A pretend rcS file\n')
                git('add Makefile.muddle program1.c instructions.xml')
                git('commit -m "A commit"')
                muddle(['import'])

            with NewDirectory('second_co'):
                git('init')
                touch('Makefile.muddle', MUDDLE_MAKEFILE2.format(progname1='program1',
                                                                 progname2='program2'))
                touch('program2.c', MAIN_C_SRC.format(progname='program2'))
                # A version of program1 that announces itself as program2
                touch('program1.c', MAIN_C_SRC.format(progname='program2'))
                git('add Makefile.muddle program2.c')
                git('commit -m "A commit"')
                muddle(['import'])

        muddle([])

        with Directory('deploy'):
            with Directory('everything'):
                check_specific_files_in_this_dir(['root.romfs'])

        # We don't have a convenient way of getting at the contents of that
        # image. Thus we're going to assume its existence is enough.
        # Also, since we can't introspect it, we're also going to assume
        # that the order of specifying what to deploy is being obeyed
        # correctly.

def main(args):

    if args:
        print __doc__
        raise GiveUp('Unexpected arguments %s'%' '.join(args))

    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with TransientDirectory(root_dir, keep_on_error=True):
        banner('MAKE OLD BUILD TREE')
        make_old_build_tree()


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
