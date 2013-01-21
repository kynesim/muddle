"""
Two-level checkouts. Makes it slightly easier to separate checkouts
out into roles. I've deliberately not implemented arbitrary-level checkouts
for fear of complicating the checkout tree.
"""

from urlparse import urljoin

import muddled.pkg as pkg
import muddled.utils as utils

from muddled.depend import Label
from muddled.repository import Repository
from muddled.utils import split_vcs_url
from muddled.version_control import checkout_from_repo

import os

def relative(builder, co_dir, co_name, repo_relative = None, rev = None, branch = None):
    """
    A two-level version of checkout.simple.relative().

    It attempts to check out <co_dir>/<co_name> (but see below).

    <rev> may be a revision (specified as a string). "HEAD" (or its equivalent)
    is assumed by default.

    <branch> may be a branch. "master" (or its equivalent) is assumed by
    default.

    If <repo_relative> is None then the repository <base_url>/<co_name> will
    be checked out, where <base_url> is the base URL as specified in
    .muddle/RootRepository (i.e., the base URL of the build description, as
    used in "muddle init").

    If <repo_relative> is not None, then the repository
    <base_url>/<repo_relative> ...

    In the normal case, the location in the repository and in the checkout
    is assumed the same (i.e., <co_dir>/<co_name>). So, for instance, with
    co_dir="A" and co_name="B", the repository would have::

        <base_url>/A/B

    which we would check out into::

        src/A/B

    Occasionally, though, the repository is organised differently, so for
    instance, one might want to checkout::

        <base_url>/B

    into::

        src/A/B

    In this latter case, one can use the 'repo_relative' argument, to say where
    the checkout is relative to the repository's "base". So, in the example
    above, we still have co_dir="A" and co_name="B", but we also want to say
    repo_relative=B.
    """

    base_repo = builder.build_desc_repo
    if repo_relative:
        repo_co_dir, repo_co_name = os.path.split(repo_relative)
        repo = base_repo.copy_with_changes(repo_co_name, prefix=repo_co_dir,
                                           revision=rev, branch=branch)
    else:
        repo = base_repo.copy_with_changes(co_name, prefix=co_dir,
                                           revision=rev, branch=branch)

    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    checkout_from_repo(builder, co_label, repo, co_dir=co_dir)

# For historical reasons
twolevel = relative

def absolute(builder, co_dir, co_name, repo_url, rev=None, branch=None):
    """
    Check out a twolevel repository from an absolute URL.

    <repo_url> must be of the form <vcs>+<url>, where <vcs> is one of the
    support version control systems (e.g., 'git', 'svn').

    <rev> may be a revision (specified as a string). "HEAD" (or its equivalent)
    is assumed by default.

    <branch> may be a branch. "master" (or its equivalent) is assumed by
    default.

    The repository <repo_url>/<co_name> will be checked out into
    src/<co_dir>/<co_name>.
    """

    co_path = os.path.join(co_dir, co_name)

    vcs, base_url = split_vcs_url(repo_url)
    repo = Repository.from_url(vcs, base_url, revision=rev, branch=branch)
    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    checkout_from_repo(builder, co_label, repo, co_dir=co_dir)

# End file.
