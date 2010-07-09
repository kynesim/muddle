#! /usr/bin/env python

import sys
import os

from muddled.commands import UnStamp
from muddled.vcs.bazaar import Bazaar
from muddled.utils import VersionStamp
import subprocess

def bzr_send(name, relative_dir, rev1, rev2):
    if not os.path.isdir(os.path.join(os.getcwd(), '.muddle')):
        print '** Oops - not at the top level of a muddle build tree'
        return

    output_filename = os.path.join(os.getcwd(), '%s.bzr_send'%name)

    # Is this always the correct directory?
    working_set_dir = os.path.join(os.getcwd(), 'src', relative_dir)

    print '.. dir:', working_set_dir

    # *Should* check that neither of the requested revision numbers
    # are above the revno of the checkout we have to hand? Anyway,
    # probably the checks in Bazaar.revision_to_checkout() are what
    # we would want to be doing...

    cmd = 'cd %s; bzr send --output=%s --revision=%s..%s -v'%(working_set_dir,
            output_filename, rev1, rev2)
    print '..',cmd
    rv = subprocess.call(cmd, shell=True)
    print '.. Return code',rv

def main(stamp_file1, stamp_file2):

    stamp1 = VersionStamp.from_file(stamp_file1)
    stamp2 = VersionStamp.from_file(stamp_file2)

    deleted, new, changed, problems = stamp1.compare(stamp2) # is this the right way round?

    print 'Deleted:  %d'%len(deleted)
    print 'New:      %d'%len(new)
    print 'Changed:  %d'%len(changed)
    print 'Problems: %d'%len(problems)

    for name, rev1, rev2 in changed:
        print "'Send'ing checkout %s, %s..%s"%(name, rev1, rev2)
        relative_dir = stamp1[name].name
        bzr_send(name, relative_dir, rev1, rev2)

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


if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) != 2:
        print 'Must specify two stamp files'
    else:
        main(args[0], args[1])

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
