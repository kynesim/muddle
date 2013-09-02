#! /usr/bin/env python
"""Test muddle pull support for pulling build descriptions first

    $ ./test_pull_build_descs_first.py [-keep]

With -keep, do not delete the 'transient' directory used for the tests.

We're working with a structure as follows:

    <toplevel>
        <sub1>
            <sub3>
        <sub2>
            <sub4>
            <sub5>
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
from muddled.withdir import Directory, NewDirectory, TransientDirectory, NewCountedDirectory
from muddled.depend import Label, label_list_to_string

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
# A build description that includes two subdomains

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
    muddled.pkgs.make.medium(builder, "main_pkg", [role], "co0")

    # A package in a different role (which we never actually build)
    muddled.pkgs.make.simple(builder, "main_pkg", 'arm', "co0")

    include_domain(builder,
                   domain_name = "sub1",
                   domain_repo = "git+file://{repo}/sub1",
                   domain_desc = "builds/01.py")

    include_domain(builder,
                   domain_name = "sub2",
                   domain_repo = "git+file://{repo}/sub2",
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
                                 domain='sub1')
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub2',
                                 domain='sub2')

    # The 'arm' role is *not* a default role
    builder.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

sub1_BUILD_DESC = """ \
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
    muddled.pkgs.make.medium(builder, "main_pkg", [role], "co0")

    include_domain(builder,
                   domain_name = "sub3",
                   domain_repo = "git+file://{repo}/sub3",
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
                                 domain='sub3')

    builder.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

sub2_BUILD_DESC = """ \
# A build description that includes two subdomains

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
    muddled.pkgs.make.medium(builder, "main_pkg", [role], "co0")

    include_domain(builder,
                   domain_name = "sub4",
                   domain_repo = "git+file://{repo}/sub3",
                   domain_desc = "builds/01.py")

    include_domain(builder,
                   domain_name = "sub5",
                   domain_repo = "git+file://{repo}/sub4",
                   domain_desc = "builds/01.py")

    collect.deploy(builder, deployment)
    collect.copy_from_role_install(builder, deployment,
                                   role = role,
                                   rel = "", dest = "",
                                   domain = None)

    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub3',
                                 domain='sub3')
    collect.copy_from_deployment(builder, deployment,
                                 dep_name=deployment,   # always the same
                                 rel='',
                                 dest='sub4',
                                 domain='sub4')

    builder.add_default_role(role)
    builder.by_default_deploy(deployment)
"""

sub3_BUILD_DESC = """ \
# A simple build description

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep
from muddled.depend import Label

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    muddled.pkgs.make.medium(builder, "main_pkg", [role], "co0")

    # The 'everything' deployment is built from our single role, and goes
    # into deploy/everything.
    muddled.deployments.filedep.deploy(builder, "", "everything", [role])

    # If no role is specified, assume this one
    builder.add_default_role(role)
    # muddle at the top level will default to building this deployment
    builder.by_default_deploy("everything")
"""

sub4_BUILD_DESC = """ \
# A simple build description

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep
from muddled.depend import Label

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    muddled.pkgs.make.medium(builder, "main_pkg", [role], "co0")

    # The 'everything' deployment is built from our single role, and goes
    # into deploy/everything.
    muddled.deployments.filedep.deploy(builder, "", "everything", [role])

    # If no role is specified, assume this one
    builder.add_default_role(role)
    # muddle at the top level will default to building this deployment
    builder.by_default_deploy("everything")
"""

sub5_BUILD_DESC = """ \
# A simple build description

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep
from muddled.depend import Label

def describe_to(builder):
    role = 'x86'
    deployment = 'everything'

    muddled.pkgs.make.medium(builder, "main_pkg", [role], "co0")

    # The 'everything' deployment is built from our single role, and goes
    # into deploy/everything.
    muddled.deployments.filedep.deploy(builder, "", "everything", [role])

    # If no role is specified, assume this one
    builder.add_default_role(role)
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

def muddle_stdout(text):
    """Expand a format string ('text') containing {muddle} and run it.
    """
    return get_stdout(text.format(muddle=MUDDLE_BINARY), False)

def check_cmd(command, expected='', unsure=False):
    """Check we get the expected output from 'muddle -n <command>'

    * If 'expected' is given, then it is a string of the expected labels
      separated by spaces
    * If 'unsure' is true, then 'expected' is ignored, and we expect
      the result of the command to be:

        'Not sure what you want to <command>'

      and an error code.
    """
    retcode, result = run2('{muddle} -n {cmd}'.format(muddle=MUDDLE_BINARY,
                                                      cmd=command))
    result = result.strip()
    lines = result.split('\n  ')

    if unsure:
        command_words = command.split(' ')
        wanted = 'Not sure what you want to {cmd}'.format(cmd=command_words[0])
        line0 = lines[0].strip()
        if retcode:
            if line0 == wanted:
                return
            else:
                raise GiveUp('Wanted "{0}" but got "{1} and'
                             ' retcode {2}"'.format(wanted, line0, retcode))
        else:
            raise GiveUp('Expecting failure and "{0}",'
                         ' got "{1}"'.format(wanted, line0))
    elif retcode:
        raise GiveUp('Command failed with retcode {0},'
                     ' got unexpected {1}'.format(retcode, result))

    lines = lines[1:]               # Drop the "explanation"
    #map(string.strip, lines)
    got = ' '.join(lines)
    if got != expected:
        raise GiveUp('Expected "{0}", got "{1}"'.format(expected, got))

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

def make_repos_with_subdomain(root_dir):
    """Create git repositories for our subdomain tests.
    """
    repo = os.path.join(root_dir, 'repo')
    with NewDirectory('repo'):
        with NewDirectory('main'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, TOPLEVEL_BUILD_DESC.format(repo=repo))
            with NewDirectory('co0') as d:
                make_standard_checkout(d.where, 'main0', 'main')
        with NewDirectory('sub1'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, sub1_BUILD_DESC.format(repo=repo))
            with NewDirectory('co0') as d:
                make_standard_checkout(d.where, 'sub1', 'sub1')
        with NewDirectory('sub2'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, sub2_BUILD_DESC.format(repo=repo))
            with NewDirectory('co0') as d:
                make_standard_checkout(d.where, 'sub2', 'sub2')
        with NewDirectory('sub3'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, sub3_BUILD_DESC)
            with NewDirectory('co0') as d:
                make_standard_checkout(d.where, 'sub3', 'sub3')
        with NewDirectory('sub4'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, sub4_BUILD_DESC)
            with NewDirectory('co0') as d:
                make_standard_checkout(d.where, 'sub4', 'sub4')
        with NewDirectory('sub5'):
            with NewDirectory('builds') as d:
                make_build_desc(d.where, sub5_BUILD_DESC)
            with NewDirectory('co0') as d:
                make_standard_checkout(d.where, 'sub5', 'sub5')

def checkout_build_descriptions(root_dir, d):

    repo = os.path.join(root_dir, 'repo')
    muddle(['init', 'git+file://{repo}/main'.format(repo=repo), 'builds/01.py'])

    check_original_build_descs(d)

def checkout_amended_build_descriptions(root_dir, d):

    repo = os.path.join(root_dir, 'repo')
    muddle(['init', 'git+file://{repo}/main'.format(repo=repo), 'builds/01.py'])

    check_amended_build_descs(d)

def check_original_build_descs(d):
    """Check our build descriptions match the original specification.
    """
    check_files([d.join('src', 'builds', '01.py'),
                 d.join('domains', 'sub1', 'src', 'builds', '01.py'),
                 d.join('domains', 'sub1', 'domains', 'sub3', 'src', 'builds', '01.py'),
                 d.join('domains', 'sub2', 'src', 'builds', '01.py'),
                 d.join('domains', 'sub2', 'domains', 'sub4', 'src', 'builds', '01.py'),
                 d.join('domains', 'sub2', 'domains', 'sub5', 'src', 'builds', '01.py'),
                ])

def check_amended_build_descs(d):
    """Check our build descriptions match the changed specification.
    """
    check_files([d.join('src', 'builds', '01.py'),
                 d.join('domains', 'sub1', 'src', 'builds', '01.py'),
                 d.join('domains', 'sub1', 'domains', 'sub4', 'src', 'builds', '01.py'),
                 d.join('domains', 'sub1', 'domains', 'sub5', 'src', 'builds', '01.py'),
                 d.join('domains', 'sub2', 'src', 'builds', '01.py'),
                 d.join('domains', 'sub2', 'domains', 'sub3', 'src', 'builds', '01.py'),
                ])

def amend_sub1_build_desc_and_push(root_dir, d):
    repo = os.path.join(root_dir, 'repo')
    with Directory('domains'):
        with Directory('sub1'):
            with Directory('src'):
                with Directory('builds'):
                    append('01.py', '\n# A harmless change\n')
                    git('commit 01.py -m "A harmless change"')
                    # We'd better push with git, since we've hacked the build description
                    git('push origin HEAD')

def swap_subdomains_and_push(root_dir, d):
    """Swap the build descriptions for subdomains 1 and 2.
    """

    repo = os.path.join(root_dir, 'repo')
    with Directory('domains'):
        with Directory('sub1'):
            with Directory('src'):
                with Directory('builds'):
                    touch('01.py', sub2_BUILD_DESC.format(repo=repo))
                    git('commit 01.py -m "Swap build desc with sub2"')
                    # We'd better push with git, since we've hacked the build description
                    git('push origin HEAD')
        with Directory('sub2'):
            with Directory('src'):
                with Directory('builds'):
                    touch('01.py', sub1_BUILD_DESC.format(repo=repo))
                    git('commit 01.py -m "Swap build desc with sub1"')
                    # We'd better push with git, since we've hacked the build description
                    git('push origin HEAD')

def change_something_else_and_push(root_dir, d):
    repo = os.path.join(root_dir, 'repo')
    with Directory('domains'):
        with Directory('sub1'):
            with Directory('src'):
                with Directory('co0'):
                    append('sub1.c', '\n// A harmless change\n')
                    git('commit sub1.c -m "A harmless change"')
                    # We'd better be able to push with muddle!
                    muddle(['push'])

def main(args):

    keep = False
    if args:
        if len(args) == 1 and args[0] == '-keep':
            keep = True
        else:
            print __doc__
            raise GiveUp('Unexpected arguments %s'%' '.join(args))

    # Working in a local transient directory seems to work OK
    # although if it's anyone other than me they might prefer
    # somewhere in $TMPDIR...
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with TransientDirectory(root_dir, keep_on_error=True, keep_anyway=keep) as root_d:
        banner('MAKE REPOSITORIES')
        make_repos_with_subdomain(root_dir)

        with NewCountedDirectory('build.original') as d1:
            banner('CHECK REPOSITORIES OUT INTO FIRST BUILD')
            checkout_build_descriptions(root_dir, d1)
            muddle(['checkout', '_all'])
            orig_dir = d1.where


        banner('TEST A SIMPLE CHANGE')
        # With an insignificant change, this should work identically by
        # both mechanisms

        with NewCountedDirectory('build.simple.noreload.pull') as d2:
            banner('CHECK REPOSITORIES OUT', 2)
            checkout_build_descriptions(root_dir, d2)
            muddle(['checkout', '_all'])
            pass1_noreload_dir = d2.where

        with NewCountedDirectory('build.simple.default.pull') as d3:
            banner('CHECK REPOSITORIES OUT', 2)
            checkout_build_descriptions(root_dir, d3)
            muddle(['checkout', '_all'])
            pass1_default_dir = d3.where

        with Directory(orig_dir) as d:
            banner('AMEND SUB1 BUILD DESCRIPTION AND PUSH', 2)
            amend_sub1_build_desc_and_push(root_dir, d)

        with Directory(pass1_noreload_dir) as d:
            banner('PULL IN THE ORIGINAL MANNER', 2)
            muddle(['pull', '-noreload', '_all'])
            check_original_build_descs(d)
            check_file_v_text(d.join('.muddle', '_just_pulled'),
                              [
                              'checkout:(sub1)builds/checked_out\n',
                              ])

        with Directory(pass1_default_dir) as d:
            banner('PULL WITH BUILD DESCRIPTIONS PULLED FIRST', 2)
            muddle(['pull', '_all'])
            check_original_build_descs(d)
            check_file_v_text(d.join('.muddle', '_just_pulled'),
                              [
                              'checkout:(sub1)builds/checked_out\n',
                              ])


        banner('TEST A MORE COMPLICATED CHANGE')
        # Since we're changing the layout of the build, this should
        # work substantially differently by the two mechanisms

        with NewCountedDirectory('build.swap.noreload.pull') as d2:
            banner('CHECK REPOSITORIES OUT', 2)
            checkout_build_descriptions(root_dir, d2)
            muddle(['checkout', '_all'])
            pass2_noreload_dir = d2.where

        with NewCountedDirectory('build.swap.default.pull') as d3:
            banner('CHECK REPOSITORIES OUT', 2)
            checkout_build_descriptions(root_dir, d3)
            muddle(['checkout', '_all'])
            pass2_default_dir = d3.where

        with Directory(orig_dir) as d:
            banner('SWAP SUBDOMAIN BUILD DESCRIPTIONS AND PUSH', 2)
            swap_subdomains_and_push(root_dir, d)

        with Directory(pass2_noreload_dir) as d:
            banner('PULL IN THE ORIGINAL MANNER', 2)
            banner('PULL THE FIRST', 3)
            muddle(['pull', '-noreload', '_all'])
            check_original_build_descs(d)
            check_file_v_text(d.join('.muddle', '_just_pulled'),
                              [
                              'checkout:(sub1)builds/checked_out\n',
                              'checkout:(sub2)builds/checked_out\n',
                              ])
            banner('PULL THE SECOND', 3)
            # Our *second* pull should bring us to the same place as the
            # single pull with the "slow" mechanism would achieve.
            #
            # Note that it shouldn't matter where in the build tree we
            # do this command from...
            with Directory('src'):
                with Directory('builds'):
                    muddle(['pull', '-noreload', '_all'])
            # We should have files following the amended build description
            check_amended_build_descs(d)
            # But we have not deleted the files from the original description
            check_original_build_descs(d)
            check_file_v_text(d.join('.muddle', '_just_pulled'),
                              [
                              'checkout:(sub1(sub4))co0/checked_out\n',
                              'checkout:(sub1(sub5))co0/checked_out\n',
                              'checkout:(sub2(sub3))co0/checked_out\n',
                              ])

        with Directory(pass2_default_dir) as d:
            banner('PULL WITH BUILD DESCRIPTIONS PULLED FIRST', 2)
            # Note that it shouldn't matter where in the build tree we
            # do this command from...
            with Directory('src'):
                with Directory('builds'):
                    muddle(['pull', '_all'])
            # We should have files following the amended build description
            check_amended_build_descs(d)
            # But we have not deleted the files from the original description
            check_original_build_descs(d)
            check_file_v_text(d.join('.muddle', '_just_pulled'),
                              [
                              'checkout:(sub1)builds/checked_out\n',
                              'checkout:(sub1(sub4))builds/checked_out\n',
                              'checkout:(sub1(sub4))co0/checked_out\n',
                              'checkout:(sub1(sub5))builds/checked_out\n',
                              'checkout:(sub1(sub5))co0/checked_out\n',
                              'checkout:(sub2)builds/checked_out\n',
                              'checkout:(sub2(sub3))builds/checked_out\n',
                              'checkout:(sub2(sub3))co0/checked_out\n',
                              ])


        banner('TEST NOT CHANGING THE BUILD DESCRIPTIONS')
        # This should work identically by both mechanisms

        with NewCountedDirectory('build.nodesc.noreload.pull') as d2:
            banner('CHECK REPOSITORIES OUT', 2)
            checkout_amended_build_descriptions(root_dir, d2)
            muddle(['checkout', '_all'])
            pass3_noreload_dir = d2.where

        with NewCountedDirectory('build.nodesc.default.pull') as d3:
            banner('CHECK REPOSITORIES OUT', 2)
            checkout_amended_build_descriptions(root_dir, d3)
            muddle(['checkout', '_all'])
            pass3_default_dir = d3.where

        with Directory(orig_dir) as d:
            banner('CHANGE SOMETHING NOT A BUILD DESCRIPTION AND PUSH', 2)
            change_something_else_and_push(root_dir, d)

        with Directory(pass3_noreload_dir) as d:
            banner('PULL IN THE ORIGINAL MANNER', 2)
            muddle(['pull', '-noreload', '_all'])
            check_amended_build_descs(d)
            check_file_v_text(d.join('.muddle', '_just_pulled'),
                              [
                              'checkout:(sub1)co0/checked_out\n',
                              ])

        with Directory(pass3_default_dir) as d:
            banner('PULL WITH BUILD DESCRIPTIONS PULLED FIRST', 2)
            muddle(['pull', '_all'])
            check_amended_build_descs(d)
            check_file_v_text(d.join('.muddle', '_just_pulled'),
                              [
                              'checkout:(sub1)co0/checked_out\n',
                              ])


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
