"""
Muddle support for Subversion

.. to be documented ..

Note that Subversion does not support "branches" in the muddle sense.
Subversion branches are handled by a different mechanism, and in a muddle
sense are more like inner paths of a Repository. At the moment muddle does
not provide any special support for Subversion branches.

Available Subversion specific options are:

* no_follow: In a build description that has set::

    builder.follow_build_desc_branch = True

  then a Subversion repository can either:

      1. Specify a particular revision
      2. Choose a different repository location (presumably a subversion
         "branch"), and set the no_follow option to True
      3. Continue using the original repository without setting a revision
         (almost certainly not sensible, but still), and set the no_follow
         option to True.

  If none of these are done, then muddle will fail with a complaint like::

    The build description wants checkouts to follow branch '<branch-name>',
    but checkout <co-name> uses VCS Subversion for which we do not support branching.
    The build description should specify a revision for checkout <co-name>.

"""

from muddled.version_control import register_vcs, VersionControlSystem
import muddled.utils as utils

class Subversion(VersionControlSystem):
    """
    Provide version control operations for Subversion
    """

    def __init__(self):
        self.short_name = 'svn'
        self.long_name = 'Subversion'
        self.allowed_options.add('no_follow')

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
            utils.shell(["svn", "add"] + list(files), show_command=verbose)

    def _r_option(self, revision):
        """
        Return the -r option to pass to svn commands, if any
        """
        if revision is None or revision == "HEAD":
            return []
        else:
            return ["-r", revision]

    def checkout(self, repo, co_leaf, options, verbose=True):
        """
        Clone a given checkout.

        Will be called in the parent directory of the checkout.

        Expected to create a directory called <co_leaf> therein.
        """
        if repo.branch:
            raise utils.GiveUp("Subversion does not support branch"
                               " in 'checkout' (branch='%s')"%repo.branch)
        utils.shell(["svn", "checkout"] + self._r_option(repo.revision) +
                   [repo.url, co_leaf], show_command=verbose)

    def pull(self, repo, options, upstream=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        This runs Subversion's "update", but only if no merging will be
        needed. That is, first it runs "svn status", and if any lines
        contain a "C" (for Conflict) in columns 0, 1 or 6, then it will not
        perform the update.

          ("svn help status" would call those columns 1, 2 and 7)
        """
        if repo.branch:
            raise utils.GiveUp("Subversion does not support branch"
                               " in 'pull' (branch='%s')"%repo.branch)
        text = utils.get_cmd_data("svn status")
        for line in text:
            if 'C' in (line[0], line[1], line[6]):
                raise utils.GiveUp("%s: 'svn status' says there is a Conflict,"
                                    " refusing to pull:\n%s\nUse 'muddle merge'"
                                    " if you want to merge"%(utils.indent(text,'    ')))

        starting_revno = self._just_revno()

        utils.shell(["svn", "update"] + self._r_option(repo.revision), show_command=verbose)

        # We could try parsing the output of 'svn update' instead, but this is
        # simpler to do...
        ending_revno = self._just_revno()
        # Did we update anything?
        return starting_revno != ending_revno

    def merge(self, other_repo, options, verbose=True):
        """
        Merge 'other_repo' into the local repository and working tree,

        This runs Subversion's "update" - its "merge" command does something
        different.

        Will be called in the actual checkout's directory.
        """
        if other_repo.branch:
            raise utils.GiveUp("Subversion does not support branch"
                               " in 'merge' (branch='%s')"%other_repo.branch)

        starting_revno = self._just_revno()

        utils.shell(["svn", "update"] +  self._r_option(other_repo.revision),
                   show_command=verbose)

        ending_revno = self._just_revno()
        # Did we update anything?
        return starting_revno != ending_revno

    def commit(self, repo, options, verbose=True):
        """
        Will be called in the actual checkout's directory.

        This command does nothing, because Subversion does not have a local
        repository. Use 'muddle push' instead.
        """
        pass

    def push(self, repo, options, upstream=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        This actually does a "svn commit", i.e., committing to the remote
        repository (which is the only one subversion has).
        """
        utils.shell(["svn", "commit"], show_command=verbose)

    def status(self, repo, options, quick=False):
        """
        Will be called in the actual checkout's directory.

        Return status text or None if there is no interesting status.
        """

        #just return an error message, don't check anything
        if quick:
            return "muddle status -quick is not supported on svn checkouts"

        text = utils.get_cmd_data("svn status --show-updates --verbose")

        lines = text.split('\n')
        stuff = []
        seven_spaces = ' '*7
        for line in lines:
            # The first 7 characters and the 9th give us our status
            if line.startswith(seven_spaces) and line[8] == ' ':
                continue
            elif line == '':    # typically, a blank final line
                continue
            else:
                stuff.append(line)

        # Was it just reporting that nothing happened in this particular
        # revision?
        if len(stuff) == 1 and stuff[0].startswith('Status against revision'):
            stuff = []

        if stuff:
            stuff.append('')        # add back a cosmetic blank line
            return '\n'.join(stuff)
        else:
            return None

    def goto_revision(self, revision, branch=None, repo=None, verbose=False):
        """
        Make the specified revision current.

        Note that this may leave the working data (the actual checkout
        directory) in an odd state, in which it is not sensible to
        commit, depending on the VCS and the revision.

        Will be called in the actual checkout's directory.

        Raises GiveUp if there is no such revision, or if branch is given.
        """
        if branch:
            raise utils.GiveUp("Subversion does not support branch (in the muddle sense), branch=%s"%branch)

        if not repo:
            raise utils.MuddleBug("Subversion needs a Repository instance to do goto_revision()");

        # Luckily, our pull method does more-or-less what we want
        repo = repo.copy_with_changed_revision(revision)
        self.pull(repo, None, verbose=verbose)

    def reparent(self, co_dir, remote_repo, options, force=False, verbose=True):
        """
        Re-associate the local repository with its original remote repository,

        Our subversion support does not provide this.
        """
        pass                # or should we say something? I assume not...

    def revision_to_checkout(self, repo, co_leaf, options, force=False, before=None, verbose=False):
        """
        Determine a revision id for this checkout, usable to check it out again.

        Uses 'svnversion', which I believe is installed as standard with 'svn'

        For the moment, at lease, the 'force' argument is ignored (so the
        working copy must be be equivalent to the repository).
        """
        if before:
            raise utils.GiveUp('%s: "before" argument not currently supported'%co_leaf)

        revision = utils.get_cmd_data('svnversion', show_command=verbose)
        revision = revision.strip()
        if all([x.isdigit() for x in revision]):
            return revision
        else:
            raise utils.GiveUp("%s: 'svnversion' reports checkout has revision"
                    " '%s'"%(co_leaf, revision))

    def _just_revno(self):
        """
        This returns the revision number for the working tree
        """
        revision = utils.get_cmd_data('svnversion')
        return revision.strip()

    def allows_relative_in_repo(self):
        return True

    def get_vcs_special_files(self):
        return ['.svn']

    def get_file_content(self, url, verbose=True):
        """
        Retrieve a file's content via Subversion.
        """
        text = utils.get_cmd_data('svn cat %s'%url, show_command=verbose)
        return text

    def must_pull_before_commit(self, options):
        """
        Subversion recommends doing 'commit' before "pull" (i.e., pull/update)
        """
        return True

# Tell the version control handler about us..
register_vcs("svn", Subversion(), __doc__)

# End file.
