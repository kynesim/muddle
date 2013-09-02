#! /usr/bin/env python
"""Test the muddle release mechanism, including release stamp files

    $ ./test_release.py [-keep]

With -keep, do not delete the 'transient' directory used for the tests.
"""

import os
import pprint
import sys
import textwrap
import traceback

from ConfigParser import NoSectionError
from subprocess import CalledProcessError

from support_for_tests import *
try:
    import muddled.cmdline
except ImportError:
    # Try one level up
    sys.path.insert(0, get_parent_dir(__file__))
    import muddled.cmdline

from muddled.utils import GiveUp, normalise_dir, LabelType, LabelTag
from muddled.withdir import Directory, NewDirectory, TransientDirectory, NewCountedDirectory
from muddled.depend import Label, label_list_to_string
from muddled.version_stamp import VersionStamp, ReleaseStamp, ReleaseSpec

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

MUDDLE_MAKEFILE_with_version = """\
# Trivial muddle makefile
all:
\t@echo Make all for '$(MUDDLE_LABEL)'
\t$(CC) $(MUDDLE_SRC)/{progname}.c -o $(MUDDLE_OBJ)/{progname}

# Generating our version.h at configure time seems appropriate
config: $(MUDDLE_OBJ_INCLUDE)/version.h
\t@echo Make configure for '$(MUDDLE_LABEL)'

# Construct a version.h including the build release name and version
$(MUDDLE_OBJ_INCLUDE)/version.h: version.h.in
\t-mkdir -p $(MUDDLE_OBJ_INCLUDE)
\t$(MUDDLE) subst $< $@

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
# A build description that includes two subdomains

import os
import shutil

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect
from muddled.mechanics import include_domain
from muddled.depend import Label, package
from muddled.utils import LabelType
from muddled.repository import Repository
from muddled.version_control import checkout_from_repo

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "main_pkg", [role], "main_co")
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role], "second_co")

    # A package in a different role (which we never actually build)
    muddled.pkgs.make.simple(builder, "main_pkg", 'arm', "main_co")

    include_domain(builder,
                   domain_name = "subdomain1",
                   domain_repo = "git+file://{repo}/subdomain1",
                   domain_desc = "builds/01.py")

    include_domain(builder,
                   domain_name = "subdomain2",
                   domain_repo = "git+file://{repo}/subdomain2",
                   domain_desc = "builds/01.py")

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role = role,
                                   rel = "", dest = "",
                                   domain = None)

    # And collect stuff from our subdomains
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub1',
                                 domain='subdomain1')
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub2',
                                 domain='subdomain2')

    # The 'arm' role is *not* a default role
    builder.add_default_role(role)
    builder.by_default_deploy(deployment)

    # A single specific label
    builder.add_to_release_build(Label.from_string('package:(subdomain2)second_pkg{{x86}}/*'))
    #
    # Adding a special name is tested in subdomain2, not here, since we want to
    # be able to check that we *don't* build everything "by accident" for a
    # release
    #
    # A list of items
    builder.add_to_release_build([package('second_pkg', 'x86', domain='subdomain2'),
                                  package('main_pkg', 'x86'),
                                  package('first_pkg', 'x86'),
                                 ])
    # And with wildcards
    builder.add_to_release_build(Label.from_string('package:(subdomain1)second_pkg{{*}}/*'))

def release_from(builder, release_dir):

    # Useful directory-finding methods, all take a label to the appropriate
    # type:
    #
    # * builder.checkout_path
    # * builder.package_obj_path
    # * builder.package_install_path
    # * builder.deploy_path
    #
    # Thus, since we know that the build description has been loaded
    # (i.e., "describe_to(builder)" has been executed), we can work out
    # where to get stuff we might want to copy into the release directory.

    f0 = package('first_pkg', 'x86')
    m0 = package('main_pkg', 'x86')
    s1 = package('second_pkg', 'x86', domain='subdomain1')
    s2 = package('second_pkg', 'x86', domain='subdomain2')

    install_path = builder.package_install_path

    # Copy our executables, with permissions intact
    shutil.copy(os.path.join(install_path(f0), 'first'), release_dir)
    shutil.copy(os.path.join(install_path(m0), 'main0'), release_dir)
    shutil.copy(os.path.join(install_path(s1), 'second'),
                os.path.join(release_dir, 'second1'))
    shutil.copy(os.path.join(install_path(s2), 'second'),
                os.path.join(release_dir, 'second2'))

"""

SUBDOMAIN1_BUILD_DESC = """ \
# A build description that includes a subdomain

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple
import muddled.deployments.collect as collect
from muddled.mechanics import include_domain
from muddled.depend import Label

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    # Checkout ..
    muddled.pkgs.make.medium(builder, "main_pkg", [role], "main_co")
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role], "second_co")

    include_domain(builder,
                   domain_name = "subdomain3",
                   domain_repo = "git+file://{repo}/subdomain3",
                   domain_desc = "builds/01.py")

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role = role,
                                   rel = "", dest = "",
                                   domain = None)

    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # also the same
                                 rel='',
                                 dest='sub3',
                                 domain='subdomain3')

    builder.add_default_role(role)
    builder.by_default_deploy(deployment)

    # Add some labels to the release here
    # This will *not* get propagated up to the top-level release
    builder.add_to_release_build([Label.from_string('package:main_pkg{{x86}}/*'),
                                  Label.from_string('package:(subdomain3)main_pkg{{x86}}/*'),
                                 ])
    # And, being awkward, add a label that does not exist
    builder.add_to_release_build(Label.from_string('package:fred{{arm}}/*'))
"""

SUBDOMAIN2_BUILD_DESC = """ \
# A simple build description

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep
from muddled.depend import Label

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    muddled.pkgs.make.medium(builder, "main_pkg", [role], "main_co")
    muddled.pkgs.make.medium(builder, "first_pkg", [role], "first_co")
    muddled.pkgs.make.medium(builder, "second_pkg", [role], "second_co")

    # The 'everything' deployment is built from our single role, and goes
    # into deploy/everything.
    muddled.deployments.filedep.deploy(builder, "", "everything", [role])

    # If no role is specified, assume this one
    builder.add_default_role(role)
    # muddle at the top level will default to building this deployment
    builder.by_default_deploy("everything")

    # Add a special name to the release here
    # This will *not* get propagated up to the top-level release
    builder.add_to_release_build('_default_deployments')
    # And another label, just for fun
    builder.add_to_release_build(Label.from_string('package:main_pkg{x86}/*'))
"""

SUBDOMAIN3_BUILD_DESC = SUBDOMAIN2_BUILD_DESC

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

VERSION_H_IN_SRC = """\
#ifndef PROJECT99_VERSION_FILE
#define PROJECT99_VERSION_FILE
#define BUILD_VERSION "${MUDDLE_RELEASE_NAME}: $(MUDDLE_RELEASE_VERSION}"
#endif
"""

def make_checkout_bare():
    """Use nasty trickery to turn our checkout bare...
    """
    # 1. Lose the working set
    files = os.listdir('.')
    for file in files:
        if file != '.git':
            os.remove(file)
    # 2. Move the contents of .git/ up one level, and delete the empty .git/
    files = os.listdir('.git')
    for file in files:
        os.rename(os.path.join('.git', file), file)
    os.rmdir('.git')
    # 3. Tell git what we've done
    git('config --bool core.bare true')

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

    make_checkout_bare()

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

    make_checkout_bare()

def make_version_checkout(co_dir, progname, desc):
    """Take some of the repetition out of making checkouts.
    """
    git('init')
    touch('{progname}.c'.format(progname=progname),
            MAIN_C_SRC.format(progname=progname))
    touch('version.h.in', VERSION_H_IN_SRC)
    touch('Makefile.muddle', MUDDLE_MAKEFILE_with_version.format(progname=progname))
    git('add {progname}.c Makefile.muddle version.h.in'.format(progname=progname))
    git('commit -a -m "Commit {desc} checkout {progname}"'.format(desc=desc,
        progname=progname))

    make_checkout_bare()

def make_repos_with_subdomain(repo):
    """Create git repositories for our subdomain tests.
    """
    with NewDirectory('repo'):
        with NewDirectory('main'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, TOPLEVEL_BUILD_DESC.format(repo=repo))
            with NewDirectory('main_co') as d:
                make_version_checkout(d.where, 'main0', 'main')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')
        with NewDirectory('subdomain1'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN1_BUILD_DESC.format(repo=repo))
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'subdomain1', 'subdomain1')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')
        with NewDirectory('subdomain2'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN2_BUILD_DESC)
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'subdomain2', 'subdomain2')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')
        with NewDirectory('subdomain3'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, SUBDOMAIN3_BUILD_DESC)
            with NewDirectory('main_co') as d:
                make_standard_checkout(d.where, 'subdomain3', 'subdomain3')
            with NewDirectory('first_co') as d:
                make_standard_checkout(d.where, 'first', 'first')
            with NewDirectory('second_co') as d:
                make_standard_checkout(d.where, 'second', 'second')

def check_stamp_file_starts(filename, repo, desc, versions_repo):
    with open(filename) as fd:
        lines = fd.readlines()
    newlines = []
    for line in lines:
        if line[0] == '#':
            continue
        while line and line[-1] in ('\n', '\r'):
            line = line[:-1]
        if line:
            newlines.append(line)

    if newlines[:11] != ['[STAMP]',
                         'version = 2',
                         '[ROOT]',
                         'repository = %s'%repo,
                         'description = %s'%desc,
                         'versions_repo = %s'%versions_repo,
                         ]:
        pprint.pprint(newlines)
        raise GiveUp('Unexpected content in plain stamp file %s'%filename)

def check_release_file_starts(filename, name, version, archive, compression,
                              repo, desc, versions_repo):
    with open(filename) as fd:
        lines = fd.readlines()
    newlines = []
    for line in lines:
        if line[0] == '#':
            continue
        while line and line[-1] in ('\n', '\r'):
            line = line[:-1]
        if line:
            newlines.append(line)

    expected = ['[STAMP]',
                'version = 2',
                '[RELEASE]',
                'name = %s'%name,
                'version = %s'%version,
                'archive = %s'%archive,
                'compression = %s'%compression,
                '[ROOT]',
                'repository = %s'%repo,
                'description = %s'%desc,
                'versions_repo = %s'%versions_repo,
                ]
    if newlines[:11] != expected:
        print '--- Expected:'
        pprint.pprint(expected)
        print '--- Got:'
        pprint.pprint(newlines[:11])
        raise GiveUp('Unexpected content in release stamp file %s'%filename)

def read_env_as_dict(package):
    text = captured_muddle(['query', 'make-env', package])
    lines = text.split('\n')
    muddle_env = {}
    for line in lines:
        if line.startswith('MUDDLE_'):
            line.rstrip()
            parts = line.split('=')
            name = parts[0]
            value = '='.join(parts[1:])
            muddle_env[name] = value
    return muddle_env

def check_program(d, path, progname, outname=None):
    """Check a program has been built and produces the expected result.
    """
    if outname is None:
        outname = progname
    fullpath = d.join(*path)
    fullname = d.join(fullpath, progname)
    if not os.path.exists(fullname):
        raise GiveUp('Program {0} does not exist'.format(fullname))
    result = run1(fullname, show_output=True)
    if result != 'Program {0}\n'.format(outname):
        raise GiveUp('Program {0} unexpectdly printed out "{1}"'.format(fullpath, result))

def test_ReleaseStamp_basics(d):
    banner('RELEASE STAMP BASICS')

    banner('Write "empty" release file', 2)
    r0 = ReleaseStamp()
    r0.write_to_file('r1.release')
    check_release_file_starts('r1.release', '<REPLACE THIS>', '<REPLACE THIS>',
                              'tar', 'gzip', '', '', '')

    # We can read that as a normal VersionStamp
    banner('Read "empty" release file as stamp', 2)
    s = VersionStamp.from_file('r1.release')
    s.write_to_file('r1.stamp')
    check_stamp_file_starts('r1.stamp', '', '', '')

    # We can't read in r1.release as a release, because of the name and version
    banner('Read "empty" release file as release (it should fail)', 2)
    try:
        r1 = ReleaseStamp.from_file('r1.release')
    except GiveUp as e:
        if 'Release name "<REPLACE THIS>" is not allowed' not in str(e):
            raise GiveUp('Unexpected error reading r1.release: %s'%e)

    # We can't read in r1.stamp as a release, because of the name and version
    banner('Read "empty" stamp file as release (it should fail)', 2)
    try:
        r1 = ReleaseStamp.from_file('r1.stamp')
    except NoSectionError as e:
        if e.section != 'RELEASE':
            raise GiveUp('Expected section "RELEASE" to be missing, but got'
                         ' NoSectionError for "%s"'%e.section)
    except Exception as e:
        raise GiveUp('Unexpected error reading r1.stamp: %s'%e)

    # We can't set a bad name, version, archive or compression
    try:
        r0.release_spec.name = '+++'
    except GiveUp as e:
        if 'Release name "+++" is not allowed' not in str(e):
            raise GiveUp('Unexpected error trying to write bad name: %s'%e)
    r0.release_spec.name = 'project99'
    try:
        r0.release_spec.version = '+++'
    except GiveUp as e:
        if 'Release version "+++" is not allowed' not in str(e):
            raise GiveUp('Unexpected error trying to write bad version: %s'%e)
    r0.release_spec.version = '1.2.3'
    try:
        r0.release_spec.archive = 'fred'
    except GiveUp as e:
        if 'Release archive "fred" is not allowed' not in str(e):
            raise GiveUp('Unexpected error trying to write bad version: %s'%e)
    r0.release_spec.archive = 'tar'
    try:
        r0.release_spec.compression = 'fred'
    except GiveUp as e:
        if 'Release compression "fred" is not allowed' not in str(e):
            raise GiveUp('Unexpected error trying to write bad version: %s'%e)
    r0.release_spec.compression = 'bzip2'
    r0.write_to_file('r2.release')

    # But when we get it right, it is OK
    check_release_file_starts('r2.release', 'project99', '1.2.3',
                              'tar', 'bzip2', '', '', '')

def test_guess_version_number(d, repo):
    banner('TEST GUESS VERSION NUMBER')
    banner('Check out build tree, and stamp it as a release', 2)
    with NewCountedDirectory('build.version-number') as build1:
        r = 'git+file://{repo}/main'.format(repo=repo)
        d = 'builds/01.py'
        v = '{root}/versions'.format(root=r)
        muddle(['init', r, d])
        muddle(['checkout', '_all'])
        muddle(['stamp', 'release', 'simple', '-next'])
        with Directory('versions'):
            check_specific_files_in_this_dir(['.git', 'simple_v0.0.release'])

        touch('versions/simple_v0.01.release', '')
        muddle(['stamp', 'release', 'simple', '-next'])
        with Directory('versions'):
            check_specific_files_in_this_dir(['.git',
                                             'simple_v0.0.release',
                                             'simple_v0.01.release',
                                             'simple_v0.2.release',
                                             ])

        # Whilst 0.03 and 0.3 are "the same" version, that doesn't matter
        # if they already exist - we only care about the next version
        touch('versions/simple_v0.3.release', '')
        touch('versions/simple_v0.03.release', '')
        muddle(['stamp', 'release', 'simple', '-next'])
        with Directory('versions'):
            check_specific_files_in_this_dir(['.git',
                                             'simple_v0.0.release',
                                             'simple_v0.01.release',
                                             'simple_v0.2.release',
                                             'simple_v0.03.release',
                                             'simple_v0.3.release',
                                             'simple_v0.03.release',
                                             'simple_v0.4.release',
                                             ])

        # We require major.minor, not any other variation - we won't
        # take notice of a file that doesn't match
        touch('versions/simple_v3.release', '')
        muddle(['stamp', 'release', 'simple', '-next'])
        with Directory('versions'):
            check_specific_files_in_this_dir(['.git',
                                             'simple_v0.0.release',
                                             'simple_v0.01.release',
                                             'simple_v0.2.release',
                                             'simple_v0.03.release',
                                             'simple_v0.3.release',
                                             'simple_v0.03.release',
                                             'simple_v0.4.release',
                                             'simple_v0.5.release',
                                             'simple_v3.release',
                                             ])
        touch('versions/simple_v3.1.1.release', '')
        muddle(['stamp', 'release', 'simple', '-next'])
        with Directory('versions'):
            check_specific_files_in_this_dir(['.git',
                                             'simple_v0.0.release',
                                             'simple_v0.01.release',
                                             'simple_v0.2.release',
                                             'simple_v0.03.release',
                                             'simple_v0.3.release',
                                             'simple_v0.03.release',
                                             'simple_v0.4.release',
                                             'simple_v0.5.release',
                                             'simple_v0.6.release',
                                             'simple_v3.release',
                                             'simple_v3.1.1.release',
                                             ])

        touch('versions/simple_v1.999999999.release', '')
        muddle(['stamp', 'release', 'simple', '-next'])
        with Directory('versions'):
            check_specific_files_in_this_dir(['.git',
                                             'simple_v0.0.release',
                                             'simple_v0.01.release',
                                             'simple_v0.2.release',
                                             'simple_v0.03.release',
                                             'simple_v0.3.release',
                                             'simple_v0.03.release',
                                             'simple_v0.4.release',
                                             'simple_v0.5.release',
                                             'simple_v0.6.release',
                                             'simple_v3.release',
                                             'simple_v3.1.1.release',
                                             'simple_v1.999999999.release',
                                             'simple_v1.1000000000.release',
                                             ])

def test_simple_release(d, repo):
    banner('TEST SIMPLE RELEASE')
    banner('Check out build tree, and stamp it as a release', 2)
    with NewCountedDirectory('build1') as build1:
        r = 'git+file://{repo}/main'.format(repo=repo)
        d = 'builds/01.py'
        v = '{root}/versions'.format(root=r)
        muddle(['init', r, d])
        muddle(['checkout', '_all'])
        muddle(['stamp', 'release', 'simple', 'v1.0'])

        rfile = os.path.join(build1.where, 'versions', 'simple_v1.0.release')
        check_release_file_starts(rfile, 'simple', 'v1.0', 'tar', 'gzip',
                                  r, d, v)

        UNSET = '(unset)'
        muddle_env = read_env_as_dict('first_pkg{x86}')
        if not (muddle_env['MUDDLE_RELEASE_NAME'] == UNSET and
                muddle_env['MUDDLE_RELEASE_VERSION'] == UNSET and
                muddle_env['MUDDLE_RELEASE_HASH'] == UNSET):
            print 'MUDDLE_RELEASE_NAME=%s'%muddle_env['MUDDLE_RELEASE_NAME']
            print 'MUDDLE_RELEASE_VERSION=%s'%muddle_env['MUDDLE_RELEASE_VERSION']
            print 'MUDDLE_RELEASE_HASH=%s'%muddle_env['MUDDLE_RELEASE_HASH']
            raise GiveUp('Expected the MUDDLE_RELEASE_ values to be all (unset)')

    banner('Try "muddle release" using that stamp', 2)
    with NewCountedDirectory('build2') as build2:
        muddle(['release', rfile])
        check_release_directory(build2)

def test_test_release(d, repo):
    banner('TEST TEST RELEASE')
    banner('Check out build tree, and stamp it as a release', 2)
    with NewCountedDirectory('build-test') as test_build:
        r = 'git+file://{repo}/main'.format(repo=repo)
        d = 'builds/01.py'
        v = '{root}/versions'.format(root=r)
        muddle(['init', r, d])
        muddle(['checkout', '_all'])
        muddle(['stamp', 'release', 'simple', 'v1.0'])

        rfile = os.path.join(test_build.where, 'versions', 'simple_v1.0.release')
        check_release_file_starts(rfile, 'simple', 'v1.0', 'tar', 'gzip',
                                  r, d, v)

        UNSET = '(unset)'
        muddle_env = read_env_as_dict('first_pkg{x86}')
        if not (muddle_env['MUDDLE_RELEASE_NAME'] == UNSET and
                muddle_env['MUDDLE_RELEASE_VERSION'] == UNSET and
                muddle_env['MUDDLE_RELEASE_HASH'] == UNSET):
            print 'MUDDLE_RELEASE_NAME=%s'%muddle_env['MUDDLE_RELEASE_NAME']
            print 'MUDDLE_RELEASE_VERSION=%s'%muddle_env['MUDDLE_RELEASE_VERSION']
            print 'MUDDLE_RELEASE_HASH=%s'%muddle_env['MUDDLE_RELEASE_HASH']
            raise GiveUp('Expected the MUDDLE_RELEASE_ values to be all (unset)')

        banner('Try "muddle release -test" using that stamp, in the same directory', 2)
        muddle(['release', '-test', rfile])
        check_release_directory(test_build)

def check_release_directory(release_dir):
    """Check the contents of our release directory, and the release.
    """
    if not os.path.exists(os.path.join('.muddle', 'Release')):
        raise GiveUp('Cannot see .muddle/Release')
    if not os.path.exists(os.path.join('.muddle', 'ReleaseSpec')):
        raise GiveUp('Cannot see .muddle/ReleaseSpec')

    rspec = ReleaseSpec.from_file(os.path.join('.muddle', 'ReleaseSpec'))
    if not (rspec.name == 'simple' and rspec.version == 'v1.0' and
            rspec.archive == 'tar' and rspec.compression == 'gzip'):
        raise GiveUp('Unexpected values in %r'%rspec)

    banner('"muddle pull _all" should fail', 3)
    # Try a command that we don't think should be allowed, because this
    # is a release build
    try:
        text = captured_muddle(['pull', '_all'])
        print text
        raise GiveUp('"muddle pull _all" did not fail')
    except CalledProcessError as e:
        if 'Command pull is not allowed in a release build' not in e.output:
            raise GiveUp('Unexpected error text in "muddle pull _all":'
                         ' %d, %s'%(e.returncode, e.output.strip()))
        else:
            # Just so the user knows this, correctly, didn't work
            print e.output
    except Exception as e:
        raise GiveUp('Unexpected error in "muddle pull _all":'
                     ' %s %s'%(e.__class__.__name__, e))

    banner('muddle environment should be set appropriately', 3)
    muddle_env = read_env_as_dict('first_pkg{x86}')
    if not (muddle_env['MUDDLE_RELEASE_NAME'] == 'simple' and
            muddle_env['MUDDLE_RELEASE_VERSION'] == 'v1.0' and
            muddle_env['MUDDLE_RELEASE_HASH'] == rspec.hash):
        print 'MUDDLE_RELEASE_NAME=%s'%muddle_env['MUDDLE_RELEASE_NAME']
        print 'MUDDLE_RELEASE_VERSION=%s'%muddle_env['MUDDLE_RELEASE_VERSION']
        print 'MUDDLE_RELEASE_HASH=%s'%muddle_env['MUDDLE_RELEASE_HASH']
        raise GiveUp('Expected the MUDDLE_RELEASE_ values to be %s, %s, %s'%(
            'simple', 'v1.0', rspec.hash))

    banner('"muddle query release -labels" should report correctly', 3)
    text = captured_muddle(['query', 'release', '-labels'])
    check_text_v_lines(text,[
                             'package:(subdomain1)second_pkg{*}/*',
                             'package:(subdomain2)second_pkg{x86}/*',
                             'package:first_pkg{x86}/*',
                             'package:main_pkg{x86}/*',
                            ])

    banner('"muddle -n build _release" should name the correct labels', 3)
    text = captured_muddle(['-n', 'build', '_release'])
    check_text_v_lines(text,['Asked to build:',
                             '  package:first_pkg{x86}/postinstalled',
                             '  package:main_pkg{x86}/postinstalled',
                             '  package:(subdomain1)second_pkg{x86}/postinstalled',
                             '  package:(subdomain2)second_pkg{x86}/postinstalled',
                            ])

    # Down in our subdomains
    banner('Checking variants in the subdomains', 3)
    with Directory('domains/subdomain1'):
        # Temporarily, stop it being a subdomain(!)
        os.remove('.muddle/am_subdomain')
        text = captured_muddle(['query', 'release', '-labels'])
        check_text_v_lines(text,[
                                 'package:(subdomain3)main_pkg{x86}/*',
                                 'package:fred{arm}/*',
                                 'package:main_pkg{x86}/*',
                                ])

        # This is where we should catch specifying a non-existant label
        try:
            text = captured_muddle(['-n', 'build', '_release'])
            raise GiveUp('"muddle -n build _release" should have failed')
        except CalledProcessError as e:
            check_text_v_lines(e.output,[
                '',
                'Argument "package:fred{arm}/*" does not match any target labels',
                '  It expands to package:fred{arm}/*',
                '  Package name "fred" is not defined in the build description',
                '  Role {arm} is not defined in the build description',
                ])
        # Muddle should, in fact, put that back for us again later on,
        # next time we do something from higher up, which realises (again)
        # that this is a subdomain.

    with Directory('domains/subdomain2'):
        # Temporarily, stop it being a subdomain(!)
        os.remove('.muddle/am_subdomain')
        text = captured_muddle(['query', 'release', '-labels'])
        check_text_v_lines(text,['_default_deployments',
                                 'package:main_pkg{x86}/*',
                                ])

        # Here, we should see the "muddle" command expands "_release" all
        # the way down to specific labels, including that "_default_deployments"
        banner('"muddle -n build _release" should name the correct labels')
        text = captured_muddle(['-n', 'build', '_release'])
        check_text_v_lines(text,['Asked to build:',
                                 '  package:first_pkg{x86}/postinstalled',
                                 '  package:main_pkg{x86}/postinstalled',
                                 '  package:second_pkg{x86}/postinstalled',
                                ])
        # Ditto

    banner('"muddle build _release" should have produced (only) the expected files', 3)
    check_program(release_dir, ['install', 'x86'], 'first')
    check_program(release_dir, ['install', 'x86'], 'main0')
    check_program(release_dir, ['domains', 'subdomain1', 'install', 'x86'], 'second')
    check_program(release_dir, ['domains', 'subdomain2', 'install', 'x86'], 'second')
    # And those should be all we've built
    with Directory(release_dir.join('install', 'x86')):
        check_specific_files_in_this_dir(['first', 'main0'])
    with Directory(release_dir.join('domains', 'subdomain1')) as d:
        with Directory(d.join('install', 'x86')):
            check_specific_files_in_this_dir(['second'])
        with Directory(d.join('domains', 'subdomain3')):
            # We shouldn't have built anything in subdomain3
            check_specific_files_in_this_dir(['.muddle', 'src'])
    with Directory(release_dir.join('domains', 'subdomain2', 'install', 'x86')):
        check_specific_files_in_this_dir(['second'])

    # The version.h file should have the correct content
    banner('Checking generated version.h', 3)
    same_content(release_dir.join('obj', 'main_pkg', 'x86', 'include', 'version.h'),
            textwrap.dedent("""\
                            #ifndef PROJECT99_VERSION_FILE
                            #define PROJECT99_VERSION_FILE
                            #define BUILD_VERSION "simple: v1.0"
                            #endif
                            """))

    # The release should have created a tarball directory, with a copy
    # of the release stamp file therein
    tarball_dir = 'simple_v1.0_%s'%rspec.hash

    with Directory(release_dir.join(tarball_dir)) as td:
        banner('tarball directory should have a release file in it', 3)
        if not os.path.exists('simple_v1.0.release'):
            raise GiveUp('Cannot see tarball directory or release file therein')

        banner('tarball directory should have required programs in it', 3)
        check_program(td, [], 'first')
        check_program(td, [], 'main0')
        check_program(td, [], 'second1', 'second')
        check_program(td, [], 'second2', 'second')

        banner('tarball directory should have nothing else in it', 3)
        check_specific_files_in_this_dir(['simple_v1.0.release',
                                          'first',
                                          'main0',
                                          'second1',
                                          'second2',
                                         ])

def test_issue_249_single_digit_version_number(d, repo):
    banner('TEST ISSUE 249')
    banner('Check out build tree, and stamp it as release version 1', 2)
    with NewCountedDirectory('build.version-number') as build:
        r = 'git+file://{repo}/main'.format(repo=repo)
        d = 'builds/01.py'
        v = '{root}/versions'.format(root=r)
        muddle(['init', r, d])
        muddle(['checkout', '_all'])
        muddle(['stamp', 'release', 'simple', '1'])
        with Directory('versions'):
            check_specific_files_in_this_dir(['.git', 'simple_1.release'])
            check_release_file_starts('simple_1.release', 'simple', '1',
                                      'tar', 'gzip', r, d, v)

def main(args):

    keep = False
    if args:
        if len(args) == 1 and args[0] == '-keep':
            keep = True
        else:
            print __doc__
            return

    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))
    repo = os.path.join(root_dir, 'repo')

    with TransientDirectory(root_dir, keep_on_error=True, keep_anyway=keep) as root_d:

        test_ReleaseStamp_basics(root_d)

        banner('CREATING REPOSITORIES')
        make_repos_with_subdomain(repo)

        test_simple_release(root_d, repo)
        test_test_release(root_d, repo)
        test_guess_version_number(root_d, repo)

        test_issue_249_single_digit_version_number(root_d, repo)


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
