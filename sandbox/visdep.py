#! /usr/bin/env python
"""Wrapper for visualise-dependencies.py and xdot.py

visualise-dependencies.py is right here in the sandbox.

xdot.py is available from http://code.google.com/p/jrfonseca/wiki/XDot, and
depends on PyGTK and Graphviz.

Usage:

    visdep.py  <label>
"""

from tempfile import mkstemp

import os
import subprocess
import sys

def main(label):
    fd, dotfile_path = mkstemp(suffix='.dot', prefix='visdep_', text=True)

    # The first program we want to run is in the sandbox with us
    thisdir = os.path.split(__file__)[0]
    visualiser = os.path.join(thisdir, 'visualise-dependencies.py')

    try:
        retcode = subprocess.call([visualiser, label], stdout=fd)
        if retcode < 0:
            print 'Error %d running %s'%(-retcode, visualiser)
            return
    except OSError as e:
        print 'Error running %s: %s'%(visualiser, e)
        return

    os.close(fd)

    # We assume that xdot.py is on our PATH
    xdot = 'xdot.py'

    try:
        retcode = subprocess.call([xdot, dotfile_path])
        if retcode < 0:
            print 'Error %d running %s'%(-retcode, xdot)
            return
    except OSError as e:
        print 'Error running %s: %s'%(xdot, e)
        return

if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) != 1:
        print __doc__
    else:
        main(args[0])

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
