#!  /usr/bin/env python
#
# An example of how to build a cpio archive as a
# deployment - e.g. for a Linux initrd.

import muddled
import muddled.pkgs.make
import muddled.deployments.cpio
import muddled.checkouts.simple

def describe_to(builder):
    # Checkout ..
    muddled.checkouts.simple.relative(builder, "cpio_co")
    muddled.pkgs.make.simple(builder, "pkg_cpio", "x86", "cpio_co")
    muddled.deployments.cpio.deploy(builder, "my_archive.cpio",
                                    {"x86": "/"},
                                    "cpio_dep", [ "x86" ])

    builder.add_default_role("x86")
    builder.by_default_deploy("cpio_dep")

# End file.
