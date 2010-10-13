"""
Simple entry points so that descriptions can assert the existence
of checkouts easily
"""

import muddled.pkg as pkg
import muddled.utils as utils
import muddled.version_control as version_control

from muddled.depend import Label

import urlparse

def relative(builder, co_name, repo_relative = None, rev = None):
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

    vcs_handler = version_control.vcs_dependable_for(builder,
                                                     co_label,
                                                     repo, rev,
                                                     rest)
    pkg.add_checkout_rules(builder.invocation.ruleset,
                           co_name, 
                           vcs_handler)

def absolute(builder, co_name, repo_url, rev = None):
    """
    Check out a twolevel repository from an absolute URL.
    """

    co_label = Label(utils.LabelType.Checkout, co_name, domain=builder.default_domain)
    builder.invocation.db.set_checkout_path(co_label, co_name)

    vcs_handler = version_control.vcs_dependable_for(builder, co_label,
                                                     repo_url, rev,
                                                     None)
    pkg.add_checkout_rules(builder.invocation.ruleset,
                           co_name, 
                           vcs_handler)




# End file.
