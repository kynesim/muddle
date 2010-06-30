#! /usr/bin/env python
#
# Build description for an example GNU package.
#
# This example shows you how to manipulate arguments to configure to 
#  persuade an autoconf package to build out of tree.
#
# You'll need to unpack a copy of GNU screen into screen-4.0.3 ,
# alongside the Makefile.muddle already in there.

import muddled
import muddled.pkgs.make
import muddled.checkouts.simple
import muddled.deployments.filedep

def describe_to(builder):
    # Register a checkout
    muddled.checkouts.simple.relative(builder, "screen-4.0.3")
    muddled.pkgs.make.simple(builder, "screen", "x86", "screen-4.0.3", 
                             usesAutoconf = True, 
                             rewriteAutoconf = True,
                             makefileName = "Makefile.muddle")

    muddled.deployments.filedep.deploy(builder, "/opt/kynesim/screen-example", 
                                       "screen", [ "x86" ])
    # If you don't specify a role, build this one.
    builder.invocation.add_default_role("x86")
    # 'muddle' from the root directory deploys .. 
    builder.by_default_deploy("screen")

# End file.

