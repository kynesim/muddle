#! /usr/bin/env python

"""Install the TODO and //== pre-commit hook.

Usage: install.py  [-f]  [<target> [<target> [...]]

For each <target> (default is the current directory), look in that directory
for a .git directory, and install the pre-commit hook therein.

Refuses if there already is a pre-commit hook, unless -f is specified.

(nb: if -f is not specified, checks all the <target> directories before it does
anything).
"""

import os
import sys
import shutil

def normalise_path(path):
    path = os.path.expanduser(path)
    path = os.path.abspath(path)
    path = os.path.normpath(path)     # remove double slashes, etc.
    return path

def main(args):

    targets = []
    force = False
    while args:

        word = args.pop(0)
        if word in ('-h', '--help', '-help'):
            print __doc__
            return
        elif word == '-f':
            force = True
        else:
            targets.append(normalise_path(word))

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

    this_file = __file__
    this_dir = normalise_path(os.path.split(this_file)[0])
    pre_commit_file = os.path.join(this_dir, 'pre-commit')
    check_names_file = os.path.join(this_dir, 'FullCheckNames.py')

    print pre_commit_file
    print check_names_file

    for hook_dir in hook_dirs:
        shutil.copy2(pre_commit_file, hook_dir)
        shutil.copy2(check_names_file, hook_dir)

if __name__ == '__main__':
    args = sys.argv[1:]
    sys.exit(main(args))

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
