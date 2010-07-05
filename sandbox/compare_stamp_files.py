#! /usr/bin/env python

import sys
import os

from muddled.commands import UnStamp
from muddled.vcs.bazaar import Bazaar
import subprocess

def compare(co1, co2):
    name1, repo1, rev1, rel1, dir1, domain1 = co1
    name2, repo2, rev2, rel2, dir2, domain2 = co2

    if not os.path.isdir(os.path.join(os.getcwd(), '.muddle')):
        print '** Oops - not at the top level of a muddle build tree'
        return

    output_filename = os.path.join(os.getcwd(), '%s.bzr_send'%name1)

    # Is this always the correct directory?
    working_set_dir = os.path.join(os.getcwd(), 'src', rel1)

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

    # Needing to do this is probably a sign that the UnStamp class is
    # doing things that should be done by a StampFile class...
    unstamp = UnStamp()

    repo_location1, build_desc1, domains1, checkouts1 = unstamp.read_file(stamp_file1)
    repo_location2, build_desc2, domains2, checkouts2 = unstamp.read_file(stamp_file2)

    # domainsX is a list of tuples, each (name, repo, desc)
    # checkoutsX is a list of tuples, each (name, repo, rev, rel, dir, domain)

    co1 = dict([ (x[0], x) for x in checkouts1 ])
    co2 = dict([ (x[0], x) for x in checkouts2 ])

    names = set(co1.keys() + co2.keys())

    # Drat - can't sort sets
    names = list(names)
    names.sort()

    # There should not be any names that are not in both checkouts...
    for name in names:
        try:
            if co1[name] == co2[name]:
                pass
            else:
                print 'Differing',name
                name1, repo1, rev1, rel1, dir1, domain1 = co1[name]
                name2, repo2, rev2, rel2, dir2, domain2 = co2[name]
                # For the moment, be *very* conservative on what we allow
                # to have changed - basically, just the revision
                # (arguably we shouldn't care about domain...)
                error = False
                if repo2 != repo1:
                    print '  Repository mismatch:',repo1,repo2
                    error = True
                if rev1 != rev2:
                    print '  Revision mismatch:',rev1,rev2
                if rel1 != rel2:
                    print '  Relative directory mismatch:',rel1,rel2
                    error = True
                if dir1 != dir2:
                    print '  Directory mismatch:',dir1,dir2
                    error = True
                if domain1 != domain2:
                    print '  Domain mismatch:',domain1,domain2
                    error = True
                if error:
                    print '  ...only revision mismatch is allowed'
                    continue
                compare(co1[name], co2[name])
        except KeyError as what:
            # We probably consider this a bug?
            if name in co1:
                print 'Missing',name,'in',stamp_file2
            else:
                print 'Missing',name,'in',stamp_file1

if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) != 2:
        print 'Must specify two stamp files'
    else:
        main(args[0], args[1])

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
