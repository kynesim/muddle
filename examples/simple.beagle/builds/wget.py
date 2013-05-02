"""
Muddle support for retrieving files via wget.

For instance::

    wget+http://android.git.kernel.org/repo
    wget+http://tibsjoan.co.uk/mxtext/Metalang.html

In each case, the "final" filename in the URL is used as the name of the file
retrieved - so the above would retrieve ``repo`` and ``Metalang.html`` to the
appropriate checkout directory.

XXX TODO XXX Fix this example so that it works again!
"""

import os
import urlparse

import muddled.utils as utils
from muddled.version_control import VersionControlHandler, \
                                    VersionControlHandlerFactory, \
                                    conventional_repo_url, \
                                    register_vcs_handler

class Wget(VersionControlHandler):
    """
    A wrapper for wget.
    """

    def __init__(self, inv, checkout_name, repo, rev, rel, checkout_dir):
        VersionControlHandler.__init__(self, inv, checkout_name, repo, rev, rel, checkout_dir)
        sp = conventional_repo_url(repo, rel)
        if sp is None:
            raise utils.GiveUp("Cannot extract repository URL from %s, checkout %s"%(repo, rel))

        (self.url, r) = sp

        parsed = urlparse.urlparse(self.url)
        self.filename = os.path.split(parsed.path)[-1]
        self.checkout_path = self.get_checkout_path(self.checkout_name)


    def path_in_checkout(self, rel):
        return conventional_repo_path(rel)

    def check_out(self):
        utils.ensure_dir(self.checkout_path)
        os.chdir(self.checkout_path)
        utils.run0("wget %s --output-document=%s"%(self.url,self.filename))

    def pull(self):
        self.check_out()

    def update(self):
        self.check_out()

    def commit(self):
        """We do not support committing with wget.
        """
        pass

    def push(self):
        """We do not support pushing with wget.
        """
        pass

    def must_update_to_commit(self):
        return False


class WgetVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "WGET"

    def manufacture(self, inv, checkout_name, repo, rev, rel, checkout_dir):
        return Wget(inv, checkout_name, repo, rev, rel, checkout_dir)

# Register us with the VCS handler factory
register_vcs_handler("wget", WgetVCSFactory())

