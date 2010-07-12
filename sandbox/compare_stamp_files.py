#! /usr/bin/env python

import os
import shutil
import sys
import subprocess

from ConfigParser import RawConfigParser

from muddled.commands import UnStamp
from muddled.vcs.bazaar import Bazaar
from muddled.utils import VersionStamp
from muddled.version_control import split_vcs_url


def canonical_path(path):
  """Expand a directory path out as far as it will go.
  """
  path = os.path.expandvars(path)       # $NAME or ${NAME}
  path = os.path.expanduser(path)       # ~
  path = os.path.normpath(path)
  path = os.path.abspath(path)          # copes with ., thing/../fred, etc.
  return path

class LocalError(Exception):
    pass

def svn_patch(name, directory, patch_filename):
    output_filename = os.path.join(os.getcwd(), '%s.svn_patch'%name)

    # Is this always the correct directory?
    if directory:
        working_set_dir = os.path.join(os.getcwd(), 'src', directory, name)
    else:
        working_set_dir = os.path.join(os.getcwd(), 'src', name)

    print '.. dir:', working_set_dir

    # Should we be checking the current revision of our checkout,
    # to make sure it matches?

    cmd = 'cd %s; patch -p0 < %s'%(working_set_dir, patch_filename)
    print '..',cmd
    rv = subprocess.call(cmd, shell=True)
    if rv:
        raise LocalError('patch returned %d'%rv)

def bzr_merge_from_send(name, directory, patch_filename):
    output_filename = os.path.join(os.getcwd(), '%s.bzr_send'%name)

    # Is this always the correct directory?
    if directory:
        working_set_dir = os.path.join(os.getcwd(), 'src', directory, name)
    else:
        working_set_dir = os.path.join(os.getcwd(), 'src', name)

    print '.. dir:', working_set_dir

    # Should we be checking the current revision of our checkout,
    # to make sure it matches?

    # The --pull argument appears to mean that we should pretend to have
    # done the required merge, just as if it were from the remote repository.
    # This should leave us with the correct revision number, and should mean
    # we do not need to commit
    #
    # Or: "bzr merge --pull" acts like "bzr pull" if it can, but reverts
    # to a "proper" merge if it cannot. So it is probably the right thing
    # to use...
    cmd = 'cd %s; bzr merge --pull %s'%(working_set_dir, patch_filename)
    print '..',cmd
    rv = subprocess.call(cmd, shell=True)
    if rv:
        raise LocalError('bzr send returned %d'%rv)

def bzr_send(name, directory, rev1, rev2, output_dir, manifest_filename):

    output_filename = '%s.bzr_send'%name
    output_path = os.path.join(output_dir, output_filename)

    # Is this always the correct directory?
    if directory:
        working_set_dir = os.path.join(os.getcwd(), 'src', directory, name)
    else:
        working_set_dir = os.path.join(os.getcwd(), 'src', name)

    print '.. dir:', working_set_dir

    # *Should* check that neither of the requested revision numbers
    # are above the revno of the checkout we have to hand? Anyway,
    # probably the checks in Bazaar.revision_to_checkout() are what
    # we would want to be doing...

    cmd = 'cd %s; bzr send --output=%s --revision=%s..%s -v'%(working_set_dir,
            output_path, rev1, rev2)
    print '..',cmd
    rv = subprocess.call(cmd, shell=True)
    print '.. Return code',rv
    if rv:
        raise LocalError('bzr send for %s returned %d'%(name,rv))

    with open(manifest_filename, 'a') as fd:
        # Lazily, just write this out by hand
        fd.write('[BZR %s]\n'
                 'checkout=%s\n'
                 'directory=%s\n'
                 'filename=%s\n'
                 'old=%s\n'
                 'new=%s\n'%(name, name, directory, output_filename,
                             rev1, rev2))

def svn_diff(name, directory, rev1, rev2, output_dir, manifest_filename):

    output_filename = '%s.svn_diff'%name
    output_path = os.path.join(output_dir, output_filename)

    # Is this always the correct directory?
    if directory:
        working_set_dir = os.path.join(os.getcwd(), 'src', directory, name)
    else:
        working_set_dir = os.path.join(os.getcwd(), 'src', name)

    print '.. dir:', working_set_dir

    # *Should* check that neither of the requested revision numbers
    # are above the revno of the checkout we have to hand? Anyway,
    # probably the checks in Bazaar.revision_to_checkout() are what
    # we would want to be doing...

    # 'svn diff' is probably the best we can do
    cmd = 'cd %s; svn diff -r %s:%s > %s'%(working_set_dir,
                                           rev1, rev2, output_path)
    print '..',cmd
    rv = subprocess.call(cmd, shell=True)
    if rv:
        raise LocalError('svn diff returned %d'%rv)

    with open(manifest_filename, 'a') as fd:
        # Lazily, just write this out by hand
        fd.write('[SVN %s]\n'
                 'checkout=%s\n'
                 'directory=%s\n'
                 'filename=%s\n'
                 'old=%s\n'
                 'new=%s\n'%(name, name, directory, output_filename,
                             rev1, rev2))


def write(stamp_file1, stamp_file2, output_dir_name):

    stamp1 = VersionStamp.from_file(stamp_file1)
    stamp2 = VersionStamp.from_file(stamp_file2)

    deleted, new, changed, problems = stamp1.compare(stamp2) # is this the right way round?

    print 'Deleted:  %d'%len(deleted)
    print 'New:      %d'%len(new)
    print 'Changed:  %d'%len(changed)
    print 'Problems: %d'%len(problems)

    output_dir = os.path.join(os.getcwd(), output_dir_name)
    if os.path.exists(output_dir):
        raise LocalError('Output directory %s already exists'%output_dir)

    os.mkdir(output_dir)
    manifest_filename = os.path.join(output_dir, 'MANIFEST.txt')

    for name, rev1, rev2 in changed:
        print "-- Determining changes for checkout %s, %s..%s"%(name, rev1, rev2)
        directory = stamp1[name].dir
        repository = stamp1[name].repo
        vcs, ignore = split_vcs_url(repository)
        if vcs == 'bzr':
            bzr_send(name, directory, rev1, rev2, output_dir, manifest_filename)
        elif vcs == 'svn':
            svn_diff(name, directory, rev1, rev2, output_dir, manifest_filename)
        elif vcs == 'git':
            print 'Unable to deal with VCS git'
            continue
        else:
            print 'Unable to deal with VCS %s'%vcs
            continue

    if deleted:
        print 'Deleted'
        for tup in deleted:
            print ' ',tup

    if new:
        print 'New'
        for tup in new:
            print ' ',tup

    if problems:
        print 'Problems'
        for tup in problems:
            print ' ',tup

def read(where):

    where = canonical_path(where)

    manifest = os.path.join(where, 'MANIFEST.txt')
    config = RawConfigParser()
    with open(manifest) as fd:
        config.readfp(fd)

    sections = config.sections()
    for section in sections:
        print 'Section %s'%section
        if section.startswith("BZR"):
            checkout = config.get(section, 'checkout')
            directory = config.get(section, 'directory')
            if directory == 'None':
                directory = None
            filename = config.get(section, 'filename')
            print '  Checkout %s, directory %s, filename %s'%(checkout,directory,filename)
            bzr_merge_from_send(checkout, directory,
                                os.path.join(where, filename))
        elif section.startswith("SVN"):
            checkout = config.get(section, 'checkout')
            directory = config.get(section, 'directory')
            if directory == 'None':
                directory = None
            filename = config.get(section, 'filename')
            print '  Checkout %s, directory %s, filename %s'%(checkout,directory,filename)
            svn_patch(checkout, directory, os.path.join(where, filename))
        else:
            print 'No support for %s yet - ignoring...'%section.split()[0]

def main(args):
    if len(args) < 2:
        print __doc__
        return
    if args[0] in ('-help', '--help', '-h'):
        print __doc__
        return

    PATCH_DIR = 'patches'

    if not os.path.isdir(os.path.join(os.getcwd(), '.muddle')):
        print '** Oops - not at the top level of a muddle build tree'
        return

    if args[0] in ('-f', '-force') and args[1] == '-write':
        args = args[1:]
        if os.path.exists(PATCH_DIR):
            shutil.rmtree(PATCH_DIR)

    if args[0] == '-write':
        args = args[1:]
        if len(args) != 2:
            print 'Must specify two stamp files'
        else:
            write(args[0], args[1], PATCH_DIR)
    elif args[0] == '-read':
        args = args[1:]
        if len(args) != 1:
            print 'Must specify the "patch" directory'
        else:
            read(args[0])
    else:
        print 'Must specify -help, -read or -write as first argument'
        return

if __name__ == '__main__':
    args = sys.argv[1:]
    main(args)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
