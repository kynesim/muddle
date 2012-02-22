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

from difflib import unified_diff

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
    add_package(builder, 'ukogl', 'x86', 'ukogl', deps=['lgpl'])
    add_package(builder, 'zlib',  'x86', 'zlib')

    add_package(builder, 'gnulibc', 'x86', 'lgpl-except')
    add_package(builder, 'linux', 'x86', 'gpl2-except')
    add_package(builder, 'busybox', 'x86', 'gpl2')

    add_package(builder, 'binary1', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary2', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary3', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary4', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary5', 'x86', LicenseBinary('Customer'))

    add_package(builder, 'secret1', 'x86', LicenseSecret('Shh'), deps=['gnulibc'])
    add_package(builder, 'secret2', 'x86', LicenseSecret('Shh'), deps=['gnulibc', 'gpl2plus'])
    add_package(builder, 'secret3', 'x86', LicenseSecret('Shh'), deps=['secret2'])
    add_package(builder, 'secret4', 'x86', LicenseSecret('Shh'), deps=['secret2', 'gpl2'])
    add_package(builder, 'secret5', 'x86', LicenseSecret('Shh'))

    add_package(builder, 'not_licensed1', 'x86', deps=['gpl2', 'gpl3'])
    add_package(builder, 'not_licensed2', 'x86')
    add_package(builder, 'not_licensed3', 'x86')
    add_package(builder, 'not_licensed4', 'x86')
    add_package(builder, 'not_licensed5', 'x86')

    builder.invocation.db.set_not_built_against(Label.from_string('package:secret2{{x86}}/*'),
                                                Label.from_string('checkout:gpl2plus/*'))

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

            new_repo('not_licensed1')
            new_repo('not_licensed2')
            new_repo('not_licensed3')
            new_repo('not_licensed4')
            new_repo('not_licensed5')

def check_text(actual, wanted):
    if actual == wanted:
        return

    actual_lines = actual.splitlines(True)
    wanted_lines = wanted.splitlines(True)
    for line in unified_diff(wanted_lines, actual_lines, fromfile='Expected', tofile='Got'):
        sys.stdout.write(line)

def actual_tests(root_dir, d):
    """Perform the actual tests.
    """
    banner('STUFF')
    text = captured_muddle(['query', 'checkout-licenses'])
    check_text(text, """\
> Checkout licenses ..
checkout:apache/*   -> LicenseOpen('Apache')
checkout:binary1/*  -> LicenseBinary('Customer')
checkout:binary2/*  -> LicenseBinary('Customer')
checkout:binary3/*  -> LicenseBinary('Customer')
checkout:binary4/*  -> LicenseBinary('Customer')
checkout:binary5/*  -> LicenseBinary('Customer')
checkout:bsd/*      -> LicenseOpen('BSD 3-clause')
checkout:busybox/*  -> LicenseGPL('GPL v2')
checkout:gnulibc/*  -> LicenseLGPL('LGPL', with_exception=True)
checkout:gpl2/*     -> LicenseGPL('GPL v2')
checkout:gpl2plus/* -> LicenseGPL('GPL v2 and above')
checkout:gpl3/*     -> LicenseGPL('GPL v3')
checkout:lgpl/*     -> LicenseLGPL('LGPL')
checkout:linux/*    -> LicenseGPL('GPL v2', with_exception=True)
checkout:mpl/*      -> LicenseOpen('MPL 1.1')
checkout:secret1/*  -> LicenseSecret('Shh')
checkout:secret2/*  -> LicenseSecret('Shh')
checkout:secret3/*  -> LicenseSecret('Shh')
checkout:secret4/*  -> LicenseSecret('Shh')
checkout:secret5/*  -> LicenseSecret('Shh')
checkout:ukogl/*    -> LicenseOpen('UK Open Government License')
checkout:zlib/*     -> LicenseOpen('zlib')

The following checkouts do not have a license:
  checkout:builds/*
  checkout:not_licensed1/*
  checkout:not_licensed2/*
  checkout:not_licensed3/*
  checkout:not_licensed4/*
  checkout:not_licensed5/*

The following checkouts have some sort of GPL license:
  checkout:busybox/*  -> LicenseGPL('GPL v2')
  checkout:gnulibc/*  -> LicenseLGPL('LGPL', with_exception=True)
  checkout:gpl2/*     -> LicenseGPL('GPL v2')
  checkout:gpl2plus/* -> LicenseGPL('GPL v2 and above')
  checkout:gpl3/*     -> LicenseGPL('GPL v3')
  checkout:lgpl/*     -> LicenseLGPL('LGPL')
  checkout:linux/*    -> LicenseGPL('GPL v2', with_exception=True)

The following are then "implicitly" GPL licensed:
  checkout:not_licensed1/* -> '<no license>'
                              because package:not_licensed1{x86}/* depends on checkout:gpl2/*
                                      package:not_licensed1{x86}/* depends on checkout:gpl3/*
  checkout:secret3/*       -> LicenseSecret('Shh')
                              because package:secret3{x86}/* depends on checkout:gpl2plus/*
  checkout:ukogl/*         -> LicenseOpen('UK Open Government License')
                              because package:ukogl{x86}/* depends on checkout:lgpl/*

Exceptions are:
  package:secret2{x86}/* not built against checkout:gpl2plus/*

Clashes between GPL-propagation and "secret" licenses are:
  checkout:secret3/*       -> LicenseSecret('Shh')
""")

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
