#! /usr/bin/env python
#
# -*- mode: python -*-
#

"""
Main program for muddle. Just calls the command line handler.
"""

import os
import sys
import traceback

# This is a bit draconian, but it really doesn't work with 2.6 or 3.x
if sys.version_info.major != 2 or sys.version_info.minor < 7:
    print("Muddle currently requires Python 2.7, not %d.%d.%d"%(sys.version_info.major,
        sys.version_info.minor, sys.version_info.micro))
    sys.exit(1)

# Perform a nasty trick to enable us to import the package
# that we are within. Unfortunately, if we're run via
# 'python <this-directory>', then Python doesn't seem to
# realise that we are within a package. I don't want to have
# a link to this file from the parent directory, so try this
# hack.
#
# TODO: work out a better way to do it!
this_file = os.path.realpath(__file__)  # follow any soft links
this_file = os.path.abspath(this_file)
this_dir = os.path.split(this_file)[0]
parent_dir = os.path.split(this_dir)[0]
sys.path.insert(0,parent_dir)

try:
    import muddled.cmdline
    from muddled.utils import MuddleBug, GiveUp, ShellError, normalise_dir
except ImportError:
    # Hah - maybe we're being run throught the 'muddle' soft link
    # from the same directory that contains the muddled/ package,
    # with PYTHONPATH unset (this is different to PYTHONPATH set
    # to nothing - ho hum). So try:
    sys.path = [this_dir] + sys.path[1:]
    import muddled.cmdline
    from muddled.utils import MuddleBug, GiveUp, ShellError, normalise_dir

if __name__ == "__main__":
    try:
        muddle_binary = normalise_dir(__file__)
        muddled.cmdline.cmdline(sys.argv[1:], muddle_binary)
        sys.exit(0)
    except MuddleBug, e:
        # We assume this represents a bug in muddle itself, so give a full
        # traceback to help locate it.
        print
        print "%s"%e
        traceback.print_exc()
        sys.exit(e.retcode)
    except ShellError, e:
        # A ShellError is a subclass of GiveUp. If it reaches this level,
        # though, it indicates that some shell command (probably run with
        # utils.run0()) failed and was not caught elsewhere. This is normally
        # a problem in the muddle infrastructure, so we treat it as a
        # MuddleBug, with a full traceback
        print
        print "%s"%e
        traceback.print_exc()
        sys.exit(e.retcode)
    except GiveUp as e:
        # We have some error or infelicity to tell the user about, which
        # is being communicated to us via a GiveUp exception. This is not
        # (should not be) a bug in muddle itself.
        print
        text = str(e)
        if text:
            print(text)
        sys.exit(e.retcode)
