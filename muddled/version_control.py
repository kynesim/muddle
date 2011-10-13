"""
Routines which deal with version control.
"""

import utils

import re
import pkg
import os

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

    def init_directory(self, repo, files=None, verbose=True):
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

    def checkout(self, repo, co_leaf, options, branch=None, revision=None, verbose=True):
        """
        Checkout (clone) a given checkout.

        Will be called in the parent directory of the checkout.

        Expected to create a directory called <co_leaf> therein.

        Any exception raised will be "wrapped" by the calling handler.
        """
        pass

    def fetch(self, repo, options, branch=None, revision=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        Any exception raised will be "wrapped" by the calling handler.
        """
        pass

    def merge(self, other_repo, options, branch=None, revision=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        Any exception raised will be "wrapped" by the calling handler.
        """
        pass

    def commit(self, options, verbose=True):
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

    def status(self, repo, options, branch=None):
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

    def revision_to_checkout(self, co_leaf, orig_revision, options, force=False, verbose=True):
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
        False


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

    * self.repository is the repository we're interested in. Its syntax is
      VCS-dependent.
    * self.revision is the revision to check out.
      Passing None means to use the head of tree. For historical reasons, the
      special name HEAD means also head of the main tree. Anything else is VCS
      specific.

    The repository is stored in its full form - with its VCS tag, though this will
    almost never be used.
    """

    def __init__(self, builder, vcs_handler, co_label, co_leaf, repo,
                 rev=None, rel=None, co_dir=None, branch=None, addoptions=None):
        """
        * 'builder' is the builder for this build
        * 'vcs_handler' knows how to do VCS operations for this checkout
        * 'co_label' is the checkout's label
        * 'co_leaf' is the name of the directory for the checkout;
           this is the *final* directory name, so if the checkout is in
          'src/fred/jim/wombat', then the checkout name is 'wombat'
        * 'repo' is the repository URL
        * 'rev' is the revision (if any - None means head of tree)
        * for systems like SVN, it is possible to have a relative path within
          the repository, and only checkout the specified portion of the whole
        * 'co_dir' is the location of the 'co_leaf' directory (within 'src'),
          so if the checkout is in 'src/fred/jim/wombat', then the checkout
          directory is 'fred/jim'. If the 'co_leaf' directory is at the "top
          level" within 'src', then this should be None or ''.
        * 'branch' is the branch to checkout, or None for "master", "trunk" or
          whatever else the main branch would be.
        """
        self.builder = builder
        self.vcs_handler = vcs_handler
        self.checkout_label = co_label
        self.checkout_leaf = co_leaf
        self.checkout_dir = co_dir
        self.repo_as_given = repo
        self.relative = rel
        if rev:
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
            # This will override any branch specified as an argument
            try:
                branch, self.revision = self._parse_revision(branch, rev)
            except TypeError:
                raise utils.GiveUp('VCS revision value should be a string, not %s'%type(rev))
        else:
            self.revision = None
        self.branch = branch

        # TODO: instead of making the caller register the checkout directory
        #       for this label separately, do it for them...
        #       (but always remember that, at this stage, we probably don't
        #       yet know if we're in a subdomain or not)


        # Sort out what our repository URL actually is
        pair = conventional_repo_url(repo, rel, co_dir=co_dir)
        if pair is None:
            raise utils.MuddleBug("Cannot extract repository URL from %s,"
                              " relative %s, checkout dir %s"%(repo, rel, co_dir))
        self.actual_repo, self.name_in_repo = pair

        self._options = default_vcs_options_dict()
        self.add_options(addoptions)

    def _inner_labels(self):
        """
        Return any "inner" labels, so their domains may be altered.
        """
        labels = [self.checkout_label]
        return labels

    def _parse_revision(self, branch, revision):
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

    def __str__(self):
        words = ['VCS %s for %s'%(self.short_name(), self.checkout_label)]
        if self.checkout_dir:
            words.append('dir=%s'%self.checkout_dir)
        words.append('leaf=%s'%self.checkout_leaf)
        words.append('repo=%s'%self.repo_as_given)
        if self.relative:
            words.append('rel=%s'%self.relative)
        if self.branch:
            words.append('branch=%s'%self.branch)
        if self.revision:
            words.append('rev=%s'%self.revision)
        return ' '.join(words)

    def short_name(self):
        return self.vcs_handler.short_name

    def long_name(self):
        return self.vcs_handler.long_name

    def checkout_tuple(self):
        return utils.CheckoutTuple(self.checkout_label.name,
                                   self.repo_as_given,
                                   self.revision,
                                   self.relative,
                                   self.checkout_dir,
                                   self.checkout_label.domain,
                                   self.checkout_leaf,
                                   self.branch)

    def get_my_absolute_checkout_path(self):
        """
        Does what it says on the tin.
        """
        return self.builder.invocation.checkout_path(self.checkout_label)

    def get_original_revision(self):
        """Return the revision id the user originally asked for.

        This may be None.
        """
        return self.revision

    def get_checkout_path(self, co_label):
        """
        When called with None, get the parent directory of this checkout.
        God knows what happens otherwise.
        
        .. todo:: Needs documenting and rewriting!

        .. TODO:: Actually, needs removing...
        """

        if co_label:
            return self.builder.invocation.checkout_path(co_label)
        else:
            return self.builder.invocation.checkout_path(None)

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

    def check_out(self):
        """A synonym for old time's sake.
        """
        self.checkout()

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
                self.vcs_handler.checkout(self.actual_repo, self.checkout_leaf,
                                          self._options,
                                          self.branch, self.revision, verbose)
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
                self.vcs_handler.fetch(self.actual_repo, self._options,
                                       self.branch, self.revision, verbose)
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
                self.vcs_handler.merge(self.actual_repo, self._options,
                                       self.branch, self.revision, verbose)
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
                self.vcs_handler.commit(self._options, verbose)
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
                self.vcs_handler.push(self.actual_repo, self._options,
                                      self.branch, verbose)
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
                status_text = self.vcs_handler.status(self.actual_repo,
                        self._options, self.branch)
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
                                      self.actual_repo, self._options,
                                      force, verbose)

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
            return self.vcs_handler.revision_to_checkout(self.checkout_leaf,
                                                         self.revision,
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

def list_registered():
    """
    Return a list of registered version control systems.
    """

    str_list = []
    for (k,v) in vcs_dict.items():
        str_list.append(utils.pad_to(k, 20))
        desc = v.long_name
        lines = desc.split("\n")
        str_list.append(lines[0])
        str_list.append("\n")
        for i in lines[1:]:
            str_list.append(utils.pad_to("", 20))
            str_list.append(i)
            str_list.append("\n")

    return "".join(str_list)

def get_vcs_handler(repo):
    vcs, url_rest = split_vcs_url(repo)
    if not vcs:
        raise utils.MuddleBug("Improperly formatted repository spec %s"%repo)

    vcs_handler = vcs_dict.get(vcs, None)
    if not vcs_handler:
        raise utils.MuddleBug("No VCS handler registered for VCS type %s"%vcs)

    return vcs_handler, url_rest

def vcs_handler_for(builder, co_label, co_leaf, repo, rev, rest, co_dir=None, branch=None):
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
    * repo - Repository URL
    * rev - Revision (None for HEAD)
    * rest - Part after the repository URL - typically the CVS module name or
      whatever.
    * co_dir - Directory relative to the 'src/' directory in which the
      checkout 'leaf' directory resides. Thus None or '' for simple checkouts.
    * branch - The branch for this checkout, if it is not the "main"/"default"
      branch.
    """

    vcs_handler, plain_url = get_vcs_handler(repo)

    if (rev is None):
        rev = "HEAD"

    return VersionControlHandler(builder, vcs_handler,
                                 co_label, co_leaf, repo, rev, rest, co_dir, branch)

def vcs_action_for(builder, co_label, repo, rev, rest, co_dir = None, co_leaf = None,
                   branch = None):
    """
    Create a VCS action for the given co_leaf, repo, etc.
    """
    if co_leaf is None:
        co_leaf = co_label.name

    handler = vcs_handler_for(builder, co_label, co_leaf, repo, rev, rest, co_dir, branch)
    if (handler is None):
        raise utils.GiveUp("Cannot build a VCS handler for %s rel = %s"%(repo, rev))

    return pkg.VcsCheckoutBuilder(co_label.name, handler)

# XXX For legacy reasons
vcs_dependable_for = vcs_action_for

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

def conventional_repo_url(repo, rel, co_dir = None):
    """
    Many VCSs adopt the convention that the first element of the relative
    string is the name of the repository.

    This routine resolves repo - a full repository URL including VCS specifier -
    and rel into the name of a repository and the path within that repository and
    returns them as a tuple (repo url, name_in_repo). The returned repo url
    lacks the VCS specifier.

    If an invalid URL is given, we will return None.
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
    vcs_handler, plain_url = get_vcs_handler(url)
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
    vcs_handler, plain_url = get_vcs_handler(url)
    options = default_vcs_options_dict()
    return vcs_handler.checkout(plain_url, directory, options)

def vcs_push_directory(url):
    """
    Push the current directory to the repository indicated by the URL

    Looks at the first few characters of the URL to determine the VCS
    to use - so, e.g., "bzr" for "bzr+ssh://whatever".

    Raises KeyError if the scheme is not one for which we have a registered
    handler.
    """
    vcs_handler, plain_url = get_vcs_handler(url)
    options = default_vcs_options_dict()
    vcs_handler.push(plain_url, options)

def vcs_fetch_directory(url):
    """
    Fetch the current directory from the repository indicated by the URL

    Looks at the first few characters of the URL to determine the VCS
    to use - so, e.g., "bzr" for "bzr+ssh://whatever".

    Raises KeyError if the scheme is not one for which we have a registered
    handler.
    """
    vcs_handler, plain_url = get_vcs_handler(url)
    options = default_vcs_options_dict()
    vcs_handler.fetch(plain_url, options)

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
