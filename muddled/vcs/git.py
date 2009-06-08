"""
Muddle suppport for Git
"""

from muddled.version_control import *
import muddled.utils as utils

class Git(VersionControlHandler):
    def __init__(self, inv, co_name, repo, rev, rel):
        VersionControlHandler.__init__(self, inv, co_name, repo, rev, rel)
        sp = conventional_repo_url(repo, rel)
        if sp is None:
            raise utils.Error("Cannot extract repository URL from %s, checkout %s"%(repo, rel))

        self.git_repo = sp[0]
        self.co_path = self.invocation.checkout_path(self.co_name)
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
        co_path = self.invocation.checkout_path(None)
        
        utils.ensure_dir(co_path)
        utils.run_cmd("git clone %s %s"%(self.git_repo,self.co_name))
        
        if not ((self.revision is None) or (not self.revision)):
            os.chdir(self.co_name)
            utils.run_cmd("git checkout %s"%self.revision)

    def pull(self):
        os.chdir(self.co_path)
        utils.run_cmd("git pull %s %s"%(self.git_repo, self.branch_name))
        
    def update(self):
        os.chdir(self.co_path)
        utils.run_cmd("git pull", allowFailure = True)

    def commit(self):
        os.chdir(self.co_path)
        utils.run_cmd("git commit")

    def push(self):
        os.chdir(self.co_path)
        utils.run_cmd("git push %s"%self.git_repo)


class GitVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "GIT"

    def manufacture(self, inv, co_name, repo, rev, rel):
        return Git(inv, co_name, repo, rev, rel)

# Register us with the VCS handler factory
register_vcs_handler("git", GitVCSFactory())

# End file.

    
                         

        
        
        
