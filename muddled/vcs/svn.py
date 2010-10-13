"""
Muddle support for svn.
"""

from muddled.version_control import *
from muddled.depend import Label
import muddled.utils as utils
import os

class Svn(VersionControlHandler):
    def __init__(self, builder, checkout_label, checkout_name, repo, rev, rel, co_dir):
        VersionControlHandler.__init__(self, builder, checkout_label, checkout_name,
                                       repo ,rev, rel, co_dir)

        sp = conventional_repo_url(repo, rel, co_dir = co_dir)
        if sp is None:
            raise utils.Error("Cannot extract repository URL from %s, checkout %s"%(repo,rel))
        
        self.svn_repo = sp[0]

        self.co_path = self.get_checkout_path(self.checkout_label)

        self.my_path = self.get_my_absolute_checkout_path()

    def check_out(self):
        parent_dir = os.path.split(self.co_path)[0]
        utils.ensure_dir(parent_dir)
        os.chdir(parent_dir)
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

    def manufacture(self, builder, checkout_label, checkout_name, repo, rev, rel, co_dir, branch):
        return Svn(builder, checkout_label, checkout_name, repo, rev, rel, co_dir)

# Register us with the VCS handler factory
register_vcs_handler("svn", SvnVCSFactory())

def svn_file_getter(url):
    """Retrieve a file's content via Subversion.
    """
    retcode, text, ignore = utils.get_cmd_data('svn cat %s'%url,
                                                fold_stderr=False)
    return text

register_vcs_file_getter('svn', svn_file_getter)

def svn_dir_handler(action, url=None, directory=None, files=None):
    """Clone/push/pull/commit a directory via svn

    For svn, "push" and "pull" ignore the 'url', and "init" does not
    know how to initialise a director
    """
    if action == 'clone':
        if directory:
            utils.run_cmd("svn checkout %s %s"%(url, directory))
        else:
            utils.run_cmd("svn checkout %s"%url)
    elif action == 'commit':
        pass
    elif action == 'push':
        utils.run_cmd("svn commit")
    elif action == 'pull':
        utils.run_cmd("svn update")
    elif action == 'init':
        print 'The svn directory handler does not know how to "init" a directory'
    elif action == 'add':
        if files:
            utils.run_cmd("svn add %s"%' '.join(files))
    else:
        raise utils.Failure("Unrecognised action '%s' for svn directory handler"%action)

register_vcs_dir_handler('svn', svn_dir_handler)

# End file.

