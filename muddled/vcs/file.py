"""
Muddle support for naive file copying.
"""

from muddled.version_control import *
import muddled.utils as utils
import urlparse 

class File(VersionControlHandler):
    """
    Version control handler for file copies.
    
    Simply copies data from a repository directory to a working directory
    It does _not_ copy data back.
    """

    def __init__(self, inv, co_name, repo, rev, rel, co_dir):
        VersionControlHandler.__init__(self, inv, co_name, repo, rev, rel, co_dir)
        
        sp = conventional_repo_url(repo, rel)
        if (sp is None):
            raise utils.Error("Cannot extract repository URL from %s, co %s"%(repo, rel))
        
        (real_repo, r) = sp


        parsed = urlparse.urlparse(real_repo)
        self.source_path = parsed.path
        self.co_path = self.get_checkout_path(self.checkout_name)


    def check_out(self):
        # Check out.
        utils.ensure_dir(self.co_path)
        utils.run_cmd("cp -r %s/* %s"%(self.source_path, self.co_path))

    def pull(self):
        # Nothing to do here.
        pass

    def update(self):
        # Just copy everything over again.
        self.check_out()

    def commit(self):
        # Nothing to do
        pass

    def push(self):
        # Nothing to do
        pass

    def must_update_to_commit(self):
        return False


class FileVCSFactory(VersionControlHandlerFactory):
    def describe(self):
        return "Copy data between directories"

    def manufacture(self, builder, co_name, repo, rev, rel, co_dir, branch):
        return File(builder, co_name, repo, rev, rel, co_dir)


# Tell the VCS handler about us.
register_vcs_handler("file", FileVCSFactory())

def _decode_file_url(url):
    result = urlparse.urlparse(url)
    if result.scheme not in ('', 'file'):
        raise utils.Error("'%s' is not a valid 'file:' URL"%url)
    if result.netloc:
        raise utils.Error("'%s' is not a valid 'file:' URL - wrong number"
                " of '/' characters?"%url)
    if result.params or result.query or result.fragment:
        raise utils.Error("'%s' is not a valid 'file:' URL - don't understand"
                " params, query or fragment"%url)
    return result.path

def file_file_getter(url):
    """Retrieve a file's content.
    """
    source_path = _decode_file_url(url)
    with open(source_path) as fd:
        return fd.read()

register_vcs_file_getter('file', file_file_getter)

def file_dir_getter(url):
    """Retrieve a directory.
    """
    source_path = _decode_file_url(url)
    target_path = os.path.split(source_path)[1]
    if os.path.exists(target_path):
        raise utils.Error("Cannot copy '%s', as target '%s' already"
                " exists"%(source_path, target_path))
    utils.recursively_copy(source_path, target_path)

register_vcs_dir_getter('file', file_dir_getter)

# End File
