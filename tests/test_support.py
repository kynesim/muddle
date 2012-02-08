#! /usr/bin/env python

"""Test support functions and stuff.

For once, intended to be safe for use with ``from test_support import *``
"""

import os
import shutil
import subprocess
import sys
import traceback
from stat import *      # Honestly, this is recommended

def get_parent_dir(this_file=None):
    """Determine the path of our parent directory.

    If 'this_file' is not given, then we'll return the parent directory
    of this file...
    """
    if this_file is None:
        this_file = __file__
    this_file = os.path.abspath(this_file)
    this_dir = os.path.split(this_file)[0]
    parent_dir = os.path.split(this_dir)[0]
    return parent_dir

PARENT_DIR = get_parent_dir()

try:
    import muddled.cmdline
except ImportError:
    # Try one level up
    sys.path.insert(0,PARENT_DIR)
    import muddled.cmdline

from muddled.utils import GiveUp, MuddleBug

# We know (strongly assume!) that there should be a 'muddle' available
# in the same directory as the 'muddled' package - we shall use that as
# the muddle program
MUDDLE_BINARY_DIR = os.path.abspath(get_parent_dir(muddled.cmdline.__file__))
MUDDLE_BINARY = os.path.join(MUDDLE_BINARY_DIR, 'muddle')

# Make up for not necessarily having a PYTHONPATH that helps
# Assume the location of muddle_patch.py relative to ourselves
MUDDLE_PATCH_COMMAND = '%s/muddle_patch.py'%(PARENT_DIR)

class ShellError(GiveUp):
    def __init__(self, cmd, retcode):
        msg = "Shell command '%s' failed with retcode %d"%(cmd, retcode)
        super(GiveUp, self).__init__(msg)
        self.retcode=retcode

def shell(cmd, verbose=True):
    """Run a command in the shell
    """
    if verbose:
        print '>> %s'%cmd
    retcode = subprocess.call(cmd, shell=True)
    if retcode:
        raise ShellError(cmd, retcode)

def get_stdout(cmd, verbose=True):
    """Run a command in the shell, and grab its (standard) output.
    """
    if verbose:
        print ">> %s"%cmd
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    stdoutdata, stderrdata = p.communicate()
    retcode = p.returncode
    if retcode:
        raise ShellError(cmd, retcode)
    return stdoutdata

def get_stdout2(cmd, verbose=True):
    """Run a command in the shell, and grab its (standard) output and retcode

    Returns (retcode, stdout)
    """
    if verbose:
        print ">> %s"%cmd
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    stdoutdata, stderrdata = p.communicate()
    retcode = p.returncode
    return retcode, stdoutdata


def muddle(args, verbose=True):
    """Pretend to be muddle

    I already know it's going to be a pain remembering that the first
    argument is a list of words...
    """
    if verbose:
        print '++ muddle %s'%(' '.join(args))
    # In order to cope with soft links in directory structures, muddle
    # tries to use the current PWD as set by the shell. Since we don't
    # know what called us, we need to do it by hand.
    old_pwd = os.environ.get('PWD', None)
    try:
        os.environ['PWD'] = os.getcwd()
        muddled.cmdline.cmdline(args, MUDDLE_BINARY)
    finally:
        if old_pwd:
            os.environ['PWD'] = old_pwd

def git(cmd, verbose=True):
    """Run a git command
    """
    shell('%s %s'%('git',cmd), verbose)

def bzr(cmd, verbose=True):
    """Run a bazaar command
    """
    shell('%s %s'%('bzr',cmd), verbose)

def svn(cmd, verbose=True):
    """Run a subversion command
    """
    shell('%s %s'%('svn',cmd), verbose)

def cat(filename):
    """Print out the contents of a file.
    """
    with open(filename) as fd:
        print '++ cat %s'%filename
        print '='*40
        for line in fd.readlines():
            print line.rstrip()
        print '='*40

def touch(filename, content=None, verbose=True):
    """Create a new file, and optionally give it content.
    """
    if verbose:
        print '++ touch %s'%filename
    with open(filename, 'w') as fd:
        if content:
            fd.write(content)

def append(filename, content, verbose=True):
    """Append 'content' to the given file
    """
    if verbose:
        print '++ append to %s'%filename
    with open(filename, 'a') as fd:
        fd.write(content)

def check_files(paths, verbose=True):
    """Given a list of paths, check they all exist.
    """
    if verbose:
        print '++ Checking files exist'
    for name in paths:
        if os.path.exists(name):
            if verbose:
                print '  -- %s'%name
        else:
            raise GiveUp('File %s does not exist'%name)
    if verbose:
        print '++ All named files exist'

def check_specific_files_in_this_dir(names, verbose=True):
    """Given a list of filenames, check they are the only files
    in the current directory
    """
    wanted_files = set(names)
    actual_files = set(os.listdir('.'))

    if verbose:
        print '++ Checking only specific files exist in this directory'
        print '++ Wanted files are: %s'%(', '.join(wanted_files))

    if wanted_files != actual_files:
        text = ''
        missing_files = wanted_files - actual_files
        if missing_files:
            text += '    Missing: %s\n'%', '.join(missing_files)
        extra_files = actual_files - wanted_files
        if extra_files:
            text += '    Extra: %s\n'%', '.join(extra_files)
        raise GiveUp('Required files are not matched\n%s'%text)
    else:
        if verbose:
            print '++ Only the requested files exist'

def check_nosuch_files(paths, verbose=True):
    """Given a list of paths, check they do not exist.
    """
    if verbose:
        print '++ Checking files do not exist'
    for name in paths:
        if os.path.exists(name):
            raise GiveUp('File %s exists'%name)
        else:
            if verbose:
                print '  -- %s'%name
    if verbose:
        print '++ All named files do not exist'

def banner(text):
    """Print a banner around the given text.
    """
    delim = '*' * (len(text)+4)
    print delim
    print '* %s *'%text
    print delim

class DirTree(object):
    """A tool for representing a directory tree in ASCII.

    Useful for testing that we have the correct files, as it can compare
    its representation against another equivalent instance, and produce
    error reports if they don't match.
    """

    def __init__(self, path, summarise_dirs=None, indent='  '):
        """Create a DirTree for 'path'.

        'path' is the path to the directory we want to represent.

        'summarise_dirs' may be a list of directory names that should
        be reported but not traversed - typically VCS directories. So,
        for instance "summarise_dirs=['.git']".

        'indent' is how much to indent each "internal" line respective
        to its container. Two spaces normally makes a good default.
        """
        self.path = path
        if summarise_dirs:
            self.summarise_dirs = summarise_dirs[:]
        else:
            self.summarise_dirs = []
        self.indent = indent

    def _filestr(self, path, filename):
        s = os.stat(path)
        m = s.st_mode
        flags = []
        if S_ISLNK(m):
            # This is *not* going to show the identical linked path as
            # (for instance) 'ls' or 'tree', but it should be simply
            # comparable to another DirTree link
            flags.append('@')
            far = os.path.realpath(path)
            head, tail = os.path.split(path)
            rel = os.path.relpath(far, head)
            flags.append(' -> %s'%rel)
            if os.path.isdir(far):
                flags.append('/')
                # We don't try to cope with a "far" executable, or if it's
                # another link (does it work like that?)
        elif S_ISDIR(m):
            flags.append('/')
            if filename in self.summarise_dirs:
                flags.append('...')
        elif (m & S_IXUSR) or (m & S_IXGRP) or (m & S_IXOTH):
            flags.append('*')
        return '%s%s'%(filename, ''.join(flags))

    def _tree(self, path, head, tail, lines, level):
        lines.append('%s%s'%(level*self.indent, self._filestr(path, tail)))
        if os.path.isdir(path) and tail not in self.summarise_dirs:
            files = os.listdir(path)
            files.sort()
            for name in files:
                self._tree(os.path.join(path, name), path, name, lines, level+1)

    def as_lines(self):
        """Return our representation as a list of text lines.

        Our "str()" output is this list joined with newlines.
        """
        lines = []
        head, tail = os.path.split(self.path)
        self._tree(self.path, head, tail, lines, 0)
        return lines

    def __str__(self):
        lines = self.as_lines()
        return '\n'.join(lines)

    def __repr__(self):
        return 'DirTree(%r)'%self.path

    def __eq__(self, other):
        """Test for identical representations.
        """
        return str(self) == str(other)

    def assert_same(self, other_path):
        """Compare this DirTree and the DirTree() for 'other_path'.

        Thus 'other_path' should be a path.

        Raises a GiveUp exception if they do not match, with an explanation
        inside it of why.

        This is really the method for which I wrote this class. It allows
        convenient comparison of two directories, a source and a target.
        """
        other = DirTree(other_path, self.summarise_dirs, self.indent)
        this_lines = self.as_lines()
        that_lines = other.as_lines()

        for index, (this, that) in enumerate(zip(this_lines, that_lines)):
            if this != that:
                context_lines = []
                for n in range(index):
                    context_lines.append(' %s'%(this_lines[n]))
                if context_lines:
                    context = '%s\n'%('\n'.join(context_lines))
                else:
                    context = ''
                raise GiveUp('Directory tree mismatch:\n'
                             '--- {us}\n'
                             '+++ {them}\n'
                             '@@@ line {index}\n'
                             '{context}'
                             '-{this}\n'
                             '+{that}'.format(us=self.path, them=other.path,
                                     context=context,
                                     index=index, this=this, that=that))

        if len(this_lines) != len(that_lines):
            len_this = len(this_lines)
            len_that = len(that_lines)
            same = min(len_this, len_that)
            context_lines = []
            for n in range(same):
                context_lines.append(' %s'%(this_lines[n]))

            if len_this > len_that:
                difference = len_this - len_that
                context_lines.append('...and then %d more line%s in %s'%(difference,
                    '' if difference==1 else 's', self.path))
            else:
                difference = len_that - len_this
                context_lines.append('...and then %d more line%s in %s'%(difference,
                    '' if difference==1 else 's', other.path))
            context = '\n'.join(context_lines)

            raise GiveUp('Directory tree mismatch:\n'
                         'Comparing: {us}\n'
                         '     with: {them}\n'
                         'Different number of lines ({uslen} versus {themlen})\n'
                         '{context}'.format(us=self.path, them=other.path,
                             uslen=len(this_lines), themlen=len(that_lines),
                             context=context))

if __name__ == '__main__':
    # Pretend to be muddle the command line program
    try:
        muddle(sys.argv[1:])
        sys.exit(0)
    except MuddleBug, why:
        print "%s"%why
        traceback.print_exc()
        sys.exit(1)
    except GiveUp as f:
        print "%s"%f
        sys.exit(1)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
