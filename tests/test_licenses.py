#! /usr/bin/env python
"""Test checkout license support in muddle

Some of this might look suspiciously like it was copied from (a version of)
test_distribute.py. There's a reason for that.

Much of it could doubtless be done more efficiently.
"""

import os
import shutil
import string
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

from muddled.utils import GiveUp, normalise_dir, LabelType, LabelTag, DirTypeDict
from muddled.utils import Directory, NewDirectory, TransientDirectory
from muddled.depend import Label, label_list_to_string
from muddled.version_stamp import VersionStamp

from muddled.distribute import standard_licenses

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

TOPLEVEL_BUILD_DESC = """ \
# Our build description

import os

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect
from muddled.mechanics import include_domain
from muddled.depend import Label
from muddled.utils import LabelType, LabelTag
from muddled.repository import Repository
from muddled.version_control import checkout_from_repo

from muddled.distribute import distribute_checkout, distribute_package, \
        set_license, LicenseBinary, LicenseSecret

def add_package(builder, name, role, license=None, co_name=None, deps=None):
    if not co_name:
        co_name = name
    muddled.pkgs.make.medium(builder, name, [role], co_name, deps=deps)

    if license:
        co_label = Label(LabelType.Checkout, co_name)
        set_license(builder, co_label, license)

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    add_package(builder, 'apache', 'x86', 'apache')
    add_package(builder, 'bsd',    'x86', 'bsd-new')
    add_package(builder, 'gpl2',   'x86', 'gpl2')
    add_package(builder, 'gpl2plus', 'x86', 'gpl2plus')
    add_package(builder, 'gpl3',  'x86', 'gpl3')
    add_package(builder, 'lgpl',  'x86', 'lgpl')
    add_package(builder, 'mpl',   'x86', 'mpl')
    add_package(builder, 'ukogl', 'x86', 'ukogl')
    add_package(builder, 'zlib',  'x86', 'zlib')

    add_package(builder, 'gnulibc', 'x86', 'lgpl-except')
    add_package(builder, 'linux', 'x86', 'gpl2-except')
    add_package(builder, 'busybox', 'x86', 'gpl2')      # is it a link-exception?

    add_package(builder, 'binary1', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary2', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary3', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary4', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary5', 'x86', LicenseBinary('Customer'))

    add_package(builder, 'secret1', 'x86', LicenseSecret('Shh'))
    add_package(builder, 'secret2', 'x86', LicenseSecret('Shh'))
    add_package(builder, 'secret3', 'x86', LicenseSecret('Shh'))
    add_package(builder, 'secret4', 'x86', LicenseSecret('Shh'))
    add_package(builder, 'secret5', 'x86', LicenseSecret('Shh'))

    add_package(builder, 'unlicensed1', 'x86', deps=['gpl2'])
    add_package(builder, 'unlicensed2', 'x86')
    add_package(builder, 'unlicensed3', 'x86')
    add_package(builder, 'unlicensed4', 'x86')
    add_package(builder, 'unlicensed5', 'x86')

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role = role,
                                   rel = "", dest = "",
                                   domain = None)

    # The 'arm' role is *not* a default role
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

def test_equalities():
    assert standard_licenses['mpl'] == standard_licenses['mpl1_1']
    assert standard_licenses['gpl2'] != standard_licenses['gpl2-except']

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

def make_repos_with_subdomain(root_dir):
    """Create git repositories for our tests.

    I'm going to start by naming them after licenses...
    """

    def new_repo(name):
        with NewDirectory(name) as d:
            make_standard_checkout(d.where, name, name)

    repo = os.path.join(root_dir, 'repo')
    with NewDirectory('repo'):
        with NewDirectory('main'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, TOPLEVEL_BUILD_DESC.format(repo=repo))

            new_repo('apache')
            new_repo('bsd')
            new_repo('gpl2')
            new_repo('gpl2plus')
            new_repo('gpl3')
            new_repo('lgpl')
            new_repo('mpl')
            new_repo('ukogl')
            new_repo('zlib')

            new_repo('gnulibc')
            new_repo('linux')
            new_repo('busybox')

            new_repo('binary1')
            new_repo('binary2')
            new_repo('binary3')
            new_repo('binary4')
            new_repo('binary5')

            new_repo('secret1')
            new_repo('secret2')
            new_repo('secret3')
            new_repo('secret4')
            new_repo('secret5')

            new_repo('unlicensed1')
            new_repo('unlicensed2')
            new_repo('unlicensed3')
            new_repo('unlicensed4')
            new_repo('unlicensed5')

def actual_tests(root_dir, d):
    """Perform the actual tests.
    """
    banner('STUFF')
    muddle(['query', 'checkout-licenses'])

def main(args):

    # Working in a local transient directory seems to work OK
    # although if it's anyone other than me they might prefer
    # somewhere in $TMPDIR...
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    if args == ['-just']:
        with Directory(root_dir):
            with Directory('build') as d:
                actual_tests(root_dir, d)
        return

    elif args:
        print __doc__
        raise GiveUp('Unexpected arguments %s'%' '.join(args))

    # Some basic assertions
    test_equalities()

    #with TransientDirectory(root_dir):     # XXX
    with NewDirectory(root_dir) as root:

        banner('MAKE REPOSITORIES')
        make_repos_with_subdomain(root_dir)

        with NewDirectory('build') as d:
            banner('CHECK REPOSITORIES OUT')
            muddle(['init', 'git+file://{repo}/main'.format(repo=root.join('repo')),
                    'builds/01.py'])
            muddle(['checkout', '_all'])
            banner('BUILD')
            muddle([])
            banner('STAMP VERSION')
            muddle(['stamp', 'version'])

            actual_tests(root_dir, d)

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
