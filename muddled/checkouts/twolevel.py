"""
Two-level checkouts. Makes it slightly easier to separate checkouts
out into roles. I've deliberately not implemented arbitrary-level checkouts
for fear of complicating the checkout tree.
"""

import muddled.pkg as pkg
import muddled.utils as utils

from muddled.depend import Label
from muddled.version_control import vcs_action_for, split_vcs_url

import os

def relative(builder, co_dir, co_name, repo_relative = None, rev = None, branch = None):
    """
    A two-level version of checkout.simple.relative().

    In the normal case, the location in the repository and in the checkout
    is assumed the same (i.e., <co_dir>/<co_name>). So, for instance, the
    repository might have::

        <repo>/A/B

    checked out into::

        src/A/B

    Occasionally, though, the repository is organised differently, so for
    instance, one might want to checkout::

        <repo>/B

    into::

        src/A/B

    In this latter case, one can use the 'repo_relative' argument, to say where
    the checkout is relative to the repository's "base". So, in the example
    above:

        * co_dir = "A"
        * co_name = "B"
        * repo_relative = B
    """
    repo = builder.invocation.db.repo.get()

    if (co_dir is None):
        tree_relative = co_name
    else:
        tree_relative = os.path.join(co_dir, co_name)


    if (repo_relative is None):
        rest = tree_relative
    else:
        rest = repo_relative

    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    builder.invocation.db.set_checkout_path(co_label, 
                                            tree_relative)

    vcs_handler = vcs_action_for(builder, co_label, repo, rev,
                                                 rest, co_dir=co_dir,
                                                 branch=branch)
    pkg.add_checkout_rules(builder.invocation.ruleset,
                           co_label,
                           vcs_handler)

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

    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    builder.invocation.db.set_checkout_path(co_label, co_path)

    vcs, base_url = split_vcs_url(repo_url)

    repo = Repository(vcs, base_url, co_name, revision=rev, branch=branch)
    builder.invocation.db.set_checkout_repo(co_label, repo)

    vcs_handler = vcs_action_for(builder, co_label, repo, co_dir=co_dir)
    pkg.add_checkout_rules(builder.invocation.ruleset, co_label, vcs_handler)

# End file.
