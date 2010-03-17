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
                      self.bzr_repo, self.checkout_name))

    def pull(self):
        update_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(update_in)
        utils.run_cmd("bzr pull %s"%self.bzr_repo)

    def update(self):
        update_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(update_in)
        utils.run_cmd("bzr update", allowFailure = True)

    def commit(self):
        commit_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(commit_in)
        utils.run_cmd("bzr commit", allowFailure = True)

    def push(self):
        push_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(push_in)
        print "> push to %s "%self.bzr_repo
        utils.run_cmd("bzr push %s"%self.bzr_repo)

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

    def revision_to_checkout(self, force=False, verbose=False):
        """
        Determine a revision id for this checkout, usable to check it out again.

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

        # It turns out that if the PYTHONPATH includes the "current directory",
        # then 'bzr missing' in particular does not play well with some of the
        # typical Python file names we sometimes have in 'src/builds'
        # directories.
        #
        # The "solution" (ick, ick) is thus to make sure this doesn't happen...
        #
        # (Specifically, this is observed with bzr version 2.0.2 on my Ubuntu
        # system with my packages installed, so it may or may not happen for
        # anyone else, but it still seems safest to avoid it!)
        work_in = os.path.join(self.checkout_path, self.checkout_name)
        os.chdir(work_in)

        if work_in in sys.path:
            saved_sys_path = sys.path[:]
            while work_in in sys.path:
                sys.path.remove(work_in)
            sys_path_altered = True
            #print
            #print 'PYTHONPATH now','\n'.join(sys.path)
            #print
        else:
            sys_path_altered = False

        try:
            # So, have we checked everything in?
            retcode, text, ignore = utils.get_cmd_data('bzr version-info --check-clean',
                                                       fold_stderr=False)
            if 'clean: False' in text:
                if force:
                    print "'bzr version-info --check-clean' reports" \
                          " checkout '%s' has uncommitted data (ignoring it)"%self.checkout_name
                else:
                    raise utils.Failure("'bzr version-info --check-clean' reports"
                            " checkout '%s' has uncommitted data"%self.checkout_name)

            # So, are we current with our original repository (or our current
            # push location)
            retcode, missing, ignore = utils.get_cmd_data('bzr missing -q',
                                                          fold_stderr=True,
                                                          fail_nonzero=False)
            if missing:
                missing = missing.strip()
                if missing == 'bzr: ERROR: No peer location known or specified.':
                    # This presumably means that they have never pushed since
                    # the original checkout - in which case we *should* be OK
                    if verbose:
                        print missing
                    return self.get_original_revision()
                else:
                    raise utils.Failure("'bzr missing' suggests checkout '%s' does"
                            " not match the remote repository:\n%s"%(self.checkout_name,
                                utils.indent(missing,'    ')))

            # So, let's get our revision number - where we are in the history
            # of the current branch
            retcode, revno, ignore = utils.get_cmd_data('bzr revno')
            revno = revno.strip()
            if all([x.isdigit() for x in revno]):
                return revno
            else:
                raise utils.Failure("'bzr revno' reports checkout '%s' has revision"
                        " '%s', which is not an integer"%(self.checkout_name,revision))
        finally:
            if sys_path_altered:
                sys.path = saved_sys_path


class BazaarVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "The Bazaar VCS"

    def manufacture(self, builder, co_name, repo, rev, rel, co_dir):
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

# End file.
