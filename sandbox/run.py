#! /usr/bin/env python

# This is what I want inside my utils.py::run_cmd...

import sys
import subprocess
import shlex
import select
import errno

# Proposed:
#
# run0(...) returns no arguments, raises an exception on error
# run1(...) returns the return code of the command
# run2(...) returns the return code and stdout
# run3(...) returns the return code, stdout and stderr
#
# (I can't see an obvious way of naming those better without getting MUCH
# longer names...)

"""
Things we're looking to replace - from muddled:utils.py:

    run_cmd_for_output(cmd_array, env = None, useShell = False, fold_stderr=False, verbose = True)
    returns (rc, out, err)

    returns run_cmd(cmd, env=None, allowFailure=False, isSystem=False, verbose=True)
    returns rc, raises on failure

    run_cmd_list(cmdlist, env=None, allowFailure=False, isSystem=False, verbose=True)
    returns rc, raises on failure

    get_cmd_data(cmd, env=None, isSystem=False, fold_stderr=True,
                 verbose=False, fail_nonzero=True)
    returns (rc, out, err), may raise on failure

I don't think we should ever allow 'useShell' (nor do I think it is actually
needed inside muddle).

  (The one exception *might* be the RunIn command, which may well want
  to do shell expansion of stuff. But that calls subprocess.call() directly
  itself, so isn't *trying* to be clever, and can thus be ignored here.)

'isSystem' controls whether an error raises a MuddleBug (isSystem == True) or
a GiveUp (isSystem == False). And the way to go may be to always raise either
a ShellError, or the systems CalledProcessError, and let the caller of the
function decide what to do with it...

'allowFailure' should be done by calling run0() if an exception is wanted on
non-zero return code, and runX otherwise (and deal with the non-zero return
code as necessary).

As it is, it's always a pain to remember how to use 'isSystem' and
'allowFailure'.

from tests/support_for_tests.py:

    shell(cmd, verbose=True)
    doesn't return anything, raises ShellError

    get_stdout(cmd, verbose=True)
    returns out, raises ShellError

    get_stdout2(cmd, verbose=True)
    returns rc, out

    muddle(args, verbose=True)
    doesn't return anything, raises ShellError

    captured_muddle(args, verbose=True, error_fails=True)
    returns out, raises CalledProcessError

    captured_muddle2(args, verbose=True)
    returns rc, out

NOTE that we *also* want a 'quiet' argument, defaulting to False. If
quiet is given as True, then we should *not* "tee" the output to the
terminal, but should just use proc.communicate() to gather the final
results.
"""

# =============================================================================
# Copied from utils.py whilst we're working on this stuff
# =============================================================================
def indent(text, indent):
    """Return the text indented with the 'indent' string.

    (i.e., place 'indent' in front of each line of text).
    """
    lines = text.split('\n')
    stuff = []
    for line in lines:
        stuff.append('%s%s'%(indent,line))
    return '\n'.join(stuff)

class GiveUp(Exception):
    """
    Use this to indicate that something has gone wrong and we are giving up.

    This is not an error in muddle itself, however, so there is no need for
    a traceback.

    By default, a return code of 1 is indicated by the 'retcode' value - this
    can be set by the caller to another value, which __main__.py should then
    use as its return code if the exception reaches it.
    """

    # We provide a single attribute, which is used to specify the exit code
    # to use when a command line handler gets back a GiveUp exception.
    retcode = 1

    def __init__(self, message=None, retcode=1):
        self.message = message
        self.retcode = retcode

    def __str__(self):
        if self.message is None:
            return ''
        else:
            return self.message

    def __repr__(self):
        parts = []
        if self.message is not None:
            parts.append(repr(self.message))
        if self.retcode != 1:
            parts.append('%d'%self.retcode)
        return 'GiveUp(%s)'%(', '.join(parts))
# =============================================================================

class ShellError(GiveUp):
    def __init__(self, cmd, retcode, output=None):
        self.cmd = cmd
        self.retcode = retcode
        self.output = output.rstrip()   # Is this sensible to do here?

        msg = "Shell command %s failed with retcode %d"%(repr(cmd), retcode)
        if output:
            msg = '%s:\n%s'%(msg, indent(output.rstrip(), "  "))
        super(GiveUp, self).__init__(msg)

def _stringify(thing):
    """Given a command, as either a string or sequence, return a string.
    """
    if isinstance(thing, basestring):
        return thing
    else:
        o = []
        for item in thing:
            if ' ' in item or '\t' in item:
                o.append(repr(item))
            else:
                o.append(item)
        return ' '.join(o)

def _rationalise_cmd(thing):
    """Given a command, as either a string or sequence, return a sequence.
    """
    if isinstance(thing, basestring):
        thing = shlex.split(thing)
    return thing

def run0(thing, show_command=True, show_output=True):
    """Run the command 'thing', returning nothing.

    'thing' may be a string (e.g., "ls -l") or a sequence (e.g., ["ls", "-l"]).
    Internally, a string will be converted into a sequence before it is used.

    If 'show_command' is true, then "> <thing>" will be printed out before
    running the command.

    If 'show_output' is true, then the output of the command (both stdout and
    stderr) will be printed out as the command runs.

    If the command returns a non-zero return code, then a ShellError will
    be raised, containing the returncode, the command string and any output
    that occurred.
    """
    rc, output = run2(thing, show_command=show_command, show_output=show_output)
    if rc != 0:
        raise ShellError(cmd=_stringify(thing), retcode=rc, output=output)

def run1(thing, show_command=True, show_output=True):
    """Run the command 'thing', returning the return code.

    'thing' may be a string (e.g., "ls -l") or a sequence (e.g., ["ls", "-l"]).
    Internally, a string will be converted into a sequence before it is used.

    If 'show_command' is true, then "> <thing>" will be printed out before
    running the command.

    If 'show_output' is true, then the output of the command (both stdout and
    stderr) will be printed out as the command runs.

    The output of the command (stdout and stderr) goes to the normal stdout
    whilst the command is running.

    The command return is returned.
    """
    rc, text = run2(thing, show_command=show_command, show_output=show_output)
    return rc

def run2(thing, show_command=True, show_output=True):
    """Run the command 'thing', returning the return code and output.

    'thing' may be a string (e.g., "ls -l") or a sequence (e.g., ["ls", "-l"]).
    Internally, a string will be converted into a sequence before it is used.

    If 'show_command' is true, then "> <thing>" will be printed out before
    running the command.

    If 'show_output' is true, then the output of the command (both stdout and
    stderr) will be printed out as the command runs.

    The output of the command (stdout and stderr) goes to the normal stdout
    whilst the command is running.

    The command return code and output are returned as a tuple:

        (retcode, output)
    """
    thing = _rationalise_cmd(thing)
    if show_command:
        print '> %s'%_stringify(thing)
    text = []
    proc = subprocess.Popen(thing, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for data in proc.stdout:
        if show_output:
            sys.stdout.write(data)
        text.append(data)
    proc.wait()
    text = ''.join(text)
    return proc.returncode, text

def run3(thing, show_command=True, show_output=True):
    """Run the command 'thing', returning the return code, stdout and stderr.

    'thing' may be a string (e.g., "ls -l") or a sequence (e.g., ["ls", "-l"]).
    Internally, a string will be converted into a sequence before it is used.

    If 'show_command' is true, then "> <thing>" will be printed out before
    running the command.

    If 'show_output' is true, then the output of the command (both stdout and
    stderr) will be printed out as the command runs.

    The output of the command is shown whilst the command is running; its
    stdout goes to the normal stdout, and its stderr to stderr.

    The command return code, stdout and stderr are returned as a tuple:

        (retcode, stdout, stderr)
    """
    thing = _rationalise_cmd(thing)
    if show_command:
        print '> %s'%_stringify(thing)
    all_stdout_text = []
    all_stderr_text = []
    proc = subprocess.Popen(thing, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # We use select here because poll is less portable (although at the moment
    # we are only working on Linux, so perhaps I shouldn't care)
    read_list = [proc.stdout, proc.stderr]
    while read_list:
        try:
            rlist, wlist, xlist = select.select(read_list, [], [])
        except select.error as e:
            if e.args[0] == errno.EINTR:
                continue
            else:
                raise GiveUp("Error selecting command output\n"
                             "For: %s\n"
                             "Error: %d %s %s"%(_stringify(thing),
                                 e.args[0], errno.errorcode[e.args[0]], e.args[1]))
        if proc.stdout in rlist:
            # We don't use readline (which would be nicer) because
            # we don't know whether the data we're being given *is*
            # a line, and readline would wait for the EOL
            stdout_text = proc.stdout.read(1024)
            if stdout_text == '':
                read_list.remove(proc.stdout)
            else:
                if show_output:
                    sys.stdout.write(stdout_text)
                all_stdout_text.append(stdout_text)
        if proc.stderr in rlist:
            # Comment as above
            stderr_text = proc.stderr.read(1024)
            if stderr_text == '':
                read_list.remove(proc.stderr)
            else:
                if show_output:
                    sys.stderr.write(stderr_text)
                all_stderr_text.append(stderr_text)
    # Make sure proc.returncode gets set
    proc.wait()

    all_stdout_text = ''.join(all_stdout_text)
    all_stderr_text = ''.join(all_stderr_text)
    return proc.returncode, all_stdout_text, all_stderr_text

def main():
    print
    print "run1: 'ls -l'"
    rc = run1('ls -l')
    print 'Return code', rc

    print
    print "run1: ['ls', '-l']"
    rc = run1(['ls', '-l'])
    print 'Return code', rc

    print
    print "run2: 'ls \"fred jim\"'"
    rc, out = run2('ls "fred jim"')
    print 'Return code', rc
    print '======================='
    print out
    print '======================='

    print
    print "run2: ['ls', 'fred jim']"
    rc, out = run2(['ls', 'fred jim'])
    print 'Return code', rc
    print '======================='
    print out
    print '======================='

    print
    print "run3: ['ls', 'fred jim']"
    rc, out, err = run3(['ls', 'fred jim'])
    print 'Return code:', rc
    print '======================='
    print 'out:', out
    print '-----------------------'
    print 'err:', err
    print '======================='

    print
    print "run0: ['ls', 'fred jim']"
    try:
        run0(['ls', 'fred jim'])
    except GiveUp as e:
        print 'Exception:', e.__class__.__name__
        print '======================='
        print e
        print '~~~~~~~~~~~~~~~~~~~~~~~'
        print repr(e)
        print '~~~~~~~~~~~~~~~~~~~~~~~'
        print e.cmd
        print e.retcode
        print e.output
        print '======================='

if __name__ == '__main__':
    main()
