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
    much about muddle, although they will have to have some understanding
    of the contents of a Repository object.
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

    def pull(self, repo, options, upstream=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        Any exception raised will be "wrapped" by the calling handler.

        Returns True if it changes its checkout (changes the files visible
        to the user), False otherwise.
        """
        return False

    def merge(self, other_repo, options, verbose=True):
        """
        Will be called in the actual checkout's directory.

        Any exception raised will be "wrapped" by the calling handler.

        Returns True if it changes its checkout (changes the files visible
        to the user), False otherwise.
        """
        return False

    def commit(self, repo, options, verbose=True):
        """
        Will be called in the actual checkout's directory.

        Any exception raised will be "wrapped" by the calling handler.
        """
        pass

    def push(self, repo, options, branch=None, upstream=None, verbose=True):
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

    def revision_to_checkout(self, repo, co_leaf, options, force=False, before=None, verbose=True):
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

    def must_pull_before_commit(self, options):
        """
        Do we need to 'pull' before we 'commit'?

        In a centralised VCS like subverson, this is highly recommended.

        In a distributed VCS like bazaar or git, it is unnecessary.

        We shall default to the distributed answer, and individual
        VCS support can override if necessary.
        """
        return False

    def get_vcs_special_files(self):
        """
        Return the names of the 'special' files/directories used by this VCS.

        For instance, if 'url' starts with "git+" then we might return
        [".git", ".gitignore", ".gitmodules"]

        Returns an empty list if there is no such concept.
        """
        return []


class VersionControlHandler(object):
    """
    Handle all version control operations for a checkout.

    The VersionControlSystem class knows how to do individual VCS operations,
    but is not required to know anything muddle-specific beyond how a
    Repository object works (or, at least, that is the aim).

    This class acts as a translator between muddle actions on a checkout label
    and the underlying VCS actions.

    Each underlying VCS (git, bzr, etc.) is used via an instance of this class.
    """

    def __init__(self, vcs):
        """
        * 'vcs' is the class corresponding to the particular version control
          system - e.g., Git.
        """
        self.vcs = vcs

    def __str__(self):
        return 'VCS %s'%self.short_name

    def short_name(self):
        return self.vcs.short_name

    def long_name(self):
        return self.vcs.long_name

    def checkout(self, builder, co_label, verbose=True):
        """
        Check this checkout out of version control.

        The actual operation we perform is commonly called "clone" in actual
        version control systems. We retain the name "checkout" because it
        instantiates a muddle checkout.
        """
        # We want to be in the checkout's parent directory
        parent_dir, co_leaf = os.path.split(builder.db.get_checkout_path(co_label))

        repo = builder.db.get_checkout_repo(co_label)
        if not repo.pull:
            raise utils.GiveUp('Failure checking out %s in %s:\n'
                               '  %s does not allow "pull"'%(co_label,
                               parent_dir, repo))

        # Be careful - if the parent is 'src/', then it may well exist by now
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir)

        options = builder.db.get_checkout_vcs_options(co_label)
        with utils.Directory(parent_dir):
            try:
                self.vcs.checkout(repo, co_leaf, options, verbose)
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error checking out %s in %s:\n%s'%(co_label,
                                      parent_dir, err))
            except utils.GiveUp as err:
                raise utils.GiveUp('Failure checking out %s in %s:\n%s'%(co_label,
                                   parent_dir, err))

    def pull(self, builder, co_label, upstream=None, repo=None, verbose=True):
        """
        Retrieve changes from the remote repository, and apply them to
        the local working copy, but not if a merge operation would be
        required, in which case an exception shall be raised.

        If 'upstream' and 'repo' are given, then they specify the upstream
        repository we should pull from, instead of using the 'normal'
        repository from the build description.

        Returns True if it changes its checkout (changes the files visible
        to the user), False otherwise.
        """
        if not (upstream and repo):
            repo = builder.db.get_checkout_repo(co_label)

        if not repo.pull:
            raise utils.GiveUp('Failure pulling %s in %s:\n'
                               '  %s does not allow "pull"'%(co_label,
                               builder.db.get_checkout_location(co_label), repo))

        options = builder.db.get_checkout_vcs_options(co_label)
        with utils.Directory(builder.db.get_checkout_path(co_label)):
            try:
                return self.vcs.pull(repo, options, upstream=upstream, verbose=verbose)
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error pulling %s in %s:\n%s'%(co_label,
                                      builder.db.get_checkout_location(co_label), err))
            except utils.Unsupported as err:
                raise utils.Unsupported('Not pulling %s in %s:\n%s'%(co_label,
                                        builder.db.get_checkout_location(co_label), err))
            except utils.GiveUp as err:
                raise utils.GiveUp('Failure pulling %s in %s:\n%s'%(co_label,
                                   builder.db.get_checkout_location(co_label), err))

    def merge(self, builder, co_label, verbose=True):
        """
        Retrieve changes from the remote repository, and apply them to
        the local working copy, performing a merge operation if necessary.

        Returns True if it changes its checkout (changes the files visible
        to the user), False otherwise.
        """
        repo = builder.db.get_checkout_repo(co_label)
        if not repo.pull:
            raise utils.GiveUp('Failure merging %s in %s:\n'
                               '  %s does not allow "pull"'%(co_label,
                               builder.db.get_checkout_location(co_label), repo))

        options = builder.db.get_checkout_vcs_options(co_label)
        with utils.Directory(builder.db.get_checkout_path(co_label)):
            try:
                return self.vcs.merge(repo, options, verbose)
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error merging %s in %s:\n%s'%(co_label,
                                      builder.db.get_checkout_location(co_label), err))
            except utils.Unsupported as err:
                raise utils.Unsupported('Not merging %s in %s:\n%s'%(co_label,
                                        builder.db.get_checkout_location(co_label), err))
            except utils.GiveUp as err:
                raise utils.GiveUp('Failure merging %s in %s:\n%s'%(co_label,
                                   builder.db.get_checkout_location(co_label), err))

    def commit(self, builder, co_label, verbose=True):
        """
        Commit any changes in the local working copy to the local repository.

        In a centralised VCS, like subverson, this does not do anything, as
        there is no *local* repository.
        """
        repo = builder.db.get_checkout_repo(co_label)
        options = builder.db.get_checkout_vcs_options(co_label)
        with utils.Directory(builder.db.get_checkout_path(co_label)):
            try:
                self.vcs.commit(repo, options, verbose)
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error commiting %s in %s:\n%s'%(co_label,
                                      builder.db.get_checkout_location(co_label), err))
            except (utils.GiveUp, utils.Unsupported) as err:
                raise utils.GiveUp('Failure commiting %s in %s:\n%s'%(co_label,
                                   builder.db.get_checkout_location(co_label), err))

    def push(self, builder, co_label, upstream=None, repo=None, verbose=True):
        """
        Push changes in the local repository to the remote repository.

        If 'upstream' and 'repo' are given, then they specify the upstream
        repository we should pull from, instead of using the 'normal'
        repository from the build description.

        Note that in a centralised VCS, like subversion, this is typically
        called "commit", since there is no local repository.

        This operaton does not do a 'commit'.
        """
        if not (upstream and repo):
            repo = builder.db.get_checkout_repo(co_label)

        if not repo.push:
            raise utils.GiveUp('Failure pushing %s in %s:\n'
                               '  %s does not allow "push"'%(co_label,
                               builder.db.get_checkout_location(co_label), repo))

        options = builder.db.get_checkout_vcs_options(co_label)
        with utils.Directory(builder.db.get_checkout_path(co_label)):
            try:
                self.vcs.push(repo, options, upstream=upstream, verbose=verbose)
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error pushing %s in %s:\n%s'%(co_label,
                                      builder.db.get_checkout_location(co_label), err))
            except (utils.GiveUp, utils.Unsupported) as err:
                raise utils.GiveUp('Failure pushing %s in %s:\n%s'%(co_label,
                                   builder.db.get_checkout_location(co_label), err))

    def status(self, builder, co_label, verbose=False):
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
            print '>>', co_label
        repo = builder.db.get_checkout_repo(co_label)
        options = builder.db.get_checkout_vcs_options(co_label)
        with utils.Directory(builder.db.get_checkout_path(co_label), show_pushd=False):
            try:
                status_text = self.vcs.status(repo, options)
                if status_text:
                    full_text = '%s status for %s in %s:\n%s'%(self.short_name(),
                                                 co_label,
                                                 builder.db.get_checkout_location(co_label),
                                                 status_text)
                    return full_text
                else:
                    return None
            except utils.MuddleBug as err:
                raise utils.MuddleBug('Error finding status for %s in %s:\n%s'%(co_label,
                                      builder.db.get_checkout_location(co_label), err))
            except utils.GiveUp as err:
                raise utils.GiveUp('Failure finding status for %s in %s:\n%s'%(co_label,
                                   builder.db.get_checkout_location(co_label), err))

    def reparent(self, builder, co_label, force=False, verbose=True):
        """
        Re-associate the local repository with its original remote repository,

        (This is not relevant for all VCS systems, and will only be overridden
        for those where it does make sense - notably Bazaar)

        This re-associates the local repository with the remote repository named
        in the muddle build description.

        If 'force' is true, it does this regardless. If 'force' is false, then
        it only does it if the checkout is actually not so associated.
        """
        actual_dir = builder.db.get_checkout_path(co_label)
        repo = builder.db.get_checkout_repo(co_label)
        options = builder.db.get_checkout_vcs_options(co_label)
        with utils.Directory(actual_dir):
            self.vcs.reparent(actual_dir, repo, options, force, verbose)

    def revision_to_checkout(self, builder, co_label, force=False, before=None, verbose=False, show_pushd=True):
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

        If 'before' is given, it should be a string describing a date/time, and
        the revision id chosen will be the last revision at or before that
        date/time.

        .. note:: This depends upon what the VCS concerned actually supports.
           This feature is experimental.

        NB: if 'before' is specified, 'force' is ignored.

        If 'show_pushd' is false, then we won't report as we "pushd" into the
        checkout directory.

        NB: If the VCS class does not override this method, then the default
        implementation will raise a GiveUp unless 'force' is true, in which
        case it will return the string '0'.
        """
        co_dir = builder.db.get_checkout_path(co_label)
        parent_dir, co_leaf = os.path.split(co_dir)
        repo = builder.db.get_checkout_repo(co_label)
        options = builder.db.get_checkout_vcs_options(co_label)
        with utils.Directory(co_dir, show_pushd=show_pushd):
            return self.vcs.revision_to_checkout(repo, co_leaf, options,
                                                 force, before, verbose)

    def must_pull_before_commit(self, builder, co_label):
        """Do we need to pull before we can commit?

        This may depend on the options chosen for this checkout.
        """
        options = builder.db.get_checkout_vcs_options(co_label)
        return self.vcs.must_pull_before_commit(options)

    def get_vcs_special_files(self):
        """
        Return the names of the 'special' files/directories used by this VCS.

        For instance, if 'url' starts with "git+" then we might return
        [".git", ".gitignore", ".gitmodules"]

        Returns an empty list if there is no such concept.
        """
        return self.vcs.get_vcs_special_files()

    def get_file_content(self, url, verbose=True):
        """
        Retrieve a file's content via a VCS.
        """
        return self.vcs.get_file_content(url, self.options, verbose)

    def add_options(self, builder, co_label, optsdict):
        """
        Add the options the user has requested, and checks them.

        For reasons mostly to do with how stamping/unstamping works,
        we require option values to be either boolean, integer or string.

        Any other choice raises an exception.
        """
        if not optsdict:
            return

        for key, value in optsdict.items():

            if option_not_allowed(self.vcs.short_name, key):
                raise utils.GiveUp("Option '%s' is not allowed for VCS %s'"%(key,
                                   self.vcs.short_name))

            if not (isinstance(value, bool) or isinstance(value, int) or
                    isinstance(value, str)):
                raise utils.GiveUp("Additional options to VCS must be bool, int or"
                                   " string. '%s' is %s"%(value, type(value)))

            builder.db.set_checkout_vcs_option(co_label, key, value)

# This dictionary holds the global list of registered VCS handler
# factories.
vcs_dict = {}
# And this one the documentation for each VCS
vcs_docs = {}
# And this one for (a list of) allowable options for each VCS
vcs_options = {}

def register_vcs_handler(scheme, factory, docs=None, options=None):
    """
    Register a VCS handler factory with a VCS scheme prefix.

    Also, preferably, register the VCS documentation on how muddle handles it.
    """
    vcs_dict[scheme] = factory
    vcs_docs[scheme] = docs
    vcs_options[scheme] = options

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

def get_vcs_docs(vcs):
    """Given a VCS short name, return the docs for how muddle handles it
    """
    try:
        return vcs_docs[vcs]
    except KeyError:
        raise utils.GiveUp("No VCS handler registered for VCS type %s"%vcs)

def option_not_allowed(vcs, option):
    if vcs in vcs_options and option in vcs_options[vcs]:
        return False
    else:
        return True

def get_vcs_handler_from_string(repo_str):
    """Given a <vcs>+<url> string, return a VCS handler and <url>.
    """
    vcs, url_rest = split_vcs_url(repo_str)
    if not vcs:
        raise utils.MuddleBug("Improperly formatted repository spec %s,"
                              " should be <vcs>+<url>"%repo_str)

    vcs_handler = get_vcs_handler(vcs)

    return vcs_handler, url_rest

def vcs_handler_for(builder, co_label):
    """
    Create a VCS handler for the given checkout label.

    We look up the repository for this label, and which VCS to use is
    determined by interpreting the initial part of the repository URI's
    protocol.

    We then create a handler that will call the appropriate VCS-specific
    mechanisms for any VCS operations on this checkout.

    * co_label - The label for this checkout. This includes the name and domain
      (if any) for the checkout
    """

    repo = builder.db.get_checkout_repo(co_label)
    vcs = get_vcs_handler(repo.vcs)

    return VersionControlHandler(vcs)

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

    # It's difficult to see how we could use a non-pull repository to
    # check our source out of...
    if not repo.pull:
        # Use a MuddleBug, because the user probably wants a traceback to see
        # where this is actually coming from
        raise utils.MuddleBug('Checkout %s cannot use %r\n'
                              '  as its main repository, as "pull" is not allowed'%(co_label, repo))

    if not co_leaf:
        co_leaf = co_label.name

    if co_dir:
        co_path = os.path.join(co_dir, co_leaf)
    else:
        co_path = co_leaf

    builder.db.set_checkout_dir_and_leaf(co_label, co_dir, co_leaf)

    builder.db.set_checkout_path(co_label, co_path)
    builder.db.set_checkout_repo(co_label, repo)

    handler = vcs_handler_for(builder, co_label)
    try:
        builder.db.set_checkout_vcs(co_label, handler)
    except Exception as e:
        raise MuddleBug('Cannot determine VCS for checkout %s:\n%s'%(co_label, e))

    # And we need an action to do the checkout of this checkout label to its
    # source directory. Since the VCS of a checkout is not expected to change.
    # we feel safe wrapping that into the action.
    action = pkg.VcsCheckoutBuilder(handler)
    pkg.add_checkout_rules(builder, co_label, action)

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
    return vcs_handler.checkout(repo, directory, {})

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
    vcs_handler.push(repo, {})

def vcs_pull_directory(url):
    """
    Pull the current directory from the repository indicated by the URL

    Looks at the first few characters of the URL to determine the VCS
    to use - so, e.g., "bzr" for "bzr+ssh://whatever".

    Raises KeyError if the scheme is not one for which we have a registered
    handler.
    """
    vcs_handler, plain_url = get_vcs_handler_from_string(url)
    repo = Repository.from_url(vcs_handler.short_name, plain_url)
    vcs_handler.pull(repo, {})

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

def vcs_special_files(url):
    """
    Return the names of the 'special' files/directories used by this VCS.

    For instance, if 'url' starts with "git+" then we might return
    [".git", ".gitignore", ".gitmodules"]
    """
    vcs_handler, plain_url = get_vcs_handler_from_string(url)
    return vcs_handler.get_vcs_special_files()

# End file.
