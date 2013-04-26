#! /usr/bin/env python

# This is what I want inside my utils.py::run_cmd...

import sys
import subprocess
import shlex

# Proposed:
#
# run0(...) returns no arguments, raises an exception on error
#           (maybe - I'm not sure if we want this one)
# run1(...) returns the return code of the command
# run2(...) returns the return code and stdout
# run3(...) returns the return code, stdout and stderr
#
# (I can't see an obvious way of naming those better without getting MUCH
# longer names...)

def run3(thing):
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
    error = ''
    print '=================='
    proc = subprocess.Popen(thing, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while proc.poll() is None:
        data = proc.stdout.readline()
        err = proc.stderr.readline()
        if data:
            sys.stdout.write(data)
            text += data
        if err:
            sys.stderr.write(err)
            error += err
    print '=================='
    print text,
    print '------------------'
    print error
    print '=================='
    print 'Return code', proc.returncode
    return proc.returncode, text, error

def run2(thing):
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
    return proc.returncode, text

def run1(thing):
    rc, text = run2(thing)
    return rc

def main():
    run1('ls -l')
    run1(['ls', '-l'])
    run2('ls "fred jim"')
    run2(['ls', 'fred jim'])

    rc, out, err = run3(['ls', 'fred jim'])
    print 'rc:', rc
    print 'out:', out
    print 'err:', err


if __name__ == '__main__':
    main()
