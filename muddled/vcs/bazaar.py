"""
Muddle support for Bazaar.
"""

from muddled.version_control import *
import muddled.utils as utils

class Bazaar(VersionControlHandler):
    """
    Version control handler for bazaar.

    Bazaar repositories are named: bzr+<url>.

    It's assumed that the first path component of 'rel' is the name of the repository.
    """

    def __init__(self, inv, co_name, repo, rev, rel, co_dir):
        VersionControlHandler.__init__(self, inv, co_name, repo, rev, rel, co_dir)
        
        sp = conventional_repo_url(repo, rel, co_dir = co_dir)
        if sp is None:
            raise utils.Error("Cannot extract repository URL from %s, co %s"%(repo, rel))

        self.bzr_repo = sp[0]
        self.checkout_path = self.get_checkout_path(None)

        if self.bzr_repo.startswith("ssh://"):
            # For some reason, the bzr command wants us to use "bzr+ssh" to
            # communicate over ssh, not just "ssh". Accomodate it, so the user
            # does not need to care about this.
            self.bzr_repo = "bzr+%s"%self.bzr_repo

    def path_in_checkout(self, rel):
        return conventional_repo_path(rel)

    def check_out(self):
        # Check out.
        utils.ensure_dir(self.checkout_path)
        os.chdir(self.checkout_path)
        utils.run_cmd("bzr checkout %s %s %s"%(self.r_option(), self.bzr_repo, self.checkout_name))
        # Tell bzr that when we "commit" in this checkout, we don't want
        # bzr to automatically "push" to the remote repository (which is
        # its default behaviour)
        os.chdir(os.path.join(self.checkout_path,self.checkout_name))
        utils.run_cmd("bzr unbind")


    def pull(self):
        os.chdir(self.checkout_path)
        utils.run_cmd("bzr pull %s"%self.bzr_repo)

    def update(self):
        update_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(update_in)
        utils.run_cmd("bzr update", allowFailure = True)

    def commit(self):
        commit_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(commit_in)
        utils.run_cmd("bzr commit", allowFailure = True)

    def push(self):
        push_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(push_in)
        print "> push to %s "%self.bzr_repo
        utils.run_cmd("bzr push %s"%self.bzr_repo)

    def must_update_to_commit(self):
        return False

    def r_option(self):
        """
        Return the -r option to pass to bzr commands, if any
        """
        if ((self.revision is None) or (self.revision == "HEAD")):
            return ""
        else:
            return "-r %s"%(self.revision)


class BazaarVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "The Bazaar VCS"

    def manufacture(self, inv, co_name, repo, rev, rel, co_dir):
        return Bazaar(inv, co_name, repo, rev, rel, co_dir)

        
# Tell the version control handler about us..
register_vcs_handler("bzr", BazaarVCSFactory())

# End file.

