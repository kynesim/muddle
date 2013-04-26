#! /usr/bin/env python

# This is what I want inside my utils.py::run_cmd...

import sys
import subprocess

def main():
    text = ''
    print '=================='
    proc = subprocess.Popen(['ls'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for data in proc.stdout:
        sys.stdout.write(data)
        text += data
    proc.wait()
    print '=================='
    print text,
    print '=================='
    print 'Return code', proc.returncode


if __name__ == '__main__':
    main()
