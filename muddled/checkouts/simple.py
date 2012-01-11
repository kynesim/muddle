"""
Simple entry points so that descriptions can assert the existence
of checkouts easily
"""

from urlparse import urljoin

import muddled.pkg as pkg
import muddled.utils as utils

from muddled.depend import Label
from muddled.repository import Repository
from muddled.version_control import split_vcs_url, checkout_from_repo

def relative(builder, co_name, repo_relative=None, rev=None, branch=None):
    """
    A simple, VCS-controlled, checkout.

    <rev> may be a revision (specified as a string). "HEAD" (or its equivalent)
    is assumed by default.

    <branch> may be a branch. "master" (or its equivalent) is assumed by
    default.

    If <repo_relative> is None then the repository <base_url>/<co_name> will
    be checked out into src/<co_name>, where <base_url> is the base URL as
    specified in .muddle/RootRepository (i.e., the base URL of the build
    description, as used in "muddle init").

    For example::

        <base_url>/<co_name>  -->  src/<co_name>

    If <repo_relative> is not None, then the repository
    <base_url>/<repo_relative> will be checked out instead::

        <base_url>/<repo_relative>  -->  src/<co_name>
    """

    base_repo = builder.build_desc_repo
    if repo_relative:
        repo_url = urljoin(base_repo.base_url, repo_relative)
        repo = Repository.from_url(base_repo.vcs, repo_url,
                                   revision=rev, branch=branch)
    else:
        repo = base_repo.copy_with_changes(co_name, revision=rev, branch=branch)

    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    checkout_from_repo(builder, co_label, repo)

def absolute(builder, co_name, repo_url, rev=None, branch=None):
    """
    Check out a repository from an absolute URL.

    <repo_url> must be of the form <vcs>+<url>, where <vcs> is one of the
    support version control systems (e.g., 'git', 'svn').

    <rev> may be a revision (specified as a string). "HEAD" (or its equivalent)
    is assumed by default.

    <branch> may be a branch. "master" (or its equivalent) is assumed by
    default.

    The repository <repo_url>/<co_name> will be checked out into src/<co_name>.
    """

    vcs, base_url = split_vcs_url(repo_url)
    repo = Repository.from_url(vcs, base_url, revision=rev, branch=branch)
    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    checkout_from_repo(builder, co_label, repo)

# End file.
