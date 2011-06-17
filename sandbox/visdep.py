#! /usr/bin/env python
"""Wrapper for visualise-dependencies.py and xdot.py

visualise-dependencies.py is right here in the sandbox.

xdot.py is available from http://code.google.com/p/jrfonseca/wiki/XDot, and
depends on PyGTK and Graphviz.

Usage:

    visdep.py  [<switches>]  <label>  [<switches>]
    visdep.py  -h[elp]|--help

Where <switches> are:

  -t[red]           The intermediate dot file will be piped through 'tred',
                    which performs transitive reduction of the graph. See ``man
                    tred`` for more information. This is recommended for many
                    muddle dependency trees.

  -f[ilter] <name>  Tell xdot.py to use the named graphviz filter (one of
                    dot, neato, twopi, circo or fdp). The default is dot.

  -v[erbose]        The programs being run and the names of the intermediate
                    dot files will be shown.

  -k[eep]           Keep the intermediate dot file(s). If you specify this
                    it's probably also worth using -verbose so you know what
                    they are called.
"""

from tempfile import mkstemp

import os
import subprocess
import sys

def process(label, reduce=False, filter='dot', keep_files=False, verbose=False):

    # The first program we want to run is in the sandbox with us
    thisdir = os.path.split(__file__)[0]
    visualiser = os.path.join(thisdir, 'visualise-dependencies.py')

    dotfile_path1 = None
    dotfile_path2 = None

    try:
        fd, dotfile_path1 = mkstemp(suffix='.dot', prefix='visdep_', text=True)
        try:
            if verbose:
                print 'Running', visualiser, 'for', label
                print 'Outut dot file is', dotfile_path1
            retcode = subprocess.call('%s %s'%(visualiser, label), stdout=fd, shell=True)
            if retcode != 0:
                print 'Error %d running %s'%(abs(retcode), visualiser)
                return
        except OSError as e:
            print 'Error running %s: %s'%(visualiser, e)
            return

        os.close(fd)

        # We assume that xdot.py is on our PATH
        if reduce:
            tred = 'tred'
            fd2, dotfile_path2 = mkstemp(suffix='.dot', prefix='visdep_', text=True)
            try:
                if verbose:
                    print 'Running', tred
                    print 'Output dot file is', dotfile_path2
                retcode = subprocess.call('%s %s'%(tred, dotfile_path1), stdout=fd2, shell=True)
                if retcode != 0:
                    print 'Error %d running %s'%(abs(retcode), tred)
                    return
            except OSError as e:
                print 'Error running %s: %s'%(tred, e)
                return
            os.close(fd2)
            dotfile_path = dotfile_path2
        else:
            dotfile_path = dotfile_path1

        xdot = 'xdot.py'
        try:
            if verbose:
                print 'Running', xdot
            retcode = subprocess.call('%s --filter=%s %s'%(xdot, filter, dotfile_path), shell=True)
            if retcode != 0:
                print 'Error %d running %s'%(abs(retcode), xdot)
                return
        except OSError as e:
            print 'Error running %s: %s'%(xdot, e)
            return
    finally:
        if not keep_files:
            if dotfile_path1:
                os.remove(dotfile_path1)
            if dotfile_path2:
                os.remove(dotfile_path2)

def main(args):

    if not args:
        print __doc__
        return 0

    reduce = False
    verbose = False
    keep_files = False
    filter = 'dot'
    label = None

    while args:
        word = args.pop(0)
        if word in ('-h', '-help', '--help'):
            print __doc__
            return
        elif word in ('-t', '-tred'):
            reduce = True
        elif word in ('-v', '-verbose'):
            verbose = True
        elif word in ('-k', '-keep'):
            keep_files = True
        elif word in ('-f', '-filter'):
            filter = args.pop(0)
        elif word[0] == '-':
            print 'Unrecognised switch', word
            return
        elif label is None:
            label = word
        else:
            print 'Label "%s" already given, only one label allowed'
            return

    if label is None:
        print __doc__
        return 1

    process(label, reduce, filter, keep_files, verbose)
    return 0

if __name__ == '__main__':
    main(sys.argv[1:])

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
