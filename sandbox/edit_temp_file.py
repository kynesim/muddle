#! /usr/bin/env python

import os
import subprocess
import tempfile

orig_text = """
-------------------------------------
This is some text already in the file
"""

def main():

    editor = os.environ.get('EDITOR', 'vim')

    fd, filename = tempfile.mkstemp(suffix='.muddle.txt')
    with os.fdopen(fd, 'w') as f:
        f.write(orig_text)
        f.close()

    print 'Editing file %s with %s'%(filename, editor)

    rv = subprocess.call((editor, filename), close_fds=True)

    print 'Return code', rv

    with open(filename) as f:
        text = f.read()

    print 'Text is:'
    print
    print text
    print

    if text == orig_text:
        print '!!! Text was not changed'
        print

    print 'Deleting',filename
    os.remove(filename)

if __name__ == '__main__':
    main()

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
