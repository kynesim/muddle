"""
Routines which deal with version control.
"""

import utils
import string
import re
import pkg
import os

class VersionControlHandler:
    """
    Subclass this class to handle a particular type of version control system.

    * self.builder is the builder we're running under.
    * self.checkout_name is the name of the checkout (the directory under
      ``/src/``) that we're responsible for.
    * self.repository is the repository we're interested in. Its syntax is
      VCS-dependent.
    * self.revision is the revision to check out. The special name HEAD means
      head of the main tree - anything else is VCS specific.

    The repository is stored in its full form - with its VCS tag, though this will
    almost never be used.
    """

    def __init__(self, builder, co_name, repo, rev, rel, co_dir = None):
        self.builder = builder;
        self.checkout_name = co_name
        self.checkout_dir = co_dir
        self.repository = repo
        self.revision = rev
        self.relative = rel

    def path_in_checkout(self, rel):
        """
        Given a path relative to the repository, give us its name in the checkout.
        
        This entry point is mainly used when trying to work out where
        the build description specified in a muddle init command has ended up.
        """
        raise utils.Error("Attempt to call path_in_checkout() of the VersionControlHandler"
                          " abstract base class.")

    def get_my_absolute_checkout_path(self):
        """
        Does what it says on the tin.
        """
        return self.builder.invocation.checkout_path(self.checkout_name,
                                                     domain = self.builder.default_domain)

    def get_original_revision(self):
        """Return the revision id the user originally asked for.
        """
        return self.revision

    def get_checkout_path(self, co_name):
        """
        When called with None, get the parent directory of this checkout.
        God knows what happens otherwise.
        
        .. todo:: Needs documenting and rewriting!
        """
        if (self.checkout_dir is not None):
            p = os.path.join(self.builder.invocation.checkout_path(None, 
                                                                   domain = self.builder.default_domain), 
                             self.checkout_dir)
            if (co_name is not None):
                p = os.path.join(co_name)
            return p
        else:
            return self.builder.invocation.checkout_path(co_name, domain = self.builder.default_domain)
        
    def check_out(self):
        """
        Check this checkout out of revision control.
        """
        pass

    def pull(self):
        """
        Pull changes from the remote site into our repository

        In a distributed VCS, make the local repository (and working copy)
        a mirror of the remote repository.

        In a centralised VCS like subversion, this does nothing.
        """
        pass


    def update(self):
        """
        Update the current checkout of revision control
        """
        pass

    def commit(self):
        """
        Commit any local changes.

        In a distributed VCS, this commits the local changes to the local
        repository.

        In a centralised VCS, like subverson, this does not do anything.
        """
        pass

    def push(self):
        """
        Push local changes to a remote repository.

        (For a centralised VCS, like subversion, the underlying VCS will probably
        call this operation "commit".)
        """
        pass

    def must_update_to_commit(self):
        """
        Must we update to commit? The answer is usually True for
        centralised VCS's (cvs and svn) and False for decentralised
        ones (git, bzr, hg).
        """
        raise utils.Failure("Attempt to call a base version of must_update_to_commit()")

    def revision_to_checkout(self, force=False, verbose=False):
        """
        Determine a revision id for this checkout, usable to check it out again.

        The revision id we want is that we could use to check out an identical
        checkout.

        If the local working set/repository/whatever appears to have been
        altered from the remove repository, or otherwise does not yield a
        satisfactory revision id (this is something only the subclass can
        tell), then the method should raise utils.Failure, with as clear an
        explanation of the problem as possible.

        If 'force' is true, then if the revision cannot be determined, return
        the orginal revision that was specified when the checkout was checked
        out.

            (Individual version control classes may opt to ignore the 'force'
            argument, either because it is not useful in their context, or
            because they can tell that the checkout is seriously
            astray/broken.)

        NB: If the VCS class does not override this method, then the default
        implementation will raise a Failure unless 'force' is true, in which
        case it will return the string '0'.
        """
        if force:
            if verbose:
                print "No way to determine a revision for" \
                      " %s checkout %s"%(self.__class__.__name__,self.checkout_name)
            return '0'
        else:
            raise utils.Failure("No way to determine a revision for"
                    " %s checkout %s"%(self.__class__.__name__,self.checkout_name))

class VersionControlHandlerFactory:
    """
    Registered to provide a means of constructing version control handlers.
    """

    def describe(self):
        return "Generic version control handler factory"

    def manufacture(self, builder, co_name, repo, rev, rel, co_dir = None):
        """
        Manufacture a VCS handler.

        Recall that repo contains the vcs specifier - it's up to the VCS handler
        to remove it.
        """
        raise utils.Error("Attempt to use the VCS handler factory base class as "
                          "a factory")

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
        desc = v.describe()
        lines = desc.split("\n")
        str_list.append(lines[0])
        str_list.append("\n")
        for i in lines[1:]:
            str_list.append(utils.pad_to("", 20))
            str_list.append(i)
            str_list.append("\n")

    return "".join(str_list)



def vcs_handler_for(builder, co_name, repo, rev, rest, co_dir = None):
    """
    Create a VCS handler for the given url, invocation and checkout name.
    
    We do this by interpreting the initial part of the URI's protocol
    
    * inv - The invocation for which we're trying to build a handler.
    * co_name - Checkout name
    * repo - Repository URL
    * rev - Revision (None for HEAD)
    * rest - Part after the repository URL - typically the CVS module name or
      whatever.
    * co_dir - Directory relative to the checkout directory in which the
      checkout resides.
    """
    
    (vcs, url_rest) = split_vcs_url(repo)
    if (vcs is None):
        raise utils.Error("Improperly formatted repository spec %s"%repo)

    factory = vcs_dict.get(vcs, None)
    if (factory is None):
        raise utils.Error("No VCS handler registered for VCS type %s"%vcs)


    if (rev is None):
        rev = "HEAD"

    return factory.manufacture(builder, co_name, repo, rev, rest, co_dir)

def vcs_dependable_for(builder, co_name, repo, rev, rest, co_dir = None):
    """
    Create a VCS dependable for the given co_name, repo, etc.
    """
    handler = vcs_handler_for(builder, co_name, repo, rev, rest, co_dir)
    if (handler is None):
        raise utils.Failure("Cannot build a VCS handler for %s rel = %s"%(repo, rev))

    return pkg.VcsCheckoutBuilder(co_name, handler)

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
    #    raise utils.Failure("Help!")

    return (out_repo, out_rel)

def conventional_repo_path(rel):
    """
    Returns the path inside a checkout for a given rel, given that the first
    element in rel is the repository name - this basically just chops off the
    first element of rel.
    """
    (rel_first, rel_rest) = rel.split("/", maxsplit = 1)
    return rel_rest


# This is a dictionary of VCS name to function-to-retrieve-a-file
vcs_file_getter = {}

def register_vcs_file_getter(scheme, getter):
    """
    Register a function for retrieving an indivual file.

    'scheme' is the VCS (short) name. This should match the mnemonic used
    at the start of URLs - so, e.g., "bzr" for "bzr+ssh://whatever".
    
    'getter' is the function. It should take one argument, the URL of the
    file to retrieve, and return the file's content as a string.
    """
    vcs_file_getter[scheme] = getter

def vcs_get_file_data(url):
    """
    Return the content of the file identified by the URL, via its VCS.

    Looks at the first few characters of the URL to determine the VCS
    to use - so, e.g., "bzr" for "bzr+ssh://whatever".

    Returns a string (the content of the file).

    Raises KeyError if the scheme is not one we have a registered file getter
    for.
    """
    scheme, url = split_vcs_url(url)
    getter = vcs_file_getter[scheme]
    return getter(url)

# End file.

    

    
    

    
