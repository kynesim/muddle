"""
Muddle support for weld

A weld is expressed in muddle as a VCS which does nothing. 

The effect is that one can write a build description within a weld and
 then use muddle to build the weld once the weld is checked out with
 git; this follows the weld idiom that one should use git commands
 to manipulate a weld.
"""

import os
import muddled.utils as utils
from muddled.version_control import register_vcs, VersionControlSystem
from muddled.withdir import Directory
from muddled.utils import GiveUp

class Weld(VersionControlSystem):
    """
    Provides version control operations for a weld -
    this is basically a no-op, and it turns out that that is
    what the base class provides, so .. 

    Obviously, the checkout revision for every checkout is just the
    revision-id of the weld itself.
    """

    def _calculate_revision(self, co_leaf, orig_revision):
        """
        This returns a bare SHA1 object name for orig_revision

        NB: if 'before' is specified, 'force' is ignored.
        """
        retcode, revision, ignore = utils.run3('git rev-parse %s'%orig_revision)
        if retcode:
            if revision:
                text = utils.indent(revision.strip(),'    ')
                raise GiveUp("%s\n%s"%(utils.wrap("%s: 'git rev-parse HEAD'"
                                                  " could not determine a revision id for checkout:"%co_leaf),
                                       text))
            else:
                raise GiveUp("%s\n"%(utils.wrap("%s: 'git rev-parse HEAD'"
                                                " could not determine a revision id for checkout:"%co_leaf)))
        return revision.strip()

    
    def __init__(self):
        self.short_name = 'weld'
        self.long_name = 'Weld'
    
    def revision_to_checkout(self, repo, co_leaf, options, force = False, before = None, 
                             verbose = True):
        return self._calculate_revision(co_leaf, 'HEAD')

    def ensure_version(self, builder, repo, co_leaf, options, verbose = True):
        """
        Ensures that the root git repo is the right version. If it exists,
        will error out if it isn't.

        Run in the root directory.
        """
        if (os.path.exists(".git")):
            # Get the checkout revision.
            rr = repo.revision
            if (rr is None):
                rr = 'HEAD'
            rev = self._calculate_revision(self, rr)
            # Now get the version we have .. 
            rev2 = self._calculate_revision(self, 'HEAD')
            if (rev != rev2):
                raise GiveUp("git repo required for %s is revision (%s) %s, but we have %s"%(co_leaf, repo.revision, rev,rev2))
        else:
            # Check out the relevant repo with the right bits in it.
            if repo.branch:
                br = repo.branch
            else:
                br = "master"
            # Because there are files here, we need to be a bit cunning.
            utils.run0("git init")
            utils.run0("git remote add origin %s"%repo.base_url)
            utils.run0("git fetch origin")
            if repo.revision:
                rev = repo.revision
                br = None
            else:
                rev = "HEAD"
            if (br is None):
                utils.run0("git checkout %s"%repo.revision)
            else:
                utils.run0("git checkout -b %s --track origin/%s"%(br,br))


register_vcs("weld", Weld(), __doc__)

# End file.
