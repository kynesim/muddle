"""
Simple entry points so that descriptions can assert the existence
of checkouts easily
"""

import muddled.pkg as pkg
import muddled.utils as utils

from muddled.depend import Label
from muddled.repository import Repository
from muddled.version_control import vcs_action_for, split_vcs_url

def relative(builder, co_name, repo_relative = None, rev = None, branch = None):
    """
    A simple, VCS-controlled, checkout from a given repo_relative
    name.

    If repo_relative is None (or unspecified), we append the
    checkout name to the default repository to work out the
    repo URL. Otherwise the normal URL relativisation rules are
    used.
    """

    repo = builder.invocation.db.repo.get()
    if (repo_relative is None):
        rest = co_name
    else:
        rest = repo_relative

    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    builder.invocation.db.set_checkout_path(co_label, co_name)

    vcs_handler = vcs_action_for(builder, co_label, repo, rev, rest, branch=branch)
    pkg.add_checkout_rules(builder.invocation.ruleset,
                           co_label,
                           vcs_handler)

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

    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    builder.invocation.db.set_checkout_path(co_label, co_name)

    vcs, base_url = split_vcs_url(repo_url)

    repo = Repository(vcs, base_url, co_name, revision=rev, branch=branch)
    builder.invocation.db.set_checkout_repo(co_label, repo)

    vcs_handler = vcs_action_for(builder, co_label, repo)
    pkg.add_checkout_rules(builder.invocation.ruleset, co_label, vcs_handler)

# End file.
