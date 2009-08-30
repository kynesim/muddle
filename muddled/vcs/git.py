"""
Muddle suppport for Git.
"""

from muddled.version_control import *
import muddled.utils as utils
import os

class Git(VersionControlHandler):
    def __init__(self, inv, checkout_name, repo, rev, rel, co_dir):
        VersionControlHandler.__init__(self, inv, checkout_name, repo, rev, rel, co_dir)
        sp = conventional_repo_url(repo, rel)
        if sp is None:
            raise utils.Error("Cannot extract repository URL from %s, checkout %s"%(repo, rel))

        self.git_repo = sp[0]
        self.co_path = self.get_checkout_path(self.checkout_name)
        self.parse_revision(rev)

    def parse_revision(self, rev):
        # Disentangle git version numbers. These are like '<branch>:<revision>'
        the_re = re.compile("([^:]*):(.*)$")
        m = the_re.match(rev)
        if (m is None):
            # No branch
            self.branch = "master"
            if (rev == "HEAD"):
                self.revision = "HEAD" # Turns out git uses this too
            else:
                self.revision = rev
        else:
            self.branch = m.group(1)
            self.revision = m.group(2)
            # No need to adjust HEAD - git uses it too.


    def path_in_checkout(self, rel):
        return conventional_repo_path(rel)

    def check_out(self):
        # Clone constructs its own directory .. 
        (parent_path, d) = os.path.split(self.co_path)

        utils.ensure_dir(parent_path)
        os.chdir(parent_path)
        utils.run_cmd("git clone %s %s"%(self.git_repo,self.checkout_name))
        
        if not ((self.revision is None) or (not self.revision)):
            os.chdir(self.checkout_name)
            utils.run_cmd("git checkout %s"%self.revision)

    def pull(self):
        os.chdir(self.co_path)
        utils.run_cmd("git pull %s %s"%(self.git_repo, self.branch))
        
    def update(self):
        os.chdir(self.co_path)
        utils.run_cmd("git pull", allowFailure = True)

    def commit(self):
        os.chdir(self.co_path)
        # We may very well fail here. git commit fails for any number
        # of bizarre reasons we don't care about .. 
        utils.run_cmd("git commit -a", allowFailure = True)

    def push(self):
        os.chdir(self.co_path)
        utils.run_cmd("git push %s"%self.git_repo)

    def must_update_to_commit(self):
        return False


class GitVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "GIT"

    def manufacture(self, inv, checkout_name, repo, rev, rel, co_dir):
        return Git(inv, checkout_name, repo, rev, rel, co_dir)

# Register us with the VCS handler factory
register_vcs_handler("git", GitVCSFactory())

# End file.

    
                         

        
        
        
