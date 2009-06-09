"""
Muddle support for svn
"""

from muddled.version_control import *
import muddled.utils as utils
import os

class Svn(VersionControlHandler):
    def __init__(self, inv, checkout_name, repo, rev, rel):
        VersionControlHandler.__init__(self, inv, checkout_name, repo ,rev, rel)
        sp = conventional_repo_url(repo, rel)
        if sp is None:
            raise utils.Error("Cannot extract repository URL from %s, checkout %s"%(repo,rel))

        self.svn_repo = sp[0]
        self.co_path = self.invocation.checkout_path(self.checkout_name)
        self.rev = rev

    def path_in_checkout(self, rel):
        return conventional_repo_path(rel)

    def check_out(self):
        co_path = self.invocation.checkout_path(None)
        utils.ensure_dir(co_path)
        os.chdir(co_path)
        utils.run_cmd("svn co %s %s %s"%(self.r_option(), self.svn_repo, self.checkout_name))
        
    def pull(self):
        # This is a centralised VCS - there is no pull.
        pass

    def update(self):
        os.chdir(self.co_path)
        utils.run_cmd("svn update %s"%(self.r_option()))
        
    def commit(self):
        # Centralised VCS - there is no local commit.
        pass

    def push(self):
        os.chdir(self.co_path)
        utils.run_cmd("svn commit")

    def must_update_to_commit(self):
        return True
    
    def r_option(self):
        """
        Return the -r option to pass to svn commands, if any
        """
        if ((self.revision is None) or (self.revision == "HEAD")):
            return ""
        else:
            return "-r %s"%(self.revision)



class SvnVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "Subversion"

    def manufacture(self, inv, checkout_name, repo, rev, rel):
        return Svn(inv, checkout_name, repo, rev, rel)

# Register us with the VCS handler factory
register_vcs_handler("svn", SvnVCSFactory())

# End file.

