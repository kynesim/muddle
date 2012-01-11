"""
Simple entry points so that descriptions can assert the existence
of checkouts easily
"""

import muddled.pkg as pkg
import muddled.utils as utils

from muddled.depend import Label
from muddled.repository import Repository
from muddled.version_control import vcs_action_for, split_vcs_url

def calc_repo_url(given_repo, rel):
    """
    Many VCSs adopt the convention that the first element of the relative
    string is the name of the repository.

    This routine resolves repo - a full repository URL - and rel into the name
    of a repository and the path within that repository and returns them as a
    tuple. if there is no path within the repository, then None is returned for
    it.
    """

    if rel is None:
        return given_repo, None

    # Split on the first '/' only
    components = rel.split("/", 1)
    if len(components) == 1:
        # There weren't any '/' to split on
        out_repo = os.path.join(given_repo, rel)
        out_rel = None
    elif len(components) == 2:
        # There was just a single '/' to split on
        out_repo = os.path.join(given_repo, components[0])
        out_rel = None
    else:
        # There were many '/' to split on
        out_repo = os.path.join(given_repo, components[0], components[1])
        out_rel = components[2]

    return out_repo, out_rel

def relative(builder, co_name, repo_relative=None, rev=None, branch=None):
    """
    A simple, VCS-controlled, checkout from a given repo_relative name.

    <rev> may be a revision (specified as a string). "HEAD" (or its equivalent)
    is assumed by default.

    <branch> may be a branch. "master" (or its equivalent) is assumed by
    default.

    If <repo_relative> is None then the repository <base_url>/<co_name> will
    be checked out into src/<co_name>, where <base_url> is the base URL as
    specified in .muddle/RootRepository (i.e., the base URL of the build
    description, as used in "muddle init").

    If <repo_relative> is not None, then the repository <base_url>/<repo_relative>
    (or unspecified), we append the checkout name to
    the default repository to work out the repo URL. Otherwise the normal URL
    relativisation rules are used.
    """

    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    builder.invocation.db.set_checkout_path(co_label, co_name)

    base_repo = builder.build_desc_repo
    if repo_relative:
        repo_url, rel_inner = calc_repo_url(base_repo.base_url, repo_relative)
        repo = Repository(base_repo.vcs, repo_url, co_name,
                          prefix=base_repo.prefix,
                          suffix=base_repo.suffix,
                          inner_path=rel_inner,
                          revision=rev, branch=branch)
    else:
        repo = base_repo.copy_with_changes(co_name, revision=rev, branch=branch)

    builder.invocation.db.set_checkout_repo(co_label, repo)

    vcs_handler = vcs_action_for(builder, co_label, repo)
    pkg.add_checkout_rules(builder.invocation.ruleset, co_label, vcs_handler)

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
