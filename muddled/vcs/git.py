"""
Muddle suppport for Git.

.. to be documented ..


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

from muddled.version_control import register_vcs_handler, VersionControlSystem
import muddled.utils as utils

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
            with utils.Directory(co_leaf):
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

    def pull(self, repo, options, upstream=None, verbose=True):
        """
        Will be called in the actual checkout's directory.
        """
        if repo.revision and repo.revision != 'HEAD':
            raise utils.GiveUp(\
                "The build description specifies revision %s for this checkout.\n"
                "'muddle pull' does a git fetch and then a fast-forwards merge.\n"
                "Since git always merges to the currrent HEAD, muddle does not\n"
                "support 'muddle pull' for a git checkout with a revision"
                " specified."%repo.revision)

        # Refuse to pull if there are any local changes or untracked files.
        self._is_it_safe()

        self._shallow_not_allowed(options)

        if not upstream or upstream == 'origin':
            # If we're not given an upstream repository name, assume we're dealing
            # with an "ordinary" pull, from our origin
            upstream = 'origin'
            # In which case, it's sufficient to do:
            utils.run_cmd("git config remote.origin.url %s"%(repo.url), verbose=verbose)
        else:
            # With a "proper" upstream, we need to set up a bit more
            self._setup_remote(upstream, repo.url, verbose=verbose)

        # Retrieve changes from the remote repository to the local repository
        utils.run_cmd("git fetch %s"%upstream, verbose=verbose)
        # Merge them into the working tree, but only if this is a fast-forward
        # merge, and thus doesn't require the user to do any thinking
        # Don't specify branch name: we definitely want to update our idea of
        # where the remote head points to be updated.
        # (See git-pull(1) and git-fetch(1): "without storing the remote branch
        # anywhere locally".)
        # And then merge "fast forward only" - i.e., not if we had to do any
        # thinking
        if repo.branch is None:
            remote = 'remotes/%s/master'%(upstream)
        else:
            remote = 'remotes/%s/%s'%(upstream,repo.branch)
        if (git_supports_ff_only()):
            utils.run_cmd("git merge --ff-only %s"%remote, verbose=verbose)
        else:
            utils.run_cmd("git merge --ff %s"%remote, verbose=verbose)


    def merge(self, other_repo, options, verbose=True):
        """
        Merge 'other_repo' into the local repository and working tree,

        Will be called in the actual checkout's directory.

        According to 'git help merge', merge is always done to the current HEAD.
        So any revision sill not affect the merge process. However, if the user
        has asked for a specific revision, which obviously already exists (else
        how did we get here?), then they are actually not interested in merging,
        or at least not for muddle purposes. In that case we're better off just
        giving up, and letting the user sort it out directly.
        """
        if other_repo.revision and other_repo.revision != 'HEAD':
            raise utils.GiveUp(\
                   "The build description specifies revision %s for this checkout.\n"
                   "Since git always merges to the currrent HEAD, muddle does not\n"
                   "support 'muddle merge' for a git checkout with a revision"
                   " specified."%other_repo.revision)

        # Refuse to pull if there are any local changes or untracked files.
        self._is_it_safe()

        self._shallow_not_allowed(options)

        utils.run_cmd("git config remote.origin.url %s"%other_repo.url, verbose=verbose)
        # Retrieve changes from the remote repository to the local repository
        utils.run_cmd("git fetch origin", verbose=verbose)
        # And merge them (all) into the current working tree
        if other_repo.branch is None:
            remote = 'remotes/origin/master'
        else:
            remote = 'remotes/origin/%s'%other_repo.branch
        utils.run_cmd("git merge %s"%remote, verbose=verbose)

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
        """
        self._shallow_not_allowed(options)
        if repo.branch:
            effective_branch = repo.branch
        else:
            # Explicitly push master if nothing else is specified.
            # This is so that the user sees what we're doing, instead of
            # being potentially confused by git's config hiding non-default
            # behaviour.
            effective_branch = "master"

        # If we're not given an upstream repository name, assume we're dealing
        # with an "ordinary" push, to our origin
        if not upstream or upstream == 'origin':
            upstream = 'origin'
            # For an upstream, we won't necessarily have the remote in our
            # configuration (unless we already did an upstream pull from
            # the same repository...)
            utils.run_cmd("git config remote.%s.url %s"%(upstream, repo.url), verbose=verbose)

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

        if text:
            return text
        else:
            return None

    def _setup_remote(self, remote_name, remote_repo, verbose=True):
        """
        Re-associate the local repository with a remote.
        """
        # We used to git config remote.origin.url %s here, but that
        # doesn't handle the case where you've created a new repo (with
        # muddle bootstrap or import) - git remote _add_ adds some
        # branch-tracking entries on the side.

        # Let's try not to do a "git remote rm" if we don't have to,
        # so that we don't show the user a nasty error message. So ask
        # if there are any configurations for remote origin...
        retcode, out, ignore = utils.get_cmd_data("git config --get-regexp remote.%s.*"%remote_name,
                                                  fail_nonzero=False)
        if retcode == 0:    # there were
            utils.run_cmd("git remote rm %s"%remote_name, verbose=verbose, allowFailure=True)

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

    def _git_rev_parse_HEAD(self, co_leaf, orig_revision, force=False, verbose=True):
        """
        This returns a bare SHA1 object name for the current revision
        """
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

    def revision_to_checkout(self, repo, co_leaf, options, force=False, verbose=True):
        """
        Determine a revision id for this checkout, usable to check it out again.

        a) Document
        b) Review the code to see if we now support versions of git that  would
           allow us to do this more sensibly

        XXX TODO: Needs reviewing given we're using a later version of git now
        """
        # Later versions of git allow one to give a '--short' switch to
        # 'git status', which would probably do what I want - but the
        # version of git in Ubuntu 9.10 doesn't have that switch. So
        # we're reduced to looking for particular strings - and the git
        # documentation says that the "long" texts are allowed to change

        # Earlier versions of this command line used 'git status -q', but
        # the '-q' switch is not present in git 1.7.0.4

        # NB: this is actually a broken solution to a broken problem, as
        # our git support is probably not terribly well designed.

        if repo.revision:
            orig_revision = repo.revision
        else:
            orig_revision = 'HEAD'

        retcode, text, ignore = utils.get_cmd_data('git status', fail_nonzero=False)
        text = text.strip()
        if not self._git_status_text_ok(text):
            raise utils.GiveUp("%s\n%s"%(utils.wrap("%s: 'git status' suggests"
                " checkout does not match master:"%co_leaf),
                utils.indent(text,'    ')))
        if False:
            # Should we try this first, and only "fall back" to the pure
            # SHA1 object name if it fails, or is the pure SHA1 object name
            # better?
            revision = self._git_describe_long(co_leaf, orig_revision, force, verbose)
        else:
            revision = self._git_rev_parse_HEAD(co_leaf, orig_revision, force, verbose)
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
register_vcs_handler("git", Git(), __doc__, ["shallow_checkout"])

# End file.
