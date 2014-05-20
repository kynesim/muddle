#! /usr/bin/env python

"""Test support functions and stuff.

For once, intended to be safe for use with ``from support_for_tests import *``
"""

import os
import shutil
import subprocess
import sys
import traceback
import stat
import string

from difflib import unified_diff, ndiff
from fnmatch import fnmatchcase
from StringIO import StringIO

__all__ = []

def export(obj):
    if obj.__name__ not in __all__:
        __all__.append(obj.__name__)
    return obj

def export_names(names):
    if isinstance(names, basestring):
        names = [names]
    for name in names:
        if name not in __all__:
            __all__.append(name)

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

from muddled.utils import GiveUp, MuddleBug, ShellError
from muddled.utils import shell, run1, run2, get_cmd_data

export_names(['GiveUp', 'MuddleBug', 'ShellError'])
export_names(['shell', 'run1', 'run2'])

# We know (strongly assume!) that there should be a 'muddle' available
# in the same directory as the 'muddled' package - we shall use that as
# the muddle program
MUDDLE_BINARY_DIR = os.path.abspath(get_parent_dir(muddled.cmdline.__file__))
MUDDLE_BINARY = os.path.join(MUDDLE_BINARY_DIR, 'muddle')

# Make up for not necessarily having a PYTHONPATH that helps
# Assume the location of muddle_patch.py relative to ourselves
MUDDLE_PATCH_COMMAND = '%s/muddle_patch.py'%(PARENT_DIR)

export_names(['MUDDLE_BINARY', 'MUDDLE_PATCH_COMMAND'])

def flushing_print(text):
    sys.stdout.write(text)
    sys.stdout.flush()

@export
def get_stdout(cmd, verbose=True):
    """Run a command in the shell, and grab its (standard) output.
    """
    return get_cmd_data(cmd, show_command=verbose)

@export
def run_muddle_directly(args, verbose=True):
    """Pretend to be muddle

    I already know it's going to be a pain remembering that the first
    argument is a list of words...

    Beware that this does not quite give the "insulation" between commands
    that actually running "muddle" as a program would. On the whole, if that
    becomes a problem it can either (a) be fixed on a case-by-case basis, or
    (b) we could move to running MUDDLE_BINARY as an actual command.
    """
    if verbose:
        flushing_print('++ muddle %s\n'%(' '.join(args)))
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

@export
def muddle(args, verbose=True):
    """Run a muddle command
    """
    if verbose:
        flushing_print('++ muddle %s\n'%(' '.join(args)))
    cmd_seq = [MUDDLE_BINARY] + args
    if verbose:
        flushing_print(">> muddle %s\n"%(' '.join(args)))
    p = subprocess.Popen(cmd_seq)
    pid, retcode = os.waitpid(p.pid, 0)
    if retcode:
        raise ShellError(' '.join(cmd_seq), retcode)

@export
def captured_muddle(args, verbose=True, error_fails=True):
    """Grab the output from a muddle command.

    We can't just capture sys.stdout/stderr, because some things (notably
    help) are output via a subprocess paging. So we need to run muddle
    just like any other command...

    Returns the text output by muddle.

    Since it runs muddle via subprocess.check_output, it will raise a
    subprocess.CalledProcessError if muddle returns a non-zero exit code,
    unless 'error_fails' is false, in which case it will just return the
    text output by muddle. Note that if a CalledProcessError *is* returned,
    then the exit code and text output are available in its .returncode and
    .output attributes.
    """
    cmd_seq = [MUDDLE_BINARY] + args
    if verbose:
        flushing_print(">> muddle %s\n"%(' '.join(args)))

    # Ask what we call not to use buffering on its outputs, so that we get
    # stdout and stderr folded together correctly, despite the fact that our
    # output is not to a console
    env = os.environ
    env['PYTHONUNBUFFERED'] = 'anything'
    try:
        output = subprocess.check_output(cmd_seq, env=env, stderr=subprocess.STDOUT)
        return output
    except subprocess.CalledProcessError as e:
        if error_fails:
            flushing_print('%s\n'%e.output)
            raise
        else:
            return e.output

@export
def captured_muddle2(args, verbose=True):
    """Grab the exit code and output from a muddle command.

    We can't just capture sys.stdout/stderr, because some things (notably
    help) are output via a subprocess paging. So we need to run muddle
    just like any other command...

    Returns the exit code and text output from muddle.
    """
    cmd_seq = [MUDDLE_BINARY] + args
    if verbose:
        flushing_print(">> muddle %s\n"%(' '.join(args)))

    # Ask what we call not to use buffering on its outputs, so that we get
    # stdout and stderr folded together correctly, despite the fact that our
    # output is not to a console
    env = os.environ
    env['PYTHONUNBUFFERED'] = 'anything'
    try:
        output = subprocess.check_output(cmd_seq, env=env, stderr=subprocess.STDOUT)
        return 0, output
    except subprocess.CalledProcessError as e:
        return e.returncode, e.output

@export
def git(cmd):
    """Run a git command
    """
    shell('%s %s'%('git',cmd))

@export
def bzr(cmd):
    """Run a bazaar command
    """
    shell('%s %s'%('bzr',cmd))

@export
def svn(cmd):
    """Run a subversion command
    """
    shell('%s %s'%('svn',cmd))

@export
def cat(filename):
    """Print out the contents of a file.
    """
    with open(filename) as fd:
        flushing_print('++ cat %s\n'%filename)
        flushing_print('%s\n'%('='*40))
        for line in fd.readlines():
            flushing_print('%s\n'%line.rstrip())
        flushing_print('%s\n'%('='*40))

@export
def touch(filename, content=None, verbose=True):
    """Create a new file, and optionally give it content.
    """
    if verbose:
        flushing_print('++ touch %s\n'%filename)
    with open(filename, 'w') as fd:
        if content:
            fd.write(content)

@export
def append(filename, content, verbose=True):
    """Append 'content' to the given file
    """
    if verbose:
        flushing_print('++ append to %s\n'%filename)
    with open(filename, 'a') as fd:
        fd.write(content)

@export
def same_content(filename, content=None, verbose=True):
    """Read a file, and check its content matches
    """
    if verbose:
        flushing_print('++ same_content %s\n'%filename)
    with open(filename) as fd:
        this_content = fd.read()
    return this_content == content

@export
def check_files(paths, verbose=True):
    """Given a list of paths, check they all exist.
    """
    if verbose:
        flushing_print('++ Checking files exist\n')
    for name in paths:
        if os.path.exists(name):
            if verbose:
                flushing_print('  -- %s\n'%name)
        else:
            raise GiveUp('File %s does not exist'%name)
    if verbose:
        flushing_print('++ All named files exist\n')

@export
def check_specific_files_in_this_dir(names, verbose=True):
    """Given a list of filenames, check they are the only files
    in the current directory
    """
    wanted_files = set(names)
    actual_files = set(os.listdir('.'))

    if verbose:
        flushing_print('++ Checking only specific files exist in this directory\n')
        flushing_print('++ Wanted files are: %s\n'%(', '.join(wanted_files)))

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
            flushing_print('++ Only the requested files exist\n')

@export
def check_nosuch_files(paths, verbose=True):
    """Given a list of paths, check they do not exist.
    """
    if verbose:
        flushing_print('++ Checking files do not exist\n')
    for name in paths:
        if os.path.exists(name):
            raise GiveUp('File %s exists'%name)
        else:
            if verbose:
                sys.sydout.write('  -- %s\n'%name)
    if verbose:
        flushing_print('++ All named files do not exist\n')

@export
def banner(text, level=1):
    """Print a banner around the given text.

    'level' is 1..3, with 1 being the "most important" level of banner
    """
    delimiters = {1:'*', 2:'+', 3:'-'}
    endpoints  = {1:'*', 2:'|', 3:':'}
    delim_char = delimiters[level]
    endpoint_char = endpoints[level]
    delim = delim_char * (len(text)+4)
    flushing_print('%s\n'%delim)
    flushing_print('%s %s %s\n'%(endpoint_char, text, endpoint_char))
    flushing_print('%s\n'%delim)
    sys.stdout.flush()

@export
def check_file_v_text(filename, expected_text, sort_first=False):
    """Check the content of the file against the expected text.

    The expected text should either be a string, or a list of strings which
    have been split into lines.

    If 'sort_first' is True, then we'll sort the lines we're comparing
    before doing the comparison.
    """
    if isinstance(expected_text, basestring):
        lines = expected_text.splitlines()
        # But we do want newlines thereon
        expected_text = []
        for line in lines:
            expected_text.append('%s\n'%line)

    with open(filename) as fd:
        content = fd.readlines()

    diffs = unified_diff(content, expected_text, filename, 'Expected text')
    difflines = list(diffs)
    if difflines:
        raise GiveUp('Expected text does not match content of %s:\n%s'%(filename,
                     ''.join(difflines)))

@export
def check_text_lines_v_lines(actual_lines, wanted_lines, fold_whitespace=False):
    """Check two pieces of text are the same.

    'wanted_lines' is the lines of text we want, presented as a list,
    without any newlines.

    If 'fold_whitespace' is true, first "fold" any sequences of whitespace
    in 'wanted_lines' to a single space each. This makes it easier to compare
    lines with data laid out using spacing.

    Prints out the differences (if any) and then raises a GiveUp if there
    *were* differences
    """

    if fold_whitespace:
        compare_lines = []
        for line in actual_lines:
            columns = line.split()
            line = ' '.join(columns)
            compare_lines.append(line)
    else:
        compare_lines = actual_lines

    diffs = unified_diff(wanted_lines, compare_lines,
                         fromfile='Missing lines', tofile='Extra lines', lineterm='')
    difflines = list(diffs)
    if difflines:
        lines = ['Text did not match'] + list(difflines)
        raise GiveUp('\n'.join(lines))

@export
def check_text_v_lines(actual, wanted_lines):
    """Check two pieces of text are the same.

    'text' is the text we got from our test.

    'wanted_lines' is the lines of text we want, presented as a list,
    without any newlines.

    Prints out the differences (if any) and then raises a GiveUp if there
    *were* differences
    """
    actual_lines = actual.splitlines()
    check_text_lines_v_lines(actual_lines, wanted_lines)

@export
def check_text(actual, wanted):
    """Check two pieces of text are the same.

    Prints out the differences (if any) and then raises a GiveUp if there
    *were* differences
    """
    if actual == wanted:
        return

    actual_lines = actual.splitlines()
    wanted_lines = wanted.splitlines()
    check_text_lines_v_lines(actual_lines, wanted_lines)

@export
def check_text_endswith(text, should_end_with):
    """Check a text ends with another.

    Prints out the differences (if any) and then raises a GiveUp if there
    *were* differences
    """
    if not text.endswith(should_end_with):
        check_text(text, should_end_with)  # which we thus know will fail

@export
class DirTree(object):
    """A tool for representing a directory tree in ASCII.

    Useful for testing that we have the correct files, as it can compare
    its representation against another equivalent instance, and produce
    error reports if they don't match.

    Really, a hack for a single solution...
    """

    def __init__(self, path, fold_dirs=None, indent='  '):
        """Create a DirTree for 'path'.

        'path' is the path to the directory we want to represent.

        'fold_dirs' may be a list of directory names that should
        be reported but not traversed - typically VCS directories. So,
        for instance "fold_dirs=['.git']". The names must be just a
        filename, no extra path elements. Also, it is only directories
        that get checked against this list.

        'indent' is how much to indent each "internal" line respective
        to its container. Two spaces normally makes a good default.
        """
        self.path = path
        if fold_dirs:
            self.fold_dirs = fold_dirs[:]
        else:
            self.fold_dirs = []
        self.indent = indent

    def _filestr(self, path, filename):
        """Return a useful representation of a file.

        'path' is the full path of the file, sufficient to "find" it with
        os.stat() (so it may be relative to the current directory).

        'filename' is just its filename, the last element of its path,
        which is what we're going to use in our representation.

        We could work the latter out from the former, but our caller already
        knew both, so this is hopefully slightly faster.
        """
        s = os.stat(path)
        m = s.st_mode
        flags = []
        if stat.S_ISLNK(m):
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
        elif stat.S_ISDIR(m):
            flags.append('/')
            if filename in self.fold_dirs:
                flags.append('...')
        elif (m & stat.S_IXUSR) or (m & stat.S_IXGRP) or (m & stat.S_IXOTH):
            flags.append('*')
        return '%s%s'%(filename, ''.join(flags))

    def path_is_wanted(self, path, unwanted_files):
        for expr in unwanted_files:
            if fnmatchcase(path, expr):
                return False
        return True

    def _tree(self, path, head, tail, unwanted_files, lines, level, report_this=True):
        """Add the next components of the tree to 'lines'

        First adds the element specified by 'path' (or 'head'/'tail'),
        and then recurses down inside it if that is a directory that
        we are reporting on (depending on self.fold_dirs).

        'lines' is our accumulator of results. 'level' indicates how
        much indentation we're currently using, at this level.

        'path' is the same as 'head' joined to 'tail' - they're passed
        down separately just because we already had to calculate 'head'
        and 'tail' higher up, but we need all three.

        See the description of 'same_as' for how 'unwanted_files' is
        interpreted.
        """
        if report_this:
            lines.append('%s%s'%(level*self.indent, self._filestr(path, tail)))
        if os.path.isdir(path) and tail not in self.fold_dirs:
            files = os.listdir(path)
            files.sort()
            for name in files:
                this_path = os.path.join(path, name)
                if self.path_is_wanted(this_path, unwanted_files):
                    self._tree(this_path, path, name, unwanted_files, lines, level+1)

    def as_lines(self, onedown=False, unwanted_files=None):
        """Return our representation as a list of text lines.

        If 'onedown' is true, then we don't list the toplevel directory
        we're given (i.e., 'path' itself).

        See the description of 'same_as' for how 'unwanted_files' is
        interpreted.

        Our "str()" output is this list joined with newlines.
        """
        lines = []
        if not os.path.exists(self.path):
            return lines

        if unwanted_files is None:
            unwanted_files = []
        else:
            # Turn our unwanted path fragments into fnmatch expressions
            # - we do this one here because we expect to do lots of comparisons
            actual_unwanted_files = []
            for expr in unwanted_files:
                actual_unwanted_files.append('*/%s'%expr)
            unwanted_files = actual_unwanted_files

        # Start with 'self.path' itself
        head, tail = os.path.split(self.path)
        if self.path_is_wanted(self.path, unwanted_files):
            self._tree(self.path, head, tail, unwanted_files, lines, 0,
                       report_this=not onedown)
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

    def assert_same(self, other_path, onedown=False, unwanted_files=None,
                    unwanted_extensions=None):
        """Compare this DirTree and the DirTree() for 'other_path'.

        Thus 'other_path' should be a path. A temporary DirTree will
        be created for 'other_path', using the same values for 'onedown',
        'fold_dirs' and 'indent' as for this DirTree.

        If 'onedown' is true, then we don't list the toplevel directory
        we're given (i.e., 'path' itself).

        If 'unwanted_files' is specified, then is should be a list of terminal
        partial paths. For each term <p> in the list, files are compared with
        the expressions '*/<p>' using fnmatch.fnmatchcase(). This means that
        "shell style" pattern macthing is used, where::

            *       matches everything
            ?       matches any single character
            [seq]   matches any character in seq
            [!seq]  matches any char not in seq

        Files whose path matches will not be reported in the output of this
        DirTree, because we expect them to be absent in the 'other_path'.

        For instance::

            muddle.utils.copy_without('source/src', 'target/src', ['.git'])
            s = DirTree('source/src', fold_dirs=['.git'])
            copy_succeeded = s.assert_same('target/src',
                                            unwanted_files=['.git',
                                                            'builds/01.pyc',
                                                            '*.c',
                                                           ])

        means that we are NOT expecting to see any of the following in
        'target/src':

            * a file or directory called '.git'
            * a file with a path that is of the form '<any-path>/builds/01.pyc'
            * a file with extension '.c'

        Raises a GiveUp exception if they do not match, with an explanation
        inside it of why.

        This is really the method for which I wrote this class. It allows
        convenient comparison of two directories, a source and a target.
        """
        other = DirTree(other_path, self.fold_dirs, self.indent)
        this_lines = self.as_lines(onedown, unwanted_files)
        that_lines = other.as_lines(onedown)

        self._same_as(this_lines, that_lines, other.path,
                      unwanted_files=None, unwanted_extensions=None)


    def _same_as(self, this_lines, that_lines, that_path,
                 unwanted_files=None, unwanted_extensions=None):
        """ The internals of our comparison. See 'same_as()' for details.
        """
        if unwanted_files:
            unwanted_text = 'Unwanted files:\n  %s\n'%('\n  '.join(unwanted_files))
        else:
            unwanted_text = ''

        for index, (this, that) in enumerate(zip(this_lines, that_lines)):
            if this != that:
                context_lines = []
                for n in range(index):
                    context_lines.append(' %s'%(this_lines[n]))
                if context_lines:
                    context = '%s\n'%('\n'.join(context_lines))
                else:
                    context = ''
                raise GiveUp('Directory tree mismatch\n'
                             '{unwanted}'
                             '--- {us}\n'
                             '+++ {them}\n'
                             '@@@ line {index}\n'
                             '{context}'
                             '-{this}\n'
                             '+{that}'.format(us=self.path, them=that_path,
                                     unwanted=unwanted_text, context=context,
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
                for count in range(min(3, difference)):
                    context_lines.append('-%s'%(this_lines[len_that+count]))
                if difference > 4:
                    context_lines.append('...etc.')
                elif difference == 4:
                    context_lines.append('-%s'%(this_lines[len_that+3]))
            else:
                difference = len_that - len_this
                context_lines.append('...and then %d more line%s in %s'%(difference,
                    '' if difference==1 else 's', that_path))
                for count in range(min(3, difference)):
                    context_lines.append('-%s'%(that_lines[len_this+count]))
                if difference > 4:
                    context_lines.append('...etc.')
                elif difference == 4:
                    context_lines.append('-%s'%(that_lines[len_this+3]))

            context = '\n'.join(context_lines)

            raise GiveUp('Directory tree mismatch\n'
                         '{unwanted}'
                         '--- {us}\n'
                         '+++ {them}\n'
                         'Different number of lines ({uslen} versus {themlen})\n'
                         '{context}'.format(us=self.path, them=that_path,
                             unwanted=unwanted_text,
                             uslen=len(this_lines), themlen=len(that_lines),
                             context=context))

    def assert_same_as_list(self, path_list, other_path, onedown=False,
                            unwanted_files=None, unwanted_extensions=None):
        """Compare this DirTree and the list of paths in 'path_list'.

        Thus 'path_list' should be what the 'as_lines()' method for a DirTree
        for such a directory would return.

        'other_path' is the string to report as the path of the "other" lines.
        """

        this_lines = self.as_lines(onedown, unwanted_files)

        self._same_as(this_lines, path_list, other_path,
                      unwanted_files=None, unwanted_extensions=None)

if __name__ == '__main__':
    # Pretend to be muddle the command line program
    try:
        run_muddle_directly(sys.argv[1:])
        sys.exit(0)
    except MuddleBug, why:
        flushing_print("%s\n"%why)
        traceback.print_exc()
        sys.exit(1)
    except GiveUp as f:
        flushing_print("%s\n"%f)
        sys.exit(1)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
