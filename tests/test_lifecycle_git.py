#! /usr/bin/env python
"""Test simple project lifecycle in git

    $ ./test_lifecycle_git.py

Git must be installed.
"""

import os
import shutil
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

from muddled.utils import GiveUp, normalise_dir
from muddled.utils import Directory, NewDirectory, TransientDirectory

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

DEVT_BUILD = """\
# A very simple build description
import os

import muddled.pkgs.make

from muddled.depend import checkout
from muddled.version_control import checkout_from_repo

def add_package(builder, pkg_name, role, co_name=None):
    if co_name is None:
        co_name = pkg_name
    root_repo = builder.build_desc_repo
    repo = root_repo.copy_with_changes(co_name)
    checkout_from_repo(builder, checkout(co_name), repo)
    muddled.pkgs.make.simple(builder, pkg_name, role, co_name)

def describe_to(builder):
    builder.build_name = '{build_name}'
    # A single checkout
    add_package(builder, 'package', 'x86', co_name='checkout')
"""

def test_git_lifecycle(root_d):
    """A linear sequence of plausible actions...
    """

    # Repositories
    with NewDirectory(root_d.join('repos')) as d:
        with NewDirectory(d.join('builds')):
            git('init --bare')
        with NewDirectory(d.join('checkout')):
            git('init --bare')
        with NewDirectory(d.join('versions')):
            git('init --bare')

        repo_url = 'git+file://%s'%d.where

    build_name = 'TestBuild'

    # First build tree
    with NewDirectory(root_d.join('build1')) as d:
        muddle(['bootstrap', repo_url, build_name])
        with Directory('src'):
            with Directory('builds'):
                os.remove('01.py')
                touch('01.py', DEVT_BUILD.format(build_name=build_name))
                git('add 01.py')  # Because we changed it since the last 'git add'
                git('commit -m "First commit of build description"')
                muddle(['push'])
            with NewDirectory('checkout'):
                touch('Makefile.muddle', MUDDLE_MAKEFILE)
                git('init')
                git('add Makefile.muddle')
                git('commit Makefile.muddle -m "A checkout needs a makefile"')
                muddle(['import'])
                muddle(['push'])

        muddle(['stamp', 'version'])
        with Directory('versions'):
            git('add TestBuild.stamp')
            git('commit -m "First stamp"')
            muddle(['stamp', 'push'])

        muddle(['query', 'checkout-id', 'builds'])
        muddle(['query', 'checkout-id', 'checkout'])


def main(args):

    if args:
        print __doc__
        return

    # Choose a place to work, rather hackily
    #root_dir = os.path.join('/tmp','muddle_tests')
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with TransientDirectory(root_dir, keep_on_error=True) as root_d:
        banner('TEST LIFECYCLE (GIT)')
        test_git_lifecycle(root_d)

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
