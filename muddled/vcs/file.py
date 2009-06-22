"""
Muddle support for naive file copying
"""

from muddled.version_control import *
import muddled.utils as utils
import urlparse

class File(VersionControlHandler):
    """
    Version control handler for file copies
    
    Simply copies data from a repository directory to a working directory
    It does _not_ copy data back.
    """

    def __init__(self, inv, co_name, repo, rev, rel, co_dir):
        VersionControlHandler.__init__(self, inv, co_name, repo, rev, rel, co_dir)
        
        sp = conventional_repo_url(repo, rel)
        if (sp is None):
            raise utils.Error("Cannot extract repository URL from %s, co %s"%(repo, rel))
        
        (real_repo, r) = sp


        parsed = urlparse.urlparse(real_repo)
        self.source_path = parsed.path
        self.co_path = self.get_checkout_path(self.checkout_name)


    def check_out(self):
        # Check out.
        utils.ensure_dir(self.co_path)
        utils.run_cmd("cp -r %s/* %s"%(self.source_path, self.co_path))

    def pull(self):
        # Nothing to do here.
        pass

    def update(self):
        # Just copy everything over again.
        self.check_out()

    def commit(self):
        # Nothing to do
        pass

    def push(self):
        # Nothing to do
        pass

    def must_update_to_commit(self):
        return False


class FileVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "Copy data between directories"

    def manufacture(self, inv, co_name, repo, rev, rel, co_dir):
        return File(inv, co_name, repo, rev, rel, co_dir)


# Tell the VCS handler about us.
register_vcs_handler("file", FileVCSFactory())


# End File
