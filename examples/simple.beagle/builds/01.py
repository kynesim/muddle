#! /usr/bin/env python

"""Muddle build description for a "plain" OMAP build on the Beagleboard.

At least initially, we're trying to build a Linux+busybox system.

The role we're providing is 'omap'.
"""

import os

import muddled.deployments.filedep as filedep
import muddled.pkgs.aptget as aptget
import muddled.checkouts.simple
import muddled.depend
from muddled.depend import Label
import muddled.pkgs.make as make

import wget

def describe_to(builder):

    role = 'omap'
    roles = ['omap']

    builder.invocation.add_default_role(role)

    # filedep.deploy(builder, target_dir, name, roles)
    #
    # Register a file deployment.
    #
    # The deployment will take the roles specified in the role list, and build
    # them into a deployment at deploy/[name].
    #
    # The deployment should eventually be located at target_dir.

    filedep.deploy(builder, 
                   '/',
                   'omap',
                   roles)

    # Both Linux and Busybox share some environment we'd like to specify
    # only once. The mechanism for doing this is a little bit cunning
    label = Label.from_string('package:*{omap}/*')      # i.e., all our packages
    # We can retrieve the "environment" (technically, an environment Store)
    # that will be used for that label - this will create one if it doesn't
    # exist yet
    env = builder.invocation.get_environment_for(label)
    # And adding values to that is simple
    env.set("MUDDLE_CROSS_COMPILE", "/opt/codesourcery/arm-2008q3/bin/arm-none-linux-gnueabi-")
    env.set("MUDDLE_ARCH", "arm")

    # There's a variety of things we need on (this, the host) system
    # in order to build - I hope I've got this right (difficult to tell
    # as I already have some stuff installed on *my* development system)
    aptget.simple(builder, 'development_packages', role,
            ['zlib1g-dev', 'uboot-mkimage'])

    # According to http://omappedia.org/wiki/LinuxOMAP_Kernel_Project, we get
    # our OMAP kernel from:
    muddled.checkouts.simple.absolute(builder, 'omap_kernel',
            'git+git://git.kernel.org/pub/scm/linux/kernel/git/tmlind/linux-omap-2.6.git')

    # Once we've got one worked out, we'll also want to retrieve a default
    # kernel configuration (we don't, eventually, want to make the developer
    # have to work that out every time!)

    # We'll aim to make that with an out-of-tree makefile
    # We could make a tailored subclass of muddled.pkgs.linux_kernel, and use
    # that to build our kernel. I may still do that once I've figured out how
    # it is different (one notable change is we're building uImage instead of
    # zImage). For now, it's probably easier to have a Makefile.muddle
    make.medium(builder,
                name = "omap_kernel",    # package name
                roles = roles,
                checkout = "helpers",
                deps = [],
                makefileName = os.path.join("omap_kernel","Makefile.muddle"))

    muddled.pkg.package_depends_on_checkout(builder.invocation.ruleset,
                                    "omap_kernel",  # this package
                                    role,           # in this role
                                    "omap_kernel")  # depends on this checkout

    # On top of that, we want to build busybox
    #
    # According to the busybox website, we can retrieve sources via git:
    #
    # To grab a copy of the BusyBox repository using anonymous git access::
    #
    #   git clone git://busybox.net/busybox.git
    #
    # Once you have the repository, stable branches can be checked out by
    # doing::
    #
    #   git checkout remotes/origin/1_NN_stable
    #
    # Once you've checked out a copy of the source tree, you can update your
    # source tree at any time so it is in sync with the latest and greatest by
    # entering your BusyBox directory and running the command::
    #
    #   git pull

    # So, for the moment, at least, let's go with the latest from source
    # control (when we're finalising this, we're maybe better identifying
    # a particular release to stick to)
    muddled.checkouts.simple.absolute(builder, 'busybox',
            'git+git://busybox.net/busybox.git')

    # We'll aim to make that with an out-of-tree makefile
    #
    # 'deps' is a list of package names, which our make depends on.
    #
    # Specifically, for each <name> in 'deps', and for each <role> in 'roles',
    # we will depend on "package:<name>{<role>}/postinstalled"
    make.medium(builder,
                name = "busybox",    # package name
                roles = roles,
                checkout = "helpers",
                deps = [ 'omap_kernel' ],
                makefileName = os.path.join("busybox","Makefile.muddle"))

    # And we also depend on having actually checked out busybox
    muddled.pkg.package_depends_on_checkout(builder.invocation.ruleset,
                                    "busybox",      # this package
                                    role,           # in this role
                                    "busybox",      # depends on this checkout
                                    None)


    # Can we use the same bootloader and such that we already had for the
    # android build?

    # The bootloader and related items, which go into the FAT32 partition on
    # the flash card, are retrieved from the net (eventually, I hope we'll be
    # building u-boot, but for now the binary should do)
    muddled.checkouts.simple.absolute(builder, 'MLO',
            'wget+http://free-electrons.com/pub/demos/beagleboard/android/MLO')
    muddled.checkouts.simple.absolute(builder, 'u-boot',
            'wget+http://free-electrons.com/pub/demos/beagleboard/android/u-boot.bin')

    # We need some way of getting them installed - let's foreshadow the day when
    # we actually want to build u-boot ourselves, and pretend
    make.medium(builder,
                name = "u-boot",    # package name
                roles = roles,
                checkout = "helpers",
                deps = [],
                makefileName = os.path.join("u-boot","Makefile.muddle"))
    muddled.pkg.package_depends_on_checkout(builder.invocation.ruleset,
                                    "u-boot",       # this package
                                    role,           # in this role
                                    "u-boot",       # depends on this checkout
                                    None)
    # Oh, and this one as well...
    rule = muddled.depend.depend_one(None,
                              Label.from_string('package:u-boot{%s}/built'%role),
                              Label.from_string('checkout:MLO/checked_out'))
    builder.invocation.ruleset.add(rule)


    # And, of course, we need (the rest of) our Linux filesystem
    muddled.checkouts.simple.absolute(builder, 'rootfs',
            'bzr+ssh://bzr@palmera.c.kynesim.co.uk//opt/kynesim/projects/052/rootfs')
    make.simple(builder, 'rootfs', role, 'rootfs', config=False,
            makefileName='Makefile.muddle')

    # But we depend on busybox to have installed the various binaries first
    rule = muddled.depend.depend_one(None,
                              Label.from_string('package:rootfs/installed'),
                              Label.from_string('package:busybox/installed'))
    builder.invocation.ruleset.add(rule)

    # Deploy all our roles
    builder.by_default_deploy_list(roles)
