The ToDoFinder
==============

This is a git pre-commit hook which:

1. checks for "TODO"
2. checks for mismatched "//==" texts (see below)

in C and C++ files (specifically, in files with extensions .c, .cpp or .h).

The idea is based on some hooks we used to have in our subversion
repositories, and this implementation was written by Rachel Crook whilst
working for Kynesim as part of her work experience in year 10 [1]_

.. [1] This is a scheme where school children of age 14 or 15 work for a
   couple of weeks to give them an idea of life after school.

TODO reporting
--------------
This reports any occurrences of the strings "TODO" (in upper case) or "@todo"
(in any case) in comments. The presence of such is reported, but does not
cause the commit to fail.

"//==" reporting
----------------
This looks for C code of the form::

  <text1> //== <text2>

and refuses to allow a commit if <text1> is not identical to <text2>.

A typical usage would be::

  #define DEBUG=1 //== #define DEBUG=0

...in other words, if the user enables DEBUG in their working code, do not
allow that change to be committed (and thus inadvertently get shipped).

Note that whitespace in <text1> and <text2> is "flattened" - i.e., the amount
of whitespace is not significant, just its presence. Also, leading and
trailing whitespace is ignored.

Unterminated comments
---------------------
If the program can't find the end of a comment, then it will fail with an
appropriate error message.

Installation
------------
The provided ``install.py`` script can be used to install the pre-commit
hook and its associated Python script. See ``./install.py -help``.

If you run it with '-n' then it will tell you what it would do, but not do it
- I highly recommend doing this before actually letting it install files.

Basically, use as::

  ./install.py  <target-dir>

where the <target-dir> is the top-level of a git tree that does not already
have a pre-commit hook installed. More than one <target-dir> can be specified,
or::

  ./install.py -muddle [<root-of-muddle-tree>]

*Beware* that it strongly expects to be run as a file within the
sandbox/ToDoFinder directory, as it looks two directories up for the "muddle"
command.

Usage
-----
Simply copy both ``pre-commit`` and ``FullCheckNames.py`` into ``.git/hooks/``
and make sure they are executable (``chmod +x``).

The default is to just report TODO messages [2]_, but to fail if there are
any mismatched "//==" comments (or unterminated comments). If you want to
change which results cause the commit to fail/abort, then edit the
``.git/hooks/pre-commit`` shell script appropriately.

.. [2] If, like me, your commit message editor is run in the terminal being
   used for the command line, then you won't see the TODO messages before the
   editor starts. The workaround is to use an editor that doesn't take over
   the terminal (e.g., set GIT_EDITOR=gvim instead of GIT_EDITOR=vim - note
   that git looks at GIT_EDITOR, VISUAL and then EDITOR, in that order).

.. vim: set filetype=rst tabstop=8 softtabstop=2 shiftwidth=2 expandtab:
