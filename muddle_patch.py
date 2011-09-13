#! /usr/bin/env python

"""muddle_patch.py

This command must be run within a muddle build tree (i.e., at the top level,
where the .muddle/ and src/ directories live).

Help
----

    muddle_patch.py help

will give this information (-h, -help or --help will also work)

Writing a patch directory
-------------------------

    muddle_patch.py write [-f[orce]] <our_stamp_file> <their_stamp_file> <patch_dir>

creates a directory containing the patches needed to update the remote build tree.

  * <our_stamp_file> must be an accurate (although not necessarily complete)
    description of "our" build tree (i.e., the build tree within which
    this command is being run)

    If <our_stamp_file> is '-' then a virtual stamp file will be calculated for
    this build tree, using the equivalent of::

        muddle stamp save -f

    (but without writing the stamp file to disk).

  * <their_stamp_file> describes the "far" build tree, which we want to patch
    to be like "our" build tree

  * <patch_dir> is the name of the directory in which to write the patches.

If '-f' or '-force' is specified, then if <patch_dir> already exists, it will
first be deleted. Otherwise, if <patch_dir> already exists, the command will
refuse to run.

Reading a patch directory
-------------------------

    muddle_patch.py read <patch_dir>

applies the patches in <patch_dir> to the current build tree.
"""

import os
import shutil
import sys
import subprocess

from ConfigParser import RawConfigParser

from muddled.commands import UnStamp
from muddled.vcs.bazaar import Bazaar
from muddled.utils import VersionStamp
from muddled.version_control import split_vcs_url

import muddled.utils
import muddled.mechanics

BZR_DO_IT_PROPERLY = False

class LocalError(Exception):
    pass

def canonical_path(path):
  """Expand a directory path out as far as it will go.
  """
  path = os.path.expandvars(path)       # $NAME or ${NAME}
  path = os.path.expanduser(path)       # ~
  path = os.path.normpath(path)
  path = os.path.abspath(path)          # copes with ., thing/../fred, etc.
  return path

def deduce_checkout_parent_dir(directory):
    # Is this always the correct directory?
    if directory:
        parent_dir = os.path.join(os.getcwd(), 'src', directory)
    else:
        parent_dir = os.path.join(os.getcwd(), 'src')
    return parent_dir

def deduce_checkout_dir(directory, leaf):
    # Is this always the correct directory?
    if directory:
        checkout_dir = os.path.join(os.getcwd(), 'src', directory, leaf)
    else:
        checkout_dir = os.path.join(os.getcwd(), 'src', leaf)
    return checkout_dir

# Subversion ==================================================================
def svn_patch(leaf, directory, patch_filename):

    checkout_dir = deduce_checkout_dir(directory, leaf)

    # Should we be checking the current revision of our checkout,
    # to make sure it matches?

    cmd = 'cd %s; patch -p0 < %s'%(checkout_dir, patch_filename)
    print '..',cmd
    rv = subprocess.call(cmd, shell=True)
    if rv:
        raise LocalError('patch returned %d'%rv)

def svn_diff(name, leaf, directory, rev1, rev2, output_dir, manifest_filename):

    output_filename = '%s.svn_diff'%name
    output_path = os.path.join(output_dir, output_filename)

    checkout_dir = deduce_checkout_dir(directory, leaf)

    # *Should* check that neither of the requested revision numbers
    # are above the revno of the checkout we have to hand? Anyway,
    # probably the checks in Bazaar.revision_to_checkout() are what
    # we would want to be doing...

    # 'svn diff' is probably the best we can do
    cmd = 'cd %s; svn diff -r %s:%s > %s'%(checkout_dir,
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
                 'patch=%s\n'
                 'old=%s\n'
                 'new=%s\n'%(name, leaf, directory, output_filename,
                             rev1, rev2))

# Bazaar ======================================================================
#
# In an ideal world, we would do::
#
#    bzr send --output=<patch_file> --revision=<r1>..<r2>> -v
#
# followed by::
#
#    bzr merge -pull <patch_file>
#
# at the other end. But at the moment (bzr 2.1.1 and 2.2.1, at least) that
# second command seems to blow up with a::
#
#    bzr: ERROR: bzrlib.errors.NoSuchRevision: CHKInventoryRepository('file:///home/tibs/sw/m3/muddle3_labels/muddle/tests/transient/test_build3/src/checkout1/.bzr/repository/') has no revision ('tibs@kynesim.co.uk-20101012153156-1wk54okzghenm296',)
#
#    *** Bazaar has encountered an internal error.  This probably indicates a
#        bug in Bazaar. <and other text pleading for help>
#
# The revision it grumbles about is the revision that is not meant to be present
# in the target checkout - i.e., the revision we are trying to "copy" over.
#
# I'm still hoping that this is something I am doing wrong, but I can't see what,
# and I'm sure this used to work. Also, there are suspiciously many bugs raised
# in Launchpad about an error very like this one.
#
# For the moment, the "solution" is to just do a diff-and-patch sequence, much
# like that we use for subversion. Which is not very nice, and loses us our
# history.

def bzr_merge_from_send(leaf, directory, patch_filename):

    checkout_dir = deduce_checkout_dir(directory, leaf)

    # Should we be checking the current revision of our checkout,
    # to make sure it matches?

    filename, extension = os.path.splitext(patch_filename)

    # The --pull argument appears to mean that we should pretend to have
    # done the required merge, just as if it were from the remote repository.
    # This should leave us with the correct revision number, and should mean
    # we do not need to commit
    #
    # Or: "bzr merge --pull" acts like "bzr pull" if it can, but reverts
    # to a "proper" merge if it cannot. So it is probably the right thing
    # to use...
    if extension == '.bzr_send':
        cmd = 'cd %s; bzr merge --pull %s'%(checkout_dir, patch_filename)
    elif extension == '.diff':
        cmd = 'cd %s; patch -p1 < %s'%(checkout_dir, patch_filename)
    else:
        raise LocalError("Unrecognised extension '%s' (not '.bzr_send' or '.diff')\n"
                         "  on patch file '%s'"%(extension, os.path.join(checkout_dir,
                                                                         patch_filename)))
    print '..',cmd
    rv = subprocess.call(cmd, shell=True)
    if rv:
        raise LocalError('bzr send returned %d'%rv)

def bzr_send(name, leaf, directory, rev1, rev2, output_dir, manifest_filename):

    if BZR_DO_IT_PROPERLY:
        output_filename = '%s.bzr_send'%name
    else:
        output_filename = '%s.diff'%name

    output_path = os.path.join(output_dir, output_filename)

    checkout_dir = deduce_checkout_dir(directory, leaf)

    # *Should* check that neither of the requested revision numbers
    # are above the revno of the checkout we have to hand? Anyway,
    # probably the checks in Bazaar.revision_to_checkout() are what
    # we would want to be doing...

    if BZR_DO_IT_PROPERLY:
        cmd = 'cd %s; bzr send --output=%s --revision=%s..%s -v'%(checkout_dir,
                output_path, rev1, rev2)
        print '..',cmd
        rv = subprocess.call(cmd, shell=True)
        if rv != 0:
            raise LocalError('bzr send for %s returned %d'%(name,rv))
    else:
        cmd = 'cd %s; bzr diff -p1 -r%s..%s -v > %s'%(checkout_dir, rev1, rev2, output_path)
        print '..',cmd
        rv = subprocess.call(cmd, shell=True)
        if rv != 1:     # for some reason
            raise LocalError('bzr send for %s returned %d'%(name,rv))

    with open(manifest_filename, 'a') as fd:
        # Lazily, just write this out by hand
        fd.write('[BZR %s]\n'
                 'checkout=%s\n'
                 'directory=%s\n'
                 'patch=%s\n'
                 'old=%s\n'
                 'new=%s\n'%(name, leaf, directory, output_filename,
                             rev1, rev2))

# Git =========================================================================
def git_am(leaf, directory, patch_directory):

    checkout_dir = deduce_checkout_dir(directory, leaf)

    # Should we be checking the current revision of our checkout,
    # to make sure it matches?

    files = os.listdir(patch_directory)
    files.sort()        # They should be in numeric order
    for filename in files:
        mailfile = os.path.join(patch_directory, filename)

        cmd = 'cd %s; git am %s'%(checkout_dir, mailfile)
        print '..',cmd
        rv = subprocess.call(cmd, shell=True)
        if rv:
            raise LocalError('git am returned %d'%rv)

def git_format_patch(name, leaf, directory, rev1, rev2, output_dir, manifest_filename):

    output_directory = '%s.git_patch'%name
    output_path = os.path.join(output_dir, output_directory)

    checkout_dir = deduce_checkout_dir(directory, leaf)

    # *Should* check that neither of the requested revision ids
    # are above the id of the checkout we have to hand?

    cmd = 'cd %s; git format-patch -o %s' \
          ' %s..%s'%(checkout_dir, output_path, rev1, rev2)
    print '..',cmd
    rv = subprocess.call(cmd, shell=True)
    if rv:
        raise LocalError('git format-patch returned %d'%rv)

    with open(manifest_filename, 'a') as fd:
        # Lazily, just write this out by hand
        fd.write('[GIT %s]\n'
                 'checkout=%s\n'
                 'directory=%s\n'
                 'patch=%s\n'
                 'old=%s\n'
                 'new=%s\n'%(name, leaf, directory, output_directory,
                             rev1, rev2))

# Tar =========================================================================
def tar_unpack(leaf, directory, tar_filename):

    parent_dir = deduce_checkout_parent_dir(directory)

    checkout_dir = deduce_checkout_dir(directory, leaf)
    if os.path.exists(checkout_dir):
        raise LocalError('Checkout directory %s alread exists\n'
                         '   not overwriting it with new data from %s'%(checkout_dir,
                             tar_filename))

    # Should we be checking the current revision of our checkout,
    # to make sure it matches?

    cmd = 'cd %s; tar -zxf %s %s'%(parent_dir, tar_filename, leaf)
    print '..',cmd
    rv = subprocess.call(cmd, shell=True)
    if rv:
        raise LocalError('tar -zxf returned %d'%rv)

def tar_pack(name, leaf, directory, output_dir, manifest_filename):

    tar_filename = '%s.tgz'%name
    tar_path = os.path.join(output_dir, tar_filename)

    parent_dir = deduce_checkout_parent_dir(directory)

    # *Should* check that neither of the requested revision ids
    # are above the id of the checkout we have to hand?

    cmd = 'tar -C %s -zcf %s %s'%(parent_dir, tar_path, leaf)
    print '..',cmd
    rv = subprocess.call(cmd, shell=True)
    if rv:
        raise LocalError('tar -zcf returned %d'%rv)

    with open(manifest_filename, 'a') as fd:
        # Lazily, just write this out by hand
        fd.write('[TAR %s]\n'
                 'checkout=%s\n'
                 'directory=%s\n'
                 'patch=%s\n'%(name, leaf, directory, tar_filename))

# =============================================================================
def find_builder(current_dir):
    try:
        build_root, build_domain = muddled.utils.find_root_and_domain(current_dir)
        if not build_root:
            raise LocalError('Cannot locate muddle build tree')

        # We should be able to get away with ``muddle_binary=__file__``
        # (even though that is clearly wrong!) since we do not intend to do any
        # building/environment setting - but it is still a bit naughty.
        return muddled.mechanics.load_builder(build_root,
                                              muddle_binary=__file__,
                                              default_domain=build_domain)
    except muddled.utils.GiveUp as f:
        raise LocalError("Error trying to load build tree: %s"%f)
    except muddled.utils.MuddleBug as e:
        raise LocalError("Cannot find build tree - %s"%e)

def determine_our_stamp(current_dir, quiet=False):
    if not quiet:
        print '-- Determining stamp for this build tree'
    builder = find_builder(current_dir)
    # I *think* we're best off with force=True (equivalent of -f)
    return VersionStamp.from_builder(builder, force=True, quiet=quiet)

def write(our_stamp_file, far_stamp_file, output_dir_name):

    current_dir = os.getcwd()

    output_dir = os.path.join(current_dir, output_dir_name)
    output_dir = canonical_path(output_dir)
    if os.path.exists(output_dir):
        raise LocalError('Output directory %s already exists'%output_dir)

    if our_stamp_file == '-':
        our_stamp, problems = determine_our_stamp(current_dir)
    else:
        our_stamp = VersionStamp.from_file(our_stamp_file)

    far_stamp = VersionStamp.from_file(far_stamp_file)

    # Determine what has changed with respect to the "far" stamp
    # - those changes are what we need to apply to make it the same as us...
    deleted, new, changed, problems = far_stamp.compare_checkouts(our_stamp)

    print
    print 'Summary: deleted %d, new %d, changed %d, problems %d'%(len(deleted),
            len(new), len(changed), len(problems))
    print

    os.mkdir(output_dir)
    manifest_filename = os.path.join(output_dir, 'MANIFEST.txt')

    for name, rev1, rev2 in changed:
        print "-- Determining changes for checkout %s, %s..%s"%(name, rev1, rev2)
        directory = our_stamp[name].dir
        leaf = our_stamp[name].co_leaf
        repository = our_stamp[name].repo
        vcs, ignore = split_vcs_url(repository)
        if vcs == 'bzr':
            bzr_send(name, leaf, directory, rev1, rev2, output_dir, manifest_filename)
        elif vcs == 'svn':
            svn_diff(name, leaf, directory, rev1, rev2, output_dir, manifest_filename)
        elif vcs == 'git':
            git_format_patch(name, leaf, directory, rev1, rev2, output_dir, manifest_filename)
        else:
            print 'Unable to deal with VCS %s'%vcs
            continue

    # For deleted checkouts, we definitely don't want to do anything
    # - if they're not being used anymore, leaving them around will not
    # hurt, and it is the simplest and safest option.
    if deleted:
        print
        print 'The following checkouts were deleted'
        for tup in deleted:
            print ' ',tup

    # TODO: For new checkouts, the best we can do is just to TAR up the
    # directory and copy it directly, and cross our fingers. We might as
    # well leave any VCS metadata intact. When restoring, it's probably
    # sensible to leave it up to the user to do a "muddle assert" of the
    # checked_out label, rather than try to second guess things...
    # ...so must remember to add a MANIFEST entry!
    # (if, at the other end, we're untarring a new checkout, we must check
    # if the directory already exists, and perhaps refuse to do it if so?)
    if new:
        for name, repo, rev, rel, dir, domain, leaf in new:
            print "-- Saving tarfile for new checkout %s"%name
            tar_pack(name, leaf, dir, output_dir, manifest_filename)

    if problems:
        print
        print 'There were the following problems'
        for tup in problems:
            print ' ',tup

def read(where):

    # TODO: Allow the user the option of just choosing a single checkout to
    # process - this makes it easier to recover if some patches worked, and
    # others didn't, but the user has figured out why and fixed things...

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
            filename = config.get(section, 'patch')
            print '  Checkout %s, directory %s, filename %s'%(checkout,directory,filename)
            bzr_merge_from_send(checkout, directory,
                                os.path.join(where, filename))
        elif section.startswith("SVN"):
            checkout = config.get(section, 'checkout')
            directory = config.get(section, 'directory')
            if directory == 'None':
                directory = None
            filename = config.get(section, 'patch')
            print '  Checkout %s, directory %s, filename %s'%(checkout,directory,filename)
            svn_patch(checkout, directory, os.path.join(where, filename))
        elif section.startswith("GIT"):
            checkout = config.get(section, 'checkout')
            directory = config.get(section, 'directory')
            if directory == 'None':
                directory = None
            patch_dir = config.get(section, 'patch')
            print '  Checkout %s, directory %s, patch_dir %s'%(checkout,directory,patch_dir)
            git_am(checkout, directory, os.path.join(where, patch_dir))
        elif section.startswith("TAR"):
            checkout = config.get(section, 'checkout')
            directory = config.get(section, 'directory')
            if directory == 'None':
                directory = None
            filename = config.get(section, 'patch')
            print '  Checkout %s, directory %s, filename %s'%(checkout,directory,filename)
            tar_unpack(checkout, directory, os.path.join(where, filename))
        else:
            print 'No support for %s yet - ignoring...'%section.split()[0]

def main(args):
    if not args:
        raise LocalError('Please specify help, read or write as the first argument')

    if args[0] in ('-help', '--help', '-h', 'help'):
        print __doc__
        return

    PATCH_DIR = 'patches'

    if not os.path.isdir(os.path.join(os.getcwd(), '.muddle')):
        raise LocalError('** Oops - not at the top level of a muddle build tree')

    if args[0] == 'write':

        args = args[1:]
        if len(args) < 3:
            raise LocalError('Must specify two stamp files and a "patch" directory')
        if len(args) > 4:
            raise LocalError('Too many arguments')

        our_stamp = args[-3]
        far_stamp = args[-2]
        patch_dir = args[-1]

        if len(args) == 3 and far_stamp in ('-f', '-force'):
            raise LocalError('Must specify two stamp files and a "patch" directory')

        if len(args) == 4:
            if args[0] in ('-f', '-force'):
                if os.path.exists(patch_dir):
                    shutil.rmtree(patch_dir)
            else:
                raise LocalError('Unexpected switch "%s" (not -f)'%args[0])

        write(our_stamp, far_stamp, patch_dir)

    elif args[0] == 'read':

        args = args[1:]
        if len(args) != 1:
            raise LocalError('Must specify the "patch" directory')
        else:
            read(args[0])

    else:
        raise LocalError('Must specify help, read or write as first argument')

if __name__ == '__main__':
    args = sys.argv[1:]
    try:
        main(args)
    except LocalError as what:
        print what

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
