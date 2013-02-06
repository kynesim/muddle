#! /usr/bin/env python

import os
import sys
import imp
import pydoc

from inspect import getmembers, isfunction, isclass, ismethod, ismodule
from inspect import isgenerator, getargspec, formatargspec, getmro, getdoc

class HashThing(object):

    def __init__(self):
        self.hash = {}

    def add(self, name, value):
        """Given a.b.c:3, add a.b.c:3, b.c:3, c:3
        """
        # Should we store the entry if the value is None?
        words = name.split('.')
        while words:
            thing = '.'.join(words)
            if thing in self.hash:
                self.hash[thing].add((name, value))
            else:
                self.hash[thing] = set([(name, value)])
            words = words[1:]

    def get(self, name):
        """Returns a set of (name, value) items.
        """
        return self.hash[name]

    def report(self):
        keys = sorted(self.hash.keys())
        maxlen = 0
        for key in keys:
            if len(key) > maxlen:
                maxlen = len(key)
        for key in keys:
            parts = []
            for name, value in self.hash[key]:
                parts.append('%s=%s'%(name, value))
            print '%-*s : %s'%(maxlen, name, ', '.join(parts))

DEBUG = False

def dissect(thing_name, thing, hash):
    for name, value in getmembers(thing):
        this_name = '%s.%s'%(thing_name, name)
        if name.startswith('__') and name.endswith('__'):
            continue
        elif isfunction(value):
            if DEBUG: print '   .. function', this_name
            hash.add(this_name, value)
        elif ismethod(value):
            if DEBUG: print '   .. method', this_name
            hash.add(this_name, value)
        elif isgenerator(value):
            if DEBUG: print '   .. generator', this_name
            hash.add(this_name, value)
        elif isclass(value):
            if DEBUG: print '   .. class', this_name
            hash.add(this_name, value)
            dissect(this_name, value, hash)

def describe_contents(thing_name, thing):
    contents = []
    for name, value in getmembers(thing):
        this_name = '%s.%s'%(thing_name, name)
        if name.startswith('__') and name.endswith('__'):
            continue
        elif isfunction(value):
            contents.append('  Function  %s'%this_name)
        elif ismethod(value):
            contents.append('  Method    %s'%this_name)
        elif isclass(value):
            contents.append('  Class     %s'%this_name)
        elif isgenerator(value):
            contents.append('  Generator %s'%this_name)
        elif isinstance(value, property):
            contents.append('  Property  %s'%this_name)
        elif ismodule(value):
            continue
        else:
            contents.append('            %s = <%s>'%(this_name, type(value).__name__))
    if len(contents):
        contents = sorted(contents)
        print 'Contents:'
        print '\n'.join(contents)

def describe_function_contents(thing_name, thing):
    contents = []
    for name, value in getmembers(thing):
        this_name = '%s.%s'%(thing_name, name)
        if name.startswith('__') and name.endswith('__'):
            continue
        elif isfunction(value):
            contents.append('  Function  %s'%this_name)
        elif isclass(value):
            contents.append('  Class     %s'%this_name)
        elif isgenerator(value):
            contents.append('  Generator %s'%this_name)
    if len(contents):
        contents = sorted(contents)
        print 'Contents:'
        print '\n'.join(contents)

def determine():

    # Import everything we can find
    hash = HashThing()
    for dirpath, dirnames, filenames in os.walk('muddled'):

        if DEBUG: print
        if DEBUG: print '%d directories in %s'%(len(dirnames), dirpath)
        for dirname in dirnames:
            if os.path.exists(os.path.join(dirpath, dirname, '__init__.py')):
                parts = dirpath.split(os.sep)
                module_name = '.'.join(parts) + '.' + dirname
                module_path = os.path.join(dirpath, dirname)
                if DEBUG: print '---', module_name, 'from', module_path
                # This works, but relies on module_name being in our path...
                module = pydoc.locate(module_name, forceload=1)
                if DEBUG: print '   ', module_name, ':', module
                hash.add(module_name, module)
                dissect(module_name, module, hash)

        if DEBUG: print
        if DEBUG: print '%d files in %s'%(len(filenames), dirpath)
        for filename in filenames:
            name, ext = os.path.splitext(filename)
            if ext == '.py':
                # We assert that the __init__.py files in muddle do not
                # contain anything we need to report.
                if name in ('__init__', '__main__'):
                        continue
                parts = dirpath.split(os.sep)
                module_name = '.'.join(parts) + '.' + name
                module_path = os.path.join(dirpath, filename)

                if DEBUG: print '---', module_name, 'from', module_path
                module = pydoc.importfile(module_path)

                if DEBUG: print '   ', module_name, ':', module
                hash.add(module_name, module)
                dissect(module_name, module, hash)

    return hash

if __name__ == '__main__':
    args = sys.argv[1:]

    hash = determine()

    if '-report' in args:
        print
        hash.report()
        sys.exit()

    if '-duplicates' in args:
        print
        print 'The following have more than one possible definition:'
        for key in sorted(hash.hash.keys()):
            if len(hash.get(key)) > 1:
                print '%s:'%key
                for name, value in sorted(hash.get(key)):
                    print '  %s : %s'%(name, value)
        sys.exit()

    for arg in args:
        try:
            results = hash.get(arg)
        except KeyError:
            print 'There is no entry for "%s"'%arg
            sys.exit(1)

        if len(results) == 1:
            results = list(results)
            name, value = results[0]

            if value is None:
                # This relies on pydoc being able to (reimport) 'name'
                print
                print pydoc.render_doc(name, 'Documentation for %s')
                continue

            print
            print '%s -> %s, %s'%(arg, name, value)
            print
            if isfunction(value):
                print 'Function %s%s'%(name, formatargspec(*getargspec(value)))
                print
                print getdoc(value)
                print
                describe_function_contents(name, value)
            elif ismethod(value):
                print 'Method %s%s'%(name, formatargspec(*getargspec(value)))
                print
                print getdoc(value)
                print
                describe_function_contents(name, value)
            elif isgenerator(value):
                print 'Generator %s%s'%(name, formatargspec(*getargspec(value)))
                print
                print getdoc(value)
                print
                describe_function_contents(name, value)
            elif isclass(value):
                mro = getmro(value)
                supers = []
                for c in mro[1:]:
                    supers.append(c.__name__)
                print 'Class %s(%s)'%(name, ', '.join(supers))
                print
                print getdoc(value)
                print
                print 'Method %s.__init__%s'%(name, formatargspec(*getargspec(value.__init__)))
                print
                print getdoc(value.__init__)
                print
                describe_contents(name, value)
            elif ismodule(value):
                print 'Module %s'%name
                print
                print getdoc(value)
                print
                describe_contents(name, value)
            else:
                print 'Something else: %s'%name
                print value
                print
                describe_contents(name, value)
        else:
            print '"%s" has more than one possibility:'%arg
            for name, value in sorted(results):
                if isfunction(value):
                    print '  Function', name
                elif ismethod(value):
                    print '  Method  ', name
                elif isclass(value):
                    print '  Class   ', name
                elif ismodule(value):
                    print '  Module  ', name
                else:
                    print '  %s -> %s'%(name, value)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
