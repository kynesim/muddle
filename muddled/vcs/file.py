"""
Muddle support for naive file copying.
"""

import os
import urlparse

from muddled.version_control import register_vcs_handler, VersionControlSystem
import muddled.utils as utils

class File(VersionControlSystem):
    """
    Provide version control operations for simple file copying
    """

    def __init__(self):
        self.short_name = 'file'
        self.long_name = 'FileSystem'

    def init_directory(self, verbose=True):
        """
        If the directory does not appear to have had '<vcs> init' run in it,
        then do so first.

        Will be called in the actual checkout's directory.
        """
        pass

    def add_files(self, files=None, verbose=True):
        """
        If files are given, add them, but do not commit.

        Will be called in the actual checkout's directory.
        """
        pass

    def checkout(self, repo, co_leaf, options, branch=None, revision=None, verbose=True):
        """
        Clone a given checkout.

        Will be called in the parent directory of the checkout.

        Expected to create a directory called <co_leaf> therein.
        """
        if revision and revision != 'HEAD':
            raise utils.GiveUp("File does not support the 'revision' argument to"
                               " 'checkout' (revision='%s'"%revision)
        if branch:
            raise utils.GiveUp("File does not support the 'branch' argument to"
                               " 'checkout' (branch='%s'"%branch)
        parsed = urlparse.urlparse(repo)
        source_path = parsed.path

        utils.recursively_copy(source_path, co_leaf, preserve=True)

    def fetch(self, repo, options, branch=None, revision=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        Just copies everything again.
        """
        if revision and revision != 'HEAD':
            raise utils.GiveUp("File does not support the 'revision' argument to"
                               " 'fetch' (revision='%s'"%revision)
        if branch:
            raise utils.GiveUp("File does not support the 'branch' argument to"
                               " 'fetch' (branch='%s'"%branch)
        self.checkout(repo, os.curdir, verbose=verbose)

    def merge(self, other_repo, options, branch=None, revision=None, verbose=True):
        """
        Merge 'other_repo' into the local repository and working tree,

        Just copies everything again. This is an imperfect sort of "merge".
        """
        if revision and revision != 'HEAD':
            raise utils.GiveUp("File does not support the 'revision' argument to"
                               " 'merge' (revision='%s'"%revision)
        if branch:
            raise utils.GiveUp("File does not support the 'branch' argument to"
                               " 'merge' (branch='%s'"%branch)
        self.checkout(other_repo, os.curdir, verbose=verbose)

    def commit(self, options, verbose=True):
        """
        Will be called in the actual checkout's directory.
        """
        pass

    def push(self, repo, options, branch=None, verbose=True):
        """
        Will be called in the actual checkout's directory.

        We refuse to copy anything back to the original directory.
        """
        pass

    def status(self, repo, options, verbose=False):
        return True

    def reparent(self, co_dir, remote_repo, options, force=False, verbose=True):
        pass

    def revision_to_checkout(self, co_leaf, orig_revision, options, force=False, verbose=False):
        """
        Determine a revision id for this checkout, usable to check it out again.
        """
        return None

    def allows_relative_in_repo(self):
        return True         # Strangely enough

    def get_file_content(self, url, options, verbose=True):
        """
        Retrieve a file's content via Subversion.
        """
        source_path = _decode_file_url(url)
        with open(source_path) as fd:
            return fd.read()

def _decode_file_url(url):
    result = urlparse.urlparse(url)
    if result.scheme not in ('', 'file'):
        raise utils.GiveUp("'%s' is not a valid 'file:' URL"%url)
    if result.netloc:
        raise utils.GiveUp("'%s' is not a valid 'file:' URL - wrong number"
                " of '/' characters?"%url)
    if result.params or result.query or result.fragment:
        raise utils.GiveUp("'%s' is not a valid 'file:' URL - don't understand"
                " params, query or fragment"%url)
    return result.path

# Tell the version control handler about us..
register_vcs_handler("file", File())

# End file.
