"""
Two-level checkouts. Makes it slightly easier to separate checkouts
out into roles. I've deliberately not implemented arbitrary-level checkouts
for fear of complicating the checkout tree.
"""

import muddled
import muddled.pkg as pkg
import muddled.version_control as version_control
import urlparse
import os

def twolevel(builder, co_dir, co_name, repo_relative = None, rev = None):
    """
    A two-level version of checkout.simple.relative().
    """
    repo = builder.invocation.db.repo.get()

    if (repo_relative is None):
        rest = os.path.join(co_dir, co_name)
        builder.invocation.db.set_checkout_path(co_name, os.path.join(co_dir, co_name))
    else:
        rest = repo_relative

    vcs_handler = version_control.vcs_dependable_for(builder,
                                                     co_name, 
                                                     repo, rev, 
                                                     rest, 
                                                     co_dir = co_dir)
    pkg.add_checkout_rules(builder.invocation.ruleset,
                           co_name, 
                           vcs_handler)
    

def absolute(builder, co_dir, co_name, repo_url, rev = None):
    """
    Check out a twolevel repository from an absolute URL.
    """
    
    rest = os.path.join(co_dir, co_name)
    builder.invocation.db.set_checkout_path(co_name, rest)
    vcs_handler = version_control.vcs_dependable_for(builder, co_name, 
                                                     repo_url, rev, 
                                                     None, co_dir = co_dir)
    pkg.add_checkout_rules(builder.invocation.ruleset,
                           co_name, 
                           vcs_handler)




# End file.


