"""
Muddle support for Subversion
"""

from muddled.version_control import register_vcs_handler, VersionControlSystem
import muddled.utils as utils

class Subversion(VersionControlSystem):
    """
    Provide version control operations for Subversion
    """

    def __init__(self):
        self.short_name = 'svn'
        self.long_name = 'Subversion'

    def init_directory(self, verbose=True):
        """
        If the directory does not appear to have had '<vcs> init' run in it,
        then do so first.

        Will be called in the actual checkout's directory.
        """
        print 'Muddle svn support does not know how to "init" a directory'

    def add_files(self, files=None, verbose=True):
        """
        If files are given, add them, but do not commit.

        Will be called in the actual checkout's directory.
        """
        if files:
            utils.run_cmd("svn add %s"%' '.join(files), verbose=verbose)

    def _r_option(self, revision):
        """
        Return the -r option to pass to svn commands, if any
        """
        if revision is None or revision == "HEAD":
            return ""
        else:
            return "-r %s"%revision

    def checkout(self, repo, co_leaf, branch=None, revision=None, verbose=True):
        """
        Clone a given checkout.

        Will be called in the parent directory of the checkout.

        Expected to create a directory called <co_leaf> therein.
        """
        if branch:
            raise utils.GiveUp("Subversion does not support the 'branch'"
                               " argument to 'checkout' (branch='%s')"%branch)
        utils.run_cmd("svn checkout %s %s %s"%(self._r_option(revision),
                                               repo, co_leaf), verbose=verbose)

    def fetch(self, repo, branch=None, revision=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        This runs Subversion's "update", but only if no merging will be
        needed. That is, first it runs "svn status", and if any lines
        contain a "C" (for Conflict) in columns 0, 1 or 6, then it will not
        perform the update.

          ("svn help status" would call those columns 1, 2 and 7)
        """
        if branch:
            raise utils.GiveUp("Subversion does not support the 'branch'"
                               " argument to 'fetch' (branch='%s')"%branch)
        retcode, text, ignore = utils.get_cmd_data("svn status")
        for line in text:
            if 'C' in (line[0], line[1], line[6]):
                raise utils.GiveUp("%s: 'svn status' says there is a Conflict,"
                                    " refusing to fetch:\n%s\nUse 'muddle merge'"
                                    " if you want to merge"%(utils.indent(text,'    ')))
        utils.run_cmd("svn update %s"%(self._r_option(revision)), verbose=verbose)

    def merge(self, other_repo, branch=None, revision=None, verbose=True):
        """
        Merge 'other_repo' into the local repository and working tree,

        This runs Subversion's "update" - its "merge" command does something
        different.

        Will be called in the actual checkout's directory.
        """
        if branch:
            raise utils.GiveUp("Subversion does not support the 'branch'"
                               " argument to 'merge' (branch='%s')"%branch)
        utils.run_cmd("svn update %s"%(self._r_option(revision)), verbose=verbose)

    def commit(self, verbose=True):
        """
        Will be called in the actual checkout's directory.

        This command does nothing, because Subversion does not have a local
        repository. Use 'muddle push' instead.
        """
        pass

    def push(self, repo, branch=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        This actually does a "svn commit", i.e., committing to the remote
        repository (which is the only one subversion has).
        """
        utils.run_cmd("svn commit", verbose=verbose)

    def status(self, repo, verbose=False):
        """
        Will be called in the actual checkout's directory.

        Runs "svn status". Looks at the first column of each line, and
        returns True if they are all <space>.
        """
        retcode, text, ignore = utils.get_cmd_data("svn status", verbose=verbose)
        if verbose:
            print text

        for line in text:
            if line[0] != ' ':
                return False

        return True

    def reparent(self, co_dir, remote_repo, force=False, verbose=True):
        """
        Re-associate the local repository with its original remote repository,

        Our subversion support does not provide this.
        """
        pass                # or should we say something? I assume not...

    def revision_to_checkout(self, co_leaf, orig_revision, force=False, verbose=False):
        """
        Determine a revision id for this checkout, usable to check it out again.

        Uses 'svnversion', which I believe is installed as standard with 'svn'

        For the moment, at lease, the 'force' argument is ignored (so the
        working copy must be be equivalent to the repository).
        """
        retcode, revision, ignore = utils.get_cmd_data('svnversion', verbose=verbose)
        revision = revision.strip()
        if all([x.isdigit() for x in revision]):
            return revision
        else:
            raise utils.GiveUp("%s: 'svnversion' reports checkout has revision"
                    " '%s'"%(co_leaf, revision))

    def allows_relative_in_repo(self):
        return True

    def get_file_content(self, url, verbose=True):
        """
        Retrieve a file's content via Subversion.
        """
        retcode, text, ignore = utils.get_cmd_data('svn cat %s'%url,
                                                   fold_stderr=False,
                                                   verbose=verbose)
        return text

    def must_fetch_before_commit(self):
        """
        Subversion recommends doing 'commit' before "fetch" (i.e., pull/update)
        """
        True

# Tell the version control handler about us..
register_vcs_handler("svn", Subversion())

# End file.
