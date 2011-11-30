#! /usr/bin/env python
#
# Build description for example D.
#
# Builds hello_world, and deploys it owned by root:root, notionally
#  in /opt/kynesim/example_d

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep

def describe_to(builder):
    # Register a checkout
    muddled.checkouts.simple.relative(builder, "d_co")
    muddled.pkgs.make.simple(builder, "pkg_d", "x86", "d_co")
    muddled.deployments.filedep.deploy(builder, "/opt/kynesim/example_d",
                                       "example_d", [ "x86" ])
    # If you don't specify a role, build this one.
    builder.invocation.add_default_role("x86")
    # 'muddle' from the root directory deploys ..
    builder.by_default_deploy("example_d")

# End file.

