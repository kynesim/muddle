"""
Muddle suppport for Git.
"""

from muddled.version_control import *
import muddled.utils as utils
import os

class Git(VersionControlHandler):
    def __init__(self, builder, checkout_name, repo, rev, rel, co_dir, branch = None):
        VersionControlHandler.__init__(self, builder, checkout_name, repo, rev, rel, co_dir)
        sp = conventional_repo_url(repo, rel, co_dir = co_dir)
        if sp is None:
            raise utils.Error("Cannot extract repository URL from %s, checkout %s"%(repo, rel))

        self.git_repo = sp[0]
        self.co_path = self.get_checkout_path(self.checkout_name)
        self.branch = branch
        self.parse_revision(rev)

    def parse_revision(self, rev):
        # Disentangle git version numbers. These are like '<branch>:<revision>'
        the_re = re.compile("([^:]*):(.*)$")
        m = the_re.match(rev)
        if (m is None):
            # No branch. If there wasn't one, we meant master.
            if (rev == "HEAD"):
                self.revision = "HEAD" # Turns out git uses this too
            else:
                self.revision = rev
        else:
            self.branch = m.group(1)
            self.revision = m.group(2)
            # No need to adjust HEAD - git uses it too.

    def get_original_revision(self):
        # Is it acceptable to return the inferred branch "master"?
        return "%s:%s"%(self.branch, self.revision)

    def path_in_checkout(self, rel):
        return conventional_repo_path(rel)

    def check_out(self):
        # Clone constructs its own directory .. 
        (parent_path, d) = os.path.split(self.co_path)

        utils.ensure_dir(parent_path)
        os.chdir(parent_path)
        args = ""
        #if not (self.revision is None) or (not self.revision):
            #args = "-n -o %s"%(self.revision)

        utils.run_cmd("git clone %s %s %s"%(args, self.git_repo, self.checkout_name))

        co_path = os.path.join(parent_path, self.checkout_name)
        if (self.branch is not None):
            os.chdir(co_path)
            utils.run_cmd("git pull origin %s"%self.branch)
        
        if not ((self.revision is None) or (not self.revision)):
            print ("checkout to %s"%(self.checkout_name))
            os.chdir(co_path)
            utils.run_cmd("git checkout %s"%self.revision)

    def pull(self):
        os.chdir(self.co_path)
        if (self.branch):
            utils.run_cmd("git pull %s %s"%(self.git_repo, self.branch))
        else:
            utils.run_cmd("git pull %s master"%(self.git_repo))
        
    def update(self):
        os.chdir(self.co_path)
        utils.run_cmd("git pull", allowFailure = True)

    def commit(self):
        os.chdir(self.co_path)
        # We may very well fail here. git commit fails for any number
        # of bizarre reasons we don't care about .. 
        utils.run_cmd("git commit -a", allowFailure = True)

    def push(self):
        os.chdir(self.co_path)
        if (self.branch is not None):
            effective_branch = self.branch
        else:
            effective_branch = ""
        utils.run_cmd("git push %s %s"%(self.git_repo, effective_branch))

    def must_update_to_commit(self):
        return False

    def revision_to_checkout(self, force=False, verbose=False):
        """
        Determine a revision id for this checkout, usable to check it out again.

        ...
        """
        # Later versions of git allow one to give a '--short' switch to
        # 'git status', which would probably do what I want - but the
        # version of git in Ubuntu 9.10 doesn't have that switch. So
        # we're reduced to looking for particular strings - and the git
        # documentation says that the "long" texts are allowed to change

        # NB: this is actually a broken solution to a broken problem, as
        # our git support is probably not terribly well designed.

        os.chdir(self.co_path)
        retcode, text, ignore = utils.get_cmd_data('git status -q', fail_nonzero=False)
        text = text.strip()
        if text != '# On branch master\nnothing to commit (working directory clean)':
            raise utils.Failure("%s\n%s"%(utils.wrap("%s: 'git status' suggests"
                " checkout does not match master:"%self.checkout_name),
                utils.indent(text,'    ')))

        retcode, revision, ignore = utils.get_cmd_data('git describe --long',
                                                       fail_nonzero=False)
        if retcode:
            if text:
                text = utils.indent(revision.strip(),'    ')
                if force:
                    if verbose:
                        print "'git describe --long' had problems with checkout" \
                              " '%s'"%self.checkout_name
                        print "    %s"%text
                        print "using original revision %s"%self.get_original_revision()
                    return self.get_original_revision()
            else:
                text = '    (it failed with return code %d)'%retcode
            raise utils.Failure("%s\n%s"%(utils.wrap("%s: 'git describe --long'"
                " could not determine a revision id for checkout:"%self.checkout_name),
                text))
        revision = revision.strip()
        return revision

class GitVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "GIT"

    def manufacture(self, builder, checkout_name, repo, rev, rel, co_dir, branch):
        return Git(builder, checkout_name, repo, rev, rel, co_dir, branch)

# Register us with the VCS handler factory
register_vcs_handler("git", GitVCSFactory())

def git_dir_getter(url):
    """Retrieve a directory via git.
    """
    utils.run_cmd("git clone %s"%url)

register_vcs_dir_getter('git', git_dir_getter)

# End file.
