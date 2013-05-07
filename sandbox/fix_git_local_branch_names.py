#! /usr/bin/env python

"""
This fixup script walks your source checkout directories to correct any
discrepancies caused by incorrect checkout behaviour by earlier versions
of muddle's git interface when non-default branch names are in use.

The issue occurs when the build description instructs muddle to check
out a branch other than "master" from the remote repository. The correct
branch is checked out, but it is named "master" locally which confuses
later invocations of "muddle push" and "muddle pull".

This script looks at all git repositories within the current muddle root
and compares their local default branch against the remote branch name.
If a discrepancy is found, muddle attempts to fix it by fetching the
remote branch correctly and deleting the local branch. This will not work
if there have been committed-but-unmerged changes on the incorrectly-named
branch; the script aborts so you can rectify the situation by hand.

Invoke this script from somewhere within a muddle tree:
    python /path/to/fix_local_branch_names.py [--dry-run] [-v]

Options:
  --dry-run, -n: Interrogate the checkouts as usual but only print out
                 the manipulating commands that it would have run.
  --verbose, -v: Be verbose about what we're doing
"""

import os
import re
import sys
import subprocess

try:
    from muddled.utils import GiveUp
except ImportError:
    # try one dir up.
    this_file = os.path.abspath(__file__)
    this_dir = os.path.split(this_file)[0]
    parent_dir = os.path.split(this_dir)[0]
    sys.path.insert(0, parent_dir)
    from muddled.utils import GiveUp
    # This still fails? add the directory containing muddled to your PYTHONPATH

from muddled.utils import run0,get_cmd_data
from muddled.cmdline import find_and_load
import muddled.vcs.git

##########################################################

def maybe_run_cmd(cmd, dry_run, verbose):
    if dry_run:
        print "(DRY RUN) > %s"%cmd
    else:
        run0(cmd, show_output=verbose)

##########################################################

def _do_cmdline(args):
    original_dir = os.getcwd()
    original_env = os.environ.copy()
    dry_run = False
    verbose = False

    # TODO: allow switches after args.
    while args:
        word = args[0]
        if word in ('-h', '--help', '-?'):
            print __doc__
            return
        elif word in ('--dry-run', '-n'):
            dry_run = True
        elif word in ('-v', '--verbose'):
            verbose = True
        elif word[0] == '-':
            raise GiveUp, "Unexpected command line option %s"%word
        else:
            break
        args = args[1:]

    if len(args) != 0:
        raise GiveUp, "Unexpected non-option arguments given"

    builder = find_and_load(original_dir, muddle_binary=None)
    # Don't bother determining muddle_binary: our invocation of find_and_load
    # doesn't make use of it. (Tibs writes: it's only needed for when
    # running makefiles, for when they use $(MUDDLE).)

    if not builder:
        raise GiveUp("Cannot find a build tree.")

    rootrepo = builder.db.RootRepository_pathfile.get()

    rules = builder.all_checkout_rules()
    rr = []
    for r in rules:
        co_dir = builder.db.get_checkout_path(r.target)
        if isinstance(r.action.vcs, muddled.vcs.git.Git):
            if verbose: print "In %s:"%co_dir
            os.chdir(co_dir)
            raw = get_cmd_data("git show-ref --heads", verbose = verbose)
            raw_heads = raw[1].rstrip('\n').split('\n')
            pat = re.compile("[0-9a-f]+ refs/heads/(.+)")
            heads = set()
            for h in raw_heads:
                m = pat.match(h)
                if m is None:
                    raise GiveUp("Unparseable output from git: %s"%h)
                heads.add(m.group(1))

            g = r.action.vcs
            #print "heads is %s"%heads.__str__()
            if g.branch is not None:
                if g.branch in heads:
                    if verbose:
                        print "%s: ok (has %s)"%(co_dir,g.branch)
                else:
                    bfrom='master'
                    # desired branch not found; if we have a master then try to fixup:
                    if bfrom in heads:
                        #if verbose:
                        print "===\nFixing %s: %s --> %s"%(co_dir,bfrom,g.branch)
                        (rc, lines, igno) = get_cmd_data("git status --porcelain -uall", verbose=verbose)
                        lines = lines.rstrip("\n")
                        if lines != '':
                            if not verbose: print "> git status --porcelain -uall"
                            print ">>%s<<"%lines
                            print ("Uncommitted changes or untracked files found in %s, deal with these before continuing"%co_dir)
                            raise GiveUp
                        maybe_run_cmd("git fetch origin %s"%(g.branch), dry_run, verbose)
                        maybe_run_cmd("git fetch origin %s:%s"%(g.branch,g.branch), dry_run, verbose)
                        maybe_run_cmd("git checkout %s"%g.branch, dry_run, verbose)
                        maybe_run_cmd("git config branch.%s.remote origin"%g.branch, dry_run, verbose)
                        maybe_run_cmd("git config branch.%s.merge %s"%(g.branch,g.branch), dry_run, verbose)
                        try:
                            maybe_run_cmd("git branch -d %s"%bfrom, dry_run, verbose)
                        except GiveUp:
                            print "\n* * * HEALTH WARNING * * *"
                            print "Unmerged changes were found committed to the '%s' branch in %s"%(bfrom,co_dir)
                            print "YOU MUST MERGE THESE INTO '%s' YOURSELF OR LOSE THEM!"%g.branch
                            #print "This script will not revisit this checkout."
                            print "The relevant changes are:"
                            run0("git log --oneline --topo-order --graph --decorate=short %s..%s"%(g.branch,bfrom))
                            raise
                    else:
                        raise GiveUp("Error: %s wants a branch named '%s', does not have one, and does not have a '%s' either - I don't know how to fix this"%(co_dir, g.branch, bfrom))
            else:
                # want master, don't care about others
                if verbose:
                    print "%s heads are: %s"%(co_dir,heads)
                if not 'master' in heads:
                    raise GiveUp("Error: %s wants a 'master' branch but does not have one, I don't know how to fix this"%co_dir)
        else:
            if verbose:
                print "Ignoring %s (not powered by git)"%co_dir

##########################################################

if __name__ == "__main__":
    try:
        _do_cmdline(sys.argv[1:])
    except GiveUp as f:
        print "%s"%f
        sys.exit(1)
