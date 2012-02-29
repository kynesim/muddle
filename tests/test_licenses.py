#! /usr/bin/env python
"""Test checkout license support in muddle

Some of this might look suspiciously like it was copied from (a version of)
test_distribute.py. There's a reason for that.

Much of it could doubtless be done more efficiently.

We do assume that test_distribute has succeeded, and thus we assume that
"muddle -n distribute ..." will give an accurate idea of what would actually
be distributed.
"""

import os
import shutil
import string
import subprocess
import sys
import traceback

from difflib import unified_diff

from support_for_tests import *
try:
    import muddled.cmdline
except ImportError:
    # Try one level up
    sys.path.insert(0, get_parent_file(__file__))
    import muddled.cmdline

from muddled.utils import GiveUp, normalise_dir, LabelType, LabelTag
from muddled.utils import Directory, NewDirectory, TransientDirectory
#from muddled.depend import Label, label_list_to_string
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

MULTILICENSE_BUILD_DESC_WITH_CLASHES = """ \
# A build description with all sorts of licenses, and even a subdomain
# The install/ directory gets secret and non-secret stuff installed to
# role x86, i.e., we have clashes

import os

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect

from muddled.mechanics import include_domain
from muddled.depend import checkout, package
from muddled.repository import Repository
from muddled.version_control import checkout_from_repo

from muddled.distribute import distribute_checkout, distribute_package
from muddled.licenses import set_license, LicenseBinary, LicenseSecret

def add_package(builder, name, role, license=None, co_name=None, deps=None):
    if not co_name:
        co_name = name
    muddled.pkgs.make.medium(builder, name, [role], co_name, deps=deps)

    if license:
        co_label = checkout(co_name)
        set_license(builder, co_label, license)

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    another_license = LicenseSecret('ignore-this')

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

    builder.invocation.db.set_not_built_against(package('secret2', 'x86'),
                                                checkout('gpl2plus'))

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role = role,
                                   rel = "", dest = "",
                                   domain = None)

    # We have a subdomain.
    include_domain(builder,
                   domain_name = "subdomain",
                   domain_repo = "git+file://{repo}/subdomain",
                   domain_desc = "builds/01.py")

    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub',
                                 domain='subdomain')

    # The 'arm' role is *not* a default role
    builder.invocation.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

MULTILICENSE_BUILD_DESC = """ \
# A build description with all sorts of licenses, and even a subdomain
# "Secret" stuff is segregated to a different role, and is described in
# a different file

import os

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect

from muddled.mechanics import include_domain
from muddled.depend import checkout, package
from muddled.repository import Repository
from muddled.version_control import checkout_from_repo

from muddled.distribute import distribute_checkout, distribute_package, \
        get_distributions_not_for, set_secret_build_files, name_distribution
from muddled.licenses import set_license, LicenseBinary, LicenseSecret, \
        get_open_not_gpl_checkouts, get_binary_checkouts, get_secret_checkouts, \
        get_license

# Our secret information
from secret import describe_secret

def add_package(builder, name, role, license=None, co_name=None, deps=None):
    if not co_name:
        co_name = name
    muddled.pkgs.make.medium(builder, name, [role], co_name, deps=deps)

    if license:
        co_label = checkout(co_name)
        set_license(builder, co_label, license)

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    another_license = LicenseSecret('ignore-this')

    add_package(builder, 'apache', role, 'apache')
    add_package(builder, 'bsd',    role, 'bsd-new')
    add_package(builder, 'gpl2',   role, 'gpl2')
    add_package(builder, 'gpl2plus', role, 'gpl2plus')
    add_package(builder, 'gpl3',  role, 'gpl3')
    add_package(builder, 'lgpl',  role, 'lgpl')
    add_package(builder, 'mpl',   role, 'mpl')
    add_package(builder, 'ukogl', role, 'ukogl', deps=['lgpl'])
    add_package(builder, 'zlib',  role, 'zlib')

    add_package(builder, 'gnulibc', role, 'lgpl-except')
    add_package(builder, 'linux', role, 'gpl2-except')
    add_package(builder, 'busybox', role, 'gpl2')

    add_package(builder, 'binary1', role, LicenseBinary('Customer'), deps=['zlib'])
    add_package(builder, 'binary2', role, LicenseBinary('Customer'))
    add_package(builder, 'binary3', role, LicenseBinary('Customer'))
    add_package(builder, 'binary4', role, LicenseBinary('Customer'))
    add_package(builder, 'binary5', role, LicenseBinary('Customer'))

    add_package(builder, 'not_licensed1', role, deps=['gpl2', 'gpl3'])
    add_package(builder, 'not_licensed2', role)
    add_package(builder, 'not_licensed3', role)
    add_package(builder, 'not_licensed4', role)
    add_package(builder, 'not_licensed5', role)

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role=role,
                                   rel="", dest="",
                                   domain=None)

    # We also have some secret stuff, described elsewhere
    describe_secret(builder, deployment=deployment)

    # So that "elsewhere" is secret - i.e., secret.py
    # and we should never distribute it in non-secret distributions
    for name in get_distributions_not_for(builder, ['secret']):
        set_secret_build_files(builder, name, ['secret.py'])

    # We have a subdomain.
    include_domain(builder,
                   domain_name = "subdomain",
                   domain_repo = "git+file://{repo}/subdomain",
                   domain_desc = "builds/01.py")

    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub',
                                 domain='subdomain')

    builder.invocation.add_default_role(role) # The 'arm' role is *not* a default role
    builder.by_default_deploy(deployment)

    # Let's have some distributions of our own
    # We rely on being at the end of the build description, so that all
    # of our checkout labels have been defined for us

    # This is an odd one - anything that is in 'open' (but not 'gpl'),
    # and we shall distribute both the checkout source and the package binary
    # NOTE that this means we will distribute everything in install/x86, because
    # we have no way of knowing (at distribute time) what came from where. If we
    # did care, we'd need to put things into different roles according to their
    # license (as we do for x86-secret)
    name_distribution(builder, 'just_open_src_and_bin', ['open']) # so, no 'gpl'
    for co_label in get_open_not_gpl_checkouts(builder):
        distribute_checkout(builder, 'just_open_src_and_bin', co_label)
        # Get the package(s) directly using this checkout
        pkg_labels = builder.invocation.packages_using_checkout(co_label)
        for label in pkg_labels:
            distribute_package(builder, 'just_open_src_and_bin', label)
    # And we mustn't forget to add this new distribution to our
    # "don't propagate secret.py" as well, since it hadn't been
    # declared yet when we did this earlier...
    set_secret_build_files(builder, 'just_open_src_and_bin', ['secret.py'])

    name_distribution(builder, 'binary_and_secret_source', ['binary', 'secret'])
    for co_label in get_binary_checkouts(builder):
        distribute_checkout(builder, 'binary_and_secret_source', co_label)
    for co_label in get_secret_checkouts(builder):
        distribute_checkout(builder, 'binary_and_secret_source', co_label)

    name_distribution(builder, 'binary_and_secret_install', ['binary', 'secret'])
    for co_label in get_binary_checkouts(builder):
        # Get the package(s) directly using this checkout
        pkg_labels = builder.invocation.packages_using_checkout(co_label)
        for label in pkg_labels:
            distribute_package(builder, 'binary_and_secret_install', label)
    for co_label in get_secret_checkouts(builder):
        pkg_labels = builder.invocation.packages_using_checkout(co_label)
        for label in pkg_labels:
            distribute_package(builder, 'binary_and_secret_install', label)
"""

SECRET_BUILD_FILE = """\
# The part of a build dealing with "secret" licensed stuff

import muddled.deployments.collect as collect
import muddled.pkg as pkg
import muddled.pkgs.make as make

from muddled import pkgs
from muddled.depend import checkout, package
from muddled.licenses import LicenseSecret, set_license, set_not_built_against

# Really, this should be in another Python file, since we're using it from
# two places. But for the moment this wil do.
def add_package(builder, name, role, license=None, co_name=None, dep_tuples=None):
    if not co_name:
        co_name = name
    make.medium(builder, name, [role], co_name)

    if dep_tuples:
        for other_name, other_role in dep_tuples:
            pkg.do_depend(builder, name, [role], [( other_name , other_role )])

    if license:
        co_label = checkout(co_name)
        set_license(builder, co_label, license)

def describe_secret(builder, *args, **kwargs):
    # Secret packages

    deployment = kwargs['deployment']

    add_package(builder, 'secret1', 'x86-secret', LicenseSecret('Shh'),
                dep_tuples=[('gnulibc', 'x86')])
    add_package(builder, 'secret2', 'x86-secret', LicenseSecret('Shh'),
                dep_tuples=[('gnulibc', 'x86'),
                            ('gpl2plus', 'x86')])
    add_package(builder, 'secret3', 'x86-secret', LicenseSecret('Shh'),
                dep_tuples=[('secret2', 'x86-secret')])
    add_package(builder, 'secret4', 'x86-secret', LicenseSecret('Shh'),
                dep_tuples=[('secret2', 'x86-secret'),
                            ('gpl2', 'x86')])
    add_package(builder, 'secret5', 'x86-secret', LicenseSecret('Shh'))

    # The following need to be true if we are not to be required to distribute
    # under GPL propagation rules
    set_not_built_against(builder, package('secret2', 'x86-secret'), checkout('gpl2plus'))
    set_not_built_against(builder, package('secret3', 'x86-secret'), checkout('gpl2plus'))
    set_not_built_against(builder, package('secret4', 'x86-secret'), checkout('gpl2plus'))
    set_not_built_against(builder, package('secret4', 'x86-secret'), checkout('gpl2'))

    collect.copy_from_role_install(builder, deployment,
                                   role = 'x86-secret',
                                   rel = "", dest = "",
                                   domain = None)
"""

SUBDOMAIN_BUILD_DESC = """ \
# A subdomain build description

import os

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep

from muddled.depend import checkout, package

from muddled.distribute import distribute_checkout, distribute_package
from muddled.licenses import set_license, LicenseBinary, LicenseSecret

def add_package(builder, name, role, license=None, co_name=None, deps=None):
    if not co_name:
        co_name = name
    muddled.pkgs.make.medium(builder, name, [role], co_name, deps=deps)

    if license:
        co_label = checkout(co_name)
        set_license(builder, co_label, license)

def describe_to(builder):
    deployment = 'everything'

    add_package(builder, 'xyzlib',  'x86', 'zlib')
    add_package(builder, 'manhattan', 'x86-secret', 'code-nightmare-green')

    builder.invocation.db.set_not_built_against(package('manhattan', 'x86-secret'),
                                                checkout('xyzlib'))

    # The 'everything' deployment is built from our single role, and goes
    # into deploy/everything.
    muddled.deployments.filedep.deploy(builder, "", "everything", ['x86', 'x86-secret'])

    # If no role is specified, assume this one
    builder.invocation.add_default_role('x86')
    # muddle at the top level will default to building this deployment
    builder.by_default_deploy("everything")
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

def make_repos(root_dir):
    """Create git repositories for our tests.

    I'm going to start by naming them after licenses...
    """

    def new_repo(name):
        with NewDirectory(name) as d:
            make_standard_checkout(d.where, name, name)

    repo = os.path.join(root_dir, 'repo')
    with NewDirectory('repo'):
        with NewDirectory('main'):
            with NewDirectory('builds_multilicense_with_clashes') as d:
                make_build_desc(d.where, MULTILICENSE_BUILD_DESC_WITH_CLASHES.format(repo=repo))

            with NewDirectory('builds_multilicense') as d:
                make_build_desc(d.where, MULTILICENSE_BUILD_DESC.format(repo=repo))
                touch('secret.py', SECRET_BUILD_FILE)
                git('add secret.py')
                git('commit -m "Secret build desc"')

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

        with NewDirectory('subdomain'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN_BUILD_DESC.format(repo=repo))

            new_repo('xyzlib')
            new_repo('manhattan')

def check_text(actual, wanted):
    if actual == wanted:
        return

    actual_lines = actual.splitlines(True)
    wanted_lines = wanted.splitlines(True)
    diffs = unified_diff(wanted_lines, actual_lines, fromfile='Expected', tofile='Got')
    for line in diffs:
        sys.stdout.write(line)
    if diffs:
        raise OurGiveUp('Text did not match')

def check_checkout_licenses_with_clashes(root_dir, d):
    """Perform the actual tests.
    """
    banner('REPORT WITH CLASHES')
    text = captured_muddle(['query', 'checkout-licenses'])
    check_text(text, """\
Checkout licenses are:

* checkout:apache/*               LicenseOpen('Apache')
* checkout:binary1/*              LicenseBinary('Customer')
* checkout:binary2/*              LicenseBinary('Customer')
* checkout:binary3/*              LicenseBinary('Customer')
* checkout:binary4/*              LicenseBinary('Customer')
* checkout:binary5/*              LicenseBinary('Customer')
* checkout:bsd/*                  LicenseOpen('BSD 3-clause')
* checkout:busybox/*              LicenseGPL('GPL v2')
* checkout:gnulibc/*              LicenseLGPL('LGPL', with_exception=True)
* checkout:gpl2/*                 LicenseGPL('GPL v2')
* checkout:gpl2plus/*             LicenseGPL('GPL v2 and above')
* checkout:gpl3/*                 LicenseGPL('GPL v3')
* checkout:lgpl/*                 LicenseLGPL('LGPL')
* checkout:linux/*                LicenseGPL('GPL v2', with_exception=True)
* checkout:mpl/*                  LicenseOpen('MPL 1.1')
* checkout:secret1/*              LicenseSecret('Shh')
* checkout:secret2/*              LicenseSecret('Shh')
* checkout:secret3/*              LicenseSecret('Shh')
* checkout:secret4/*              LicenseSecret('Shh')
* checkout:secret5/*              LicenseSecret('Shh')
* checkout:ukogl/*                LicenseOpen('UK Open Government License')
* checkout:zlib/*                 LicenseOpen('zlib')
* checkout:(subdomain)manhattan/* LicenseSecret('Code Nightmare Green')
* checkout:(subdomain)xyzlib/*    LicenseOpen('zlib')

The following checkouts do not have a license:

* checkout:builds_multilicense_with_clashes/*
* checkout:not_licensed1/*
* checkout:not_licensed2/*
* checkout:not_licensed3/*
* checkout:not_licensed4/*
* checkout:not_licensed5/*
* checkout:(subdomain)builds/*

The following checkouts have some sort of GPL license:

* checkout:busybox/*              LicenseGPL('GPL v2')
* checkout:gnulibc/*              LicenseLGPL('LGPL', with_exception=True)
* checkout:gpl2/*                 LicenseGPL('GPL v2')
* checkout:gpl2plus/*             LicenseGPL('GPL v2 and above')
* checkout:gpl3/*                 LicenseGPL('GPL v3')
* checkout:lgpl/*                 LicenseLGPL('LGPL')
* checkout:linux/*                LicenseGPL('GPL v2', with_exception=True)

Exceptions to "implicit" GPL licensing are:

* package:secret2{x86}/* is not built against checkout:gpl2plus/*
* package:(subdomain)manhattan{x86-secret}/* is not built against checkout:(subdomain)xyzlib/*

The following are "implicitly" GPL licensed for the given reasons:

* checkout:not_licensed1/*  (was None)
  - package:not_licensed1{x86}/* depends on checkout:gpl2/*
  - package:not_licensed1{x86}/* depends on checkout:gpl3/*
* checkout:secret3/*  (was LicenseSecret('Shh'))
  - package:secret3{x86}/* depends on checkout:gpl2plus/*
* checkout:secret4/*  (was LicenseSecret('Shh'))
  - package:secret4{x86}/* depends on checkout:gpl2/*
  - package:secret4{x86}/* depends on checkout:gpl2plus/*
* checkout:ukogl/*  (was LicenseOpen('UK Open Government License'))
  - package:ukogl{x86}/* depends on checkout:lgpl/*

This means that the following have irreconcilable clashes:

* checkout:secret3/*              LicenseSecret('Shh')
* checkout:secret4/*              LicenseSecret('Shh')
""")

def check_checkout_licenses_without_clashes(root_dir, d):
    """Perform the actual tests.
    """
    banner('REPORT WITHOUT CLASHES')
    text = captured_muddle(['query', 'checkout-licenses'])
    check_text(text, """\
Checkout licenses are:

* checkout:apache/*               LicenseOpen('Apache')
* checkout:binary1/*              LicenseBinary('Customer')
* checkout:binary2/*              LicenseBinary('Customer')
* checkout:binary3/*              LicenseBinary('Customer')
* checkout:binary4/*              LicenseBinary('Customer')
* checkout:binary5/*              LicenseBinary('Customer')
* checkout:bsd/*                  LicenseOpen('BSD 3-clause')
* checkout:busybox/*              LicenseGPL('GPL v2')
* checkout:gnulibc/*              LicenseLGPL('LGPL', with_exception=True)
* checkout:gpl2/*                 LicenseGPL('GPL v2')
* checkout:gpl2plus/*             LicenseGPL('GPL v2 and above')
* checkout:gpl3/*                 LicenseGPL('GPL v3')
* checkout:lgpl/*                 LicenseLGPL('LGPL')
* checkout:linux/*                LicenseGPL('GPL v2', with_exception=True)
* checkout:mpl/*                  LicenseOpen('MPL 1.1')
* checkout:secret1/*              LicenseSecret('Shh')
* checkout:secret2/*              LicenseSecret('Shh')
* checkout:secret3/*              LicenseSecret('Shh')
* checkout:secret4/*              LicenseSecret('Shh')
* checkout:secret5/*              LicenseSecret('Shh')
* checkout:ukogl/*                LicenseOpen('UK Open Government License')
* checkout:zlib/*                 LicenseOpen('zlib')
* checkout:(subdomain)manhattan/* LicenseSecret('Code Nightmare Green')
* checkout:(subdomain)xyzlib/*    LicenseOpen('zlib')

The following checkouts do not have a license:

* checkout:builds_multilicense/*
* checkout:not_licensed1/*
* checkout:not_licensed2/*
* checkout:not_licensed3/*
* checkout:not_licensed4/*
* checkout:not_licensed5/*
* checkout:(subdomain)builds/*

The following checkouts have some sort of GPL license:

* checkout:busybox/*              LicenseGPL('GPL v2')
* checkout:gnulibc/*              LicenseLGPL('LGPL', with_exception=True)
* checkout:gpl2/*                 LicenseGPL('GPL v2')
* checkout:gpl2plus/*             LicenseGPL('GPL v2 and above')
* checkout:gpl3/*                 LicenseGPL('GPL v3')
* checkout:lgpl/*                 LicenseLGPL('LGPL')
* checkout:linux/*                LicenseGPL('GPL v2', with_exception=True)

Exceptions to "implicit" GPL licensing are:

* package:secret2{x86-secret}/* is not built against checkout:gpl2plus/*
* package:secret3{x86-secret}/* is not built against checkout:gpl2plus/*
* package:(subdomain)manhattan{x86-secret}/* is not built against checkout:(subdomain)xyzlib/*
* package:secret4{x86-secret}/* is not built against checkout:gpl2/*, checkout:gpl2plus/*

The following are "implicitly" GPL licensed for the given reasons:

* checkout:not_licensed1/*  (was None)
  - package:not_licensed1{x86}/* depends on checkout:gpl2/*
  - package:not_licensed1{x86}/* depends on checkout:gpl3/*
* checkout:ukogl/*  (was LicenseOpen('UK Open Government License'))
  - package:ukogl{x86}/* depends on checkout:lgpl/*
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
        make_repos(root_dir)

        with NewDirectory('build_with_clashes') as d:
            banner('CHECK REPOSITORIES OUT, WITH CLASHES')
            muddle(['init', 'git+file://{repo}/main'.format(repo=root.join('repo')),
                    'builds_multilicense_with_clashes/01.py'])
            muddle(['checkout', '_all'])
            banner('BUILD')
            muddle([])
            banner('STAMP VERSION')
            muddle(['stamp', 'version'])
            check_checkout_licenses_with_clashes(root_dir, d)

        with NewDirectory('build') as d:
            banner('CHECK REPOSITORIES OUT, WITHOUT CLASHES')
            muddle(['init', 'git+file://{repo}/main'.format(repo=root.join('repo')),
                    'builds_multilicense/01.py'])
            muddle(['checkout', '_all'])
            banner('BUILD')
            muddle([])
            banner('STAMP VERSION')
            muddle(['stamp', 'version'])
            check_checkout_licenses_without_clashes(root_dir, d)

            # And we can try distributing some things

            banner('TESTING DISTRIBUTE SOURCE RELEASE')
            target_dir = os.path.join(root_dir, '_source_release')
            muddle(['distribute', '_source_release', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           'obj',
                                           'install',
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions',
                                           '.muddle/tags/package',
                                           '.muddle/tags/deployment',
                                          ])

            banner('TESTING DISTRIBUTE FOR GPL')
            target_dir = os.path.join(root_dir, '_for_gpl')
            muddle(['distribute', '_for_gpl', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           # Some 'open' things, by propagation, but not:
                                           'src/apache',
                                           'src/bsd',
                                           'src/mpl',
                                           'src/zlib',
                                           # No binary things, because they're not GPL
                                           'src/binary*',
                                           # No secret things, they're very not GPL
                                           'src/secret*',
                                           # No not licensed things, because they're not GPL,
                                           # except for 1, by propagation
                                           'src/not_licensed[2345]',
                                           'obj',
                                           'install',
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions',
                                           '.muddle/tags/package',
                                           '.muddle/tags/deployment',
                                           '.muddle/tags/checkout/apache',
                                           '.muddle/tags/checkout/bsd',
                                           '.muddle/tags/checkout/mpl',
                                           '.muddle/tags/checkout/zlib',
                                           '.muddle/tags/checkout/binary*',
                                           '.muddle/tags/checkout/not_licensed[2345]',
                                           '.muddle/tags/checkout/secret*',
                                           # Nothing in the subdomains is GPL
                                           'domains',
                                          ])
            # Check the "secret" build description file has been replaced
            assert not same_content(d.join(target_dir, 'src', 'builds_multilicense', 'secret.py'),
                                SECRET_BUILD_FILE)

            banner('TESTING DISTRIBUTE FOR ALL OPEN')
            target_dir = os.path.join(root_dir, '_all_open')
            muddle(['distribute', '_all_open', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           # No binary things, because they're not GPL
                                           'src/binary*',
                                           # No secret things, they're very not GPL
                                           'src/secret*',
                                           'domains/subdomain/src/manhattan',
                                           # No not licensed things, because they're not open,
                                           # except for 1, by propagation from GPL
                                           'src/not_licensed[2345]',
                                           'obj',
                                           'install',
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions',
                                           '.muddle/tags/package',
                                           '.muddle/tags/deployment',
                                           '.muddle/tags/checkout/binary*',
                                           '.muddle/tags/checkout/not_licensed[2345]',
                                           '.muddle/tags/checkout/secret*',
                                           # And, in our subdomain
                                           '.muddle/tags/checkout/manhattan',
                                          ])
            # Check the "secret" build description file has been replaced
            assert not same_content(d.join(target_dir, 'src', 'builds_multilicense', 'secret.py'),
                                SECRET_BUILD_FILE)

            banner('TESTING DISTRIBUTE FOR BY LICENSE')
            target_dir = os.path.join(root_dir, '_by_license')
            muddle(['distribute', '_by_license', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           # No secret things, they're very not GPL
                                           'src/secret*',
                                           'obj/*/x86-secret',
                                           'install/x86-secret',
                                           # No not licensed things, because they're not
                                           # licensed(!), except for 1, by propagation from GPL
                                           'src/not_licensed[2345]',
                                           #
                                           'src/binary*/*.c',   # just the muddle makefiles
                                           #
                                           'obj',
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions',
                                           '.muddle/tags/checkout/secret*',
                                           '.muddle/tags/checkout/not_licensed[2345]',
                                           '.muddle/tags/package/secret*',
                                           '.muddle/tags/package/not_licensed*',
                                           # No package tags for source-only things
                                           '.muddle/tags/package/apache',
                                           '.muddle/tags/package/bsd',
                                           '.muddle/tags/package/gpl*',
                                           '.muddle/tags/package/lgpl',
                                           '.muddle/tags/package/mpl',
                                           '.muddle/tags/package/ukogl',
                                           '.muddle/tags/package/zlib',
                                           '.muddle/tags/package/gnulibc',
                                           '.muddle/tags/package/linux',
                                           '.muddle/tags/package/busybox',
                                           # We don't do deployment...
                                           '.muddle/tags/deployment',
                                           # And, in our subdomain
                                           'domains/subdomain/src/manhattan',
                                           'domains/subdomain/install',
                                           'domains/subdomain/.muddle/tags/checkout/manhattan',
                                           'domains/subdomain/.muddle/tags/package',
                                           'domains/subdomain/.muddle/tags/deploy',
                                          ])
            # Check the "secret" build description file has been replaced
            assert not same_content(d.join(target_dir, 'src', 'builds_multilicense', 'secret.py'),
                                SECRET_BUILD_FILE)

            banner('TESTING DISTRIBUTE FOR JUST OPEN')
            # As it says in the build description, this is an odd one, and
            # not a "proper" useful distribution. We've selected all
            # checkouts that are 'open' (not including 'gpl'), and also
            # asked for a binary distribution (the "install/" directory)
            # for their packages. However, since the distribution code can't
            # know who put what into "install/x86/", we also end up distributing
            # stuff that is *not* from 'open' checkouts. This is not a bug, it
            # is a limitation of the mechanism, and the correct work around
            # would be to split the build up into more roles of the correct
            # granularity.
            # So why this test? Mainly to show the "problem" and verify that
            # it is indeed working as expected...
            target_dir = os.path.join(root_dir, 'just_open_src_and_bin')
            muddle(['distribute', 'just_open_src_and_bin', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           # No binary or secret things
                                           'src/binary*',
                                           'src/secret*',
                                           'domains/subdomain/src/manhattan',
                                           # No GPL things
                                           'src/gpl*',
                                           'src/lgpl',
                                           'src/gnulibc',
                                           'src/linux',
                                           'src/busybox',
                                           # No not licensed things, because they're not open
                                           'src/not_licensed*',
                                           # But we end up with all of install/x86 - see above
                                           # We don't want any of install/x86-secret, of course
                                           'install/x86-secret',
                                           'obj',
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions',
                                           '.muddle/tags/checkout/binary*',
                                           '.muddle/tags/checkout/busybox',
                                           '.muddle/tags/checkout/gnulibc',
                                           '.muddle/tags/checkout/gpl*',
                                           '.muddle/tags/checkout/lgpl',
                                           '.muddle/tags/checkout/linux',
                                           '.muddle/tags/checkout/not_licensed*',
                                           '.muddle/tags/checkout/secret*',
                                           '.muddle/tags/package/binary*',
                                           '.muddle/tags/package/busybox',
                                           '.muddle/tags/package/gnulibc',
                                           '.muddle/tags/package/gpl*',
                                           '.muddle/tags/package/lgpl',
                                           '.muddle/tags/package/linux',
                                           '.muddle/tags/package/not_licensed*',
                                           '.muddle/tags/package/secret*',
                                           '.muddle/tags/deployment',
                                           # And, in our subdomain
                                           'domains/subdomain/src/manhattan',
                                           'domains/subdomain/.muddle/tags/checkout/manhattan',
                                           'domains/subdomain/.muddle/tags/package/manhattan',
                                          ])
            # Check the "secret" build description file has been replaced
            assert not same_content(d.join(target_dir, 'src', 'builds_multilicense', 'secret.py'),
                                SECRET_BUILD_FILE)

            # See, it does say that it is doing what we asked...
            text = captured_muddle(['-n', 'distribute', 'just_open_src_and_bin', '../fred'])
            check_text(text, """\
Writing distribution just_open_src_and_bin to ../fred
checkout:apache/distributed                DistributeCheckout: just_open_src_and_bin[*]
checkout:bsd/distributed                   DistributeCheckout: just_open_src_and_bin[*]
checkout:builds_multilicense/distributed   DistributeBuildDescription: _all_open[-1], _by_license[-1], _for_gpl[-1], just_open_src_and_bin[-1]
checkout:mpl/distributed                   DistributeCheckout: just_open_src_and_bin[*]
checkout:ukogl/distributed                 DistributeCheckout: just_open_src_and_bin[*]
checkout:zlib/distributed                  DistributeCheckout: just_open_src_and_bin[*]
checkout:(subdomain)builds/distributed     DistributeBuildDescription: just_open_src_and_bin[]
checkout:(subdomain)xyzlib/distributed     DistributeCheckout: just_open_src_and_bin[*]
package:apache{x86}/distributed            DistributePackage: just_open_src_and_bin[install]
package:bsd{x86}/distributed               DistributePackage: just_open_src_and_bin[install]
package:mpl{x86}/distributed               DistributePackage: just_open_src_and_bin[install]
package:ukogl{x86}/distributed             DistributePackage: just_open_src_and_bin[install]
package:zlib{x86}/distributed              DistributePackage: just_open_src_and_bin[install]
package:(subdomain)xyzlib{x86}/distributed DistributePackage: just_open_src_and_bin[install]
""")

            banner('TESTING DISTRIBUTE FOR BINARY AND SECRET SOURCE')
            target_dir = os.path.join(root_dir, 'binary_and_secret_source')
            muddle(['distribute', 'binary_and_secret_source', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           # No open things (including 'gpl')
                                           'src/apache',
                                           'src/bsd',
                                           'src/busybox',
                                           'src/gnulibc',
                                           'src/gpl*',
                                           'src/lgpl',
                                           'src/linux',
                                           'src/mpl',
                                           'src/ukogl',
                                           'src/zlib',
                                           # No not licensed things
                                           'src/not_licensed*',
                                           # No binaries
                                           'obj',
                                           'install',
                                           #
                                           'deploy',
                                           'versions',
                                           #
                                           '.muddle/instructions',
                                           '.muddle/tags/checkout/apache',
                                           '.muddle/tags/checkout/bsd',
                                           '.muddle/tags/checkout/busybox',
                                           '.muddle/tags/checkout/gnulibc',
                                           '.muddle/tags/checkout/gpl*',
                                           '.muddle/tags/checkout/lgpl',
                                           '.muddle/tags/checkout/linux',
                                           '.muddle/tags/checkout/mpl',
                                           '.muddle/tags/checkout/ukogl',
                                           '.muddle/tags/checkout/zlib',
                                           '.muddle/tags/checkout/not_licensed*',
                                           # No package tags because we're only doing source
                                           '.muddle/tags/package',
                                           # We don't do deployment...
                                           '.muddle/tags/deployment',
                                           # And, in our subdomain
                                           'domains/subdomain/src/xyzlib',
                                           'domains/subdomain/.muddle/tags/checkout/xyzlib',
                                          ])
            # Check the "secret" build description file has NOT been replaced
            assert same_content(d.join(target_dir, 'src', 'builds_multilicense', 'secret.py'),
                                SECRET_BUILD_FILE)

            # Then test:
            #
            # - binary_and_secret_install

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
