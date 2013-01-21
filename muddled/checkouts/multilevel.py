"""
Multi-level checkouts. Required for embedding things like android, which
have a lot of deep internal checkouts.
"""

import posixpath
from urlparse import urljoin

import muddled.pkg as pkg
import muddled.utils as utils

from muddled.depend import Label
from muddled.repository import Repository
from muddled.utils import split_vcs_url
from muddled.version_control import checkout_from_repo

import os


def relative(builder, co_dir, co_name, repo_relative = None, rev = None,
             branch = None):
    """
    A multilevel checkout, with checkout name unrelated to checkout directory.

    Sometimes it is necessary to cope with checkouts that either:

        a. are more than two directories below src/, or
        b. have a checkout name that is not the same as the "leaf"
           directory in their path

    Both of these can happen when trying to represent an Android build,
    for instance.

    Thus::

      multilevel.relative(builder, co_dir='this/is/here', co_name='checkout1')

    will look for the repository <base_url>/this/is/here and check it out
    into src/this/is/here, but give it label checkout:checkout1/checked_out.

       (<base_url> is the base URL as specified in .muddle/RootRepository
       (i.e., the base URL of the build description, as used in "muddle init").

    For the moment, <repo_relative> is ignored.
    """
    base_repo = builder.build_desc_repo

    # urljoin doesn't work well with the sort of path fragment we tend to have
    repo_url = posixpath.join(base_repo.base_url, co_dir)
    repo = Repository.from_url(base_repo.vcs, repo_url,
                               revision=rev, branch=branch)

    # The version control handler wants to know the "leaf" separately
    # from the rest of the checkout path relative to src/
    co_dir_dir, co_dir_leaf = os.path.split(co_dir)

    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    checkout_from_repo(builder, co_label, repo, co_dir=co_dir_dir, co_leaf=co_dir_leaf)

def absolute(builder, co_dir, co_name, repo_url, rev=None, branch=None):
    """
    Check out a multilevel repository from an absolute URL.

    <repo_url> must be of the form <vcs>+<url>, where <vcs> is one of the
    support version control systems (e.g., 'git', 'svn').

    <rev> may be a revision (specified as a string). "HEAD" (or its equivalent)
    is assumed by default.

    <branch> may be a branch. "master" (or its equivalent) is assumed by
    default.

    The repository <repo_url> will be checked out into src/<co_dir>. The
    checkout will be identified by the label checkout:<co_name>/checked_out.
    """

    vcs, base_url = split_vcs_url(repo_url)

    repo = Repository.from_url(vcs, base_url, revision=rev, branch=branch)

    # The version control handler wants to know the "leaf" separately
    # from the rest of the checkout path relative to src/
    co_dir_dir, co_dir_leaf = os.path.split(co_dir)

    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    checkout_from_repo(builder, co_label, repo, co_dir=co_dir_dir, co_leaf=co_dir_leaf)

# End file.
