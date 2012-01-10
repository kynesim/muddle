#! /usr/bin/env python
"""A new way of handling repositories
"""

import os
import re

class GiveUp(Exception):
    pass

branch_and_revision_re = re.compile("([^:]*):(.*)$")

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
      >>> r.co_name
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

    The default handler name is actually 'guess', which tries to decide by
    looking at the repository URL - basically, if the repository starts with
    "https://code.google.com/p/" it will use the 'code.google.com' handler,
    and otherwise it won't.

      Note: this only applies if the VCS is 'git' at the moment.

    Sometimes, we need some extra "path" between the repository base path and
    the checkout name. For instance:

      >>> r = Repository('git', 'ssh://git@project-server/opt/kynesim/projects/042/git/',
      ...                'busybox-1.18.5', prefix='core')
      >>> r.base_url
      'ssh://git@project-server/opt/kynesim/projects/042/git/'
      >>> r.url
      'ssh://git@project-server/opt/kynesim/projects/042/git/core/busybox-1.18.5'

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

      >>> r = Repository('svn', 'ssh://svn@project-server/opt/kynesim/projects/042/svn/',
      ...                'all_our_code', inner_path='core/busybox-1.18.4')
      >>> r.url
      'ssh://svn@project-server/opt/kynesim/projects/042/svn/all_our_code/core/busybox-1.18.4'

    If you specify more than one of 'extension' and 'inner_path', the result
    is undefined.

    Finally, it is possible to specify a revision and branch. These are both
    handled as strings, with no defined interpretation (and are not always
    relevant to a particular VCS - see the discussion of Bazaar above).

    For legacy reasons, a combined form is also supported:

        >>> r = Repository('git', 'git@github.com:tibs', 'withdir', revision='branch2:rev99')
        >>> r.branch
        'branch2'
        >>> r.revision
        'rev99'
    """

    # A dictionary of specialised path handlers.
    # Keys are of the form (vcs, starts_with), and values are handler
    # functions that take a Repository instance as their single argument
    # and return a value for our 'path' method to return.
    path_handlers = {}

    def __init__(self, vcs, base_url, co_name, prefix=None, suffix=None,
                 inner_path=None, revision=None, branch=None, handler='guess'):
        self.vcs = vcs
        self.base_url = base_url

        self.co_name = co_name
        self.prefix = prefix
        self.suffix = suffix
        self.inner_path = inner_path

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
            # Which, of course, we can test by finding out if the next call
            # falls over at us...

            # Check for the legacy mechanism for specifying a branch
            # (i.e., as a revision of "<branch>:<revision>")
            # This will clash with any branch specified as an argument
            try:
                maybe_branch, maybe_revision = self._parse_revision(revision)
            except TypeError:
                raise utils.GiveUp('VCS revision value should be a string,'
                                   ' not %s'%type(revision))
            if branch and maybe_branch:
                raise utils.GiveUp('VCS revision value "%s" specifies branch'
                                   ' "%s", but branch "%s" was specified'
                                   ' explicitly'%(revision, maybe_branch, branch))

            revision = maybe_revision
            if maybe_branch:
                branch = maybe_branch

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

        if handler:
            try:
                handler_fn = self.path_handlers[(self.vcs, handler)]
            except KeyError:
                raise GiveUp('Cannot find %s "%s" handler, for %s'%(self.vcs,
                             handler, self))
            self.url = handler_fn(self)
        else:
            self.url = self.default_path()

    def _parse_revision(self, revision):
        """
        Legacy build descriptions may be passing the branch required as
        part of the revision, i.e., as '<branch>:<revision>'. So we need
        to support this, at least for a while.

        Return <branch>, <revision>

        If the given string *does* include a <branch> component, then
        it overrides any 'branch' argument we may be given.
        """
        m = branch_and_revision_re.match(revision)
        if m:
            branch = m.group(1)
            revision = m.group(2)
            # No need to adjust HEAD - git uses it too.
            return branch, revision
        else:
            return None, revision

    def __repr__(self):
        parts = [repr(self.vcs), repr(self.base_url), repr(self.co_name)]
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
        return 'Repository(%s)'%(', '.join(parts))

    def default_path(self):
        """Return the default repository path, calculated from all the parts.

        It is returned in a manner suitable for passing to the appropriate
        command line tool for cloning the repository.
        """
        parts = [self.base_url]
        if self.prefix:
            parts.append(self.prefix)
        parts.append(self.co_name)
        # We trust and hope that inner_path doesn't clash with suffix...
        if self.inner_path:
            parts.append(self.inner_path)
        result = os.path.join(*parts)

        if self.suffix:
            result = '%s%s'%(result, self.suffix)

        return result

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

    def copy_with_changes(self, co_name, prefix=None, suffix=None,
                          inner_path=None, revision=None, branch=None):
        """Return a new instance based on this one.

        A simple copy is taken, and then any amendments are made to it.

        'co_name' must be given.

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
        """
        # We do it this way, rather than making a copy.copy() and amending
        # that, so that we correctly trigger any handler actions that might
        # be necessary - a handler might be looking at any of the values
        return Repository(self.vcs, self.base_url, co_name,
                          prefix=(self.prefix if prefix is None else prefix),
                          suffix=(self.suffix if suffix is None else suffix),
                          inner_path=(self.inner_path if inner_path is None else inner_path),
                          revision=revision,
                          branch=branch)

def google_code_handler(repo):
    if repo.vcs != 'git':
        raise GiveUp('The code.google.com handler currently only understands'
                     ' git, not %s, in %s'%(vcs, repo))

    if repo.prefix:
        raise GiveUp('The code.google.com handler does not support the'
                     ' prefix value, in %s'%repo)
    if repo.suffix:
        raise GiveUp('The code.google.com handler does not support the'
                     ' suffix value, in %s'%repo)
    if repo.inner_path:
        raise GiveUp('The code.google.com handler does not support the'
                     ' inner_path value, in %s'%repo)

    if repo.co_name == 'default':
        return repo.base_url
    else:
        return '%s.%s'%(repo.base_url, repo.co_name)

Repository.register_path_handler('git', 'code.google.com', google_code_handler)

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
