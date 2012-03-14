"""
Muddle support for Bazaar.

.. to be documented ..
"""

import os

from muddled.version_control import register_vcs_handler, VersionControlSystem
import muddled.utils as utils

class Bazaar(VersionControlSystem):
    """
    Provide version control operations for Bazaar
    """

    def __init__(self):
        self.short_name = 'bzr'
        self.long_name = 'Bazaar'

    def _normalised_repo(self, repo):
        """
        For some reason, the bzr command wants us to use "bzr+ssh" to
        communicate over ssh, not just "ssh".
        Accomodate it, so the user does not need to care about this.
        """
        if repo.startswith("ssh:"):
            return "bzr+%s"%repo
        else:
            return repo

    def _r_option(self, revision):
        """
        Return the -r option(s) to pass to bzr commands, if any
        """
        if revision is None or revision == "HEAD":
            return ""
        else:
            # We can't says "-r revno:xxx" because we don't know what the
            # user has given us, and it may not be a revno (indeed, they
            # could have given us "date:yesterday"
            return "-r %s"%revision

    def _derive_env(self):
        """
        Return a "safe" environment dictionary.

        It turns out that if the PYTHONPATH includes the "current directory",
        then various bzr commands ('bzr missing' in particular) do not play
        well with some of the typical Python file names we sometimes have in
        'src/builds' directories.

        (Specifically, this is observed with bzr version 2.0.2 on my Ubuntu
        system with my packages installed, so it may or may not happen for
        anyone else, but it still seems safest to avoid it!)

        The "solution" (ick, ick) is thus to make sure this doesn't happen...
        - and the simplest way to do that is probably to ignore any PYTHONPATH
        in our local environment when running the command(s)
        """
        env = os.environ.copy()
        if 'PYTHONPATH' in env:
            del env['PYTHONPATH']
        return env

    def init_directory(self, verbose=True):
        """
        If the directory does not appear to have had '<vcs> init' run in it,
        then do so first.

        Will be called in the actual checkout's directory.
        """
        # This is *really* hacky...
        if not os.path.exists('.bzr'):
            utils.run_cmd("bzr init", env=self._derive_env(), verbose=verbose)

    def add_files(self, files=None, verbose=True):
        """
        If files are given, add them, but do not commit.

        Will be called in the actual checkout's directory.
        """
        if files:
            utils.run_cmd("bzr add %s"%' '.join(files))

    def checkout(self, repo, co_leaf, options, verbose=True):
        """
        Checkout (clone) a given checkout.

        Will be called in the parent directory of the checkout.

        Expected to create a directory called <co_leaf> therein.
        """
        # Remember that 'bzr checkout' does something different - it produces
        # a checkout that is "bound" to the remote repository, so that doing
        # 'bzr commit' will behave like SVN, and commit/push to the remote
        # repository. We don't want that behaviour.

        utils.run_cmd("bzr branch %s %s %s"%(self._r_option(repo.revision),
                                             self._normalised_repo(repo.url),
                                             co_leaf),
                      env=self._derive_env(), verbose=verbose)

    def _is_it_safe(self, env):
        """
        No dentists here...

        Raise an exception if there are (uncommitted) local changes.
        """
        ok, cmd, txt = self._all_checked_in(env)
        if not ok:
            raise utils.GiveUp("There are uncommitted changes")

    def fetch(self, repo, options, verbose=True):
        """
        Fetch changes, but don't do a merge.

        Will be called in the actual checkout's directory.
        """

        rspec = self._r_option(repo.revision)

        # Refuse to pull if there are any local changes
        env = self._derive_env()
        self._is_it_safe(env)

        utils.run_cmd("bzr pull %s %s"%(rspec, self._normalised_repo(repo.url)),
                      env=env, verbose=verbose)

    def merge(self, other_repo, options, verbose=True):
        """
        Merge 'other_repo' into the local repository and working tree,

        'bzr merge' will not (by default) merge if there are uncommitted changes
        in the destination (i.e., local) tree. This is what we want.

        Will be called in the actual checkout's directory.
        """

        # Refuse to pull if there are any local changes
        env = self._derive_env()
        self._is_it_safe(env)

        rspec = self._r_option(other_repo.revision)

        utils.run_cmd("bzr merge %s %s"%(rspec, self._normalised_repo(other_repo.url)),
                      env=env, verbose=verbose)

    def commit(self, repo, options, verbose=True):
        """
        Will be called in the actual checkout's directory.
        """
        # Options: --strict means it will not commit if there are unknown
        # files in the working tree
        utils.run_cmd("bzr commit", allowFailure=True,
                      env=self._derive_env(), verbose=verbose)

    def push(self, repo, options, verbose=True):
        """
        Will be called in the actual checkout's directory.
        """

        utils.run_cmd("bzr push %s"%self._normalised_repo(repo.url),
                      env=self._derive_env(), verbose=verbose)

    def status(self, repo, options=None, branch=None, verbose=False):
        """
        Will be called in the actual checkout's directory.

        Return status text or None if there is no interesting status.
        """
        env = self._derive_env()

        # --quiet means only report warnings and errors
        cmd = 'bzr status --quiet -r branch:%s'%self._normalised_repo(repo.url),

        retcode, text, ignore = utils.get_cmd_data(cmd, env=env, fold_stderr=False)
        if text:
            return text
        else:
            return None

        # --- UNREACHED CODE
        # So, have we checked everything in?
        ok, cmd, text = self._all_checked_in(env)
        if not ok:
            if verbose:
                print "'%s' reports uncommitted data\n%s"%(cmd, text)
            return False

        # So, is our current revision (on this local branch) also present
        # in the remote branch (our push/pull location)?
        missing, cmd = self._current_revision_missing(env)
        missing = missing.strip()
        if missing:
            if verbose:
                print "'%s' reports checkout does not match the remote" \
                        " repository"%cmd
                print missing
            return False
        return True

    def reparent(self, co_leaf, remote_repo, options, force=False, verbose=True):
        """
        Re-associate the local repository with its original remote repository,

        * 'co_leaf' should be the name of this checkout directory, for use
          in messages reporting what we are doing. Note that we are called
          already *in* that directory, though.
        * 'remote_repo' is the repository we would like to associate it with.

        ``bzr info`` is your friend for finding out if the checkout is
        already associated with a remote repository. The "parent branch"
        is used for pulling and merging (and is what we set). If present,
        the "push branch" is used for pushing.

        If force is true, we set "parent branch", and delete "push branch" (so
        it will default to the "parent branch").

        If force is false, we only set "parent branch", and then only if it is
        not set.

        The actual information is held in <checkout-dir>/.bzr/branch/branch.conf,
        which is a .INI file.
        """
        if verbose:
            print "Re-associating checkout '%s' with remote repository"%co_leaf
        this_dir = os.curdir
        this_file = os.path.join(this_dir, '.bzr', 'branch', 'branch.conf')

        remote_repo = self._normalised_repo(remote_repo.url)

        # It would be nice if Bazaar used the ConfigParser for the branch.conf
        # files, but it doesn't - they lack a [section] name. Thus we will have
        # to do this by hand...
        #
        # Note that I'm going to try to preserve, as much as possible, any lines
        # that I do not actually change...
        with open(this_file) as f:
            lines = f.readlines()
        items = {}
        posns = []
        count = 0
        for orig_line in lines:
            count += 1                  # normal people like first line is line 1
            line = orig_line.strip()
            if len(line) == 0 or line.startswith('#'):
                posns.append(('#', orig_line))
                continue
            elif '=' not in line:
                raise utils.GiveUp("Cannot parse '%s' - no '=' in line %d:"
                                    "\n    %s"%(this_file, count, line))
            words = line.split('=')
            key = words[0].strip()
            val = ''.join(words[1:]).strip()
            items[key] = val
            posns.append((key, orig_line))

        changed = False
        if force:
            changed = True
            if 'push_location' in items:        # Forget it
                if verbose:
                    print
                    print '.. Forgetting "push" location'
                items['push_location'] = None
            if 'parent_location' not in items:  # Place it at the end
                posns.append(('parent_location', remote_repo))
                if verbose:
                    print
                    print '.. Setting "parent" location %s'%remote_repo
            else:
                if verbose:
                    print '.. Overwriting "parent" location'
                    print '   it was     %s'%items['parent_location']
                    print '   it becomes %s'%remote_repo
            items['parent_location'] = remote_repo
        else:
            if 'parent_location' not in items:  # Place it at the end
                if verbose:
                    print
                    print '.. Setting "parent" location %s'%remote_repo
                posns.append(('parent_location', remote_repo))
                items['parent_location'] = remote_repo
                changed = True
            elif verbose:
                print ' - already associated'
                if items['parent_location'] != remote_repo:
                    print '.. NB with %s'%items['parent_location']
                    print '       not %s'%remote_repo

        if changed:
            print '.. Writing branch configuration file'
            with open(this_file, 'w') as fd:
                for key, orig_line in posns:
                    if key == '#':
                        fd.write(orig_line)
                    elif key in items:
                        if items[key] is not None:
                            fd.write('%s = %s\n'%(key, items[key]))
                    else:
                        fd.write(orig_line)

    def _all_checked_in(self, env):
        """
        Do we have anything that is not yet checked in?

        Returns (True, <cmd>, None) if everything appears OK,
        (False, <cmd>, <text>) if not, where <cmd> is the BZR command used, and
        <text> is its output.
        """
        cmd = 'bzr version-info --check-clean'
        retcode, text, ignore = utils.get_cmd_data(cmd, env=env, fold_stderr=False)
        if 'clean: False' in text:
            return False, cmd, text
        return True, cmd, None

    def _current_revision_missing(self, env):
        """
        Is our current revision (on this local branch) also present in
        the remote branch (our push/pull location)?

        Return (True, <cmd>) if it is missing, (False, <cmd>) if it is not
        """
        cmd = 'bzr missing -q --mine-only'
        retcode, missing, ignore = utils.get_cmd_data(cmd, env=env,
                                                      fold_stderr=True,
                                                      fail_nonzero=False)
        return missing, cmd

    def revision_to_checkout(self, repo, co_leaf, options, force=False, verbose=True):
        """
        Determine a revision id for this checkout, usable to check it out again.

        * 'co_leaf' should be the name of this checkout directory, for use
          in messages reporting what we are doing. Note that we are called
          already *in* that directory, though.

        If 'force' is true, then if we can't get one from bzr, and it seems
        "reasonable" to do so, use the original revision from the muddle
        depend file (if it is not HEAD).

        'bzr revno' always returns a simple integer (or so I believe)

        'bzr version-info' returns several lines, including::

              revision-id: <something>
              revno: <xxx>

        where <xxx> is the same number as 'bzr revno', and <something>
        will be different depending on whether we're "the same" as the
        far repository.

        If the --check-clean flag is used, then there will also be a line
        of the form::

              clean: True

        indicating whether the source tree contains uncommitted changes
        (although not whether it is matching the far repository).

        So ideally we would (1) grumble if not clean, and (2) grumble
        if our revision id was different than after the last
        push/pull/checkout

        Well, 'bzr missing' should show unmerged/unpulled revisions
        between two branches, so if it ends "Branches are up to date"
        then that may be useful. Or no output with '-q' if they're OK.
        (needs to ignore stderr output, since I get that for mismatch
        in Bazaar network protocols)
        """

        env = self._derive_env()

        if repo.revision:
            orig_revision = repo.revision
        else:
            orig_revision = 'HEAD'

        # So, have we checked everything in?
        ok, cmd, txt = self._all_checked_in(env)
        if not ok:
            if force:
                print "'%s' reports checkout '%s' has uncommitted data" \
                        " (ignoring it)"%(cmd, co_leaf)
            else:
                raise utils.GiveUp("%s: '%s' reports"
                        " checkout has uncommitted data"%(cmd, co_leaf))

        # So, is our current revision (on this local branch) also present
        # in the remote branch (our push/pull location)?
        missing, cmd = self._current_revision_missing(env)
        if missing:
            missing = missing.strip()
            if missing == 'bzr: ERROR: No peer location known or specified.':
                # This presumably means that they have never pushed since
                # the original checkout
                if force:
                    if all([x.isdigit() for x in orig_revision]):
                        if verbose:
                            print missing
                            print 'Using original revision: %s'%orig_revision
                        return orig_revision
                    else:
                        raise utils.GiveUp("%s: 'bzr missing' says '%s',\n"
                                            "    and original revision is '%s', so"
                                            " cannot use that"%(co_leaf,
                                                                missing[5:],
                                                                orig_revision))
                else:
                    raise utils.GiveUp("%s: 'bzr missing' says '%s',\n"
                                        "    so cannot determine revision"%(co_leaf,
                                                                            missing[5:]))
            #elif missing.startswith("cannot import name install_lazy_named_hook"):
            #    print 'bzr says:'
            #    lines = missing.split('\n')
            #    for line in lines:
            #        print '   ', line
            #    print 'Assuming this is a problem with bzr itself, and ignoring it'
            #    print '(This is a horrible hack, until I find a better way round)'
            else:
                raise utils.GiveUp("%s: 'bzr missing' suggests checkout does"
                                    " not match the remote repository:\n%s"%(co_leaf,
                                    utils.indent(missing,'    ')))

        # So, let's get our revision number - where we are in the history
        # of the current branch
        retcode, revno, ignore = utils.get_cmd_data('bzr revno', env=env)
        revno = revno.strip()
        if all([x.isdigit() for x in revno]):
            return revno
        else:
            raise utils.GiveUp("%s: 'bzr revno' reports checkout has revision"
                    " '%s', which is not an integer"%(co_leaf, revno))

    def allows_relative_in_repo(self):
        return False

    def get_file_content(self, url, options, verbose=True):
        """
        Retrieve a file's content via BZR.
        """
        retcode, text, ignore = utils.get_cmd_data('bzr cat %s'%self._normalised_repo(url),
                                                    fold_stderr=False, verbose=verbose)
        return text

    def get_vcs_special_files(self):
        return ['.bzr', '.bzrignore']

# Tell the version control handler about us..
register_vcs_handler("bzr", Bazaar(), __doc__)

# End file.
