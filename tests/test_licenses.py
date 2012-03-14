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
# The install/ directory gets private and non-private stuff installed to
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
from muddled.licenses import set_license, LicenseBinary, LicensePrivate, \
        set_nothing_builds_against

def add_package(builder, name, role, license=None, co_name=None, deps=None, license_file=None):
    if not co_name:
        co_name = name
    muddled.pkgs.make.medium(builder, name, [role], co_name, deps=deps)

    if license:
        co_label = checkout(co_name)
        set_license(builder, co_label, license, license_file)

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    another_license = LicensePrivate('ignore-this')

    add_package(builder, 'apache', 'x86', 'Apache-2.0')
    add_package(builder, 'bsd',    'x86', 'BSD-3-Clause', license_file='LICENSE.txt')
    add_package(builder, 'gpl2',   'x86', 'GPL-2.0')
    add_package(builder, 'gpl2plus', 'x86', 'GPL-2.0+')
    add_package(builder, 'gpl3',  'x86', 'GPL-3.0')
    add_package(builder, 'lgpl',  'x86', 'LGPL-3.0')
    add_package(builder, 'mpl',   'x86', 'MPL-2.0')
    add_package(builder, 'ukogl', 'x86', 'UKOGL', deps=['lgpl'])
    add_package(builder, 'zlib',  'x86', 'Zlib')

    add_package(builder, 'gnulibc', 'x86', 'GPL-3.0-with-GCC-exception')
    add_package(builder, 'linux', 'x86', 'GPL-2.0-linux')
    add_package(builder, 'busybox', 'x86', 'GPL-2.0')

    set_nothing_builds_against(builder, checkout('busybox'))

    add_package(builder, 'scripts', 'x86', 'Proprietary')

    add_package(builder, 'binary1', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary2', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary3', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary4', 'x86', LicenseBinary('Customer'))
    add_package(builder, 'binary5', 'x86', LicenseBinary('Customer'))

    add_package(builder, 'private1', 'x86', LicensePrivate('Shh'), deps=['gnulibc'])
    add_package(builder, 'private2', 'x86', LicensePrivate('Shh'), deps=['gnulibc', 'gpl2plus'])
    add_package(builder, 'private3', 'x86', LicensePrivate('Shh'), deps=['private2'])
    add_package(builder, 'private4', 'x86', LicensePrivate('Shh'), deps=['private2', 'gpl2'])
    add_package(builder, 'private5', 'x86', LicensePrivate('Shh'))

    add_package(builder, 'not_licensed1', role, deps=['gpl2', 'gpl3'])
    add_package(builder, 'not_licensed2', 'x86')
    add_package(builder, 'not_licensed3', 'x86')
    add_package(builder, 'not_licensed4', 'x86')
    add_package(builder, 'not_licensed5', 'x86')

    builder.invocation.db.set_license_not_affected_by(package('private2', 'x86'),
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
# "Private" stuff is segregated to a different role, and is described in
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
        get_distributions_not_for, set_private_build_files, name_distribution
from muddled.licenses import set_license, LicenseBinary, LicensePrivate, \
        get_open_not_gpl_checkouts, get_binary_checkouts, get_private_checkouts, \
        get_license, set_nothing_builds_against

# Our private information
from private import describe_private

def add_package(builder, name, role, license=None, co_name=None, deps=None, license_file=None):
    if not co_name:
        co_name = name
    muddled.pkgs.make.medium(builder, name, [role], co_name, deps=deps)

    if license:
        co_label = checkout(co_name)
        set_license(builder, co_label, license, license_file)

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    another_license = LicensePrivate('ignore-this')

    add_package(builder, 'apache', 'x86', 'Apache-2.0')
    add_package(builder, 'bsd',    'x86', 'BSD-3-Clause', license_file='LICENSE.txt')
    add_package(builder, 'gpl2',   'x86', 'GPL-2.0')
    add_package(builder, 'gpl2plus', 'x86', 'GPL-2.0+')
    add_package(builder, 'gpl3',  'x86', 'GPL-3.0')
    add_package(builder, 'lgpl',  'x86', 'LGPL-3.0')
    add_package(builder, 'mpl',   'x86', 'MPL-2.0')
    add_package(builder, 'ukogl', 'x86', 'UKOGL', deps=['lgpl'])
    add_package(builder, 'zlib',  'x86', 'Zlib')

    add_package(builder, 'gnulibc', 'x86', 'GPL-3.0-with-GCC-exception')
    add_package(builder, 'linux', 'x86', 'GPL-2.0-linux')
    add_package(builder, 'busybox', 'x86', 'GPL-2.0')

    set_nothing_builds_against(builder, checkout('busybox'))

    add_package(builder, 'scripts', 'x86', 'Proprietary')

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

    # We also have some private stuff, described elsewhere
    describe_private(builder, deployment=deployment)

    # So that "elsewhere" is private - i.e., private.py
    # and we should never distribute it in non-private distributions
    for name in get_distributions_not_for(builder, ['private']):
        set_private_build_files(builder, name, ['private.py'])

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

    # This is an odd one - anything that is in 'open-source' (but not 'gpl'),
    # and we shall distribute both the checkout source and the package binary
    # NOTE that this means we will distribute everything in install/x86, because
    # we have no way of knowing (at distribute time) what came from where. If we
    # did care, we'd need to put things into different roles according to their
    # license (as we do for x86-private)
    name_distribution(builder, 'just_open_src_and_bin', ['open-source']) # so, no 'gpl'
    for co_label in get_open_not_gpl_checkouts(builder):
        distribute_checkout(builder, 'just_open_src_and_bin', co_label)
        # Get the package(s) directly using this checkout
        pkg_labels = builder.invocation.packages_using_checkout(co_label)
        for label in pkg_labels:
            distribute_package(builder, 'just_open_src_and_bin', label)
    # And we mustn't forget to add this new distribution to our
    # "don't propagate private.py" as well, since it hadn't been
    # declared yet when we did this earlier...
    set_private_build_files(builder, 'just_open_src_and_bin', ['private.py'])

    name_distribution(builder, 'binary_and_private_source', ['binary', 'private'])
    for co_label in get_binary_checkouts(builder):
        distribute_checkout(builder, 'binary_and_private_source', co_label)
    for co_label in get_private_checkouts(builder):
        distribute_checkout(builder, 'binary_and_private_source', co_label)

    # This one sounds like it should work as you'd expect, but again there's
    # the problem of distribute not having enough information about what is
    # in the 'install/' directory, and thus distributing all the binaries
    # from 'install/x86/'. So much the same caveats as just_open_src_and_bin.
    name_distribution(builder, 'binary_and_private_install', ['binary', 'private'])
    for co_label in get_binary_checkouts(builder):
        # Get the package(s) directly using this checkout
        pkg_labels = builder.invocation.packages_using_checkout(co_label)
        for label in pkg_labels:
            distribute_package(builder, 'binary_and_private_install', label)
    for co_label in get_private_checkouts(builder):
        pkg_labels = builder.invocation.packages_using_checkout(co_label)
        for label in pkg_labels:
            distribute_package(builder, 'binary_and_private_install', label)

    # Let's have another deployment
    second_deployment = 'something'
    collect.deploy(builder, second_deployment)
    collect.copy_from_package_obj(builder, second_deployment, 'mpl', 'x86', '', '')
    collect.copy_from_package_obj(builder, second_deployment, 'zlib', 'x86', '', '')
    collect.copy_from_package_obj(builder, second_deployment, 'scripts', 'x86', '', '')
    collect.copy_from_package_obj(builder, second_deployment, 'binary1', 'x86', '', '')
"""

PRIVATE_BUILD_FILE = """\
# The part of a build dealing with "private" licensed stuff

import muddled.deployments.collect as collect
import muddled.pkg as pkg
import muddled.pkgs.make as make

from muddled import pkgs
from muddled.depend import checkout, package
from muddled.licenses import LicensePrivate, set_license, set_license_not_affected_by

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

def describe_private(builder, *args, **kwargs):
    # Private packages

    deployment = kwargs['deployment']

    add_package(builder, 'private1', 'x86-private', LicensePrivate('Shh'),
                dep_tuples=[('gnulibc', 'x86')])
    add_package(builder, 'private2', 'x86-private', LicensePrivate('Shh'),
                dep_tuples=[('gnulibc', 'x86'),
                            ('gpl2plus', 'x86')])
    add_package(builder, 'private3', 'x86-private', LicensePrivate('Shh'),
                dep_tuples=[('private2', 'x86-private')])
    add_package(builder, 'private4', 'x86-private', LicensePrivate('Shh'),
                dep_tuples=[('private2', 'x86-private'),
                            ('gpl2', 'x86')])
    add_package(builder, 'private5', 'x86-private', LicensePrivate('Shh'))

    # The following need to be true if we are not to be required to distribute
    # under GPL propagation rules
    set_license_not_affected_by(builder, package('private2', 'x86-private'), checkout('gpl2plus'))
    set_license_not_affected_by(builder, package('private3', 'x86-private'), checkout('gpl2plus'))
    set_license_not_affected_by(builder, package('private4', 'x86-private'), checkout('gpl2plus'))
    set_license_not_affected_by(builder, package('private4', 'x86-private'), checkout('gpl2'))

    collect.copy_from_role_install(builder, deployment,
                                   role = 'x86-private',
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
from muddled.licenses import set_license, LicenseBinary, LicensePrivate

def add_package(builder, name, role, license=None, co_name=None, deps=None):
    if not co_name:
        co_name = name
    muddled.pkgs.make.medium(builder, name, [role], co_name, deps=deps)

    if license:
        co_label = checkout(co_name)
        set_license(builder, co_label, license)

def describe_to(builder):
    deployment = 'everything'

    add_package(builder, 'xyzlib',  'x86', 'Zlib')
    add_package(builder, 'manhattan', 'x86-private', 'CODE NIGHTMARE GREEN')

    builder.invocation.db.set_license_not_affected_by(package('manhattan', 'x86-private'),
                                                      checkout('xyzlib'))

    # The 'everything' deployment is built from our single role, and goes
    # into deploy/everything.
    muddled.deployments.filedep.deploy(builder, "", "everything", ['x86', 'x86-private'])

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
                touch('private.py', PRIVATE_BUILD_FILE)
                git('add private.py')
                git('commit -m "Private build desc"')

            new_repo('apache')
            new_repo('bsd')
            with Directory('bsd'):
                touch('LICENSE.txt', "This is a BSD license file. Honest\n")
                git('add LICENSE.txt')
                git('commit -m "BSD license file"')
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

            with NewDirectory('scripts') as d:
                git('init')
                touch('script.py', "#! /usr/bin/env python\nprint 'Hello'\n")
                touch('Makefile.muddle', "# Nothing to do\nall:\n\nconfig:\n\n"
                                         "install:\n\nclean:\n\ndistclean:\n\n")
                git('add script.py Makefile.muddle')
                git('commit -a -m "Commit scripts checkout"')

            new_repo('binary1')
            new_repo('binary2')
            new_repo('binary3')
            new_repo('binary4')
            new_repo('binary5')

            new_repo('private1')
            new_repo('private2')
            new_repo('private3')
            new_repo('private4')
            new_repo('private5')

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

def check_checkout_licenses_with_clashes(root_dir, d):
    """Perform the actual tests.
    """
    banner('REPORT WITH CLASHES')
    err, text = captured_muddle(['query', 'checkout-licenses'])
    check_text(text, """\
Checkout licenses are:

* checkout:apache/*               LicenseOpen('Apache', version='2.0')
* checkout:binary1/*              LicenseBinary('Customer')
* checkout:binary2/*              LicenseBinary('Customer')
* checkout:binary3/*              LicenseBinary('Customer')
* checkout:binary4/*              LicenseBinary('Customer')
* checkout:binary5/*              LicenseBinary('Customer')
* checkout:bsd/*                  LicenseOpen('BSD 3-clause "New" or "Revised" license')
* checkout:busybox/*              LicenseGPL('GPL', version='v2.0 only')
* checkout:gnulibc/*              LicenseGPL('GPL with GCC Runtime Library exception', version='v3.0', with_exception=True)
* checkout:gpl2/*                 LicenseGPL('GPL', version='v2.0 only')
* checkout:gpl2plus/*             LicenseGPL('GPL', version='v2.0 or later')
* checkout:gpl3/*                 LicenseGPL('GPL', version='v3.0 only')
* checkout:lgpl/*                 LicenseLGPL('Lesser GPL', version='v3.0 only')
* checkout:linux/*                LicenseGPL('GPL', version='v2.0', with_exception=True)
* checkout:mpl/*                  LicenseOpen('Mozilla Public License', version='2.0')
* checkout:private1/*             LicensePrivate('Shh')
* checkout:private2/*             LicensePrivate('Shh')
* checkout:private3/*             LicensePrivate('Shh')
* checkout:private4/*             LicensePrivate('Shh')
* checkout:private5/*             LicensePrivate('Shh')
* checkout:scripts/*              LicenseProprietarySource('Proprietary Source')
* checkout:ukogl/*                LicenseOpen('UK Open Government License')
* checkout:zlib/*                 LicenseOpen('zlib/libpng license')
* checkout:(subdomain)manhattan/* LicensePrivate('Code Nightmare Green')
* checkout:(subdomain)xyzlib/*    LicenseOpen('zlib/libpng license')

The following checkouts do not have a license:

* checkout:builds_multilicense_with_clashes/*
* checkout:not_licensed1/*
* checkout:not_licensed2/*
* checkout:not_licensed3/*
* checkout:not_licensed4/*
* checkout:not_licensed5/*
* checkout:(subdomain)builds/*

The following checkouts have some sort of GPL license:

* checkout:busybox/*              LicenseGPL('GPL', version='v2.0 only')
* checkout:gnulibc/*              LicenseGPL('GPL with GCC Runtime Library exception', version='v3.0', with_exception=True)
* checkout:gpl2/*                 LicenseGPL('GPL', version='v2.0 only')
* checkout:gpl2plus/*             LicenseGPL('GPL', version='v2.0 or later')
* checkout:gpl3/*                 LicenseGPL('GPL', version='v3.0 only')
* checkout:lgpl/*                 LicenseLGPL('Lesser GPL', version='v3.0 only')
* checkout:linux/*                LicenseGPL('GPL', version='v2.0', with_exception=True)

Exceptions to "implicit" GPL licensing are:

* nothing builds against checkout:busybox/*
* package:private2{x86}/* is not affected by checkout:gpl2plus/*
* package:(subdomain)manhattan{x86-private}/* is not affected by checkout:(subdomain)xyzlib/*

The following are "implicitly" GPL licensed for the given reasons:

* checkout:not_licensed1/*  (was None)
  - package:not_licensed1{x86}/* depends on checkout:gpl2/*
  - package:not_licensed1{x86}/* depends on checkout:gpl3/*
* checkout:private3/*  (was LicensePrivate('Shh'))
  - package:private3{x86}/* depends on checkout:gpl2plus/*
* checkout:private4/*  (was LicensePrivate('Shh'))
  - package:private4{x86}/* depends on checkout:gpl2/*
  - package:private4{x86}/* depends on checkout:gpl2plus/*
* checkout:ukogl/*  (was LicenseOpen('UK Open Government License'))
  - package:ukogl{x86}/* depends on checkout:lgpl/*

This means that the following have irreconcilable clashes:

* checkout:private3/*             LicensePrivate('Shh')
* checkout:private4/*             LicensePrivate('Shh')
""")

def check_checkout_licenses_without_clashes(root_dir, d):
    """Perform the actual tests.
    """
    banner('REPORT WITHOUT CLASHES')
    err, text = captured_muddle(['query', 'checkout-licenses'])
    check_text(text, """\
Checkout licenses are:

* checkout:apache/*               LicenseOpen('Apache', version='2.0')
* checkout:binary1/*              LicenseBinary('Customer')
* checkout:binary2/*              LicenseBinary('Customer')
* checkout:binary3/*              LicenseBinary('Customer')
* checkout:binary4/*              LicenseBinary('Customer')
* checkout:binary5/*              LicenseBinary('Customer')
* checkout:bsd/*                  LicenseOpen('BSD 3-clause "New" or "Revised" license')
* checkout:busybox/*              LicenseGPL('GPL', version='v2.0 only')
* checkout:gnulibc/*              LicenseGPL('GPL with GCC Runtime Library exception', version='v3.0', with_exception=True)
* checkout:gpl2/*                 LicenseGPL('GPL', version='v2.0 only')
* checkout:gpl2plus/*             LicenseGPL('GPL', version='v2.0 or later')
* checkout:gpl3/*                 LicenseGPL('GPL', version='v3.0 only')
* checkout:lgpl/*                 LicenseLGPL('Lesser GPL', version='v3.0 only')
* checkout:linux/*                LicenseGPL('GPL', version='v2.0', with_exception=True)
* checkout:mpl/*                  LicenseOpen('Mozilla Public License', version='2.0')
* checkout:private1/*             LicensePrivate('Shh')
* checkout:private2/*             LicensePrivate('Shh')
* checkout:private3/*             LicensePrivate('Shh')
* checkout:private4/*             LicensePrivate('Shh')
* checkout:private5/*             LicensePrivate('Shh')
* checkout:scripts/*              LicenseProprietarySource('Proprietary Source')
* checkout:ukogl/*                LicenseOpen('UK Open Government License')
* checkout:zlib/*                 LicenseOpen('zlib/libpng license')
* checkout:(subdomain)manhattan/* LicensePrivate('Code Nightmare Green')
* checkout:(subdomain)xyzlib/*    LicenseOpen('zlib/libpng license')

The following checkouts do not have a license:

* checkout:builds_multilicense/*
* checkout:not_licensed1/*
* checkout:not_licensed2/*
* checkout:not_licensed3/*
* checkout:not_licensed4/*
* checkout:not_licensed5/*
* checkout:(subdomain)builds/*

The following checkouts have some sort of GPL license:

* checkout:busybox/*              LicenseGPL('GPL', version='v2.0 only')
* checkout:gnulibc/*              LicenseGPL('GPL with GCC Runtime Library exception', version='v3.0', with_exception=True)
* checkout:gpl2/*                 LicenseGPL('GPL', version='v2.0 only')
* checkout:gpl2plus/*             LicenseGPL('GPL', version='v2.0 or later')
* checkout:gpl3/*                 LicenseGPL('GPL', version='v3.0 only')
* checkout:lgpl/*                 LicenseLGPL('Lesser GPL', version='v3.0 only')
* checkout:linux/*                LicenseGPL('GPL', version='v2.0', with_exception=True)

Exceptions to "implicit" GPL licensing are:

* nothing builds against checkout:busybox/*
* package:private2{x86-private}/* is not affected by checkout:gpl2plus/*
* package:private3{x86-private}/* is not affected by checkout:gpl2plus/*
* package:private4{x86-private}/* is not affected by checkout:gpl2/*, checkout:gpl2plus/*
* package:(subdomain)manhattan{x86-private}/* is not affected by checkout:(subdomain)xyzlib/*

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

            banner('TESTING DISTRIBUTE BINARY RELEASE')
            target_dir = os.path.join(root_dir, '_binary_release')
            muddle(['distribute', '_binary_release', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           'src/*/*.c',
                                           'src/scripts/script.py',
                                           # But we do want src/bsd/LICENSE.txt
                                           # And we want each Makefile.muddle
                                           'obj',
                                           # And we do want install
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions',
                                           # And all the package tags
                                           '.muddle/tags/deployment',
                                          ])

            banner('TESTING DISTRIBUTE FOR GPL')
            target_dir = os.path.join(root_dir, '_for_gpl')
            muddle(['distribute', '_for_gpl', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           # Some 'open-source' things, by propagation, but not:
                                           'src/apache',
                                           'src/bsd',
                                           'src/mpl',
                                           'src/zlib',
                                           # No proprietary source things, they're not GPL
                                           'src/scripts',
                                           # No binary things, because they're not GPL
                                           'src/binary*',
                                           # No private things, they're very not GPL
                                           'src/private*',
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
                                           '.muddle/tags/checkout/scripts',
                                           '.muddle/tags/checkout/binary*',
                                           '.muddle/tags/checkout/not_licensed[2345]',
                                           '.muddle/tags/checkout/private*',
                                           # Nothing in the subdomains is GPL
                                           'domains',
                                          ])
            # Check the "private" build description file has been replaced
            assert not same_content(d.join(target_dir, 'src', 'builds_multilicense', 'private.py'),
                                PRIVATE_BUILD_FILE)

            banner('TESTING DISTRIBUTE FOR ALL OPEN')
            target_dir = os.path.join(root_dir, '_all_open')
            muddle(['distribute', '_all_open', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           # No proprietary source things, they're not open
                                           'src/scripts',
                                           # No binary things, they're not open
                                           'src/binary*',
                                           # No private things, they're very not open
                                           'src/private*',
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
                                           '.muddle/tags/checkout/scripts',
                                           '.muddle/tags/checkout/binary*',
                                           '.muddle/tags/checkout/not_licensed[2345]',
                                           '.muddle/tags/checkout/private*',
                                           # And, in our subdomain
                                           '.muddle/tags/checkout/manhattan',
                                          ])
            # Check the "private" build description file has been replaced
            assert not same_content(d.join(target_dir, 'src', 'builds_multilicense', 'private.py'),
                                PRIVATE_BUILD_FILE)

            banner('TESTING DISTRIBUTE FOR BY LICENSE')
            target_dir = os.path.join(root_dir, '_by_license')
            muddle(['distribute', '_by_license', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           # No private things, they're private
                                           'src/private*',
                                           'obj/*/x86-private',
                                           'install/x86-private',
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
                                           '.muddle/tags/checkout/private*',
                                           '.muddle/tags/checkout/not_licensed[2345]',
                                           '.muddle/tags/package/private*',
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
                                           '.muddle/tags/package/scripts',
                                           # We don't do deployment...
                                           '.muddle/tags/deployment',
                                           # And, in our subdomain
                                           'domains/subdomain/src/manhattan',
                                           'domains/subdomain/install',
                                           'domains/subdomain/.muddle/tags/checkout/manhattan',
                                           'domains/subdomain/.muddle/tags/package',
                                           'domains/subdomain/.muddle/tags/deploy',
                                          ])
            # Check the "private" build description file has been replaced
            assert not same_content(d.join(target_dir, 'src', 'builds_multilicense', 'private.py'),
                                PRIVATE_BUILD_FILE)

            banner('TESTING DISTRIBUTE FOR JUST OPEN SRC AND BIN')
            # As it says in the build description, this is an odd one, and
            # not a "proper" useful distribution. We've selected all
            # checkouts that are 'open-source' (not including 'gpl'), and also
            # asked for a binary distribution (the "install/" directory)
            # for their packages. However, since the distribution code can't
            # know who put what into "install/x86/", we also end up distributing
            # stuff that is *not* from 'open-source' checkouts. This is not a
            # bug, it is a limitation of the mechanism, and the correct work
            # around would be to split the build up into more roles of the
            # correct granularity.
            # So why this test? Mainly to show the "problem" and verify that
            # it is indeed working as expected...
            target_dir = os.path.join(root_dir, 'just_open_src_and_bin')
            muddle(['distribute', 'just_open_src_and_bin', target_dir])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           # No proprietary or binary or private things
                                           'src/scripts',
                                           'src/binary*',
                                           'src/private*',
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
                                           # We don't want any of install/x86-private, of course
                                           'install/x86-private',
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
                                           '.muddle/tags/checkout/scripts',
                                           '.muddle/tags/checkout/private*',
                                           '.muddle/tags/package/binary*',
                                           '.muddle/tags/package/busybox',
                                           '.muddle/tags/package/gnulibc',
                                           '.muddle/tags/package/gpl*',
                                           '.muddle/tags/package/lgpl',
                                           '.muddle/tags/package/linux',
                                           '.muddle/tags/package/scripts',
                                           '.muddle/tags/package/not_licensed*',
                                           '.muddle/tags/package/private*',
                                           '.muddle/tags/deployment',
                                           # And, in our subdomain
                                           'domains/subdomain/src/manhattan',
                                           'domains/subdomain/.muddle/tags/checkout/manhattan',
                                           'domains/subdomain/.muddle/tags/package/manhattan',
                                          ])
            # Check the "private" build description file has been replaced
            assert not same_content(d.join(target_dir, 'src', 'builds_multilicense', 'private.py'),
                                PRIVATE_BUILD_FILE)

            # See, it does say that it is doing what we asked...
            err, text = captured_muddle(['-n', 'distribute', 'just_open_src_and_bin', '../fred'])
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

            banner('TESTING DISTRIBUTE FOR BINARY AND PRIVATE SOURCE')
            # That's "source for checkouts with binary and private licenses",
            # not "binaries and private-source".
            target_dir = os.path.join(root_dir, 'binary_and_private_source')
            muddle(['distribute', 'binary_and_private_source', target_dir])
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
                                           # No proprietary sources
                                           'src/scripts',
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
                                           '.muddle/tags/checkout/scripts',
                                           # No package tags because we're only doing source
                                           '.muddle/tags/package',
                                           # We don't do deployment...
                                           '.muddle/tags/deployment',
                                           # And, in our subdomain
                                           'domains/subdomain/src/xyzlib',
                                           'domains/subdomain/.muddle/tags/checkout/xyzlib',
                                          ])
            # Check the "private" build description file has NOT been replaced
            assert same_content(d.join(target_dir, 'src', 'builds_multilicense', 'private.py'),
                                PRIVATE_BUILD_FILE)

            banner('TESTING DISTRIBUTE FOR BINARY AND PRIVATE INSTALL')
            # Again, since we're distributing 'install/', we don't have enough
            # information to discriminate *what* from 'install/' gets distributed.
            # So this is, again, a test of what we can't do as well as what we can.
            target_dir = os.path.join(root_dir, 'binary_and_private_install')
            muddle(['distribute', 'binary_and_private_install', target_dir])
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
                                           # No proprietary source things
                                           'src/scripts',
                                           # No not licensed things
                                           'src/not_licensed*',
                                           # No source files
                                           'src/*.c',
                                           # All the binaries (because distribute can't
                                           # tell which are whose in install/x86)
                                           #
                                           'obj',
                                           'deploy',
                                           'versions',
                                           #
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
                                           '.muddle/tags/checkout/scripts',
                                           '.muddle/tags/checkout/not_licensed*',
                                           # No package tags for unwanted things
                                           '.muddle/tags/package/apache',
                                           '.muddle/tags/package/bsd',
                                           '.muddle/tags/package/busybox',
                                           '.muddle/tags/package/gnulibc',
                                           '.muddle/tags/package/gpl*',
                                           '.muddle/tags/package/lgpl',
                                           '.muddle/tags/package/linux',
                                           '.muddle/tags/package/mpl',
                                           '.muddle/tags/package/ukogl',
                                           '.muddle/tags/package/zlib',
                                           '.muddle/tags/package/not_licensed*',
                                           '.muddle/tags/package/scripts',
                                           # We don't do deployment...
                                           '.muddle/tags/deployment',
                                           # And, in our subdomain
                                           'domains/subdomain/src/xyzlib',
                                           'domains/subdomain/.muddle/tags/checkout/xyzlib',
                                           'domains/subdomain/.muddle/tags/package/xyzlib',
                                           'domains/subdomain/install/x86',
                                          ])
            # Check the "private" build description file has NOT been replaced
            assert same_content(d.join(target_dir, 'src', 'builds_multilicense', 'private.py'),
                                PRIVATE_BUILD_FILE)

            banner('TESTING DISTRIBUTE FOR BY LICENSE OF SECOND DEPLOYMENT')
            # Note that this WILL copy too much into the install directory, as
            # we can't discriminate on just things built for binary1
            target_dir = os.path.join(root_dir, '_by_license_something')
            muddle(['distribute', '_by_license', target_dir, 'deployment:something'])
            dt = DirTree(d.where, fold_dirs=['.git'])
            dt.assert_same(target_dir, onedown=True,
                           unwanted_files=['.git*',
                                           'src/builds*/*.pyc',
                                           'src/apache',
                                           'src/bsd',
                                           'src/busybox',
                                           'src/gnulibc',
                                           'src/gpl*',
                                           'src/lgpl',
                                           'src/linux',
                                           'src/ukogl',
                                           'src/binary[2-5]',
                                           'src/binary1/*.c',   # just the muddle makefile
                                           'src/not_licensed*',
                                           'src/private*',
                                           #
                                           'obj/*/x86-private',
                                           'install/x86-private',
                                           #
                                           'obj',
                                           'deploy',
                                           'versions',
                                           '.muddle/instructions',
                                           '.muddle/tags/checkout/apache',
                                           '.muddle/tags/checkout/bsd',
                                           '.muddle/tags/checkout/gpl*',
                                           '.muddle/tags/checkout/lgpl',
                                           '.muddle/tags/checkout/ukogl',
                                           '.muddle/tags/checkout/gnulibc',
                                           '.muddle/tags/checkout/linux',
                                           '.muddle/tags/checkout/busybox',
                                           '.muddle/tags/checkout/private*',
                                           '.muddle/tags/checkout/binary[2-5]',
                                           '.muddle/tags/checkout/not_licensed*',
                                           #
                                           '.muddle/tags/package/binary[2-5]',
                                           '.muddle/tags/package/private*',
                                           '.muddle/tags/package/not_licensed*',
                                           '.muddle/tags/package/apache',
                                           '.muddle/tags/package/bsd',
                                           '.muddle/tags/package/gpl*',
                                           '.muddle/tags/package/lgpl',
                                           '.muddle/tags/package/mpl',
                                           '.muddle/tags/package/zlib',
                                           '.muddle/tags/package/ukogl',
                                           '.muddle/tags/package/gnulibc',
                                           '.muddle/tags/package/linux',
                                           '.muddle/tags/package/busybox',
                                           '.muddle/tags/package/scripts',
                                           # We don't do deployment...
                                           '.muddle/tags/deployment',
                                           # And, in our subdomain
                                           'domains',
                                          ])
            # Check the "private" build description file has been replaced
            assert not same_content(d.join(target_dir, 'src', 'builds_multilicense', 'private.py'),
                                PRIVATE_BUILD_FILE)

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
