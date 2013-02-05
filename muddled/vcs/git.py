"""
Muddle suppport for Git.

TODO: The following needs rewriting after work for issue 225

* muddle checkout

  Clones the appropriate checkout with ``git clone``. Honours a requested
  branch (with ``-b <branch>``, defaulting to "master"), and a requested
  revision.

* muddle pull, muddle push-upstream

  This does a ``git fetch`` followed by a fast-forwards ``git merge``.

  If a revision is specified that is not "HEAD", then this will give up, since
  ``git merge`` always merges to "HEAD".

  If there are any local changes uncommitted, or untracked files, then this
  will give up. Also, if the checkout is marked as "shallow', this will give
  up.

  The command checks that the remote is configured as such, then does ``git
  fetch`` and then does ``git merge --ff-only`` - i.e., it will only merge in
  the fetch if it doesn't require human interaction.

* muddle push, muddle push-upstream

  If the checkout is marked as "shallow', this will give up.

  The command checkts that the remote is configured as such, then does ``git
  push``, honouring any branch.

* muddle merge

  This is essentially identical to "muddle pull", except that it does a simple
  ``git merge``, allowing human interaction if necessary.

* muddle commit

  Simply runs ``git commit -a``.

* muddle status

  This first does ``git status --porcelain``. If that does not return anything,
  it then determines the SHA1 for the local HEAD, and the SHA1 for the
  equivalent HEAD in the remote repository. If these are different (so
  presumably the remote repository is ahead of the local one), then it reports
  as much,

* muddle reparent

  Sets the fetch URL to be the current repository URL. XXX What else?

Available git specific options are:

* shallow_checkout: If True, then only clone to a depth of 1 (i.e., pass
  the git switch "--depth 1"). If False, then no effect. The default is
  False.

  This is typically of use when cloning the Linux kernel (or some other
  large tree with a great deal of history), when one is not expecting to
  modify the checkout in any way in the future (i.e., neither to push it
  nor to pull it again).

  If 'shallow_checkout' is specified, then "muddle pull", "muddle merge"
  and "muddle push" will refuse to do anything.
"""

import os
import re

import muddled.utils as utils
from muddled.version_control import register_vcs, VersionControlSystem
from muddled.withdir import Directory

g_supports_ff_only = None

def git_supports_ff_only():
    """
    Does my git support --ff-only?
    """
    global g_supports_ff_only

    if (g_supports_ff_only is None):
        retcode, stdout, stderr = utils.run_cmd_for_output("git --version", useShell = True)
        version = stdout
        m = re.search(r' ([0-9]+)\.([a0-9]+)', version)
        if (int(m.group(1)) <= 1 and int(m.group(2)) <= 6):
            # As of Jun 2012, that's 2 years ago - when do we drop this support?
            g_supports_ff_only = False
        else:
            g_supports_ff_only = True

    return g_supports_ff_only


class Git(VersionControlSystem):
    """
    Provide version control operations for Git
    """

    def __init__(self):
        self.short_name = 'git'
        self.long_name = 'Git'

    def init_directory(self, verbose=True):
        """
        If the directory does not appear to have had '<vcs> init' run in it,
        then do so first.

        Will be called in the actual checkout's directory.
        """
        # This is *really* hacky...
        if not os.path.exists('.git'):
            utils.run_cmd("git init", verbose=verbose)

    def add_files(self, files=None, verbose=True):
        """
        If files are given, add them, but do not commit.

        Will be called in the actual checkout's directory.
        """
        if files:
            utils.run_cmd("git add %s"%' '.join(files), verbose=verbose)

    def checkout(self, repo, co_leaf, options, verbose=True):
        """
        Clone a given checkout.

        Will be called in the parent directory of the checkout.

        Expected to create a directory called <co_leaf> therein.
        """
        if repo.branch:
            args = "-b %s"%repo.branch
        else:
            # Explicitly use master if no branch specified - don't default
            args = "-b master"

        if options.get('shallow_checkout'):
            args="%s --depth 1"%args

        utils.run_cmd("git clone %s %s %s"%(args, repo.url, co_leaf), verbose=verbose)

        if repo.revision:
            with Directory(co_leaf):
                # XXX Arguably, should use '--quiet', to suppress the warning
                # XXX that we are ending up in 'detached HEAD' state, since
                # XXX that is rather what we asked for...
                # XXX Or maybe we want to leave the message, as the warning
                # XXX it is meant to be
                utils.run_cmd("git checkout %s"%repo.revision)

    def _is_it_safe(self):
        """
        No dentists here...

        Raise an exception if there are (uncommitted) local changes or
        untracked files...
        """
        retcode, text, ignore = utils.get_cmd_data("git status --porcelain",
                                                   fail_nonzero=False)
        if retcode == 129:
            print "Warning: Your git does not support --porcelain; you should upgrade it."
            retcode, text, ignore = utils.get_cmd_data("git status", fail_nonzero=False)
            if text.find("working directory clean") >= 0:
                text = ''

        if text:
            raise utils.GiveUp("There are uncommitted changes/untracked files\n"
                                "%s"%utils.indent(text,'    '))

    def _shallow_not_allowed(self, options):
        """Checks to see if the current checkout is shallow, and refuses if so.

        Must only be called from the checkout directory.
        """
        if options.get('shallow_checkout'):
            if os.path.exists('.git/shallow'):
                raise utils.Unsupported('Shallow checkouts cannot interact with their upstream repositories.')


    def _pull_or_merge(self, repo, options, upstream=None, verbose=True, merge=False):
        """
        Will be called in the actual checkout's directory.
        """
        starting_revision = self._git_rev_parse_HEAD()

        if merge:
            cmd = 'merge'
        else:
            cmd = 'pull'

        if repo.revision and repo.revision == starting_revision:

            # XXX We really only want to grumble here if an unfettered pull
            # XXX would take us past this revision - if it would have had
            # XXX no effect, it seems a bit unfair to complain.
            # XXX So ideally we'd check here with whatever is currently
            # XXX fetched, and then (if necessary) check again further on
            # XXX after actually doing a fetch. But it's not obvious how
            # XXX to do this, so I shall ignore it for the moment...
            #
            # XXX (checking HEAD against FETCH_HEAD may or may not be
            # XXX helpful)

            # It's a bit debatable whether we should raise GiveUp or just
            # print the message and return. However, if we just printed, the
            # "report any problems" mechanism in the "muddle pull" command
            # would not know to mention this happening, which would mean that
            # for a joint pull of many checkouts, such messages might get lost.
            # So we'll go with (perhaps) slightly overkill approach.
            raise utils.GiveUp(\
                "The build description specifies revision %s... for this checkout,\n"
                "and it is already at that revision. 'muddle %s' will not take the\n"
                "checkout past the specified revision."%(repo.revision[:8], cmd))

        # Refuse to do anything if there are any local changes or untracked files.
        self._is_it_safe()

        # Refuse to do anything if this was a shallow checkout
        self._shallow_not_allowed(options)

        # Are we on the correct branch?
        this_branch = self.get_current_branch()
        if repo.branch is None:
            if this_branch != 'master':
                self.goto_branch('master')
        elif repo.branch != this_branch:
            self.goto_branch(repo.branch)

        if not upstream:
            # If we're not given an upstream repository name, assume we're
            # dealing with an "ordinary" pull, from our origin
            upstream = 'origin'

        self._setup_remote(upstream, repo, verbose=verbose)

        # Retrieve changes from the remote repository to the local repository
        utils.run_cmd("git fetch %s"%upstream, verbose=verbose)

        if repo.branch is None:
            remote = 'remotes/%s/master'%(upstream)
        else:
            remote = 'remotes/%s/%s'%(upstream,repo.branch)

        if repo.revision:
            # If the build description specifies a particular revision, all we
            # can really do is go to that revision (we did the fetch anyway in
            # case the user had edited the build descrtiption to refer to a
            # revision id we had not yet reached).
            #
            # This may also be a revision specified in an "unstamp -update"
            # operation, which is why the message doesn't say it's the build
            # description we're obeying
            print '++ Just changing to the revision explicitly requested for this checkout'
            utils.run_cmd("git checkout %s"%repo.revision)
        elif merge:
            # Just merge what we fetched into the current working tree
            utils.run_cmd("git merge %s"%remote, verbose=verbose)
        else:
            # Merge what we fetched into the working tree, but only if this is
            # a fast-forward merge, and thus doesn't require the user to do any
            # thinking.
            # Don't specify branch name: we definitely want to update our idea
            # of where the remote head points to be updated.
            # (See git-pull(1) and git-fetch(1): "without storing the remote
            # branch anywhere locally".)
            if (git_supports_ff_only()):
                utils.run_cmd("git merge --ff-only %s"%remote, verbose=verbose)
            else:
                utils.run_cmd("git merge --ff %s"%remote, verbose=verbose)

        ending_revision = self._git_rev_parse_HEAD()

        # So, did we update things?
        return starting_revision != ending_revision

    def pull(self, repo, options, upstream=None, verbose=True):
        """
        Pull changes from 'repo' into the local repository and working tree.

        Will be called in the actual checkout's directory.

        Broadly, does a 'git fetch' followed by a fast-forward merge - so it
        will only merge if it is obvious how to do it.

        If the build description specifies a particular revision, then if it
        was already at that revision, nothing needs doing. Otherwise, the
        'git fetch' is done and then the specified revision is checked out
        using 'git checkout'.
        """
        return self._pull_or_merge(repo, options,
                                   upstream=upstream, verbose=verbose,
                                   merge=False)

    def merge(self, repo, options, verbose=True):
        """
        Merge changes from 'repo' into the local repository and working tree.

        Will be called in the actual checkout's directory.

        Broadly, does a 'git fetch' followed by a merge. Be aware that this
        last may require user interaction.

        If a fast-forward merge is possible, then this identical to doing
        a "muddle pull".

        If the build description specifies a particular revision, then if it
        was already at that revision, nothing needs doing. Otherwise, the
        'git fetch' is done and then the specified revision is checked out
        using 'git checkout'.
        """
        return self._pull_or_merge(repo, options,
                                   upstream=None, verbose=verbose,
                                   merge=True)

    def commit(self, repo, options, verbose=True):
        """
        Will be called in the actual checkout's directory.

        Does 'git commit -a' - i.e., this implicitly does 'git add' for you.
        This is a contentious choice, and needs review.
        """
        utils.run_cmd("git commit -a", verbose=verbose)

    def push(self, repo, options, upstream=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        XXX Should we grumble if the 'effective' branch is not the same as
        XXX the branch that is currently checked out?
        """
        self._shallow_not_allowed(options)

        if self._is_detached_HEAD():
            raise utils.GiveUp('This checkout is in "detached HEAD" state, it is not\n'
                         'on any branch, and thus "muddle push" is not alllowed.\n'
                         'If you really want to push, first choose a branch,\n'
                         'e.g., "git checkout -b <new-branch-name>"')

        if repo.branch:
            effective_branch = repo.branch
        else:
            # Explicitly push master if nothing else is specified.
            # This is so that the user sees what we're doing, instead of
            # being potentially confused by git's config hiding non-default
            # behaviour.
            effective_branch = "master"

        if not upstream:
            # If we're not given an upstream repository name, assume we're
            # dealing with an "ordinary" push, to our origin
            upstream = 'origin'

        # For an upstream, we won't necessarily have the remote in our
        # configuration (unless we already did an upstream pull from the same
        # repository...)
        self._setup_remote(upstream, repo, verbose=verbose)

        utils.run_cmd("git push %s %s"%(upstream, effective_branch), verbose=verbose)

    def status(self, repo, options):
        """
        Will be called in the actual checkout's directory.

        Return status text or None if there is no interesting status.
        """
        retcode, text, ignore = utils.get_cmd_data("git status --porcelain",
                                                   fail_nonzero=False)
        if retcode == 129:
            print "Warning: Your git does not support --porcelain; you should upgrade it."
            retcode, text, ignore = utils.get_cmd_data("git status", fail_nonzero=False)

        detached_head = self._is_detached_HEAD()

        if detached_head:
            # That's all the user really needs to know
            note = '\n# Note that this checkout has a detached HEAD'
            if text:
                text = '%s\n#%s'%(text, note)
            else:
                text = note

        if text:
            return text

        # git status will tell us if there uncommitted changes, etc., or if
        # we are ahead of or behind (the local idea of) the remote repository,
        # but it cannot tell us if the remote repository is behind us (and our
        # local idea of it).

        if detached_head:
            head_name = 'HEAD'
        else:
            # First, find out what our HEAD actually is
            retcode, text, ignore = utils.get_cmd_data("git rev-parse --symbolic-full-name HEAD")
            head_name = text.strip()

        # Now we can look up its SHA1, locally
        retcode, head_revision, ignore = utils.get_cmd_data("git rev-parse %s"%head_name)
        local_head_ref = head_revision.strip()

        # So look up the remote equivalents...
        retcode, text, ignore = utils.get_cmd_data("git ls-remote",
                                                   fail_nonzero=False)
        lines = text.split('\n')
        if retcode:
            # Oh dear - something nasty happened
            # We know we get this if, for instance, the remote repository does
            # not actually exist
            newlines = []
            newlines.append('Whilst trying to check local HEAD against remote HEAD')
            for line in lines:
                newlines.append('# %s'%line)
            return '\n'.join(newlines)
        else:
            for line in lines[1:]:          # The first line is the remote repository
                if not line:
                    continue
                ref, what = line.split('\t')
                if what == head_name:
                    if ref != local_head_ref:
                        return '\n'.join(('After checking local HEAD against remote HEAD',
                                          '# The local repository does not match the remote:',
                                          '#',
                                          '#  HEAD   is %s'%head_name,
                                          '#  Local  is %s'%local_head_ref,
                                          '#  Remote is %s'%ref,
                                          '#',
                                          '# You probably need to pull with "muddle pull".'))

        # Should we check to see if we found HEAD?

        return None

    def _setup_remote(self, remote_name, remote_repo, verbose=True):
        """
        Re-associate the local repository with a remote.

        Makes some attempt to only do this if necessary. Of course, that may
        actually be slower than just always doing it...
        """
        need_to_set_url = False
        # Are there actually any values already stored for this remote?
        retcode, out, ignore = utils.get_cmd_data("git config --get-regexp remote.%s.*"%remote_name,
                                                  fail_nonzero=False)
        if retcode == 0:    # there were
            # Were the URLs OK?
            for line in out.split('\n'):
                if not line:
                    continue
                parts = line.split()
                if parts[0].endswith('url'):    # .url, .pushurl
                    url = ' '.join(parts[1:])   # are spaces allowed in our url?
                    if url != str(remote_repo):
                        need_to_set_url = True
                        break
            if need_to_set_url:
                # We don't want to do this unless it is necessary, because it
                # will give an error if there is nothing for it to remove
                utils.run_cmd("git remote rm %s"%remote_name, verbose=verbose, allowFailure=True)
        else:               # there were not
            need_to_set_url = True

        if need_to_set_url:
            # 'git remote add' sets up remote.origin.fetch and remote.origin.url
            # which are the minimum we should need
            utils.run_cmd("git remote add %s %s"%(remote_name, remote_repo), verbose=verbose)

    def reparent(self, co_dir, remote_repo, options, force=False, verbose=True):
        """
        Re-associate the local repository with its original remote repository,
        """
        if verbose:
            print "Re-associating checkout '%s' with remote repository"%co_dir

        # This is the special case where our "remote" is our origin...
        self._setup_remote('origin', remote_repo, verbose=verbose)

    def _git_status_text_ok(self, text):
        """
        Is the text returned by 'git status -q' probably OK?
        """
        # The bit in the middle is the branch name
        # - typically "master" or "astb/master" (for branch "astb")
        return text.startswith('# On branch') and \
               text.endswith('\nnothing to commit (working directory clean)')

    def _git_describe_long(self, co_leaf, orig_revision, force=False, verbose=True):
        """
        This returns a "pretty" name for the revision, but only if there
        are annotated tags in its history.
        """
        retcode, revision, ignore = utils.get_cmd_data('git describe --long',
                                                       fail_nonzero=False)
        if retcode:
            if revision:
                text = utils.indent(revision.strip(),'    ')
                if force:
                    if verbose:
                        print "'git describe --long' had problems with checkout" \
                              " '%s'"%co_leaf
                        print "    %s"%text
                        print "using original revision %s"%orig_revision
                    return orig_revision
            else:
                text = '    (it failed with return code %d)'%retcode
            raise utils.GiveUp("%s\n%s"%(utils.wrap("%s: 'git describe --long'"
                " could not determine a revision id for checkout:"%co_leaf),
                text))
        return revision.strip()

    def _is_detached_HEAD(self):
        """
        Detect if the current checkout is 'detached HEAD'
        """
        # This is a documented usage of 'git symbolic-ref -q HEAD'
        retcode, out, err = utils.get_cmd_data('git symbolic-ref -q HEAD', fail_nonzero=False)
        if retcode == 0:
            # HEAD is a symbolic reference - so not detached
            return False
        elif retcode == 1:
            # HEAD is not a symbolic reference, but a detached HEAD
            return True
        else:
            raise utils.GiveUp('Error running "git symbolic-ref -q HEAD" to detect detached HEAD')

    def supports_branching(self):
        return True

    def get_current_branch(self):
        """
        Return the name of the current branch.

        Will be called in the actual checkout's directory.

        Returns None if we are not on a branch (e.g., a detached HEAD)
        """
        retcode, out, err = utils.get_cmd_data('git symbolic-ref -q HEAD', fail_nonzero=False)
        if retcode == 0:
            out = out.strip()
            if out.startswith('refs/heads'):
                return out[11:]
            else:
                return None
        elif retcode == 1:
            # HEAD is not a symbolic reference, but a detached HEAD
            return None
        else:
            raise utils.GiveUp('Error running "git symbolic-ref -q HEAD" to determine current branch')

    def create_branch(self, branch):
        """
        Create a branch of the given name.

        Will be called in the actual checkout's directory.

        Also sets up the equivalent remote.

        It is an error if the branch already exists, in which case a GiveUp
        exception will be raised.
        """
        # If the user tried "git branch 'sp ace'", which is an illegal branch
        # name, we want the command to propagate 'sp ace' down as a single
        # word, so it gets reported with the appropriate error. Thus we need
        # to pass the command as a list.
        retcode, out, err = utils.run_cmd_for_output(['git', 'branch', branch], fold_stderr=True)
        if retcode:
            raise utils.GiveUp('Error creating branch "%s": %s'%(branch, out))

        # Add this branch to the 'origin' remote for this checkout
        utils.run_cmd("git remote set-branches --add origin %s"%branch)

    def goto_branch(self, branch):
        """
        Make the named branch the current branch.

        Will be called in the actual checkout's directory.

        It is an error if the branch does not exist, in which case a GiveUp
        exception will be raised.
        """
        retcode, out, err = utils.run_cmd_for_output(['git', 'checkout', branch], fold_stderr=True)
        if retcode:
            raise utils.GiveUp('Error going to branch "%s": %s'%(branch, out))

    def goto_revision(self, revision, branch=None):
        """
        Make the specified revision current.

        Note that this may leave the working data (the actual checkout
        directory) in an odd state, in which it is not sensible to
        commit, depending on the VCS and the revision.

        Will be called in the actual checkout's directory.

        If a branch name is given, it will be ignored.

        Raises GiveUp if there is no such revision, or no such branch.
        """
        retcode, out, err = utils.run_cmd_for_output(['git', 'checkout', revision], fold_stderr=True)
        if retcode:
            raise utils.GiveUp('Error going to revision "%s": %s'%(revision, out))

    def branch_exists(self, branch):
        """
        Is there a branch of this name?

        Will be called in the actual checkout's directory.
        """
        retcode, out, err = utils.get_cmd_data('git branch -a', fail_nonzero=False)
        if retcode:
            raise utils.GiveUp('Error looking up existing branches: %s'%out)

        lines = out.split('\n')
        for line in lines:
            text = line[2:]         # Ignore the initial '  ' or '* '
            text = text.strip()     # Ignore trailing whitespace
            if '->' in text:        # Ignore 'remotes/origin/HEAD -> origin/master'
                continue
            if '/' in text:
                text = text.split('/')[-1]  # just take the name at the end
            if text == branch:
                return True
        return False

    def _git_rev_parse_HEAD(self):
        """
        This returns a bare SHA1 object name for the current revision
        """
        retcode, revision, ignore = utils.get_cmd_data('git rev-parse HEAD',
                                                       fail_nonzero=False)
        if retcode:
            raise utils.GiveUp("'git rev-parse HEAD' failed with return code %d"%retcode)
        return revision.strip()

    def _calculate_revision(self, co_leaf, orig_revision, force=False,
                            before=None, verbose=True):
        """
        This returns a bare SHA1 object name for the current revision

        NB: if 'before' is specified, 'force' is ignored.
        """
        if before:
            print "git rev-list -n 1 --before='%s' HEAD"%before
            retcode, revision, ignore = utils.get_cmd_data("git rev-list -n 1 --before='%s' HEAD"%before,
                                                           fail_nonzero=False)
            print retcode, revision
            if retcode:
                if revision:
                    text = utils.indent(revision.strip(),'    ')
                else:
                    text = '    (it failed with return code %d)'%retcode
                raise utils.GiveUp("%s\n%s"%(utils.wrap("%s:"
                    " \"git rev-list -n 1 --before='%s' HEAD\"'"
                    " could not determine a revision id for checkout:"%(co_leaf, before)),
                    text))
        else:
            retcode, revision, ignore = utils.get_cmd_data('git rev-parse HEAD',
                                                           fail_nonzero=False)
            if retcode:
                if revision:
                    text = utils.indent(revision.strip(),'    ')
                    if force:
                        if verbose:
                            print "'git rev-parse HEAD' had problems with checkout" \
                                  " '%s'"%co_leaf
                            print "    %s"%text
                            print "using original revision %s"%orig_revision
                        return orig_revision
                else:
                    text = '    (it failed with return code %d)'%retcode
                raise utils.GiveUp("%s\n%s"%(utils.wrap("%s: 'git rev-parse HEAD'"
                    " could not determine a revision id for checkout:"%co_leaf),
                    text))
        return revision.strip()

    def revision_to_checkout(self, repo, co_leaf, options, force=False, before=None, verbose=True):
        """
        Determine a revision id for this checkout, usable to check it out again.

        a) Document
        b) Review the code to see if we now support versions of git that  would
           allow us to do this more sensibly

        If 'before' is given, it should be a string describing a date/time, and
        the revision id chosen will be the last revision at or before that
        date/time.

        NB: if 'before' is specified, 'force' is ignored.

        XXX TODO: Needs reviewing given we're using a later version of git now
        """
        # Later versions of git allow one to give a '--short' switch to
        # 'git status', which would probably do what I want - but the
        # version of git in Ubuntu 9.10 doesn't have that switch. So
        # we're reduced to looking for particular strings - and the git
        # documentation says that the "long" texts are allowed to change

        # Earlier versions of this command line used 'git status -q', but
        # the '-q' switch is not present in git 1.7.0.4

        if repo.revision:
            orig_revision = repo.revision
        else:
            orig_revision = 'HEAD'

        ### I think that it is not useful to do the following check...
        ##retcode, text, ignore = utils.get_cmd_data('git status', fail_nonzero=False)
        ##text = text.strip()
        ##if not self._git_status_text_ok(text):
        ##    raise utils.GiveUp("%s\n%s"%(utils.wrap("%s: 'git status' suggests"
        ##        " checkout does not match master:"%co_leaf),
        ##        utils.indent(text,'    ')))
        if False:
            # Should we try this first, and only "fall back" to the pure
            # SHA1 object name if it fails, or is the pure SHA1 object name
            # better?
            try:
                revision = self._git_describe_long(co_leaf, orig_revision, force, verbose)
            except utils.GiveUp:
                revision = self._calculate_revision(co_leaf, orig_revision, force, verbose)
        else:
            revision = self._calculate_revision(co_leaf, orig_revision, force,
                                                before, verbose)
        return revision

    def allows_relative_in_repo(self):
        """TODO: Check that this is correct!
        """
        return False

    def get_vcs_special_files(self):
        return ['.git', '.gitignore', '.gitmodules']

    # I can't see any way to do 'get_file_content', but this needs
    # reinvestigating periodically

# Tell the version control handler about us..
register_vcs("git", Git(), __doc__, ["shallow_checkout"])

# End file.
