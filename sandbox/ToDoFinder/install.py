#! /usr/bin/env python

"""Install the TODO and //== pre-commit hook.

Usage: install.py  [-f] [-n]  [<target> [<target> [...]]
       install.py  [-f] [-n]  -muddle [<muddle-root>]

For each <target> (default is the current directory), look in that directory
for a .git directory, and install the pre-commit hook therein.

Refuses if there already is a pre-commit hook, unless -f is specified.

(nb: if -f is not specified, checks all the <target> directories before it does
anything).

If -n is specified, say what we would do, but don't do it.

(If both -n and -f are specified, then -n "wins")

Alternatively, specify -muddle to insert a pre-commit hook in each .git
directory of each checkout in the current muddle tree (or the muddle tree
at <muddle-root> if that is specified). This requires that the muddle command
be "muddle".
"""

import os
import sys
import shutil
import subprocess

def normalise_path(path):
    path = os.path.expanduser(path)
    path = os.path.abspath(path)
    path = os.path.normpath(path)     # remove double slashes, etc.
    return path

def main(args):

    targets = []
    force = False
    dry_run = False
    muddle = False
    muddle_root = None

    while args:

        word = args.pop(0)
        if word in ('-h', '--help', '-help'):
            print __doc__
            return
        elif word == '-f':
            force = True
        elif word == '-n':
            dry_run = True
        elif word == '-muddle':
            muddle = True
            # I don't like making -muddle have to be last on the command line,
            # but it's the simplest thing to do...
            if args:
                if len(args) != 1:
                    print 'Too many arguments after -muddle'
                    return 1
                muddle_root = args[0]
                break
        else:
            targets.append(normalise_path(word))

    this_file = __file__
    this_dir = normalise_path(os.path.split(this_file)[0])

    if muddle:
        # Rather horribly, make sure we use the muddle we came with
        our_muddle = normalise_path(os.path.join(this_dir, '..', '..', 'muddle'))
        if not muddle_root:
            # We use shell=True in case "muddle" is (for instance) an alias
            # rather than on the path
            try:
                cmd = [our_muddle, 'query', 'root']
                muddle_root = subprocess.check_output(cmd)
            except subprocess.CalledProcessError as e:
                print '%r returned %d and said:'%(' '.join(cmd), e.returncode)
                print e.output
                return 1
            muddle_root.strip()
        print 'muddle_root', muddle_root

        cmd = [our_muddle, '--tree', muddle_root, 'query', 'checkout-dirs']
        try:
            checkout_report = subprocess.check_output(cmd)
        except subprocess.CalledProcessError as e:
            print '%r returned %d and said:'%(' '.join(cmd), e.returncode)
            print e.output
            return 1

        checkout_paths = {}
        lines = checkout_report.split('\n')
        for line in lines:
            if not line or line.startswith('> Checkout'):
                continue
            words = line.split()
            checkout = words[0]
            rest = line[len(checkout):].lstrip()
            if rest.startswith('->'):
                path = rest[len('->'):].lstrip()
            else:
                print 'Expected "->" in %r'%line
                return 1
            checkout_paths[checkout] = path

        cmd = [our_muddle, '--tree', muddle_root, 'query', 'checkout-vcs']
        try:
            checkout_report = subprocess.check_output(cmd)
        except subprocess.CalledProcessError as e:
            print '%r returned %d and said:'%(' '.join(cmd), e.returncode)
            print e.output
            return 1

        git_checkouts = []
        lines = checkout_report.split('\n')
        for line in lines:
            if not line or line.startswith('> Checkout'):
                continue
            words = line.split()
            checkout = words[0]
            vcs = words[-1]
            if vcs == 'git':
                git_checkouts.append(checkout)
            else:
                print 'Ignoring %s checkout %s'%(vcs, checkout)

        for checkout in git_checkouts:
            targets.append(os.path.join(muddle_root, checkout_paths[checkout]))

        if not targets:
            print 'No git checkouts in %s'%muddle_root
            return 1

    if not targets:
        targets.append(normalise_path('.'))

    errors = {}
    hook_dirs = []
    for target in targets:
        if not os.path.exists(target):
            errors[target] = 'No such path'
        elif not os.path.isdir(target):
            errors[target] = 'Not a directory'
        git_dir = os.path.join(target, '.git')
        if not os.path.exists(git_dir):
            errors[target] = 'No .git in'
        hook_dir = os.path.join(git_dir, 'hooks')
        if not os.path.exists(git_dir):
            errors[target] = 'No hooks dir in'
        pre_commit = os.path.join(hook_dir, 'pre-commit')
        if os.path.exists(pre_commit):
            errors[target] = 'Existing pre-commit'
        hook_dirs.append(hook_dir)

    if errors:
        for key in sorted(errors.keys()):
            print '%-20s %s'%(errors[key], key)

        if force:
            print 'Continuing anyway'
        else:
            print 'Giving up'
            return 1

    pre_commit_file = os.path.join(this_dir, 'pre-commit')
    check_names_file = os.path.join(this_dir, 'FullCheckNames.py')

    print pre_commit_file
    print check_names_file

    for hook_dir in hook_dirs:
        if dry_run:
            print 'Copy %s to %s'%(pre_commit_file, hook_dir)
            print ' and %s to %s'%(check_names_file, hook_dir)
        else:
            shutil.copy2(pre_commit_file, hook_dir)
            shutil.copy2(check_names_file, hook_dir)

if __name__ == '__main__':
    args = sys.argv[1:]
    sys.exit(main(args))

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
