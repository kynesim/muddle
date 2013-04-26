#! /usr/bin/env python

# This is what I want inside my utils.py::run_cmd...

import sys
import subprocess
import shlex

def run(thing):
    if isinstance(thing, basestring):
        print '> %s'%thing
        thing = shlex.split(thing)
    else:
        o = []
        for item in thing:
            if ' ' in item or '\t' in item:
                o.append(repr(item))
            else:
                o.append(item)
        print '> %s'%(' '.join(o))
    text = ''
    print '=================='
    proc = subprocess.Popen(thing, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for data in proc.stdout:
        sys.stdout.write(data)
        text += data
    proc.wait()
    print '=================='
    print text,
    print '=================='
    print 'Return code', proc.returncode

def main():
    run('ls -l')
    run(['ls', '-l'])
    run('ls "fred jim"')
    run(['ls', 'fred jim'])


if __name__ == '__main__':
    main()
