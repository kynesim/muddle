"""
Routines which deal with version control
"""

import utils
import string
import re
import pkg
import os

class VersionControlHandler:
    """
    Subclass this object to handle a particular type of version control system

    self.invocation       is the invocation we're running under.
    self.checkout_name is the name of the checkout (the directory under /src/) that 
                       we're responsible for.
    self.repository    is the repository we're interested in. Its syntax is 
                        VCS-dependent.
    self.revision      The revision to check out. The special name HEAD means
                         head of the main tree - anything else is VCS specific.

    The repository is stored in its full form - with its VCS tag, though this will
    almost never be used.

    """

    def __init__(self, inv, co_name, repo, rev, rel, co_dir = None):
        self.invocation = inv
        self.checkout_name = co_name
        self.checkout_dir = co_dir
        self.repository = repo
        self.revision = rev

    def path_in_checkout(self, rel):
        """
        Given a path relative to the repository, give us its name in the checkout.
        
        This entry point is mainly used when trying to work out where
        the build description specified in a muddle init command has ended up.
        """
        raise utils.Error("Attempt to call path_in_checkout() of the VersionControlHandler" +
                          " abstract base class.")

    def get_checkout_path(self, co_name):
        if (self.checkout_dir is not None):
            p = os.path.join(self.invocation.checkout_path(None), self.checkout_dir)
            if (co_name is not None):
                p = os.path.join(co_name)
            return p
        else:
            return self.invocation.checkout_path(co_name)
        
    def check_out(self):
        """
        Check this checkout out of revision control.
        """
        pass

    def pull(self):
        """
        Pull changes from the remote site into our repository
        """
        pass


    def update(self):
        """
        Update the current checkout of revision control
        """
        pass

    def commit(self):
        """
        Commit any local changes
        """
        pass

    def push(self):
        """
        Push local changes to a remote repository
        """
        pass

    def must_update_to_commit(self):
        """
        Must we update to commit? The answer is usually True for
        centralised VCS's (cvs and svn) and False for decentralised
        ones (git, bzr, hg).
        """
        raise utils.Failure("Attempt to call a base version of must_update_to_commit()")

class VersionControlHandlerFactory:
    """
    Registered to provide a means of constructing version control handlers
    """

    def describe():
        return "Generic version control handler factory"

    def manufacture(self, inv, co_name, repo, rev, rel, co_dir = None):
        """
        Manufacture a VCS handler.
        Recall that repo contains the vcs specifier - it's up to the VCS handler
        to remove it.
        """
        raise utils.Error("Attempt to use the VCS handler factory base class as " +
                          "a factory")

# This dictionary holds the global list of registered VCS handler
# factories.
vcs_dict = { }

def register_vcs_handler(scheme, factory):
    """
    Register a VCS handler factory with a VCS scheme prefix
    """
    vcs_dict[scheme] = factory

def list_registered():
    """
    Return a list of registered version control systems
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



def vcs_handler_for(inv, co_name, repo, rev, rest, co_dir = None):
    """
    Create a VCS handler for the given url, invocation and 
    checkout name. We do this by interpreting the initial part
    of the URI's protocol
    
    @param[in] inv  The invocation for which we're trying to build a handler.
    @param[in] co_name Checkout name
    @param[in] repo Repository URL
    @param[in] rev  Revision (None for HEAD)
    @param[in] rest Part after the repository URL - typically the CVS module name or 
                    whatever.
    @param[in] co_dir Directory relative to the checkout directory in which the
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

    return factory.manufacture(inv, co_name, repo, rev, rest, co_dir)

def vcs_dependable_for(builder, co_name, repo, rev, rest, co_dir = None):
    """
    Create a VCS dependable for the given co_name, repo, etc.
    """
    handler = vcs_handler_for(builder.invocation, co_name, repo, rev, rest, co_dir)
    if (handler is None):
        raise utils.Failure("Cannot build a VCS handler for %s rel = %s"%(repo, rel))

    return pkg.VcsCheckoutBuilder(co_name, handler)

def split_vcs_url(url):
    """
    Split a URL into a vcs and a repository URL. If there's no VCS
    specifier, return (None, None)
    """

    the_re = re.compile("^([A-Za-z]+)\+([A-Za-z]+):(.*)$")

    m = the_re.match(url)
    if (m is None):
        return (None, None)
    
    return (m.group(1).lower(), "%s:%s"%(m.group(2),m.group(3)))

def conventional_repo_url(repo, rel):
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

    # Find the first element of rel
    if (rel.find("/") != -1):
        (rel_first, rel_rest) = rel.split("/", 1)
    else:
        rel_first = rel
        rel_rest = None

    # The first element of the relative path is the repository name, so
    out_repo = "%s/%s"%(repo_rest, rel_first)
    out_rel = rel_rest

    return (out_repo, out_rel)

def conventional_repo_path(rel):
    """
    Returns the path inside a checkout for a given rel, given that the first
    element in rel is the repository name - this basically just chops off the
    first element of rel
    """
    (rel_first, rel_rest) = rel.split("/", maxsplit = 1)
    return rel_rest



# End file.

    

    
    

    
