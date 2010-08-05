"""
Muddle support for svn.
"""

from muddled.version_control import *
import muddled.utils as utils
import os

class Svn(VersionControlHandler):
    def __init__(self, builder, checkout_name, repo, rev, rel, co_dir):
        VersionControlHandler.__init__(self, builder, checkout_name, repo ,rev, rel, co_dir)

        sp = conventional_repo_url(repo, rel, co_dir = co_dir)
        if sp is None:
            raise utils.Error("Cannot extract repository URL from %s, checkout %s"%(repo,rel))
        
        self.svn_repo = sp[0]

        self.co_path = self.get_checkout_path(self.checkout_name)
        self.my_path = self.get_my_absolute_checkout_path()

    def path_in_checkout(self, rel):
        return conventional_repo_path(rel)

    def check_out(self):
        co_path = self.get_checkout_path(None)
        utils.ensure_dir(co_path)
        os.chdir(co_path)
        utils.run_cmd("svn checkout %s %s %s"%(self.r_option(),
                      self.svn_repo, self.checkout_name))
        
    def pull(self):
        # This is a centralised VCS - there is no pull.
        pass

    def update(self):
        os.chdir(self.my_path)
        #print "> path = %s"%self.my_path
        utils.run_cmd("svn update %s"%(self.r_option()))
        
    def commit(self):
        # Centralised VCS - there is no local commit.
        pass

    def push(self):
        os.chdir(self.my_path)
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

    def revision_to_checkout(self, force=False, verbose=False):
        """
        Determine a revision id for this checkout, usable to check it out again.

        Uses 'svnversion', which I believe is installed as standard with 'svn'

        For the moment, at lease, the 'force' argument is ignored (so the
        working copy must be be equivalent to the repository).
        """
        os.chdir(self.my_path)
        retcode, revision, ignore = utils.get_cmd_data('svnversion')
        revision = revision.strip()
        if all([x.isdigit() for x in revision]):
            return revision
        else:
            raise utils.Failure("%s: 'svnversion' reports checkout has revision"
                    " '%s'"%(self.checkout_name,revision))


class SvnVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "Subversion"

    def manufacture(self, builder, checkout_name, repo, rev, rel, co_dir, branch):
        return Svn(builder, checkout_name, repo, rev, rel, co_dir, branch)

# Register us with the VCS handler factory
register_vcs_handler("svn", SvnVCSFactory())

def svn_file_getter(url):
    """Retrieve a file's content via Subversion.
    """
    retcode, text, ignore = utils.get_cmd_data('svn cat %s'%url,
                                                fold_stderr=False)
    return text

register_vcs_file_getter('svn', svn_file_getter)

def svn_dir_getter(url):
    """Retrieve a directory via Subversion.
    """
    utils.run_cmd("svn checkout %s"%url)

register_vcs_dir_getter('svn', svn_dir_getter)


# End file.

