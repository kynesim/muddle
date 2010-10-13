#! /usr/bin/env python
"""Test the general muddle imports

As a *very* simple test, importing all of the following should just work
"""

import muddled

import muddled.__main__

import muddled.cmdline
import muddled.commands
import muddled.cpiofile
import muddled.db
import muddled.depend
import muddled.deployment
import muddled.env_store
import muddled.filespec
import muddled.instr
import muddled.mechanics
import muddled.pkg
import muddled.rewrite
import muddled.rrw
import muddled.subst
import muddled.test
import muddled.utils
import muddled.version_control
import muddled.xmlconfig

import muddled.checkouts.multilevel
import muddled.checkouts.simple
import muddled.checkouts.twolevel

import muddled.deployments.collect
import muddled.deployments.cpio
import muddled.deployments.filedep
import muddled.deployments.tools

import muddled.pkgs.aptget
import muddled.pkgs.deb
import muddled.pkgs.depmod_merge
import muddled.pkgs.initscripts
import muddled.pkgs.linux_kernel
import muddled.pkgs.make
import muddled.pkgs.setvars
import muddled.pkgs.version

# The 'profiles' directory does not have an __init__.py file,
# and is thus not a (sub)package, so we can't import it
#import muddled.profiles.app

import muddled.vcs.bazaar
import muddled.vcs.file
import muddled.vcs.git
import muddled.vcs.svn
