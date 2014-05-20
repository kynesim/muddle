"""
Muddle suppport for Git.

TODO: The following needs rewriting after work for issue 225

* muddle checkout

  Clones the appropriate checkout with ``git clone``.

  If the build description (by whatever means) requires a branch, then
  ``git clone -b <branch>`` is used. If no branch is specified, we default to
  ``git clone -b master``.

  If a shallow checkout is selected, then the ``--depth 1`` switch is added
  to the clone command. Note that there are some restrictions on what can be
  done with a shallow checkout - git says::

      A shallow repository has a number of limitations (*you cannot clone or
      fetch from it, nor push from nor into it*), but is adequate if you are
      only interested in the recent history of a large project with a long
      history, and would want to send in fixes as patches.

  (the emphasis is mine).

  If a revision is requested, then ``git checkout`` is used to check it out.

  If a branch *and* a revision are requested, then muddle checks to see if
  cloning the branch gave the correct revision, and only does the ``git
  checkout`` if it did not. This avoids unnecessary detached HEADs,

  Note: the checking of the revision id is very simple, and assumes that
  the revision is specified as a full SHA1 string (it is compared with the
  output of ``git rev-parse HEAD``).

* muddle pull, muddle pull-upstream

  This does a ``git fetch`` followed by a fast-forwards ``git merge``.

  If the build description specifies a particular revision, and the checkout
  is already at that revision, then an error will be reported, saying that.

  If there are any local changes uncommitted, or untracked files, then
  appropriate error messages will also be reported.

  If the build description specified a branch for this repository (by whatever
  means), then we will first go to that branch. If no branch was specified,
  we first go to "master".

  The command checks that the remote is configured as such, then does ``git
  fetch``. If a revision was specified, it then checks out that revision,
  otherwise it does ``git merge --ff-only``, which will merge in the fetch if
  it doesn't require human interaction.

* muddle push, muddle push-upstream

  If the checkout is marked as "shallow', or is on a detached HEAD, then an
  appropriate error message will be given.

  The command checks that the remote is configured as such, then does ``git
  push`` of the current branch. If the branch does not exist at the far end,
  it will be created.

* muddle merge

  This is identical to "muddle pull", except that instead of doing a
  fast-forward merge, it does a simple ``git merge``, allowing human
  interaction if necessary.

* muddle commit

  Simply runs ``git commit -a``.

* muddle status

  This first does ``git status --porcelain``. If that does not return anything,
  it then determines the SHA1 for the local HEAD, and the SHA1 for the
  equivalent HEAD in the remote repository. If these are different (so
  presumably the remote repository is ahead of the local one), then it reports
  as much,

  Note that a normal ``git status`` does not talk to the remote repository,
  and is thus fast. If this command does talk over the network, it can be
  rather slower.

* muddle reparent

  Re-associates the local repository's "origin" with the remote repository
  indicated by the build description. It tries to detect if this is necessary
  first.

Available git specific options are:

* shallow_checkout: If True, then only clone to a depth of 1 (i.e., pass
  the git switch "--depth 1"). If False, then no effect. The default is
  False.

  This is typically of use when cloning the Linux kernel (or some other
  large tree with a great deal of history), when one is not expecting to
  modify the checkout in any way in the future (i.e., neither to push it
  nor to pull it again).

  If 'shallow_checkout' is specified, then "muddle push" will refuse to do
  anything.
"""

import os
import re

import muddled.utils as utils
from muddled.version_control import register_vcs, VersionControlSystem
from muddled.withdir import Directory
from muddled.utils import GiveUp

g_supports_ff_only = None

def git_supports_ff_only():
    """
    Does my git support --ff-only?
    """
    global g_supports_ff_only

    if (g_supports_ff_only is None):
        retcode, stdout = utils.run2("git --version", show_command=False)
        version = stdout
        m = re.search(r' ([0-9]+)\.([a0-9]+)', version)
        if (int(m.group(1)) <= 1 and int(m.group(2)) <= 6):
            # As of Jun 2012, that's 2 years ago - when do we drop this support?
            g_supports_ff_only = False
        else:
            g_supports_ff_only = True

    return g_supports_ff_only

def expand_revision(revision):
    """Given something that names a revision, return its full SHA1.

    Raises GiveUp if the revision appears non-existent or ambiguous
    """
    rv, out = utils.run2('git rev-parse %s'%revision, show_command=False)
    if rv:
        raise GiveUp('Revision "%s" is either non-existant or ambiguous'%revision)
    return out.strip()

class Git(VersionControlSystem):
    """
    Provide version control operations for Git
    """

    def __init__(self):
        self.short_name = 'git'
        self.long_name = 'Git'
        self.allowed_options.add('shallow_checkout')

    def init_directory(self, verbose=True):
        """
        If the directory does not appear to have had '<vcs> init' run in it,
        then do so first.

        Will be called in the actual checkout's directory.
        """
        # This is *really* hacky...
        if not os.path.exists('.git'):
            utils.shell(["git", "init"])

    def add_files(self, files=None, verbose=True):
        """
        If files are given, add them, but do not commit.

        Will be called in the actual checkout's directory.
        """
        if files:
            utils.shell(["git", "add"] + list(files), show_command=verbose)

    def checkout(self, repo, co_leaf, options, verbose=True):
        """
        Clone a given checkout.

        Will be called in the parent directory of the checkout.

        Expected to create a directory called <co_leaf> therein.
        """
        if repo.branch:
            args = ["-b", repo.branch]
        else:
            # Explicitly use master if no branch specified - don't default
            args = ["-b", "master"]

        if options.get('shallow_checkout'):
            args += ["--depth", "1"]

        utils.shell(["git", "clone"] + args + [repo.url, str(co_leaf)],
                   show_command=verbose)

        if repo.revision:
            with Directory(co_leaf):
                # Are we already at the correct revision?
                actual_revision = self._git_rev_parse_HEAD()
                if actual_revision != expand_revision(repo.revision):
                    # XXX Arguably, should use '--quiet', to suppress the warning
                    # XXX that we are ending up in 'detached HEAD' state, since
                    # XXX that is rather what we asked for...
                    # XXX Or maybe we want to leave the message, as the warning
                    # XXX it is meant to be
                    utils.shell(["git", "checkout", repo.revision])

    def _is_it_safe(self):
        """
        No dentists here...

        Raise an exception if there are (uncommitted) local changes or
        untracked files...
        """
        retcode, text= utils.run2("git status --porcelain", show_command=False)
        if retcode == 129:
            print "Warning: Your git does not support --porcelain; you should upgrade it."
            retcode, text = utils.run2("git status", show_command=False)
            if text.find("working directory clean") >= 0:
                text = ''

        if text:
            raise GiveUp("There are uncommitted changes/untracked files\n"
                         "%s"%utils.indent(text,'    '))

    def _shallow_not_allowed(self, options):
        """Checks to see if the current checkout is shallow, and refuses if so.

        Must only be called from the checkout directory.
        """
        if options.get('shallow_checkout'):
            if os.path.exists('.git/shallow'):
                raise utils.Unsupported('Shallow checkouts cannot push to'
                                        ' their upstream repositories.')

    def _pull_or_merge(self, repo, options, upstream=None, verbose=True, merge=False):
        """
        Will be called in the actual checkout's directory.
        """
        starting_revision = self._git_rev_parse_HEAD()

        if merge:
            cmd = 'merge'
        else:
            cmd = 'pull'

        if repo.revision:
            revision = expand_revision(repo.revision)
        else:
            revision = None

        if revision and revision == starting_revision:

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
            raise GiveUp(\
                "The build description specifies revision %s... for this checkout,\n"
                "and it is already at that revision. 'muddle %s' will not take the\n"
                "checkout past the specified revision."%(repo.revision[:8], cmd))

        # Refuse to do anything if there are any local changes or untracked files.
        self._is_it_safe()

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
        # We want to get the output from this so we can put it into any exception,
        # for instance if we try to fetch a branch that does not exist.
        # This *does* mean there's a slight delay before the user sees the output,
        # though
        cmd = "git fetch %s"%upstream
        rv, out = utils.run2(cmd, show_command=verbose)
        if rv:
            raise GiveUp('Error %d running "%s"\n%s'%(rv, cmd, out))
        else:
            # The older version of this code just used utils.run_cmd(), which
            # runs the command in a sub-shell, and thus its output is always
            # presented, regardless of the "verbose" setting. For the moment
            # at least, we'll stay compatible with that.
            print out.rstrip()

        if repo.branch is None:
            remote = 'remotes/%s/master'%(upstream)
        else:
            remote = 'remotes/%s/%s'%(upstream,repo.branch)

        if repo.revision:
            # If the build description specifies a particular revision, all we
            # can really do is go to that revision (we did the fetch anyway in
            # case the user had edited the build description to refer to a
            # revision id we had not yet reached).
            #
            # This may also be a revision specified in an "unstamp -update"
            # operation, which is why the message doesn't say it's the build
            # description we're obeying
            print '++ Just changing to the revision explicitly requested for this checkout'
            utils.shell(["git", "checkout", repo.revision])
        elif merge:
            # Just merge what we fetched into the current working tree
            utils.shell(["git", "merge", remote], show_command=verbose)
        else:
            # Merge what we fetched into the working tree, but only if this is
            # a fast-forward merge, and thus doesn't require the user to do any
            # thinking.
            # Don't specify branch name: we definitely want to update our idea
            # of where the remote head points to be updated.
            # (See git-pull(1) and git-fetch(1): "without storing the remote
            # branch anywhere locally".)
            if (git_supports_ff_only()):
                utils.shell(["git", "merge", "--ff-only", remote], show_command=verbose)
            else:
                utils.shell(["git", "merge", "--ff", remote], show_command=verbose)

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
        utils.shell(["git", "commit", "-a"], show_command=verbose)

    def push(self, repo, options, upstream=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        XXX Should we grumble if the 'effective' branch is not the same as
        XXX the branch that is currently checked out?
        """
        self._shallow_not_allowed(options)

        if self._is_detached_HEAD():
            raise GiveUp('This checkout is in "detached HEAD" state, it is not\n'
                         'on any branch, and thus "muddle push" is not alllowed.\n'
                         'If you really want to push, first choose a branch,\n'
                         'e.g., "git checkout -b <new-branch-name>"')

        # Push this branch to the branch of the same name, whether it exists
        # yet or not
        effective_branch = 'HEAD'

        if not upstream:
            # If we're not given an upstream repository name, assume we're
            # dealing with an "ordinary" push, to our origin
            upstream = 'origin'

        # For an upstream, we won't necessarily have the remote in our
        # configuration (unless we already did an upstream pull from the same
        # repository...)
        self._setup_remote(upstream, repo, verbose=verbose)

        utils.shell(["git", "push", upstream, effective_branch], show_command=verbose)

    def status(self, repo, options, quick=False):
        """
        Will be called in the actual checkout's directory.

        Return status text or None if there is no interesting status.
        """
        retcode, text = utils.run2("git status --porcelain", show_command=False)
        if retcode == 129:
            print "Warning: Your git does not support --porcelain; you should upgrade it."
            retcode, text = utils.run2("git status", show_command=False)

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

        # git status will tell us if there uncommitted changes, etc., but not if
        # we are ahead of or behind (the local idea of) the remote repository,
        # or it will, but not with --porcelain


        if detached_head:
            head_name = 'HEAD'
        else:
            # First, find out what our HEAD actually is
            retcode, text = utils.run2("git rev-parse --symbolic-full-name HEAD",
                                       show_command=False)
            head_name = text.strip()

        # Now we can look up its SHA1, locally
        retcode, head_revision = utils.run2("git rev-parse %s"%head_name,
                                            show_command=False)
        local_head_ref = head_revision.strip()

        if quick:
            branch_name = utils.get_cmd_data("git rev-parse --abbrev-ref HEAD")
            text = utils.get_cmd_data("git show-ref origin/%s"%branch_name)
            ref, what = text.split()
            if ref != local_head_ref:
                return '\n'.join(
                    ('After checking local HEAD against our local record of the remote HEAD',
                     '# The local repository does not match the remote:',
                     '#',
                     '#  HEAD   is %s'%head_name,
                     '#  Local  is %s'%local_head_ref,
                     '#  last known origin/%s is %s'%(branch_name, ref),
                     '#',
                     '# You probably need to push or pull.',
                     '# Use "muddle status" without "-quick" to get a better idea'))
            else:
                return None

        # So look up the remote equivalents...
        retcode, text = utils.run2("git ls-remote", show_command=False)
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
        retcode, out = utils.run2("git config --get-regexp remote.%s.*"%remote_name,
                                  show_command=False)
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
                utils.shell(["git", "remote", "rm", remote_name], show_command=verbose)
        else:               # there were not
            need_to_set_url = True

        if need_to_set_url:
            # 'git remote add' sets up remote.origin.fetch and remote.origin.url
            # which are the minimum we should need
            utils.shell(["git", "remote", "add", remote_name, remote_repo],
                       show_command=verbose)

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
        retcode, revision = utils.run2('git describe --long', show_command=False)
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
            raise GiveUp("%s\n%s"%(utils.wrap("%s: 'git describe --long'"
                " could not determine a revision id for checkout:"%co_leaf),
                text))
        return revision.strip()

    def _is_detached_HEAD(self):
        """
        Detect if the current checkout is 'detached HEAD'
        """
        # This is a documented usage of 'git symbolic-ref -q HEAD'
        retcode, out = utils.run2('git symbolic-ref -q HEAD', show_command=False)
        if retcode == 0:
            # HEAD is a symbolic reference - so not detached
            return False
        elif retcode == 1:
            # HEAD is not a symbolic reference, but a detached HEAD
            return True
        else:
            raise GiveUp('Error running "git symbolic-ref -q HEAD" to detect detached HEAD')

    def supports_branching(self):
        return True

    def get_current_branch(self):
        """
        Return the name of the current branch.

        Will be called in the actual checkout's directory.

        Returns None if we are not on a branch (e.g., a detached HEAD)
        """
        retcode, out = utils.run2('git symbolic-ref -q HEAD', show_command=False)
        if retcode == 0:
            out = out.strip()
            if out.startswith('refs/heads'):
                return out[11:]
            else:
                raise GiveUp('Error running "git symbolic-ref -q HEAD" to determine current branch\n  Got back "%s" instead of "refs/heads/<something>"'%out)
        elif retcode == 1:
            # HEAD is not a symbolic reference, but a detached HEAD
            return None
        else:
            raise GiveUp('Error running "git symbolic-ref -q HEAD" to determine current branch')

    def create_branch(self, branch, verbose=False):
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
        retcode, out = utils.run2(['git', 'branch', branch], show_command=verbose)
        if retcode:
            raise GiveUp('Error creating branch "%s": %s'%(branch, out))

        # Add this branch to the 'origin' remote for this checkout
        utils.shell(["git", "remote", "set-branches", "--add", "origin", branch],
                   show_command=verbose)

    def goto_branch(self, branch, verbose=False):
        """
        Make the named branch the current branch.

        Will be called in the actual checkout's directory.

        It is an error if the branch does not exist, in which case a GiveUp
        exception will be raised.
        """
        retcode, out = utils.run2(['git', 'checkout', branch], show_command=verbose)
        if retcode:
            raise GiveUp('Error going to branch "%s": %s'%(branch, out))

    def goto_revision(self, revision, branch=None, repo=None, verbose=False):
        """
        Make the specified revision current.

        Note that this may leave the working data (the actual checkout
        directory) in an odd state, in which it is not sensible to
        commit, depending on the VCS and the revision.

        Will be called in the actual checkout's directory.

        If a branch name is given, we will go to that branch first, and see
        if we already got to the correct revision. Note that the check for this
        assumes that 'revision' is a full SHA1, so is a bit simplistic. If we
        don't appear to be at the required revision, we'll then go there as
        normal.

        Raises GiveUp if there is no such revision, or no such branch.
        """
        if branch:
            # First, go to the branch and see if that's all we need to do
            try:
                self.goto_branch(branch)
            except GiveUp as e:
                raise GiveUp('Error going to branch "%s" for'
                             ' revision "%s":\n%s'%(branch, revision, e))
            new_revision = self._git_rev_parse_HEAD()
            if new_revision == expand_revision(revision): # Heh, we're already there
                return

        retcode, out = utils.run2(['git', 'checkout', revision],
                                  show_command=verbose, show_output=True)
        if retcode:
            raise GiveUp('Error going to revision "%s": %s'%(revision, out))

    def branch_exists(self, branch):
        """
        Is there a branch of this name?

        Will be called in the actual checkout's directory.
        """
        retcode, out = utils.run2('git branch -a', show_command=False)
        if retcode:
            raise GiveUp('Error looking up existing branches: %s'%out)

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
        This returns a bare SHA1 object name for the current HEAD
        """
        retcode, revision = utils.run2('git rev-parse HEAD', show_command=False)
        if retcode:
            raise GiveUp("'git rev-parse HEAD' failed with return code %d"%retcode)
        return revision.strip()

    def _calculate_revision(self, co_leaf, orig_revision, force=False,
                            before=None, verbose=True):
        """
        This returns a bare SHA1 object name for the current HEAD

        NB: if 'before' is specified, 'force' is ignored.
        """
        if before:
            print "git rev-list -n 1 --before='%s' HEAD"%before
            retcode, revision = utils.run2("git rev-list -n 1 --before='%s' HEAD"%before,
                                           show_command=False)
            print retcode, revision
            if retcode:
                if revision:
                    text = utils.indent(revision.strip(),'    ')
                else:
                    text = '    (it failed with return code %d)'%retcode
                raise GiveUp("%s\n%s"%(utils.wrap("%s:"
                    " \"git rev-list -n 1 --before='%s' HEAD\"'"
                    " could not determine a revision id for checkout:"%(co_leaf, before)),
                    text))
        else:
            retcode, revision = utils.run2('git rev-parse HEAD', show_command=False)
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
                raise GiveUp("%s\n%s"%(utils.wrap("%s: 'git rev-parse HEAD'"
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

        if False:
            # Should we try this first, and only "fall back" to the pure
            # SHA1 object name if it fails, or is the pure SHA1 object name
            # better?
            try:
                revision = self._git_describe_long(co_leaf, orig_revision, force, verbose)
            except GiveUp:
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
register_vcs("git", Git(), __doc__)

# End file.
