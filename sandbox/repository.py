"""A new way of handling repositories
"""

class Repository(object):
    """The representation of a single repository.

    At minimum, a repository is specified by a base path, and a checkout name.
    For instance:

      >>> r = Repository('git+ssh://git@project-server/opt/kynesim/projects/042/git/',
                         'builds')
      >>> r.path()
      "ssh://git@project-server/opt/kynesim/projects/042/git/builds"

    Note that it is possible for some project hosts to be treated differently
    - for instance, we have a built-in rule for google code projects:

      >>> g1 = Repository('git+https://code.google.com/p/grump', 'default')
      >>> g1.path()
      "https://code.google.com/p/grump/'
      >>> g2 = Repository('git+https://code.google.com/p/grump', 'wiki')
      >>> g2.path()
      "https://code.google.com/p/grump.wiki/'

    Sometimes, we need some extra "path" between the repository base path and
    the checkout name. For instance:

      >>> r = Repository('git+ssh://git@project-server/opt/kynesim/projects/042/git/',
                         'busybox-1.18.5', prefix='core')
      >>> r.path()
      "git+ssh://git@project-server/opt/kynesim/projects/042/git/core/busybox-1.18.5'

    Git servers sometimes want us to put '.git' on the end of a checkout name.
    This can be done as follows:

        >>> r = Repository('git+git@github.com:tibs', 'withdir', extension='.git')
        >>> r.path()
        "git@github.com:tibs/withdir.git"

    (although note that github will cope with or without the '.git' at the end).

    Bazaar, in particular, sometimes wants to add trailing text to the checkout
    name, commonly to indicate a branch (bzr doesn't really support branches as
    such, but instead sometimes uses conventions on how different repositories
    are named). So, for instance:

      >>> r = Repository('bzr+ssh://bzr@project-server/opt/kynesim/projects/042/bzr/',
                         'repo42', postfix='fixit_branch')
      >>> r.path()
      "ssh://bzr@project-server/opt/kynesim/projects/042/bzr/repo42/fixit_branch"

    Subversion allows retrieving *part* of a repository, by specifying the
    internal path leading to the entity to be retrieved. So, for instance:

      >>> r = Repository('svn+ssh://svn@project-server/opt/kynesim/projects/042/svn/',
                         'all_our_code', inner_path='core/busybox-1.18.4')
      >>> r.path()
      "ssh://svn@project-server/opt/kynesim/projects/042/svn/all_our_code/core/busybox-1.18.4')

    Finally, it is possible to specify a revision and branch. These are both
    handled as strings, with no defined interpretation (and are not always
    relevant to a particular VCS - see the discussion of Bazaar above).
    """

    def __init__(self, base_path, co_name, prefix=None, extension=None, postfix=None,
                 inner_path=None, revision=None, branch=None):
        self.base_path = base_path
        self.co_name = co_name,
        self.prefix = prefix
        self.postfix = postfix
        self.inner_path = inner_path
        self.revision = revision
        self.branch = branch

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
        """
        raise NotImplementedError

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
