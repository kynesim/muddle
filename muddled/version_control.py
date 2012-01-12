"""
Routines which deal with version control.
"""

import re
import os

import muddled.pkg as pkg
import muddled.utils as utils

from muddled.depend import Label
from repository import Repository

branch_and_revision_re = re.compile("([^:]*):(.*)$")

class VersionControlSystem(object):
    """
    Provide version control operations for a particular VCS.

    This is a super-class, acting as a template for the actual classes.

    The intent is  that implementors of this interface do not need to know
    anything at all about muddle.
    """

    def __init__(self):
        self.short_name = 'NoName'
        self.long_name = 'No VCS name'

    def init_directory(self, files=None, verbose=True):
        """
        If the directory does not appear to have had '<vcs> init' run in it,
        then do so first.

        Will be called in the actual checkout's directory.
        """
        pass

    def add_files(self, files=None, verbose=True):
        """
        If files are given, add them, but do not commit.

        Will be called in the actual checkout's directory.
        """
        pass

    def checkout(self, repo, co_leaf, options, verbose=True):
        """
        Checkout (clone) a given checkout.

        Will be called in the parent directory of the checkout.

        Expected to create a directory called <co_leaf> therein.

        Any exception raised will be "wrapped" by the calling handler.
        """
        pass

    def fetch(self, repo, options, verbose=True):
        """
        Will be called in the actual checkout's directory.

        Any exception raised will be "wrapped" by the calling handler.
        """
        pass

    def merge(self, other_repo, options, verbose=True):
        """
        Will be called in the actual checkout's directory.

        Any exception raised will be "wrapped" by the calling handler.
        """
        pass

    def commit(self, repo, options, verbose=True):
        """
        Will be called in the actual checkout's directory.

        Any exception raised will be "wrapped" by the calling handler.
        """
        pass

    def push(self, repo, options, branch=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        Any exception raised will be "wrapped" by the calling handler.
        """
        pass

    def status(self, repo, options):
        """
        Will be called in the actual checkout's directory.

        Return status text or None if there is no interesting status.
        """
        pass

    def reparent(self, co_leaf, remote_repo, options, force=False, verbose=True):
        """
        TODO: Is 'co_leaf' (used for reporting problems) the best thing to
        pass down? It shouldn't be too long, so the entire directory path
        is not appropriate...

        Will be called in the actual checkout's directory.
        """
        if verbose:
            print "Re-associating checkout '%s' with remote repository:" \
                    " %s does not support 'reparent'"%(co_leaf, self.short_name)

    def revision_to_checkout(self, repo, co_leaf, options, force=False, verbose=True):
        """
        TODO: Is 'co_leaf' (used for reporting problems) the best thing to
        pass down? It shouldn't be too long, so the entire directory path
        is not appropriate...

        Will be called in the actual checkout's directory.
        """
        raise utils.GiveUp("VCS '%s' cannot calculate a checkout revision"%self.long_name)

    def allows_relative_in_repo(self):
        """
        Does this VCS allow relative locations within the repository to be checked out?

        Subversion does. Distributed revision control systems tend not to.
        """
        return False

    def get_file_content(self, url, options, verbose=True):
        """
        Retrieve a file's content via a VCS.
        """
        raise utils.GiveUp("Do not know how to get file content from '%s'"%url)

    def must_fetch_before_commit(self, options):
        """
        Do we need to 'fetch' before we 'commit'?

        In a centralised VCS like subverson, this is highly recommended.

        In a distributed VCS like bazaar or git, it is unnecessary.

        We shall default to the distributed answer, and individual
        VCS support can override if necessary.
        """
        return False


class VersionControlHandler(object):
    """
    Handle all version control operations for a checkout.

    * self.builder is the builder we're running under.
    * self.vcs_handler is an instance of the class that knows how to handle
      operations for the VCS used for this checkout
    * self.checkout_label is the label for this checkout
    * self.checkout_leaf is the name of the checkout (normally the directory under
      ``/src/``) that we're responsible for. This may not be the same as the label
      name for multilevel checkouts

      TODO: Explain this rather better

    * self.repo is the Repository we're interested in.
    """

    def __init__(self, builder, vcs_handler, co_label, co_leaf, repo,
                 co_dir=None, addoptions=None):
        """
        * 'builder' is the builder for this build
        * 'vcs_handler' knows how to do VCS operations for this checkout
        * 'co_label' is the checkout's label
        * 'co_leaf' is the name of the directory for the checkout;
           this is the *final* directory name, so if the checkout is in
          'src/fred/jim/wombat', then the checkout leaf name is 'wombat'
        * 'repo' is the Repository instance describing where this checkout
          comes from
        * 'co_dir' is the location of the 'co_leaf' directory (within 'src'),
          so if the checkout is in 'src/fred/jim/wombat', then the checkout
          directory is 'fred/jim'. If the 'co_leaf' directory is at the "top
          level" within 'src', then this should be None or ''.
        """
        self.builder = builder
        self.vcs_handler = vcs_handler
        self.checkout_label = co_label
        self.repo = repo

        self.checkout_dir = co_dir          # should we get this from the db?
        self.checkout_leaf = co_leaf        # should we calculate this as needed?

        self._options = default_vcs_options_dict()
        self.add_options(addoptions)

    def _inner_labels(self):
        """
        Return any "inner" labels, so their domains may be altered.
        """
        labels = [self.checkout_label]
        return labels

    def __str__(self):
        words = ['VCS %s for %s'%(self.short_name(), self.checkout_label)]
        if self.checkout_dir:
            words.append('dir=%s'%self.checkout_dir)
        words.append('leaf=%s'%self.checkout_leaf)
        words.append('repo=%s'%self.repo)
        return ' '.join(words)

    def short_name(self):
        return self.vcs_handler.short_name

    def long_name(self):
        return self.vcs_handler.long_name

    def checkout_tuple(self):
        # This is used for stamp files
        #
        # XXX Note that 'inner_path' should now be part of the URL
        # XXX - this definitely needs thinking about
        return utils.CheckoutTuple(self.checkout_label.name,
                                   '%s+%s'%(self.repo.vcs, self.repo.url),
                                   self.repo.revision if self.repo.revision else 'HEAD',
                                   self.repo.inner_path, # was self.relative,
                                   self.checkout_dir,
                                   self.checkout_label.domain,
                                   self.checkout_leaf,
                                   self.repo.branch)

    def get_my_absolute_checkout_path(self):
        """
        Does what it says on the tin.
        """
        return self.builder.invocation.checkout_path(self.checkout_label)

    def get_original_revision(self):
        """Return the revision id the user originally asked for.

        This may be None.
        """
        return self.repo.revision

    def src_rel_dir(self):
        """For exceptions, we want the directory relative to the root

        (but if we have subdomains, we probably had better mean the root of the
        topmost build)
        """
        if self.checkout_label.domain:
            domain_part = utils.domain_subpath(self.checkout_label.domain)
        else:
            domain_part = ''

        if self.checkout_dir:
            src_rel_dir = os.path.join(domain_part, 'src', self.checkout_dir,
                                       self.checkout_leaf)
        else:
            src_rel_dir = os.path.join(domain_part, 'src', self.checkout_leaf)

        return src_rel_dir

    def checkout(self, verbose=True):
        """
        Check this checkout out of version control.

        The actual operation we perform is commonly called "clone" in actual
        version control systems. We retain the name "checkout" because it
        instantiates a muddle checkout.
        """
        # We want to be in the checkout's parent directory
        parent_dir, rest = os.path.split(self.get_my_absolute_checkout_path())

        # Be careful - if the parent is 'src/', then it may well exist by now
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir)

        with utils.Directory(parent_dir):
            try:
                self.vcs_handler.checkout(self.repo, self.checkout_leaf,
                                          self._options, verbose)
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error checking out %s in %s:\n%s'%(self.checkout_label,
                                      parent_dir, err))
            except utils.GiveUp as err:
                raise utils.GiveUp('Failure checking out %s in %s:\n%s'%(self.checkout_label,
                                   parent_dir, err))

    def fetch(self, verbose=True):
        """
        Retrieve changes from the remote repository, and apply them to
        the local working copy, but not if a merge operation would be
        required, in which case an exception shall be raised.
        """
        with utils.Directory(self.get_my_absolute_checkout_path()):
            try:
                self.vcs_handler.fetch(self.repo, self._options, verbose)
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error fetching %s in %s:\n%s'%(self.checkout_label,
                                  self.src_rel_dir(), err))
            except utils.Unsupported as err:
                raise utils.Unsupported('Not fetching %s in %s:\n%s'%(self.checkout_label,
                                     self.src_rel_dir(), err))
            except utils.GiveUp as err:
                raise utils.GiveUp('Failure fetching %s in %s:\n%s'%(self.checkout_label,
                                    self.src_rel_dir(), err))

    def merge(self, verbose=True):
        """
        Retrieve changes from the remote repository, and apply them to
        the local working copy, performing a merge operation if necessary.
        """
        with utils.Directory(self.get_my_absolute_checkout_path()):
            try:
                self.vcs_handler.merge(self.repo, self._options, verbose)
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error merging %s in %s:\n%s'%(self.checkout_label,
                                  self.src_rel_dir(), err))
            except utils.Unsupported as err:
                raise utils.Unsupported('Not merging %s in %s:\n%s'%(self.checkout_label,
                                      self.src_rel_dir(), err))
            except utils.GiveUp as err:
                raise utils.GiveUp('Failure merging %s in %s:\n%s'%(self.checkout_label,
                                    self.src_rel_dir(), err))

    def commit(self, verbose=True):
        """
        Commit any changes in the local working copy to the local repository.

        In a centralised VCS, like subverson, this does not do anything, as
        there is no *local* repository.
        """
        with utils.Directory(self.get_my_absolute_checkout_path()):
            try:
                self.vcs_handler.commit(self.repo, self._options, verbose)
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error commiting %s in %s:\n%s'%(self.checkout_label,
                                  self.src_rel_dir(), err))
            except (utils.GiveUp, utils.Unsupported) as err:
                raise utils.GiveUp('Failure commiting %s in %s:\n%s'%(self.checkout_label,
                                    self.src_rel_dir(), err))

    def push(self, verbose=True):
        """
        Push changes in the local repository to the remote repository.

        Note that in a centralised VCS, like subversion, this is typically
        called "commit", since there is no local repository.

        This operaton does not do a 'commit'.
        """
        with utils.Directory(self.get_my_absolute_checkout_path()):
            try:
                self.vcs_handler.push(self.repo, self._options, verbose)
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error pushing %s in %s:\n%s'%(self.checkout_label,
                                  self.src_rel_dir(), err))
            except (utils.GiveUp, utils.Unsupported) as err:
                raise utils.GiveUp('Failure pushing %s in %s:\n%s'%(self.checkout_label,
                                    self.src_rel_dir(), err))

    def status(self, verbose=False):
        """
        Report on the status of the checkout, in a VCS-appropriate manner

        If there is nothing to be done for this repository, returns None.

        Otherwise, returns a string comprising a report on the status
        of the repository, in a VCS appropriate manner.

        If 'verbose', then report each checkout label as it is checked.

        The reliability and accuracy of this varies by VCS, but the idea
        is that a checkout is 'safe' if:

        * there are no files in the local checkout that are not also in the
          (local) repository, unless explicitly marked to be ignored
        * there are no files that need committing to the local repository

        In general, if a checkout is 'safe' then it should be OK to 'merge'
        the remote repository into it.
        """
        if verbose:
            print '>>', self.checkout_label
        with utils.Directory(self.get_my_absolute_checkout_path(), show_pushd=False):
            try:
                status_text = self.vcs_handler.status(self.repo, self._options)
                if status_text:
                    full_text = '%s status for %s in %s:\n%s'%(self.short_name(),
                                                 self.checkout_label,
                                                 self.src_rel_dir(),
                                                 status_text)
                    return full_text
                else:
                    return None
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error finding status for %s in %s:\n%s'%(self.checkout_label,
                                  self.src_rel_dir(), err))
            except utils.GiveUp as err:
                raise utils.GiveUp('Failure finding status for %s in %s:\n%s'%(self.checkout_label,
                                    self.src_rel_dir(), err))

    def reparent(self, force=False, verbose=True):
        """
        Re-associate the local repository with its original remote repository,

        (This is not relevant for all VCS systems, and will only be overridden
        for those where it does make sense - notably Bazaar)

        This re-associates the local repository with the remote repository named
        in the muddle build description.

        If 'force' is true, it does this regardless. If 'force' is false, then
        it only does it if the checkout is actually not so associated.
        """
        actual_dir = self.get_my_absolute_checkout_path()
        with utils.Directory(actual_dir):
            self.vcs_handler.reparent(actual_dir, # or self.checkout_leaf
                                      self.repo, self._options, force, verbose)

    def revision_to_checkout(self, force=False, verbose=False):
        """
        Determine a revision id for this checkout, usable to check it out again.

        The revision id we want is that we could use to check out an identical
        checkout.

        If the local working set/repository/whatever appears to have been
        altered from the remove repository, or otherwise does not yield a
        satisfactory revision id (this is something only the subclass can
        tell), then the method should raise utils.GiveUp, with as clear an
        explanation of the problem as possible.

        If 'force' is true, then if the revision cannot be determined, return
        the orginal revision that was specified when the checkout was checked
        out.

            (Individual version control classes may opt to ignore the 'force'
            argument, either because it is not useful in their context, or
            because they can tell that the checkout is seriously
            astray/broken.)

        NB: If the VCS class does not override this method, then the default
        implementation will raise a GiveUp unless 'force' is true, in which
        case it will return the string '0'.
        """
        with utils.Directory(self.get_my_absolute_checkout_path()):
            return self.vcs_handler.revision_to_checkout(self.repo,
                                                         self.checkout_leaf,
                                                         self._options,
                                                         force, verbose)

    def must_fetch_before_commit(self):
        return self.vcs_handler.must_fetch_before_commit(self._options)

    def get_file_content(self, url, verbose=True):
        """
        Retrieve a file's content via a VCS.
        """
        return self.vcs_handler.get_file_content(url, self._options, verbose)

    def get_options(self):
        return self._options

    def add_options(self, optsdict=None, **kwargs):
        """
        Adds extra VCS options to this checkout - specified by dictionary,
        keyword args or both. (If an option is present both in the dictionary
        and the keyword args, the resulting effect is undefined.)

        Any unrecognised option causes an exception.
        """
        newopts = {}
        if optsdict is not None:
            newopts.update(optsdict)
        newopts.update(kwargs)
        for o in newopts:
            if not o in self._options:
                raise utils.GiveUp("VCS option %s was not recognised"%o)
            self._options[o] = newopts[o]

def default_vcs_options_dict():
    """
    Construct a default VCS options dictionary for a checkout.
    This dictionary is also the set of allowed options.

    NOTE: The implementer of a new option is responsible for deciding
    what the option's behaviour should be across ALL currently-implemented
    VCS modules. By default a VCS module simply ignores options it doesn't
    understand; in some cases this might not be appropriate and a module
    would instead want to raise an error because the option doesn't make
    sense to that system.
    """
    return {
            'shallow_checkout': False,
            }

# This dictionary holds the global list of registered VCS handler
# factories.
vcs_dict = { }

def register_vcs_handler(scheme, factory):
    """
    Register a VCS handler factory with a VCS scheme prefix.
    """
    vcs_dict[scheme] = factory

def list_registered(indent=''):
    """
    Return a list of registered version control systems.
    """

    str_list = []
    for (k,v) in vcs_dict.items():
        if indent:
            str_list.append(indent)
        str_list.append(utils.pad_to(k, 20))
        desc = v.long_name
        lines = desc.split("\n")
        str_list.append(lines[0])
        str_list.append("\n")
        for i in lines[1:]:
            if indent:
                str_list.append(indent)
            str_list.append(utils.pad_to("", 20))
            str_list.append(i)
            str_list.append("\n")

    return "".join(str_list)

def get_vcs_handler(vcs):
    """Given a VCS short name, return a VCS handler.
    """
    try:
        return vcs_dict[vcs]
    except KeyError:
        raise utils.MuddleBug("No VCS handler registered for VCS type %s"%vcs)

def get_vcs_handler_from_string(repo_str):
    """Given a <vcs>+<url> string, return a VCS handler and <url>.
    """
    vcs, url_rest = split_vcs_url(repo_str)
    if not vcs:
        raise utils.MuddleBug("Improperly formatted repository spec %s,"
                              " should be <vcs>+<url>"%repo_str)

    vcs_handler = get_vcs_handler(vcs)

    return vcs_handler, url_rest

def vcs_handler_for(builder, co_label, co_leaf, repo, co_dir=None):
    """
    Create a VCS handler for the given url, invocation and checkout name.

    Which VCS is determined by interpreting the initial part of the URI's
    protocol.

    We then create a handler that will call the appropriate VCS-specific
    mechanisms for any VCS operations on this checkout.

    * inv - The invocation for which we're trying to build a handler.
    * co_label - The label for this checkout. This includes the name and domain
      (if any) for the checkout
    * co_leaf - The 'leaf' directory for this checkout. This is the final
      element of the checkout's directory name. In many/most cases it will be
      the same as the checkout name (in the label), but particularly in
      multilevel checkouts it may be different.
    * repo - the Repository instance
    * co_dir - Directory relative to the 'src/' directory in which the
      checkout 'leaf' directory resides. Thus None or '' for simple checkouts.
    """

    vcs_handler = get_vcs_handler(repo.vcs)

    return VersionControlHandler(builder, vcs_handler,
                                 co_label, co_leaf, repo, co_dir)

def vcs_action_for(builder, co_label, repo, co_dir = None, co_leaf = None):
    """
    Create a VCS action for the given co_leaf, repo, etc.
    """
    if co_leaf is None:
        co_leaf = co_label.name

    handler = vcs_handler_for(builder, co_label, co_leaf, repo, co_dir)
    if (handler is None):
        raise utils.GiveUp("Cannot build a VCS handler for %s rel = %s"%(repo, rev))

    return pkg.VcsCheckoutBuilder(co_label.name, handler)

def split_vcs_url(url):
    """
    Split a URL into a vcs and a repository URL. If there's no VCS
    specifier, return (None, None).
    """

    the_re = re.compile("^([A-Za-z]+)\+([A-Za-z+]+):(.*)$")

    m = the_re.match(url)
    if (m is None):
        return (None, None)

    return (m.group(1).lower(), "%s:%s"%(m.group(2),m.group(3)))

def checkout_from_repo(builder, co_label, repo, co_dir=None, co_leaf=None):
    """Declare that the checkout for 'co_label' comes from Repository 'repo'

    We will take the repository described in 'repo' and check it out into:

    * src/<co_label>.name or
    * src/<co_dir>/<co_label>.name or
    * src/<co_dir>/<co_leaf> or
    * src/<co_leaf>

    depending on whether <co_dir> and/or <co_leaf> are given. We will assign
    the label <co_label> to this directory/repository combination.
    """

    if co_dir:
        if co_leaf:
            co_path = os.path.join(co_dir, co_leaf)
        else:
            co_path = os.path.join(co_dir, co_label.name)
    else:
        if co_leaf:
            co_path = co_leaf
        else:
            co_path = co_label.name

    builder.invocation.db.set_checkout_path(co_label, co_path)
    builder.invocation.db.set_checkout_repo(co_label, repo)

    vcs_handler = vcs_action_for(builder, co_label, repo, co_dir=co_dir, co_leaf=co_leaf)
    pkg.add_checkout_rules(builder.invocation.ruleset, co_label, vcs_handler)


def conventional_repo_url(repo, rel, co_dir = None):
    """
    Many VCSs adopt the convention that the first element of the relative
    string is the name of the repository.

    This routine resolves repo - a full repository URL including VCS specifier -
    and rel into the name of a repository and the path within that repository and
    returns them as a tuple (repo url, name_in_repo). The returned repo url
    lacks the VCS specifier.

    If an invalid URL is given, we will return None.

    XXX This function is deprecated, as we do not use it any more. It will
    be removed in a later version of muddle.
    """
    split = split_vcs_url(repo)
    if (split is None):
        return None

    (vcs_spec, repo_rest) = split

    # Now, depending on whether we have a co_dir or not, either the
    # first or the first and second elements of rel are the repository
    # name.
    #
    # If rel is None, there is no repository name - it's all in repo.

    if (rel is None):
        return (repo_rest, None)

    if (co_dir is None):
        dir_components = 1
    else:
        dir_components = 2

    components = rel.split("/", dir_components)
    if (len(components) == 1):
        out_repo = os.path.join(repo_rest, rel)
        out_rel = None
    elif (len(components) == 2):
        if (co_dir is None):
            out_repo = os.path.join(repo_rest, components[0])
            out_rel = components[1]
        else:
            # The second component is part of the repo, not the relative
            # path. Need to be a bit careful to do this test right else
            # otherwise we'll end up misinterpreting things like
            # 'builds/01.py'
            out_repo = os.path.join(repo_rest, components[0], components[1])
            out_rel = None
    else:
        out_repo = os.path.join(repo_rest, components[0], components[1])
        out_rel = components[2]

    #if (co_dir is not None):
    #    print "rel = %s"%rel
    #    print "components = [%s]"%(" ".join(components))
    #    print "out_repo = %s out_rel = %s"%(out_repo, out_rel)
    #    raise utils.GiveUp("Help!")

    return (out_repo, out_rel)

def vcs_get_file_data(url):
    """
    Return the content of the file identified by the URL, via its VCS.

    Looks at the first few characters of the URL to determine the VCS
    to use - so, e.g., "bzr" for "bzr+ssh://whatever".

    Returns a string (the content of the file).

    Raises KeyError if the scheme is not one we have a registered file getter
    for.
    """
    vcs_handler, plain_url = get_vcs_handler_from_string(url)
    return vcs_handler.get_file_content(plain_url)

# This is a dictionary of VCS name to function-to-clone/push/pull-a-directory
vcs_dir_handler = {}

def register_vcs_dir_handler(scheme, handler):
    """
    Register a function for cloning/pushing/pulling an indivual directory.

    'scheme' is the VCS (short) name. This should match the mnemonic used
    at the start of URLs - so, e.g., "bzr" for "bzr+ssh://whatever".

    'handler' is the function. It should take (at least) two arguments:

    1. the action to perform. One of "clone", "push", "pull", "commit".
    2. the URL of the repository to use. This is not needed for "commit".
    3. for "clone", optionally the name of the directory to clone into

    For "clone" it assumes it will produce the clone in the current directory.
    For "push" and "pull" it assumes that the current directory is the cloned
    directory.
    """
    vcs_dir_handler[scheme] = handler

def vcs_get_directory(url, directory=None):
    """
    Retrieve (clone) the directory identified by the URL, via its VCS.

    If 'directory' is given, then clones to the named directory.

    Looks at the first few characters of the URL to determine the VCS
    to use - so, e.g., "bzr" for "bzr+ssh://whatever".

    Raises KeyError if the scheme is not one for which we have a registered
    handler.
    """
    vcs_handler, plain_url = get_vcs_handler_from_string(url)
    repo = Repository.from_url(vcs_handler.short_name, plain_url)
    options = default_vcs_options_dict()
    return vcs_handler.checkout(repo, directory, options)

def vcs_push_directory(url):
    """
    Push the current directory to the repository indicated by the URL

    Looks at the first few characters of the URL to determine the VCS
    to use - so, e.g., "bzr" for "bzr+ssh://whatever".

    Raises KeyError if the scheme is not one for which we have a registered
    handler.
    """
    vcs_handler, plain_url = get_vcs_handler_from_string(url)
    repo = Repository.from_url(vcs_handler.short_name, plain_url)
    options = default_vcs_options_dict()
    vcs_handler.push(repo, options)

def vcs_fetch_directory(url):
    """
    Fetch the current directory from the repository indicated by the URL

    Looks at the first few characters of the URL to determine the VCS
    to use - so, e.g., "bzr" for "bzr+ssh://whatever".

    Raises KeyError if the scheme is not one for which we have a registered
    handler.
    """
    vcs_handler, plain_url = get_vcs_handler_from_string(url)
    repo = Repository.from_url(vcs_handler.short_name, plain_url)
    options = default_vcs_options_dict()
    vcs_handler.fetch(repo, options)

def vcs_init_directory(scheme, files=None):
    """
    Initialised the current directory for this VCS, and add the given list of files.

    'scheme' is "git", "bzr", etc. - as taken from the first few characters of
    the muddle repository URL - so, e.g., "bzr" for "bzr+ssh://whatever".

    Raises KeyError if the scheme is not one for which we have a registered
    handler.
    """
    vcs_handler = vcs_dict.get(scheme, None)
    if not vcs_handler:
        raise utils.MuddleBug("No VCS handler registered for VCS type %s"%scheme)
    vcs_handler.init_directory()
    vcs_handler.add_files(files)

# End file.
