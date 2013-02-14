#! /usr/bin/env python
"""Test CPIO file support

    $ ./test_deploy_cpio.py [-keep]

With -keep, do not delete the 'transient' directory used for the tests.
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

DEPLOYMENT_BUILD_DESC = """ \
# A simple build description using deployment of a CPIO file

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.cpio as cpio

def describe_to(builder):
    role1 = 'role1'
    role2 = 'role2'
    deployment = 'everything'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "first_pkg", [role1], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role2], "second_co")

    fw = cpio.create(builder, 'firmware.cpio', deployment)
    fw.copy_from_role(role1, '', '/')
    fw.copy_from_role(role2, '', '/')
    fw.done()

    builder.by_default_deploy(deployment)
"""

PACKAGE_BUILD_DESC_12 = """ \
# A simple build description using a package with a CPIO file in it
# It copies from role1, then from role2

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.cpio as cpio
from muddled.depend import package

def describe_to(builder):
    role1 = 'role1'
    role2 = 'role2'
    cpio_role = 'x86-cpiofile'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "first_pkg", [role1], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role2], "second_co")

    # This should implicitly create the specified package label in our
    # dependency tree
    fw = cpio.create(builder, 'fred/firmware.cpio', package('firmware', cpio_role))
    fw.copy_from_role(role1, '', '/')
    fw.copy_from_role(role2, '', '/')
    fw.done()

    builder.add_default_role(cpio_role)
"""

PACKAGE_BUILD_DESC_21 = """ \
# A simple build description using a package with a CPIO file in it
# It copies from role2, then from role1

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.cpio as cpio
from muddled.depend import package

def describe_to(builder):
    role1 = 'role1'
    role2 = 'role2'
    cpio_role = 'x86-cpiofile'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "first_pkg", [role1], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role2], "second_co")

    # This should implicitly create the specified package label in our
    # dependency tree
    fw = cpio.create(builder, 'fred/firmware.cpio', package('firmware', cpio_role))
    fw.copy_from_role(role2, '', '/')
    fw.copy_from_role(role1, '', '/')
    fw.done()

    builder.add_default_role(cpio_role)
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
\tmkdir -p $(MUDDLE_INSTALL)/etc/init.d
\ttouch $(MUDDLE_INSTALL)/etc/init.d/rcS

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

def check_cpio_archive(archive):
    text = get_stdout("cpio -itv -F '%s'"%archive)

    # The output should look something like:
    #
    # drwxr-xr-x   5 tibs     staff           0 Jan 27 15:48 /
    # drwxr-xr-x   3 root     wheel           0 Jan 27 15:48 /etc
    # drwxr-xr-x   3 root     wheel           0 Jan 27 15:48 /etc/init.d
    # -rwxr-xr-x   1 root     wheel           0 Jan 27 15:48 /etc/init.d/rcS
    # drwxr-xr-x   4 root     wheel           0 Jan 27 15:48 /bin
    # -rwxr-xr-x   1 root     wheel        8696 Jan 27 15:48 /bin/program1
    # -rwxr-xr-x   1 root     wheel        8696 Jan 27 15:48 /bin/program2
    # drwxr-xr-x   2 root     wheel           0 Jan 27 15:48 /dev
    # crw-------   1 root     wheel         5,1 Jan 27 15:48 /dev/console
    #
    # but we don't expect the username (tibs) or the group names (staff/wheel)
    # or the date/time to be the same.
    #
    # So we're basically checking that the first, third and last columns match.
    # And we don't need to store the third column, as we can determine it
    expected = [ ('drwxr-xr-x', '/'),
                 ('drwxr-xr-x', '/etc'),
                 ('drwxr-xr-x', '/etc/init.d'),
                 ('-rwxr-xr-x', '/etc/init.d/rcS'),
                 ('drwxr-xr-x', '/bin'),
                 ('-rwxr-xr-x', '/bin/program1'),
                 ('-rwxr-xr-x', '/bin/program2'),
                 ('drwxr-xr-x', '/dev'),
                 ('crw-------', '/dev/console'),
               ]
    lines = text.splitlines()
    if len(lines) != len(expected):
        print '---------------------------- EXPECTED'
        print '\n'.join(expected)
        print '---------------------------- GOT'
        print '\n'.join(lines)
        print '----------------------------'
        raise GiveUp('Expected %d lines, got %d lines of CPIO data'%(len(expected), len(lines)))

    for n, got, expect in izip(count(), lines, expected):
        parts = got.split()
        prot = parts[0]
        owner = parts[2]
        file = parts[-1]

        if prot != expect[0]:
            raise GiveUp('Protection %d does not match: got %s, wanted %s'%(n, prot, expect[0]))

        if n==0:
            wanted_owner = getpass.getuser()
        else:
            wanted_owner = 'root'
        if owner != wanted_owner:
            raise GiveUp('Owner %d does not match: got %s, wanted %s'%(n, owner, wanted_owner))

        if file != expect[1]:
            raise GiveUp('Filename %d does not match: got %s, wanted %s'%(n, file, expect[1]))

    print
    print 'CPIO archive %s appears to have the correct contents'%archive

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
    """Make a build tree that deploys a CPIO file, and use/test it
    """
    with NewDirectory('build.old') as d:
        muddle(['bootstrap', 'git+file:///nowhere', 'cpio-test-build'])

        with Directory('src'):
            with Directory('builds'):
                touch('01.py', DEPLOYMENT_BUILD_DESC)
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')

            with NewDirectory('first_co'):
                git('init')
                touch('Makefile.muddle', MUDDLE_MAKEFILE1.format(progname='program1'))
                touch('program1.c', MAIN_C_SRC.format(progname='program1'))
                touch('instructions.xml', INSTRUCTIONS)
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
                check_cpio_archive('firmware.cpio')

                # Check we got the correct version of program1
                extract_file('firmware.cpio', '/bin/program1')
                text = get_stdout('bin/program1')
                if text != 'Program program2\n':
                    raise GiveUp('Expected the program1 from role2, but it output %s'%text)
                print 'That looks like the correct program1'

def extract_file(cpio_archive, filepath):
    """Extract a single file from our CPIO archive.
    """
    # GNU cpio has --no-absolute-pathname, but BSD cpio does not
    # BSD tar can read from CPIO archives, but GNU tar cannot
    try:
        # Try for GNU cpio
        if filepath[0] == '/':
            path = filepath[1:]
        else:
            path = filepath
        shell('cpio -idvm --no-absolute-filenames -F %s %s'%(cpio_archive, path))
        return
    except ShellError as e:
        # Otherwise, try for BSD tar
        shell('tar -f %s -x -v %s'%(cpio_archive, filepath))

def make_new_build_tree():
    """Make a build tree that creates a CPIO file in a package, and use/test it
    """
    with NewDirectory('build.new') as d:
        muddle(['bootstrap', 'git+file:///nowhere', 'cpio-test-build'])

        with Directory('src'):
            with Directory('builds'):
                touch('01.py', PACKAGE_BUILD_DESC_12)
                # Then remove the .pyc file, because Python probably won't realise
                # that this new 01.py is later than the previous version
                os.remove('01.pyc')

            with NewDirectory('first_co'):
                git('init')
                touch('Makefile.muddle', MUDDLE_MAKEFILE1.format(progname='program1'))
                touch('program1.c', MAIN_C_SRC.format(progname='program1'))
                touch('instructions.xml', INSTRUCTIONS)
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

        # Magically, we have package output with no corresponding checkout.

        with Directory('install'):
            with Directory('x86-cpiofile'):
                with Directory('fred'):
                    check_cpio_archive('firmware.cpio')

                    # Check we got the correct version of program1
                    extract_file('firmware.cpio', '/bin/program1')

                    text = get_stdout('bin/program1')
                    if text != 'Program program2\n':
                        raise GiveUp('Expected the program1 from role2, but it output %s'%text)
                    print 'That looks like the correct program1'

        # Now let's try requesting the roles in the other order
        with Directory('src'):
            with Directory('builds'):
                touch('01.py', PACKAGE_BUILD_DESC_21)
                # Then remove the .pyc file, because Python probably won't
                # realise that this new 01.py is later than the previous
                # version
                os.remove('01.pyc')

        muddle(['veryclean'])
        muddle([])

        with Directory('install'):
            with Directory('x86-cpiofile'):
                with Directory('fred'):
                    check_cpio_archive('firmware.cpio')

                    # Check we got the other version of program1
                    extract_file('firmware.cpio', '/bin/program1')
                    text = get_stdout('bin/program1')
                    if text != 'Program program1\n':
                        raise GiveUp('Expected the program1 from role1, but it output %s'%text)
                    print 'That looks like the correct program1'

def main(args):

    keep = False
    if args:
        if len(args) == 1 and args[0] == '-keep':
            keep = True
        else:
            print __doc__
            return

    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with TransientDirectory(root_dir, keep_on_error=True, keep_anyway=keep):
        banner('MAKE OLD BUILD TREE')
        make_old_build_tree()

        banner('MAKE NEW BUILD TREE')
        make_new_build_tree()



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
