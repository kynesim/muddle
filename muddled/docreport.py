#! /usr/bin/env python

"""Extract documentation from inside muddle itself.

This is *very* muddle specific - if you want something more general, stick
with pydoc (which, for instance, honours __all__ if it finds it).
"""

import os
import sys
import imp
import pydoc

from inspect import getmembers, isfunction, isclass, ismethod, ismodule, \
        isgenerator, getargspec, formatargspec, getmro, getdoc, getmodule, \
        getfile

import utils

from muddled.utils import GiveUp, page_text
from muddled.withdir import Directory


class HashThing(object):

    def __init__(self):
        self.hash = {}
        self.full_names = set()

    def add(self, name, value):
        """Given a.b.c:3, add a.b.c:3, b.c:3, c:3
        """
        self.full_names.add(name)
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

    def dump(self):
        """Return a sorted lists of lines describing our dictionary content
        """
        keys = sorted(self.hash.keys())
        maxlen = 0
        for key in keys:
            if len(key) > maxlen:
                maxlen = len(key)
        lines = []
        for key in keys:
            parts = []
            for name, value in self.hash[key]:
                what = value.__class__.__name__
                if what == 'type':
                    what = 'class'
                parts.append('<%s %s>'%(what, name))
            lines.append('%-*s : %s'%(maxlen, key, ', '.join(parts)))
        return lines

    def contains(self, word):
        result = []
        for name in self.full_names:
            if word in name:
                result.append('  %s'%name)
        return ['The following names contain "%s":'%word] + sorted(result)

    def duplicates(self):
        lines = ['The following have more than one possible definition:']
        for key in sorted(self.hash.keys()):
            if len(self.hash[key]) > 1:
                lines.append('%s:'%key)
                for name, value in sorted(self.hash[key]):
                    what = value.__class__.__name__.capitalize()
                    if what == 'Type':
                        what = 'Class'
                    lines.append('  %-15s %s'%(what, name))
        return lines

DEBUG = False

def dissect(thing_name, thing, hash):
    for name, value in getmembers(thing):
        this_name = '%s.%s'%(thing_name, name)
        if getmodule(value) != getmodule(thing):
            # Doesn't look like 'thing' defined this - presumably imported
            continue
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
        elif ismodule(value):
            continue
        else:
            contents.append('            %s = <%s>'%(this_name, type(value).__name__))
    if len(contents):
        contents = ['Contents:'] + sorted(contents)
    return contents

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

def report__doc__(value):
    if value.__doc__:
        return ['', getdoc(value)]
    else:
        return []

def wrapargs(text):
    try:
        return utils.wrap(text, subsequent_indent='    ')
    except:
        return text

def report_on_item_ourselves(name, value):
    lines = []
    if isfunction(value):
        lines.append(wrapargs('FUNCTION %s%s'%(name, formatargspec(*getargspec(value)))))
        lines.extend(report__doc__(value))
    elif ismethod(value):
        lines.append(wrapargs('METHOD %s%s'%(name, formatargspec(*getargspec(value)))))
        lines.extend(report__doc__(value))
    elif isgenerator(value):
        lines.append(wrapargs('GENERATOR %s%s'%(name, formatargspec(*getargspec(value)))))
        lines.extend(report__doc__(value))
    elif isclass(value):
        mro = getmro(value)
        supers = []
        for c in mro[1:]:
            supers.append(c.__name__)
        lines.append('CLASS %s(%s)'%(name, ', '.join(supers)))
        lines.extend(report__doc__(value))
        lines.append('')
        lines.append(wrapargs('METHOD %s.__init__%s'%(name, formatargspec(*getargspec(value.__init__)))))
        lines.extend(report__doc__(value.__init__))
        lines.append('')
        lines.extend(describe_contents(name, value))
    elif ismodule(value):
        lines.append('MODULE %s'%name)
        lines.extend(report__doc__(value))
        lines.append('')
        lines.extend(describe_contents(name, value))
    else:
        lines.append('SOMETHING ELSE: %s'%name)
        lines.append(value)
        lines.append('')
        lines.extend(describe_contents(name, value))
    return lines

def report_on_item(what, name, value, use_render_doc):
    lines = []
    lines.append('')
    lines.append('%s is %s'%(what, name))
    try:
        lines.append('%s in %s'%(' '*len(what), os.path.abspath(getfile(value))))
    except TypeError:
        lines.append('%s is <built-in>'%(' '*len(what)))
    lines.append('')

    if use_render_doc:
        # Just use pydoc's own tool
        lines.append(pydoc.render_doc(value, 'Documentation for %s'))
    else:
        lines.extend(report_on_item_ourselves(name, value))

    return lines

def report_on_multiple_results(what, results):
    lines = ['"%s" has more than one possibility:'%what]
    for name, value in sorted(results):
        if isfunction(value):
            lines.append('  Function %s'%name)
        elif ismethod(value):
            lines.append('  Method  %s'%name)
        elif isclass(value):
            lines.append('  Class   %s'%name)
        elif ismodule(value):
            lines.append('  Module  %s'%name)
        else:
            lines.append('  %s -> %s'%(name, value))
    return lines

def page(pager, stuff):
    # Allow for being passed a list of parts/lines
    if not isinstance(stuff, basestring):
        stuff = '\n'.join(stuff)

    try:
        page_text(pager, stuff)
    except IOError: # For instance, a pipe error due to 'q' at the prompt
        pass

def report(args):
    """Print out documentation on modules, classes, methods or functions in muddle.

    'args' are the arguments from the "muddle doc" command.

    "Normal" arguments are:

        * '<name>'               for help on <name>
        * '-contains', '<what>'  to list all names that contain <what>

    and also, for more specialise use (well, I use them):

        * '-duplicates'          to list all duplicate (partial) names
        * '-list'                to list all the "full" names we know
        * '-dump'                to dump the internal map of names/values

    all of which tend to generate long output.

    Additional arguments may also be the switches:

        * '-p', '<pager>' or '-pager', '<pager>'

          to specify a pager through which the text will be piped.The default
          is $PAGER (if set) or else 'more'.

        * '-nop' or '-nopager'

          don't use a pager, just print the text out.

        * '-pydoc'

          Use pydoc's rendering to output the text about the item. This tends
          to produce more information.

    For more information, see "muddle help doc".
    """

    # We want to do our investigations from the directory containing the
    # "muddled/" directory. Luckily, we believe we know where that is...
    this_file = os.path.abspath(__file__)
    this_dir = os.path.split(this_file)[0]
    parent_dir = os.path.split(this_dir)[0]

    with Directory(parent_dir, show_pushd=False):
        hash = determine()

    use_render_doc = False
    DUMP, DUPLICATES, CONTAINS, LIST, DOC = 'dump', 'duplicates', 'contains', 'list', 'doc'
    want = DOC
    what = None
    dup = None
    pager = os.environ.get('PAGER', 'more')

    while args:
        word = args.pop(0)
        if word == '-dump':
            want = DUMP
        elif word == '-duplicates':
            want = DUPLICATES
        elif word == '-list':
            want = LIST
        elif word in ('-p', '-pager'):
            try:
                pager = args.pop(0)
            except IndexError:
                raise GiveUp('"-pager" needs an argument')
        elif word in ('-nop', '-nopager'):
            pager = None
        elif word in ('-contains', '-contain'):
            want = CONTAINS
            try:
                dup = args.pop(0)
            except IndexError:
                raise GiveUp('"-contains" needs an argument')
        elif word == '-pydoc':
            use_render_doc = True
        elif word.startswith('-'):
            raise GiveUp('Unexpected switch "%s"'%word)
        elif what is not None:
            raise GiveUp('Too many arguments: %s %s'%(word, ' '.join(args)))
        else:
            what = word

    if what and want is not DOC:
        raise GiveUp('The switches do not need argument "%s"'%what)

    if want == DUMP:
        page(pager, hash.dump())
    elif want == DUPLICATES:
        page(pager, hash.duplicates())
    elif want == LIST:
        page(pager, sorted(hash.full_names))
    elif want == CONTAINS:
        page(pager, hash.contains(dup))
    elif want == DOC:
        try:
            results = hash.get(what)
        except KeyError:
            raise GiveUp('There is no information for "%s"'%what)

        if len(results) == 1:
            results = list(results)
            name, value = results[0]
            page(pager, report_on_item(what, name, value, use_render_doc))

        else:
            page(pager, report_on_multiple_results(what, results))

if __name__ == '__main__':
    args = sys.argv[1:]
    try:
        report(args)
    except GiveUp as e:
        print e
        sys.exit(1)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
