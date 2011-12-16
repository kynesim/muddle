#! /usr/bin/env python
"""A new way of handling repositories
"""

class GiveUp(Exception):
    pass

class Repository(object):
    """The representation of a single repository.

    At minimum, a repository is specified by a base path, and a checkout name.
    For instance:

      >>> r = Repository('git+ssh://git@project-server/opt/kynesim/projects/042/git/',
      ...                'builds')
      >>> r.path()
      "ssh://git@project-server/opt/kynesim/projects/042/git/builds"
      >>> r.base_path
      'git+ssh://git@project-server/opt/kynesim/projects/042/git/'
      >>> r.co_name
      'builds'
      >>> r.vcs
      'git'
      >>> r.repo
      'ssh://git@project-server/opt/kynesim/projects/042/git/'

    Note that it is possible for some project hosts to be treated differently
    - for instance, we have a built-in rule for google code projects:

      >>> g1 = Repository('git+https://code.google.com/p/grump', 'default')
      >>> g1.path()
      'https://code.google.com/p/grump/'
      >>> g2 = Repository('git+https://code.google.com/p/grump', 'wiki')
      >>> g2.path()
      'https://code.google.com/p/grump.wiki/'

    Sometimes, we need some extra "path" between the repository base path and
    the checkout name. For instance:

      >>> r = Repository('git+ssh://git@project-server/opt/kynesim/projects/042/git/',
      ...                'busybox-1.18.5', prefix='core')
      >>> r.path()
      'git+ssh://git@project-server/opt/kynesim/projects/042/git/core/busybox-1.18.5'

    Git servers sometimes want us to put '.git' on the end of a checkout name.
    This can be done as follows:

        >>> r = Repository('git+git@github.com:tibs', 'withdir', extension='.git')
        >>> r.path()
        'git@github.com:tibs/withdir.git'

    (although note that github will cope with or without the '.git' at the end).

    Bazaar, in particular, sometimes wants to add trailing text to the checkout
    name, commonly to indicate a branch (bzr doesn't really support branches as
    such, but instead sometimes uses conventions on how different repositories
    are named). So, for instance:

      >>> r = Repository('bzr+ssh://bzr@project-server/opt/kynesim/projects/042/bzr/',
      ...                'repo42', postfix='fixit_branch')
      >>> r.path()
      'ssh://bzr@project-server/opt/kynesim/projects/042/bzr/repo42/fixit_branch'

    Subversion allows retrieving *part* of a repository, by specifying the
    internal path leading to the entity to be retrieved. So, for instance:

      >>> r = Repository('svn+ssh://svn@project-server/opt/kynesim/projects/042/svn/',
      ...                'all_our_code', inner_path='core/busybox-1.18.4')
      >>> r.path()
      'ssh://svn@project-server/opt/kynesim/projects/042/svn/all_our_code/core/busybox-1.18.4'

    Finally, it is possible to specify a revision and branch. These are both
    handled as strings, with no defined interpretation (and are not always
    relevant to a particular VCS - see the discussion of Bazaar above).
    """

    # A dictionary of specialised path handlers.
    # Keys are of the form (vcs, starts_with), and values are handler
    # functions that take a Repository instance as their single argument
    # and return a value for our 'path' method to return.
    path_handlers = {}

    def __init__(self, base_path, co_name, prefix=None, extension=None, postfix=None,
                 inner_path=None, revision=None, branch=None):
        self.base_path = base_path

        # Work out our VCS
        parts = base_path.split('+')
        if len(parts) == 1 or parts[0] == '':
            raise GiveUp('Repository base_path must be <vcs>+<url>,'
                         ' but got "%s"'%base_path)

        self.vcs = parts[0]
        self.repo = '+'.join(parts[1:])  # we'll hope that made sense

        self.co_name = co_name
        self.prefix = prefix
        self.extension = extension
        self.postfix = postfix
        self.inner_path = inner_path
        self.revision = revision
        self.branch = branch

    def __repr__(self):
        parts = [repr(self.base_path), repr(self.co_name)]
        if self.prefix:
            parts.append('prefix=%s'%repr(self.prefix))
        if self.extension:
            parts.append('extension=%s'%repr(self.extension))
        if self.postfix:
            parts.append('postfix=%s'%repr(self.postfix))
        if self.inner_path:
            parts.append('inner_path=%s'%repr(self.inner_path))
        if self.revision:
            parts.append('revision=%s'%repr(self.revision))
        if self.branch:
            parts.append('branch=%s'%repr(self.branch))
        return 'Repository(%s)'%(', '.join(parts))

    def path(self):
        """Return the repository path.

        It is returned in a manner suitable for passing to the appropriate
        command line tool for cloning the repository.
        """
        raise NotImplementedError

    @staticmethod
    def register_path_handler(vcs, starts_with, handler):
        """Register a special handler for a particular repository location.

        * 'vcs' is the short name of the VCS we're interested in, as returned
          by split_vcs_url().
        * 'starts_with' is what a repository 'base_path' must start with in
          order for us to use the handler
        * 'handler' is a function that takes a Repository instance and
          returns a path suitable for return by the Repository 'path()'
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

def google_code_handler(repo):
    return 'Fred'

Repository.register_path_handler('git', 'https://code.google.com/p/',
                                 google_code_handler)

if __name__ == '__main__':
    import doctest
    doctest.testmod()
    r = Repository('git+https://fred', 'jim', branch='99')
    print r
    h = Repository.get_path_handler('git', 'https://code.google.com/p/')
    print h
    h = Repository.get_path_handler('git', 'https://code.google.com/fred')
    print h

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
