"""
Muddle support for Bazaar.
"""

from muddled.version_control import *
import muddled.utils as utils

import sys

class Bazaar(VersionControlHandler):
    """
    Version control handler for bazaar.

    Bazaar repositories are named: bzr+<url>.

    It's assumed that the first path component of 'rel' is the name of the repository.
    """

    def __init__(self, builder, co_name, repo, rev, rel, co_dir):
        VersionControlHandler.__init__(self, builder, co_name, repo, rev, rel, co_dir)
        sp = conventional_repo_url(repo, rel, co_dir = co_dir)
        if sp is None:
            raise utils.Error("Cannot extract repository URL from %s, co %s"%(repo, rel))

        self.bzr_repo = sp[0]
        self.checkout_path = self.get_checkout_path(None)

        if self.bzr_repo.startswith("ssh://"):
            # For some reason, the bzr command wants us to use "bzr+ssh" to
            # communicate over ssh, not just "ssh". Accomodate it, so the user
            # does not need to care about this.
            self.bzr_repo = "bzr+%s"%self.bzr_repo

    def path_in_checkout(self, rel):
        return conventional_repo_path(rel)

    def check_out(self):
        # If we do "checkout" and then "unbind", then (a) we've made a non-standard
        # branch and then converted it into a standard one (!), but (b) we've lost
        # the linkage to the original repository, and so ``bzr revno`` will report
        # HEAD until after our first pull or push. Moreover, we'll need to tell
        # that pull or push what reposiroty we want to use.
        #
        # Solution: just make a local branch...
        utils.ensure_dir(self.checkout_path)
        os.chdir(self.checkout_path)
        utils.run_cmd("bzr branch %s %s %s"%(self.r_option(),
                      self.bzr_repo, self.checkout_name),
                      env=self._derive_env())

    def pull(self):
        update_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(update_in)
        utils.run_cmd("bzr pull %s"%self.bzr_repo,
                      env=self._derive_env())

    def update(self):
        update_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(update_in)
        utils.run_cmd("bzr update", allowFailure=True,
                      env=self._derive_env())

    def commit(self):
        commit_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(commit_in)
        utils.run_cmd("bzr commit", allowFailure=True,
                      env=self._derive_env())

    def push(self):
        push_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(push_in)
        print "> push to %s "%self.bzr_repo
        utils.run_cmd("bzr push %s"%self.bzr_repo,
                      env=self._derive_env())

    def reparent(self, force=False, verbose=True):
        """
        Re-associate the local repository with its original remote repository,

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
            print "Re-associating checkout '%s' with remote repository"%(
                  self.checkout_name),
        this_dir = os.path.join(self.checkout_path, self.checkout_name)
        this_file = os.path.join(this_dir, '.bzr', 'branch', 'branch.conf')

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
                raise utils.Failure("Cannot parse '%s' - no '=' in line %d:"
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
                posns.append(('parent_location', self.bzr_repo))
                if verbose:
                    print
                    print '.. Setting "parent" location %s'%self.bzr_repo
            else:
                if verbose:
                    print '.. Overwriting "parent" location'
                    print '   it was     %s'%items['parent_location']
                    print '   it becomes %s'%self.bzr_repo
            items['parent_location'] = self.bzr_repo
        else:
            if 'parent_location' not in items:  # Place it at the end
                if verbose:
                    print
                    print '.. Setting "parent" location %s'%self.bzr_repo
                posns.append(('parent_location', self.bzr_repo))
                items['parent_location'] = self.bzr_repo
                changed = True
            elif verbose:
                print ' - already associated'
                if items['parent_location'] != self.bzr_repo:
                    print '.. NB with %s'%items['parent_location']
                    print '       not %s'%self.bzr_repo

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


    def must_update_to_commit(self):
        return False

    def r_option(self):
        """
        Return the -r option to pass to bzr commands, if any
        """
        if ((self.revision is None) or (self.revision == "HEAD")):
            return ""
        else:
            return "-r %s"%(self.revision)

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

    def revision_to_checkout(self, force=False, verbose=False):
        """
        Determine a revision id for this checkout, usable to check it out again.

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

        work_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(work_in)

        # So, have we checked everything in?
        retcode, text, ignore = utils.get_cmd_data('bzr version-info --check-clean',
                                                   env=env,
                                                   fold_stderr=False)
        if 'clean: False' in text:
            if force:
                print "'bzr version-info --check-clean' reports" \
                      " checkout '%s' has uncommitted data (ignoring it)"%self.checkout_name
            else:
                raise utils.Failure("%s: 'bzr version-info --check-clean' reports"
                        " checkout has uncommitted data"%self.checkout_name)

        # So, is our current revision (on this local branch) also present
        # in the remote branch (our push/pull location)?
        retcode, missing, ignore = utils.get_cmd_data('bzr missing -q --mine-only',
                                                      env=env,
                                                      fold_stderr=True,
                                                      fail_nonzero=False)
        if missing:
            missing = missing.strip()
            if missing == 'bzr: ERROR: No peer location known or specified.':
                # This presumably means that they have never pushed since
                # the original checkout
                if force:
                    orig_revision = self.get_original_revision()
                    if all([x.isdigit() for x in orig_revision]):
                        if verbose:
                            print missing
                            print 'Using original revision: %s'%orig_revision
                        return orig_revision
                    else:
                        raise utils.Failure("%s: 'bzr missing' says '%s',\n"
                                            "    and original revision is '%s', so"
                                            " cannot use that"%(self.checkout_name,
                                                                missing[5:],
                                                                orig_revision))
                else:
                    raise utils.Failure("%s: 'bzr missing' says '%s',\n"
                                        "    so cannot determine revision"%(self.checkout_name,
                                                                            missing[5:]))
            else:
                raise utils.Failure("%s: 'bzr missing' suggests checkout does"
                        " not match the remote repository:\n%s"%(self.checkout_name,
                            utils.indent(missing,'    ')))

        # So, let's get our revision number - where we are in the history
        # of the current branch
        retcode, revno, ignore = utils.get_cmd_data('bzr revno', env=env)
        revno = revno.strip()
        if all([x.isdigit() for x in revno]):
            return revno
        else:
            raise utils.Failure("%s: 'bzr revno' reports checkout has revision"
                    " '%s', which is not an integer"%(self.checkout_name,revision))


class BazaarVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "The Bazaar VCS"

    def manufacture(self, builder, co_name, repo, rev, rel, co_dir, branch):
        return Bazaar(builder, co_name, repo, rev, rel, co_dir)

        
# Tell the version control handler about us..
register_vcs_handler("bzr", BazaarVCSFactory())

def bzr_file_getter(url):
    """Retrieve a file's content via BZR.
    """
    if url.startswith("ssh://"):
        # For some reason, the bzr command wants us to use "bzr+ssh" to
        # communicate over ssh, not just "ssh". Accomodate it, so the user
        # does not need to care about this.
        url = "bzr+%s"%url
    retcode, text, ignore = utils.get_cmd_data('bzr cat %s'%url,
                                                fold_stderr=False)
    return text

register_vcs_file_getter('bzr', bzr_file_getter)

def bzr_dir_getter(url):
    """Retrieve a directory via BZR.
    """
    if url.startswith("ssh://"):
        # For some reason, the bzr command wants us to use "bzr+ssh" to
        # communicate over ssh, not just "ssh". Accomodate it, so the user
        # does not need to care about this.
        url = "bzr+%s"%url
    env = os.environ.copy()
    if 'PYTHONPATH' in env:
        del env['PYTHONPATH']
    utils.run_cmd("bzr branch %s"%url, env=env)

register_vcs_dir_getter('bzr', bzr_dir_getter)

# End file.
