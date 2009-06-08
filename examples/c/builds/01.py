#! /usr/bin/env python
#
# Build description for example C. This one has a brief test
# of instructions.

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple

def describe_to(builder):
    # Register a checkout
    muddled.checkouts.simple.relative(builder, "c_co")
    
    # Build pkg_c from it
    muddled.pkgs.make.simple(builder, "pkg_c", "x86", "c_co")
    
    # Set the default role ..
    builder.invocation.add_default_role("x86")

