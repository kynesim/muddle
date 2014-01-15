#! /usr/bin/env python
"""A new way of handling repositories
"""

import copy
import os
import posixpath
import re

from functools import total_ordering

from urlparse import urlparse, urljoin, urlunparse

from muddled.utils import GiveUp

_branch_and_revision_re = re.compile("([^:]*):(.*)$")

@total_ordering
class Repository(object):
    """The representation of a single repository.

    At minimum, a repository is specified by a VCS, a base URL, and a checkout
    name. For instance:

      >>> r = Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/',
      ...                'builds')

    As you might expect, it remembers what you told it:

      >>> r.vcs
      'git'
      >>> r.base_url
      'ssh://git@project-server/opt/kynesim/projects/042/git/'
      >>> r.repo_name
      'builds'

    but it also calculates the full URL for accessing the repository:

      >>> r.url
      'ssh://git@project-server/opt/kynesim/projects/042/git/builds'

    (this is calculated when the object is created because it is expected to
    be queried many times, and a Repository object is intended to be treated
    as immutable, even though we don't *enforce* that).

        Why do we split the repository into a base URL and a checkout name?
        Mainly because we assume that we are going to have more than one
        repository with the same base URL, so we can use the
        ``copy_with_changes`` method to construct new instances without
        having to constantly propagate the base URL explicitly.

    Note that it is possible for some project hosts to be treated differently
    - for instance, we have a built-in rule for google code projects:

      >>> g1 = Repository('git', 'https://code.google.com/p/grump', 'default')
      >>> g1.url
      'https://code.google.com/p/grump'
      >>> g2 = Repository('git', 'https://code.google.com/p/grump', 'wiki')
      >>> g2.url
      'https://code.google.com/p/grump.wiki'

    which is detected automatically, and the appropriate handler used. If we
    don't want that, we can explicitly say so:

      >>> g3 = Repository('git', 'https://code.google.com/p/grump', 'default',
      ...                 handler=None)
      >>> g3.url
      'https://code.google.com/p/grump/default'

    or we can ask for it explicitly by name:

      >>> g4 = Repository('git', 'https://code.google.com/p/grump', 'default',
      ...                 handler='code.google.com')
      >>> g4.url
      'https://code.google.com/p/grump'
      >>> g4.handler
      'code.google.com'

    The default handler name is actually 'guess', which tries to decide by
    looking at the repository URL and the VCS - basically, if the repository
    starts with "https://code.google.com/p/" and the VCS is 'git', then it will
    use the 'code.google.com' handler, and otherwise it won't. The 'handler'
    value reflects which handler was actually used:

      >>> g2.handler
      'code.google.com'
      >>> print g3.handler
      None
      >>> g4.handler
      'code.google.com'

    Sometimes, we need some extra "path" between the repository base path and
    the checkout name. For instance:

      >>> r = Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/',
      ...                'busybox-1.18.5', prefix='core')
      >>> r.base_url
      'ssh://git@project-server/opt/kynesim/projects/042/git/'
      >>> r.url
      'ssh://git@project-server/opt/kynesim/projects/042/git/core/busybox-1.18.5'

    By default, that prefix is added in as a pseudo-file-path - i.e., with '/'
    before and after it. If that's the wrong thing to do, then specifying
    'use_prefix_as_is=True' will cause the 'prefix' to be used as-is (does
    anyone actually support this sort of thing?):

      >>> r = Repository('git', 'http://example.com',
      ...                'busybox-1.18.5', prefix='?repo=', prefix_as_is=True)
      >>> r.base_url
      'http://example.com'
      >>> r.url
      'http://example.com?repo=busybox-1.18.5'

    Bazaar, in particular, sometimes wants to add trailing text to the checkout
    name, commonly to indicate a branch (bzr doesn't really support branches as
    such, but instead sometimes uses conventions on how different repositories
    are named). So, for instance:

      >>> r = Repository('bzr', 'ssh://bzr@project-server/opt/kynesim/projects/042/bzr/',
      ...                'repo42', suffix='/fixit_branch')
      >>> r.url
      'ssh://bzr@project-server/opt/kynesim/projects/042/bzr/repo42/fixit_branch'

    Note that we had to specify the '/' in 'suffix', it wasn't assumed.

    Git servers sometimes want us to put '.git' on the end of a checkout name.
    This can be done using the same mechanism:

        >>> r = Repository('git', 'git@github.com:tibs', 'withdir', suffix='.git')
        >>> r.url
        'git@github.com:tibs/withdir.git'

    (although note that github will cope with or without the '.git' at the end).
    Note that we had to specify the '.' in '.git', it wasn't assumed.

    Subversion allows retrieving *part* of a repository, by specifying the
    internal path leading to the entity to be retrieved. So, for instance:

      >>> r = Repository('svn', 'ssh://svn@project-server/opt/kynesim/projects/042/svn',
      ...                'all_our_code', inner_path='core/busybox-1.18.4')
      >>> r.url
      'ssh://svn@project-server/opt/kynesim/projects/042/svn/all_our_code/core/busybox-1.18.4'

    It is not intended that <inner_path> and <suffix> be used together, and the
    result if they are is not guaranteed.

    Finally, it is possible to specify a revision and branch. These are both
    handled as strings, with no defined interpretation (and are not always
    relevant to a particular VCS - see the discussion of Bazaar above).
    """

    # A dictionary of specialised path handlers.
    # Keys are of the form (vcs, starts_with), and values are handler
    # functions that take a Repository instance as their single argument
    # and return a value for our 'path' method to return.
    path_handlers = {}

    def __init__(self, vcs, base_url, repo_name, prefix=None, prefix_as_is=False,
                 suffix=None, inner_path=None, revision=None, branch=None,
                 handler='guess', push=True, pull=True):
        """Creating a new Repository instance

        - 'vcs' is the (short name) for the Version Control System being used
          to access this repository. For instance, "git" or "svn".
        - 'base_url' is the first part of the URL for the repository. This is
          separated out because it is common for different repositories to
          share the first part of their URL, not because it necessarily has
          any greater meaning.
        - 'repo_name' is the part that names this particular repository. It
          is often the same as the name of the checkout using this repository
          (but that depends on how the reposiory is accessed).
        - 'prefix' is a string to put between the 'base_url' and 'repo_name',
          when constructing the full repository URL.
        - if 'prefix_as_is' is true, then 'prefix' is inserted between
          'base_url' and 'repo_name' exactly as it is given, otherwise it is
          delimited by "/" characters. It is ignored if 'prefix' is None.
        - 'suffix' is a string to put after the 'repo_name' when constructing
          the full repository URL.
        - 'inner_path' is used to specify a path *inside* the repository, for
          version control systems that allow this (typically Subversion).
        - 'revision' is the revision to use. This should always be a string,
          regardless of what the VCS expects. It may look like an integer
          (e.g., "123") or an expression ("-r123" or "date:20120101")
          depending on the VCS.
        - 'branch' is the branch to use.
        - 'handler' is either None, or "guess" (the default) or the name of
          a registered handler for constructing the full repository URL if
          the normal mechanisms are not adequate.
        - 'push' is true if we can push to this repository. The default is
          True.
        - 'pull' is true if we can pull from this repository. The default is
          True.

        If there is no handler in action, the full repository URL is thus
        either:

            * <base_url>/<prefix>/<repo_name>/<inner_path><suffix> or
            * <base_url><prefix><repo_name>/<inner_path><suffix> or

        depending on the value of 'prefix_as_is', and with values that
        are None being turned into empty strings. Note that it is not
        really intended that both <inner_path> and <suffix> be used on
        the same repository.
        """
        self.vcs = vcs
        self.base_url = base_url

        self.repo_name = repo_name
        self.prefix = prefix
        self.prefix_as_is = prefix_as_is
        self.suffix = suffix
        self.inner_path = inner_path

        # By default, repositories can be pushed to and pulled from
        self.push = push
        self.pull = pull
        # XXX Are push and pull realy fundamental properties of the repository,
        # XXX or merely of its use(r)?

        self.from_url_string = None        # no, from parts as given

        if revision:
            # Subversion, for instance, has revisions that look like numbers.
            # It is thus very tempting for people to put the revision number
            # in *as* a number. We could, of course, normalise that into a
            # string.
            #
            # However, git also uses "numbers" as revision identifiers,
            # although they are SHA1 values, which are (large) hexadecimal
            # numbers. If someone wrote one of those as a (hex) number, then
            # we could, of course, transform that as well. But I don't think
            # git would be happy being given it as a decimal value.
            #
            # Anyway, for various reasons which come down to "let's not try to
            # be too clever", we shall insist on a string-ish type of thing.
            if not isinstance(revision, basestring):
                raise GiveUp('VCS revision value should be a string,'
                             ' not %s'%type(revision))

        self.revision = revision
        self.branch = branch

        # TODO: should revision default to HEAD - i.e., if revision is None,
        #       should we set it to "HEAD"? There is precedent in
        #       version_control.py and the vcs_handler_for function

        # Yes, this is rather horrible...
        if handler == 'guess':
            if self.vcs == 'git' and self.base_url.startswith('https://code.google.com/p/'):
                handler = 'code.google.com'
            else:
                handler = None

        self.handler = handler

        if handler:
            try:
                handler_fn = self.path_handlers[(self.vcs, handler)]
            except KeyError:
                raise GiveUp('Cannot find %s "%s" handler, for %s'%(self.vcs,
                             handler, self))
            self.url = handler_fn(self)
        else:
            self.url = self.default_path()

    def __repr__(self):
        if self.from_url_string:
            parts = [repr(self.vcs), repr(self.from_url_string)]
            if self.revision:
                parts.append('revision=%s'%repr(self.revision))
            if self.branch:
                parts.append('branch=%s'%repr(self.branch))
            if not self.push:
                parts.append('push=False')
            if not self.pull:
                parts.append('pull=False')
            return 'Repository.from_url(%s)'%(', '.join(parts))
        else:
            parts = [repr(self.vcs), repr(self.base_url), repr(self.repo_name)]
            if self.prefix:
                parts.append('prefix=%s'%repr(self.prefix))
            if self.suffix:
                parts.append('suffix=%s'%repr(self.suffix))
            if self.inner_path:
                parts.append('inner_path=%s'%repr(self.inner_path))
            if self.revision:
                parts.append('revision=%s'%repr(self.revision))
            if self.branch:
                parts.append('branch=%s'%repr(self.branch))
            if not self.push:
                parts.append('push=False')
            if not self.pull:
                parts.append('pull=False')
            return 'Repository(%s)'%(', '.join(parts))

    def __str__(self):
        """It is terribly convenient if this returns our URL.
        """
        if self.from_url_string:
            return self.from_url_string
        else:
            return self.url

    def __eq__(self, other):
        """Equal if VCS, actual URL, branch, revision, push and pull are equal.

        We don't care how the URL is derived (from parts or given as a whole),
        just that it be the same.

        So:

            >>> a = Repository('git', 'ssh://git@example.com/', 'builds')
            >>> b = Repository.from_url('git', 'ssh://git@example.com/builds')
            >>> a == b
            True
        """
        for this, that in zip(self._comparables(), other._comparables()):
            if this != that:
                return False
        return True

    def __ne__(self, other):
        """In Python2 we need to provide __ne__ as well as __eq__

        (total_ordering doesn't seem to define "ne" for us)
        """
        return not self.__eq__(other)

    def __hash__(self):
        """We need this if we want to be in sets, or as dictionary keys.
        """
        return hash(self._comparables())

    def __lt__(self, other):
        """We need this if we're to be sorted, which can be nice when printing.
        """
        for this, that in zip(self._comparables(), other._comparables()):
            if this != that:
                return this < that
        return False

    def _comparables(self):
        """What we use to identify ourself...
        """
        return (self.vcs, self.url, self.branch, self.revision,
                self.push, self.pull)

    def same_ignoring_revision(self, other):
        """Requires equality except for the revision.
        """
        return (self.vcs == other.vcs and
                self.url == other.url and
                self.branch == other.branch and
                self.push == other.push and
                self.pull == other.pull)

    def default_path(self):
        """Return the default repository path, calculated from all the parts.

        It is returned in a manner suitable for passing to the appropriate
        command line tool for cloning the repository.
        """
        parts = []
        if self.prefix_as_is:
            parts.append('%s%s%s'%(self.base_url, self.prefix, self.repo_name))
        else:
            parts.append(self.base_url)
            if self.prefix:
                parts.append(self.prefix)
            parts.append(self.repo_name)

        # We trust and hope that inner_path doesn't clash with suffix...
        if self.inner_path:
            parts.append(self.inner_path)

        # So now we have the start of our URL plus some path parts to go
        # after it. Join the path parts with posixpath.join so that
        # it will cope with parts starting with '/' correctly
        result = posixpath.join(*parts)

        if self.suffix:
            result = '%s%s'%(result, self.suffix)

        return result

    @staticmethod
    def from_url(vcs, repo_url, revision=None, branch=None, push=True, pull=True):
        """Construct a Repository instance from a URL.

        - 'vcs' is the version control system ('git', 'svn', etc.)
        - 'repo_url' is the complete URL used to access the repository
        - 'revision' and 'branch' are the revision and branch to use,
          just as for the normal constructor.
        - 'push' and 'pull' indicate whether one can push to and/or pull from
          the repository, again as for the normal constructor.

        We make a good guess as to the 'checkout name', assuming it is
        the last component of the path in the URL. But, of course, no path
        handler gets called, so the result may not be quite what is expected.

        Thus:

            >>> r = Repository.from_url('git', 'http://example.com/fred/jim.git?branch=a')
            >>> r
            Repository.from_url('git', 'http://example.com/fred/jim.git?branch=a')
            >>> r.url
            'http://example.com/fred/jim.git?branch=a'
            >>> r.repo_name
            'jim.git'
            >>> r.suffix
            '?branch=a'

        and even:

            >>> f = Repository.from_url('file', 'file:///home/tibs/versions')
            >>> f
            Repository.from_url('file', 'file:///home/tibs/versions')
            >>> f.url
            'file:///home/tibs/versions'
            >>> f.repo_name
            'versions'

        We do, however, set the 'from_url_string' value to the original URL as
        given:

            >>> f.from_url_string
            'file:///home/tibs/versions'
            >>> r.from_url_string
            'http://example.com/fred/jim.git?branch=a'

        which allows one to tell definitively what URL was requested, and
        also distinguishes this from a Repository instance created in the
        normal manner (in a normal Repository instance. 'from_url_string' will
        be None).

        Also, the handler will always be None for a Repository created with
        this method:

            >>> print f.handler
            None
            >>> print r.handler
            None
        """
        scheme, netloc, path, params, query, fragment = urlparse(repo_url)
        words = posixpath.split(path)
        repo_name = words[-1]
        other_stuff = posixpath.join(*words[:-1])
        base_url = urlunparse((scheme, netloc, other_stuff, '', '', ''))
        suffix = urlunparse(('', '', '', params, query, fragment))
        repo = Repository(vcs, base_url, repo_name, suffix=suffix,
                          revision=revision, branch=branch, handler=None,
                          push=push, pull=pull)
        repo.from_url_string = repo_url
        repo.handler = None
        return repo

    @staticmethod
    def register_path_handler(vcs, starts_with, handler):
        """Register a special handler for a particular repository location.

        * 'vcs' is the short name of the VCS we're interested in, as returned
          by split_vcs_url().
        * 'starts_with' is what a repository 'base_url' must start with in
          order for us to use the handler
        * 'handler' is a function that takes a Repository instance and
          returns a path suitable for putting into the Repository instance's
          'url' value
          method.

        For instance, the google code handler for git might be registered
        using::

            Repository.register_path_handle('git', 'https://code.google.com/p/',
                                            google_code_git_handler)

        The handler is associated with both 'vcs' and 'starts_with'. Calling
        this function again with the same 'vcs' and 'starts_with', but a
        different 'handler', will silently override the previous entry.
        """
        # For them moment, it's enough to use the 'starts_with' string as a
        # discriminator. It is possible that in the future we will need to
        # add another mechanism that calls a function to look at a Repository
        # and decide if it needs to use a handler mechanism, but for the
        # moment let's not do that.
        Repository.path_handlers[(vcs, starts_with)] = handler

    @staticmethod
    def get_path_handler(vcs, starts_with):
        """Retrieve the handler for 'vcs' and 'starts_with'.

        Returns None if there isn't one (which is actually the primary
        reason for providing this function).
        """
        return Repository.path_handlers.get((vcs, starts_with))

    def copy_with_changes(self, repo_name, prefix=None, suffix=None,
                          inner_path=None, revision=None, branch=None,
                          push=None, pull=None):
        """Return a new instance based on this one.

        A simple copy is taken, and then any amendments are made to it.

        'repo_name' must be given.

        This is expected to be (typically) useful for working out a repository
        relative to another (for instance, relative to the default, builds,
        repository). For instance:

            >>> r = Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/',
            ...                'builds')
            >>> r
            Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/', 'builds')
            >>> s = r.copy_with_changes('fred')
            >>> s
            Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/', 'fred')
            >>> s = r.copy_with_changes('jim', suffix='bob')
            >>> s
            Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/', 'jim', suffix='bob')

        Thus it does *not* default to using the branch or revision from the
        original object:

            >>> x = Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/',
            ...                'builds', revision='123', branch='fred')
            >>> x
            Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/', 'builds', revision='123', branch='fred')
            >>> x.copy_with_changes('jim')
            Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/', 'jim')
            >>> x.copy_with_changes('jim', branch='thrim')
            Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/', 'jim', branch='thrim')

        Looking at a google code example:

            >>> g = Repository('git', 'https://code.google.com/p/raw-cctv-replay', 'builds')
            >>> g.url
            'https://code.google.com/p/raw-cctv-replay.builds'
            >>> g2 = g.copy_with_changes('stuff')
            >>> g2.url
            'https://code.google.com/p/raw-cctv-replay.stuff'

        Note that, by its nature, calling this will result in a Repository
        instance that has 'from_url_string' unset.
        """
        # We do it this way, rather than making a copy.copy() and amending
        # that, so that we correctly trigger any handler actions that might
        # be necessary - a handler might be looking at any of the values
        return Repository(self.vcs, self.base_url, repo_name,
                          prefix=(self.prefix if prefix is None else prefix),
                          suffix=(self.suffix if suffix is None else suffix),
                          inner_path=(self.inner_path if inner_path is None else inner_path),
                          revision=revision,
                          branch=branch,
                          push=(self.push if push is None else push),
                          pull=(self.pull if pull is None else pull))

    def copy_with_changed_revision(self, revision):
        """Return a Repository that differs only in its revision.

        A simple copy is taken, and then the revision is changed. This is used
        in version stamping.

        For instance:

            >>> r = Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/',
            ...                'builds', revision='23')
            >>> r
            Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/', 'builds', revision='23')
            >>> s = r.copy_with_changed_revision('27')
            >>> s
            Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/', 'builds', revision='27')

        Note that the copy will have the same value of 'from_url_string' as
        the original.
        """
        # For this one, we *do* want a complete copy
        new = copy.deepcopy(self)
        new.revision = revision
        return new

    def copy_with_changed_branch(self, branch, revision=None):
        """Return a Repository that differs only in its branch (and revision).

        A simple copy is taken, and then the branch and revision are changed.
        Typically, the revision is just unset.

        Note that we don't check that you don't set the revision to the same
        value again, although it seems unlikely to be sensible in most version
        control systems to do this.

        For instance:

            >>> r = Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/',
            ...                'builds', branch='fred', revision='23')
            >>> r
            Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/', 'builds', revision='23', branch='fred')
            >>> s = r.copy_with_changed_branch('jim')
            >>> s
            Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/', 'builds', branch='jim')
            >>> s = r.copy_with_changed_branch('jim', revision='99')
            >>> s
            Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/', 'builds', revision='99', branch='jim')

        Note that the copy will have the same value of 'from_url_string' as
        the original.
        """
        # For this one, we *do* want a complete copy
        new = copy.deepcopy(self)
        new.branch = branch
        new.revision = revision     # Conveniently, defaulting to None
        return new

def google_code_handler(repo):
    """A repository path handler for google code projects.

    Google code project repository URLs are of the form:

        * https://code.google.com/p/<project> for the default repository
        * https://code.google.com/p/<project>.<repo> for any other repository

    This is registered as the "code.google.com" handler for "git".
    """

    # Note that error messages must use %r for the 'repo' representation,
    # because %s uses repo.url, which isn't set up until we've returned(!)
    if repo.vcs != 'git':
        raise GiveUp('The code.google.com handler currently only understands'
                     ' git, not %s, in %r'%(repo.vcs, repo))

    if repo.prefix:
        raise GiveUp('The code.google.com handler does not support the'
                     ' prefix value, in %r'%repo)
    if repo.suffix:
        raise GiveUp('The code.google.com handler does not support the'
                     ' suffix value, in %r'%repo)
    if repo.inner_path:
        raise GiveUp('The code.google.com handler does not support the'
                     ' inner_path value, in %r'%repo)

    if repo.repo_name == 'default':
        return repo.base_url
    else:
        # If we're going to put '.<repo_name>' on the end, we don't want a
        # trailing '/'
        if repo.base_url[-1] == '/':
            repo.base_url = repo.base_url[:-1]
        return '%s.%s'%(repo.base_url, repo.repo_name)

Repository.register_path_handler('git', 'code.google.com', google_code_handler)

# Some convenience functions
def get_checkout_repo(builder, co_label):
    """Returns the Repository instance for this checkout label

    A convenience wrapper around 'builder.db.get_checkout_repo'.
    """
    return builder.db.get_checkout_repo(co_label)

def add_upstream_repo(builder, orig_repo, upstream_repo, names):
    """Add an upstream repo to 'orig_repo'.

    - 'orig_repo' is the original Repository that we are adding an
      upstream for.
    - 'upstream_repo' is the upstream Repository. It is an error if
      that repository is already an upstream of 'orig_repo'.
    - 'names' is a either a single string, or a sequence of strings, that can
      be used to select this (and possibly other) upstream repositories.

    Upstream repository names must be formed of A-Z, a-z, 0-9 and underscore or
    hyphen.

    A convenience wrapper around 'builder.db.add_upstream_repo'.
    """
    builder.db.add_upstream_repo(orig_repo, upstream_repo, names)

def get_upstream_repos(builder, orig_repo, names=None):
    """Retrieve the upstream repositories for 'orig_repo'

    If 'names' is given, it must be a sequence of strings, in which
    case only those upstream repositories annotated with any of the
    names will be returned.

    Returns a set of upstream repositories. This will be empty if there
    are no upstream repositories for 'orig_repo', or none with any of the
    names in 'names' (if given).

    A convenience wrapper around 'builder.db.get_upstream_repos'.
    """
    return builder.db.add_upstream_repo(orig_repo, names)

if __name__ == '__main__':
    print 'Running doctests'
    import doctest
    failures, tests = doctest.testmod()
    print '{failures} failures in {tests} tests'.format(failures=failures, tests=tests)
    print 'Running other tests'
    r = Repository('git', 'https://fred', 'jim', branch='99')
    print r
    assert repr(r) == "Repository('git', 'https://fred', 'jim', branch='99')"
    h = Repository.get_path_handler('git', 'https://code.google.com/p/')
    assert h is None
    h = Repository.get_path_handler('git', 'https://code.google.com/fred')
    assert h is None
    print 'OK'

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
