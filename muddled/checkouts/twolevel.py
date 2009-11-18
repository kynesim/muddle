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

def relative(builder, co_dir, co_name, repo_relative = None, rev = None):
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

    if (repo_relative is None):
        rest = os.path.join(co_dir, co_name)
    else:
        rest = repo_relative

    builder.invocation.db.set_checkout_path(co_name, os.path.join(co_dir, co_name), 
                                            domain = builder.default_domain)

    vcs_handler = version_control.vcs_dependable_for(builder,
                                                     co_name, 
                                                     repo, rev, 
                                                     rest, 
                                                     co_dir = co_dir)
    pkg.add_checkout_rules(builder.invocation.ruleset,
                           co_name, 
                           vcs_handler)

# For historical reasons
twolevel = relative   

def absolute(builder, co_dir, co_name, repo_url, rev = None):
    """
    Check out a twolevel repository from an absolute URL.
    """
    
    rest = os.path.join(co_dir, co_name)
    builder.invocation.db.set_checkout_path(co_name, rest, 
                                            domain = builder.default_domain)
    vcs_handler = version_control.vcs_dependable_for(builder, co_name, 
                                                     repo_url, rev, 
                                                     None, co_dir = co_dir)
    pkg.add_checkout_rules(builder.invocation.ruleset,
                           co_name, 
                           vcs_handler)




# End file.


