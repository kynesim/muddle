"""
Muddle support for Bazaar.

.. to be documented ..

Note that Bazaar does not support "branches" in the muddle sense. Bazaar
itself uses the "bzr branch" command to make a clone of a repository. It
does not (or did not at time of writing) support lightweight branching in
the manner of git - i.e., separate branches stored within the same clone.
Thus the "branch" argument of a Repository class is not supported for
Bazaar.

Available Bazaar specific options are:

* no_follow: In a build description that has set::

    builder.follow_build_desc_branch = True

  then a Bazaar repository can either:

      1. Specify a particular revision
      2. Choose a different repository location (presumably a bazaar
         "branch"), and set the no_follow option to True
      3. Continue using the original repository without setting a revision
         (almost certainly not sensible, but still), and set the no_follow
         option to True.

  If none of these are done, then muddle will fail with a complaint like::

    The build description wants checkouts to follow branch '<branch-name>',
    but checkout <co-name> uses VCS Bazaar for which we do not support branching.
    The build description should specify a revision for checkout <co-name>.

"""

import os
import re

from muddled.version_control import register_vcs, VersionControlSystem
import muddled.utils as utils

class Bazaar(VersionControlSystem):
    """
    Provide version control operations for Bazaar
    """

    def __init__(self):
        self.short_name = 'bzr'
        self.long_name = 'Bazaar'
        self.allowed_options.add('no_follow')

    def _run2(self, cmd, env=None, verbose=False):
        """Run command, prune output, return return code and output.
        """
        rc, output = utils.run2(cmd, env=env, show_command=verbose)
        return rc, self._prune_spurious_bzr_output(output)

    def _run1(self, cmd, env=None, verbose=False, fold_stderr=True):
        """Run command, prune output, return just that.

        If fold_stderr is False, then ignore any stderr output.
        """
        if fold_stderr:
            rc, output = utils.run2(cmd, env=env, show_command=verbose)
        else:
            rc, output, errors = utils.run3(cmd, env=env, show_command=verbose)
        if rc:
            raise utils.ShellError(cmd, rc, output)
        else:
            return self._prune_spurious_bzr_output(output)

    def _prune_spurious_bzr_output(self, in_str):
        """
        Sanitise the output of a bzr command by removing warnings which
        bzr will happily produce despite being told to be quiet, but
        which are in fact a tale told by an idiot, full of sound and
        fury, signifying nothing.
        """
        # If you downloaded your bazaar it may report that compiled 
        # extensions couldn't be loaded; this doesn't mean your repo doesn't
        # match.
        lines = in_str.split('\n')
        rv = [ ]
        my_re = re.compile(".*some compiled extensions")
        for l in lines:
            if (not my_re.match(l)):
                rv.append(l)
        out_str = "\n".join(rv)
        return out_str

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
            utils.shell("bzr init", env=self._derive_env(), show_command=verbose)

    def add_files(self, files=None, verbose=True):
        """
        If files are given, add them, but do not commit.

        Will be called in the actual checkout's directory.
        """
        if files:
            utils.shell("bzr add %s"%' '.join(files))

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

        if repo.branch:
            raise utils.GiveUp("Bazaar does not support branch (in the muddle sense)"
                               " in 'checkout' (branch='%s')"%repo.branch)
        utils.shell("bzr branch %s %s %s"%(self._r_option(repo.revision),
                                          self._normalised_repo(repo.url),
                                          co_leaf),
                   env=self._derive_env(), show_command=verbose)

    def _is_it_safe(self, env):
        """
        No dentists here...

        Raise an exception if there are (uncommitted) local changes.
        """
        ok, cmd, txt = self._all_checked_in(env)
        if not ok:
            raise utils.GiveUp("There are uncommitted changes")

    def pull(self, repo, options, upstream=None, verbose=True):
        """
        Pull changes, but don't do a merge.

        Will be called in the actual checkout's directory.
        """
        if repo.branch:
            raise utils.GiveUp("Bazaar does not support branch (in the muddle sense)"
                               " in 'pull' (branch='%s')"%repo.branch)

        rspec = self._r_option(repo.revision)

        # Refuse to pull if there are any local changes
        env = self._derive_env()
        self._is_it_safe(env)

        starting_revno = self._just_revno()

        text = self._run1("bzr pull %s %s"%(rspec, self._normalised_repo(repo.url)),
                          env=env, verbose=verbose)
        print text
        if (text.startswith('No revisions to pull')  # older versions of bzr
            or
            text.startswith('No revisions or tags to pull') # bzr v2.6
           ) and repo.revision:
            # Try going back to that particular revision.
            #
            # First we 'uncommit' to take our history back. The --force answers
            # 'yes' to all questions (otherwise the user would be prompted as
            # to whether they really wanted to do this operation
            retcode, text = self._run2("bzr uncommit --force --quiet %s"%rspec,
                                       env=env, verbose=verbose)
            if retcode:
                raise utils.GiveUp('Error uncommiting to revision %s (we already tried'
                                   ' pull)\nReturn code  %d\n%s'%(rspec, retcode, text))
            print text
            # Then we need to 'revert' to undo any changes (since uncommit
            # doesn't change our working set). The --no-backup stops us
            # being left with copies of the changes in backup files (which
            # is exactly what we don't want)
            retcode, text = self._run2("bzr revert --no-backup %s"%rspec,
                                       env=env, verbose=verbose)
            if retcode:
                raise utils.GiveUp('Error reverting to revision %s (we already'
                                   ' uncommitted)\nReturn code %d\n%s'%(rspec, retcode, text))
            print text

        ending_revno = self._just_revno()
        # Did we update anything?
        return starting_revno != ending_revno

    def merge(self, other_repo, options, verbose=True):
        """
        Merge 'other_repo' into the local repository and working tree,

        'bzr merge' will not (by default) merge if there are uncommitted changes
        in the destination (i.e., local) tree. This is what we want.

        Will be called in the actual checkout's directory.
        """
        if other_repo.branch:
            raise utils.GiveUp("Bazaar does not support branch (in the muddle sense)"
                               " in 'merge' (branch='%s')"%other_repo.branch)

        # Refuse to pull if there are any local changes
        env = self._derive_env()
        self._is_it_safe(env)

        rspec = self._r_option(other_repo.revision)

        starting_revno = self._just_revno()

        utils.shell("bzr merge %s %s"%(rspec, self._normalised_repo(other_repo.url)),
                   env=env, show_command=verbose)

        ending_revno = self._just_revno()
        # Did we update anything?
        return starting_revno != ending_revno

    def commit(self, repo, options, verbose=True):
        """
        Will be called in the actual checkout's directory.
        """
        # Options: --strict means it will not commit if there are unknown
        # files in the working tree
        utils.shell("bzr commit", allowFailure=True,
                   env=self._derive_env(), show_command=verbose)

    def push(self, repo, options, upstream=None, verbose=True):
        """
        Will be called in the actual checkout's directory.
        """

        utils.shell("bzr push %s"%self._normalised_repo(repo.url),
                   env=self._derive_env(), show_command=verbose)

    def status(self, repo, options=None, branch=None, verbose=False, quick=False):
        """
        Will be called in the actual checkout's directory.

        Return status text or None if there is no interesting status.
        """
        env = self._derive_env()

        #just return an error message, don't check anything
        if quick:
            return "muddle status -quick is not supported on bzr checkouts"

        # --quiet means only report warnings and errors
        cmd = 'bzr status --quiet -r branch:%s'%self._normalised_repo(repo.url),

        text = self._run1(cmd, env=env, fold_stderr=False)
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

    def goto_revision(self, revision, branch=None, repo=None, verbose=False):
        """
        Make the specified revision current.

        Note that this may leave the working data (the actual checkout
        directory) in an odd state, in which it is not sensible to
        commit, depending on the VCS and the revision.

        Will be called in the actual checkout's directory.

        Raises GiveUp if there is no such revision, or if a branch is given.
        """
        if branch:
            raise utils.GiveUp("Bazaar does not support branch (in the muddle sense), branch=%s"%branch)

        if not repo:
            raise utils.MuddleBug("Bazaar needs a Repository instance to do goto_revision()");

        # Luckily, our pull method does more-or-less what we want
        repo = repo.copy_with_changed_revision(revision)
        self.pull(repo, None, verbose=verbose)

    def _all_checked_in(self, env):
        """
        Do we have anything that is not yet checked in?

        Returns (True, <cmd>, None) if everything appears OK,
        (False, <cmd>, <text>) if not, where <cmd> is the BZR command used, and
        <text> is its output.
        """
        cmd = 'bzr version-info --check-clean'
        text = self._run1(cmd, env=env, fold_stderr=False)
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
        # We don't want to fail if we get a non-zero return code
        retcode, missing = self._run2(cmd, env=env)
        return missing, cmd

    def _revision_id(self, env, revspec):
        """Find the revision id for revision 'revspec'
        """
        cmd = "bzr log -l 1 -r '%s' --long --show-ids"%revspec
        retcode, text = self._run2(cmd, env=env)
        if retcode != 0:
            raise utils.GiveUp("'%s' failed with return code %d\n%s"%(cmd, retcode, text))
        # Let's look for the revision-id field therein

        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            parts = line.split(':')
            if parts[0] == 'revision-id':
                revision = ':'.join(parts[1:]) # although I hope there aren't internal colons!

                return revision.strip()
        raise utils.GiveUp("'%s' did not return text containing 'revision-id:'"
                           "\n%s"%(cmd, text))

    def revision_to_checkout(self, repo, co_leaf, options, force=False, before=None, verbose=True):
        """
        Determine a revision id for this checkout, usable to check it out again.

        * 'co_leaf' should be the name of this checkout directory, for use
          in messages reporting what we are doing. Note that we are called
          already *in* that directory, though.

        If 'force' is true, then if we can't get one from bzr, and it seems
        "reasonable" to do so, use the original revision from the muddle
        depend file (if it is not HEAD).

        If 'before' is given, it should be a string describing a date/time, and
        the revision id chosen will be the last revision at or before that
        date/time.

        .. note:: This depends upon what the VCS concerned actually supports.
           This feature is experimental. XXX NOT YET IMPLEMENTED XXX

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

        if before:
            # XXX For now, we're going to short-circuit everything else if we
            # XXX are asked for 'before'.
            try:
                return self._revision_id(env, 'before:date:%s'%before)
            except utils.GiveUp as e:
                raise utils.GiveUp('%s: %s'%(co_leaf, e))

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
                raise utils.GiveUp("%s: 'bzr missing' suggests this checkout revision"
                                    " is not present in the remote repository:\n%s"%(co_leaf,
                                    utils.indent(missing,'    ')))

        # So let's go with the revision id for the last commit of this local branch
        try:
            return self._revision_id(env, 'revno:-1')
        except utils.GiveUp as e:
            raise utils.GiveUp('%s: %s'%(co_leaf, e))

    def _just_revno(self):
        """
        This returns the revision number for the working tree
        """
        retcode, revision = self._run2('bzr revno --tree')
        return revision.strip()

    def allows_relative_in_repo(self):
        return False

    def get_file_content(self, url, verbose=True):
        """
        Retrieve a file's content via BZR.
        """
        retcode, text = self._run2('bzr cat %s'%self._normalised_repo(url),
                                   fold_stderr=False, verbose=verbose)
        return text

    def get_vcs_special_files(self):
        return ['.bzr', '.bzrignore']

# Tell the version control handler about us..
register_vcs("bzr", Bazaar(), __doc__)

# End file.
