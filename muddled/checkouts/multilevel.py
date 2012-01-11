"""
Multi-level checkouts. Required for embedding things like android, which
have a lot of deep internal checkouts.
"""

import muddled.pkg as pkg
import muddled.utils as utils

from muddled.depend import Label
from muddled.version_control import vcs_action_for, split_vcs_url

import os


def relative(builder, co_dir, co_name, repo_relative = None, rev = None,
             branch = None):
    """
    A multilevel version of checkout.simple.relative()

    See the docs for twolevel.relative() for details; multilevel checkouts
    are distinguished by having a different checkout name from their
    directory entirely, which is a bit confusing, but also allows for
    multiple repositories all called the same thing - again, this is an
    adaptation for things like android which actually require it.

    NB: Although the argument 'repo_relative' is provided, it is ignored.
    For the moment, multilevel checkouts must be in the same location on
    the repository as given in the 'co_dir' argument.
    """
    repo = builder.invocation.db.repo.get()

    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    builder.invocation.db.set_checkout_path(co_label, co_dir)

    # Version control is slightly weird here ..
    (co_dir_dir, co_dir_leaf) = os.path.split(co_dir)

    # We have to lie a bit here and reconstruct repo as the classic
    #  two-level resolver doesn't really work.
    real_repo = os.path.join(repo, co_dir)

    #print 'VCS',co_name
    #print '... full co_dir',co_dir
    #print '... co_dir',co_dir
    #print '... co_leaf',co_leaf

    vcs_handler = vcs_action_for(builder, co_label, real_repo,
                                                 rev, None,
                                                 co_dir = co_dir_dir,
                                                 co_leaf = co_dir_leaf,
                                                 branch = branch)
    pkg.add_checkout_rules(builder.invocation.ruleset,
                           co_label,
                           vcs_handler)

def absolute(builder, co_dir, co_name, repo_url, rev=None, branch=None):
    """
    Check out a multilevel repository from an absolute URL.

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

    vcs_handler = vcs_action_for(builder, co_label, repo, co_dir=co_dir,
    pkg.add_checkout_rules(builder.invocation.ruleset, co_label, vcs_handler)

# End file.
