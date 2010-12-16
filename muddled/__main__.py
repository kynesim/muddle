#! /usr/bin/env python
#
# -*- mode: python -*-
#

"""
Main program for muddle:

  muddle [<options>] <command> [<arg> ...]

Options include:

  --help, -h, -?      This help text
  --tree [dir]        Use the muddle build tree at [dir]
  --just-print, -n    Just print what you would have done.

If you don't give --tree, we'll traverse directories up to the root
to try and find a .muddle directory which signifies the top of the
build tree.

To get help on commands, use:

  muddle help [<command>]
"""

import os
import sys
import traceback

# Perform a nasty trick to enable us to import the package
# that we are within. Unfortunately, if we're run via
# 'python <this-directory>', then Python doesn't seem to
# realise that we are within a package. I don't want to have
# a link to this file from the parent directory, so try this
# hack.
#
# TODO: work out a better way to do it!
this_dir = os.path.split(os.path.abspath(__file__))[0]
parent_dir = os.path.split(this_dir)[0]
sys.path.insert(0,parent_dir)

try:
    import muddled.cmdline
    from muddled.utils import MuddleBug, GiveUp
except ImportError:
    # Hah - maybe we're being run throught the 'muddle' soft link
    # from the same directory that contains the muddled/ package,
    # with PYTHONPATH unset (this is different to PYTHONPATH set
    # to nothing - ho hum). So try:
    sys.path = [this_dir] + sys.path[1:]
    import muddled.cmdline
    from muddled.utils import MuddleBug, GiveUp

if __name__ == "__main__":
    try:
        muddle_binary = __file__
        muddled.cmdline.cmdline(sys.argv[1:], muddle_binary)
        sys.exit(0)
    except MuddleBug, why:
        print "%s"%why
        traceback.print_exc()
        sys.exit(1)
    except GiveUp as f:
        print "%s"%f
        sys.exit(1)
