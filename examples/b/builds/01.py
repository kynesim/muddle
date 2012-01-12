#! /usr/bin/env python
#
# Build description for the second example. We now have a
# package which is built from a checkout.

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple

def describe_to(builder):
    # Register a checkout
    muddled.checkouts.simple.relative(builder, "b_co")

    # Build pkg_b from it.
    muddled.pkgs.make.simple(builder, "pkg_b", "x86", "b_co")

    # And always build the role x86
    builder.invocation.add_default_role("x86")

# End file.
