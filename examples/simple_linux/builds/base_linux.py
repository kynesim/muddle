#! /usr/bin/env python
#
# Build description for building a simple Linux system
#
# It turns out that all you need here is:
#
#  * A Linux kernel
#  * Busybox
#  * udev
#  * Some files in /etc
#
# DANGER WILL ROBINSON! This example hasn't been tested (at all)
# - though it is copied from a system that does actually work;
# bug fixes and improvements welcomed! - rrw 2009-08-03

import muddled
import muddled.pkgs.make as make
import muddled.pkgs.linux_kernel as linux_kernel
import muddled.checkouts.simple as co_simple
import muddled.deployments.filedep as filedep
import muddled.deployments.cpio as cpio
import muddled.deployment as deployment
import muddled.pkg as pkg
import sys

def describe_to(builder):
    """
    Construct a very basic Linux system
    """

    # We want a kernel..
    linux_kernel.simple(builder,
                        name = "kernel",
                        checkout = "kernel-2.6.30-1",
                        linux_dir = "linux-2.6.30",
                        config_file = "kernel_config",
                        kernel_version = "2.6.30",
                        makeInstall = False)

    # Steal a few basic libraries from Debian.
    deb.simple(builder,
               coName = "ubuntu-9.04",
               name = "libc6",
               roles = [ "root" ],
               depends_on = [ ],
               pkgFile = "libc6_2.9.4-ubuntu6_i386.deb")
    deb.simple(builder,
               coName = "ubuntu-9.04",
               name = "libgcc1",
               roles = [ "root" ],
               depends_on = [ "libc6" ],
               pkgFile = "libgcc1_4.3.3-5ubuntu4_i386.deb")

    # If you want networking, you'll need nss too ..
    deb.simple(builder,
               coName = "ubuntu-9.04",
               name = "libnss",
               roles = [ "root" ],
               depends_on = [ "libc6" ],
               pkgFile = "libnss3-1d_3.12.2-rc1-0ubuntu2_i386.deb")
    deb.simple(builder,
               coName = "ubuntu-9.04",
               name = "libnss-mdns",
               roles = [ "root" ],
               depends_on = [ "libc6" ],
               pkgFile = "libnss-mdns_0.10-3ubuntu2_i386.deb")


    # Some shells 'n' stuff :-)
    make.simple(builder,
                name = "busybox",
                roles = [ "root" ],
                checkout = "busybox-1.14.1",
                deps = [ "libc6" ],
                makefileName = "Makefile.muddle")

    make.simple(builder,
                name = "udev",
                roles = [ "root" ],
                checkout = "udev-142",
                deps = [ "libc6" ],
                makefileName = "Makefile.muddle")

    make.simple(builder,
                name = "etc-files",
                roles = [ "root" ],
                checkout = "etc-files",
                deps = [ "libc6" ],
                makefileName = "Makefile.muddle")

    # Not strictly necessary, but let's face it - you're
    # going to want DHCP
    make.simple(builder,
                name = "dhcpcd",
                roles = [ "root" ],
                checkout = "dhcpcd-5.0.4",
                deps = [ ],
                makefileName = "Makefile.muddle")

    # Declare the Ubuntu checkout explicitly, since the
    # deb builder obviously doesn't declare it every
    # time it's used.
    co_simple.relative(builder,
                       "ubuntu-9.04")

    # OK. Deploy the ramdisk
    cpio.deploy(builder, "root.cpio",
                { "root" : "/" },
                "root",
                [ "root" ])

    # Construct a collector to take the cpio archive and kernel
    # we've built and put them somewhere convenient.

    collect.deploy(builder, "firmware")
    collect.copy_from_package_obj(builder,
                                  name = "firmware",
                                  pkg_name = "kernel",
                                  pkg_role = "kernel",
                                  rel = "obj/arch/i386/boot/bzImage",
                                  dest = "vmlinuz")
    collect.copy_from_deployment(builder,
                                 name = "firmware",
                                 dep_name = "root",
                                 rel = "root.cpio",
                                 dest = "initrd",
                                 recursive = False,
                                 copyExactly = False)



    builder.by_default_deploy_list(["root", "firmware"])


# .. and that's all, folks.

