#! /usr/bin/env python
#
# Build description for building a package (in this case kbus)
# from sources stored in its original repository.

import muddled
import muddled.pkgs.make
import muddled.pkg
import muddled.checkouts.simple
import muddled.deployments.filedep

def describe_to(builder):
    # Pull kbus from the original repository.
    muddled.checkouts.simple.absolute(builder = builder,
                                      co_name = "kbus",
                                      repo_url = "svn+http://kbus.googlecode.com/svn/trunk/kbus")

    # Pull a checkout that knows how to build it.
    muddled.checkouts.simple.relative(builder = builder,
                                      co_name = "kbusbuilder",
                                      repo_relative = "kbusbuilder")

    # Create a package that builds kbus using the kbusbuilder repo
    muddled.pkgs.make.simple(builder = builder,
                             name = "kbus",
                             role = "main",
                             checkout = "kbusbuilder",
                             simpleCheckout = False,
                             makefileName = "Makefile.kbus")

    # Assert that the kbus package depends on the original version of
    # kbus we pulled.
    muddled.pkg.package_depends_on_checkout(builder.ruleset,
                                            "kbus", "main",
                                            "kbus")

    # Let's deploy main somewhere ..
    muddled.deployments.filedep.deploy(builder, "/opt/kynesim/original_checkout",
                                       "orig_checkout", [ "main" ])

    # .. and set the default role
    builder.add_default_role("main")
    builder.by_default_deploy("orig_checkout")

# And that's all.

