"""Useful tools for changing into a directory.

This is the muddle version. It is close to that at
https://github.com/tibs/withdir, but integrated with muddle - specifically, it
uses muddle's GiveUp exception.
"""

import os
import sys
import shutil
import tempfile

from muddled.utils import normalise_dir, GiveUp

class Directory(object):
    """A class to facilitate pushd/popd behaviour

    It is intended for use with 'with', as in::

        with Directory('~'):
            print 'My home directory contains'
            print ' ',' '.join(os.listdir('.'))

    or::

        with Directory('fred') as d:
            print 'In directory', d.where

    'where' is the directory to change to. The value 'self.where' will be
    set to a normalised version of 'where'. It is an error if the directory
    does not exist, in which case a GiveUp exception will be raised.

    If 'stay_on_error' is true, then the directory will not be left ("popd"
    will not be done) if an exception occurs in its 'with' clause.

    If 'show_pushd' is true, then a message will be printed out showing the
    directory that is being 'cd'ed into.

    If 'show_popd' is true, then a message will be printed out showing the
    directory that is being returned to. An extra "wrapper" message for any
    exception being propagated out will also be shown.

    If 'set_PWD' is true, then set the os.environ['PWD'] to the directory
    that is being "cd"ed into. This emulates the behaviour of "cd" in bash.
    Checking the value of PWD is often used to find out what directory the
    user thinks they are in, especially in the presence of soft links in
    directory trees.
    """
    def __init__(self, where, stay_on_error=False, show_pushd=True,
                 show_popd=False, set_PWD=True):
        self.start = normalise_dir(os.getcwd())
        self.where = normalise_dir(where)
        self.close_on_error = not stay_on_error
        self.show_pushd = show_pushd
        self.show_popd = show_popd
        self.set_PWD = set_PWD
        try:
            os.chdir(self.where)
        except OSError as e:
            raise GiveUp('Cannot change to directory %s: %s\n'%(where, e))

        if set_PWD:
            if 'PWD' in os.environ:
                self.got_old_PWD = True
                self.old_PWD = os.environ['PWD']
            else:
                self.got_old_PWD = False
                self.old_PWD = None
            os.environ['PWD'] = self.where

        if show_pushd:
            sys.stdout.write('++ pushd to %s\n'%self.where)

    def join(self, *args):
        """Return ``os.path.join(self.where, *args)``.
        """
        return os.path.join(self.where, *args)

    def close(self):
        os.chdir(self.start)

        if self.set_PWD:
            if self.got_old_PWD:
                os.environ['PWD'] = self.old_PWD
            else:
                del os.environ['PWD']

        if self.show_popd:
            sys.stdout.write('++ popd to  %s\n'%self.start)

    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        if tb is None:
            # No exception, so just finish normally
            self.close()
        else:
            # An exception occurred, so do any tidying up necessary
            if self.show_popd:
                sys.stdout.write('** Oops, an exception occurred - %s tidying up\n'%self.__class__.__name__)
            # well, there isn't anything special to do, really
            if self.close_on_error:
                self.close()
            if self.show_popd:
                sys.stdout.write('** ----------------------------------------------------------------------\n')
            # And allow the exception to be re-raised
            return False

class NewDirectory(Directory):
    """A pushd/popd directory that gets created first.

    If 'where' is given, then it is the directory to change to. In this case it
    is an error if the directory already exists, in which case a GiveUp
    exception will be raised.

    If 'where' is None, then tempfile.mkdtemp() will be used to create a
    directory, and that will be used.

    In either case the value 'self.where' will be set to a normalised version
    of 'where'.

    If 'stay_on_error' is True, then the directory will not be left ("popd"
    will not be done) if an exception occurs in its 'with' clause.

    If 'show_pushd' is true, then a message will be printed out showing the
    directory that is being 'cd'ed into.

    If 'show_popd' is true, then a message will be printed out showing the
    directory that is being returned to. An extra "wrapper" message for any
    exception being propagated out will also be shown.

    If 'set_PWD' is true, then set the os.environ['PWD'] to the directory
    that is being "cd"ed into. This emulates the behaviour of "cd" in bash.
    Checking the value of PWD is often used to find out what directory the
    user thinks they are in, especially in the presence of soft links in
    directory trees.

    If 'show_dirops' is true, then a message will be printed out showing the
    'mkdir' command used to create the new directory.
    """
    def __init__(self, where=None, stay_on_error=False, show_pushd=True,
                 show_popd=False, set_PWD=True, show_dirops=True):
        self.show_dirops = show_dirops
        if where is None:
            where = tempfile.mkdtemp()
            if show_dirops:     # Obviously, this is a bit of a bluff
                # The extra spaces are to line up with 'pushd to'
                sys.stdout.write('++ mkdir    %s\n'%where)
        else:
            where = normalise_dir(where)
            if os.path.exists(where):
                raise GiveUp('Directory %s already exists'%where)
            if show_dirops:
                # The extra spaces are to line up with 'pushd to'
                sys.stdout.write('++ mkdir    %s\n'%where)
            os.makedirs(where)
        super(NewDirectory, self).__init__(where, stay_on_error, show_pushd,
                                           show_popd, set_PWD)

class TransientDirectory(NewDirectory):
    """A pushd/popd directory that gets created first and deleted afterwards

    If 'where' is given, then it is the directory to change to. In this case it
    is an error if the directory already exists, in which case a GiveUp
    exception will be raised.

    If 'where' is None, then tempfile.mkdtemp() will be used to create a
    directory, and that will be used.

    In either case the value 'self.where' will be set to a normalised version
    of 'where'.

    If 'stay_on_error' is True, then the directory will not be left ("popd"
    will not be done) if an exception occurs in its 'with' clause.

    If 'keep_on_error' is True, then the directory will not be deleted
    if an exception occurs in its 'with' clause.

    If 'keep_anyway' is True, then the directory will not be deleted - this
    is sometimes useful in test code where one wishes to choose whether to
    retain a test directory or not.

    If 'show_pushd' is true, then a message will be printed out showing the
    directory that is being 'cd'ed into.

    If 'show_popd' is true, then a message will be printed out showing the
    directory that is being returned to. An extra "wrapper" message for any
    exception being propagated out will also be shown.

    If 'set_PWD' is true, then set the os.environ['PWD'] to the directory
    that is being "cd"ed into. This emulates the behaviour of "cd" in bash.
    Checking the value of PWD is often used to find out what directory the
    user thinks they are in, especially in the presence of soft links in
    directory trees.

    If 'show_dirops' is true, then a message will be printed out showing the
    'mkdir' command used to create and the 'rmtree' command used to delete the
    transient directory.
    """
    def __init__(self, where=None, stay_on_error=False, keep_on_error=False,
                 keep_anyway=False, show_pushd=True, show_popd=False,
                 set_PWD=True, show_dirops=True):
        self.rmtree_on_error = not keep_on_error and not keep_anyway
        self.dont_delete = not keep_anyway
        super(TransientDirectory, self).__init__(where, stay_on_error,
                                                 show_pushd, show_popd,
                                                 set_PWD, show_dirops)

    def close(self, delete_tree):
        # Don't delete the tree unless asked to
        super(TransientDirectory, self).close()
        if delete_tree:
            if self.show_dirops:
                # The extra space after 'rmtree' is so the directory name
                # left aligns with any previous 'popd  to' message
                sys.stdout.write('++ rmtree   %s\n'%self.where)
            shutil.rmtree(self.where)

    def __exit__(self, etype, value, tb):
        if tb is None:
            # No exception, so just finish normally
            self.close(self.dont_delete)
        else:
            # An exception occurred, so do any tidying up necessary
            if self.show_popd:
                sys.stdout.write('** Oops, an exception occurred - %s tidying up\n'%self.__class__.__name__)
            if self.close_on_error:
                self.close(self.rmtree_on_error)
            if self.show_popd:
                sys.stdout.write('** ----------------------------------------------------------------------\n')
            # And allow the exception to be re-raised
            return False


class NewCountedDirectory(NewDirectory):
    """A version of NewDirectory that prefixes a count to its directory names.

    Given a directory name <name>, the actual directory will be <count>.<name>,
    where <count> is a 2 digit value starting at 01.

    It is deliberately kept fairly limited in its options - specifically,
    it doesn't support most of the options that NewDirectory does. This
    decision may be revisited later.
    """

    dir_count = 0

    def __init__(self, name):
        NewCountedDirectory.dir_count += 1
        name = '%02d.%s'%(NewCountedDirectory.dir_count, name)
        super(NewCountedDirectory, self).__init__(name)
