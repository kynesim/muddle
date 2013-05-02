"""
Builds a Linux kernel based on a checkout and some data about
where your config file resides.

.. warning:: DEPRECATION WARNING - this whole module is deprecated. It is not
             portable for cross-compilation, and compared to using a simple
             Makefile.muddle, it is quite hard to understand.
"""

import muddled.pkg as pkg
from muddled.pkg import PackageBuilder
import muddled.utils as utils
import muddled.checkouts.simple as simple_checkouts
import muddled.checkouts.twolevel as twolevel_checkouts

from muddled.depend import Label
from muddled.withdir import Directory

import os

class LinuxKernel(PackageBuilder):
    """
    Build a Linux kernel.
    """

    def __init__(self, name, role, co, linuxSrc, configFile,
                 kernelVersion,
                 makeInstall = False, inPlace = False,
                 arch = None, crossCompile = None):
        """

        * builder - The builder we're going to use to build this kernel.
        * linuxSrc - Where the Linux kernel is relative to the co directory
          (usually something like 'linux-2.6.30')
        * configFile - Where the configuration file lives, relative to the
          linuxSrc directory.
        * makeInstall - Should we run 'make install' in the checkout when done?
          Commonly used to copy kernel images and the like to useful places.
        * inPlace - If true, we copy the kernel source and build it in place.
          If false, we build out of tree. Some modules - specifically, nVidia's
          graphics drivers - require an in-place build. This is best done by
          building them in a separate step and checking in the binaries since
          otherwise committing back to source control gets hard.
        * arch - what we should tell the kernel the target architecture is,
                 if any.
        * crossCompile - the prefix to apply to tools to get a cross-compiler
                 for the target - e.g. 'ia64-linux-'

        If arch and crossCompile are not specified, we will try to get them
        from the environment: arch will come from ARCHSPEC and crossCompile from
        PFX, so that if you've set up your tools right in rrw.py, cross-compiling
        a kernel will 'just work'.

        """

        PackageBuilder.__init__(self, name, role)
        self.co = co
        self.linux_src = linuxSrc
        self.config_file = configFile
        self.make_install = makeInstall
        self.kernel_version= kernelVersion
        self.in_place = inPlace
        self.arch = arch
        self.crossCompile = crossCompile

    def ensure_dirs(self, builder, label):
        """
        Make sure the relevant directories exist
        """
        tmp = Label(utils.LabelType.Checkout, self.co, domain=label.domain)
        co_path = builder.db.get_checkout_path(tmp)
        build_path = builder.package_obj_path(label)
        inst_path = builder.package_install_path(label)
        utils.ensure_dir(co_path)
        utils.ensure_dir(os.path.join(build_path, "obj"))
        utils.ensure_dir(inst_path)





    def build_label(self, builder, label):
        tag = label.tag

        self.ensure_dirs(builder, label)

        tmp = Label(utils.LabelType.Checkout, self.co, domain=label.domain)
        co_path = builder.db.get_checkout_path(tmp)
        build_path = builder.package_obj_path(label)

        make_cmd = "make"
        if not self.in_place:
            make_cmd = make_cmd + " O=%s"%(os.path.join(build_path, "obj"))

        # Annoyingly, giving 'ARCH=' doesn't work so we need to do this
        # 'properly'.

        if self.arch is not None:
            make_cmd = make_cmd + " ARCH=%s"%(self.arch)
        elif os.environ['ARCHSPEC'] is not None:
            make_cmd = make_cmd + " ARCH=%s"%(os.environ['ARCHSPEC'])

        if self.crossCompile is not None:
            make_cmd = make_cmd + " CROSS_COMPILE=%s"%(self.crossCompile)
        elif os.environ['PFX'] is not None:
            make_cmd = make_cmd + " CROSS_COMPILE=%s"%(os.environ['PFX'])

        # The kernel will append the necessary 'include' directory.
        hdr_path = os.path.join(build_path)
        fw_path = os.path.join(build_path, "firmware")
        modules_path = os.path.join(build_path, "modules")


        if (tag == utils.LabelTag.PreConfig):
            pass
        elif (tag == utils.LabelTag.Configured):
            # Copy the .config file across and run a distclean
            self.dist_clean(builder, label)
            self.ensure_dirs(builder,label)


            if self.in_place:
                # Build in place. Ugh.
                utils.ensure_dir(os.path.join(build_path, "obj", self.linux_src))
                utils.recursively_copy(os.path.join(co_path, self.linux_src),
                                       os.path.join(build_path, "obj", self.linux_src))
                dot_config = os.path.join(build_path, "obj", self.linux_src, ".config")
            else:
                dot_config = os.path.join(build_path, "obj", ".config")

            config_src = os.path.join(co_path, self.config_file)
            if not (os.path.exists(config_src)):
                raise utils.GiveUp("Cannot find kernel config source file %s"%config_src)
            utils.copy_file(config_src, dot_config)

        elif (tag == utils.LabelTag.Built):
            if self.in_place:
	        linux_src_path = os.path.join(build_path, "obj", self.linux_src)
            else:
		linux_src_path = os.path.join(co_path, self.linux_src)
            with Directory(os.path.join(linux_src_path)):
                utils.run0("%s bzImage"%make_cmd)
                utils.run0("%s modules"%make_cmd)
                utils.run0("%s INSTALL_HDR_PATH=\"%s\" headers_install"%(make_cmd, hdr_path))
                utils.run0("%s INSTALL_FW_PATH=\"%s\" firmware_install"%(make_cmd, fw_path))
                utils.run0("%s INSTALL_MOD_PATH=\"%s\" modules_install"%(make_cmd, modules_path))

                # Now link up the kerneldir directory so that other people can build modules which
                # depend on us.
                utils.run0("ln -fs %s %s"%(os.path.join(modules_path, "lib", "modules",
                                                        self.kernel_version, "build"),
                                           os.path.join(build_path, "kerneldir")))

                # .. and link kernelsource to the source directory.
                utils.run0("ln -fs %s %s"%(linux_src_path,
                                           os.path.join(build_path, "kernelsource")))

            # This was a doomed idea, and remains here to show you that it's doomed.
            # Really, really doomed.
            #
            # - rrw 2009-06-18

            # Some - really irritating - kernel modules - require an include directory
            # which is the union of source and object kernel includes.
            #combined_include_path = os.path.join(build_path, "fake-kernel-source")
            #utils.run0("rm -rf \"%s\""%combined_include_path)

            #actual_inc = os.path.join(combined_include_path, "include")
            #utils.ensure_dir(actual_inc)

            # .. and this for autogenerated include files.
            # (needs to be first because it gets the asm link right)
            #utils.recursively_copy(os.path.join(build_path, "obj", "include"),
             #                      actual_inc)


            # .. and this for source files which have been sanitised for userspace.
            #utils.recursively_copy(os.path.join(linux_src_path,
            #                                    "include"),
            #                       actual_inc)

            # .. and this for the asm files themselves. Ugh.
            #utils.run0("cp -r -t %s %s"%(os.path.join(actual_inc, "asm"),
            #                                os.path.join(build_path, "include", "asm", "*")))


        elif (tag == utils.LabelTag.Installed):
            if (self.make_install):
                with Directory(co_path):
                    utils.run0("make install")
        elif (tag == utils.LabelTag.PostInstalled):
            # .. and postinstall
            pass
        elif (tag == utils.LabelTag.Clean):
            with Directory(os.path.join(co_path, self.linux_src)):
                utils.run0("%s clean"%make_cmd)
        elif (tag == utils.LabelTag.DistClean):
            self.dist_clean(builder, label)
        else:
            raise utils.MuddleBug("Invalid tag specified for "
                              "linux kernel build - %s"%(label))

    def dist_clean(self, builder, label):
        # Just wipe out the object file directory
        utils.recursively_remove(builder.package_obj_path(label))



def simple(builder, name, role, checkout, linux_dir, config_file,
           kernel_version,
           makeInstall = False, inPlace = False,
           arch = None, crossCompile = None):
    """
    Build a linux kernel in the given checkout where the kernel sources
    themselves are in checkout/linux_dir and the config file in
    checkout/config_file.

    * kernel_version - The version of the kernel (e.g. '2.6.30').
    """

    simple_checkouts.relative(builder, checkout)
    the_pkg = LinuxKernel(name, role,  checkout, linux_dir, config_file,
                          kernel_version,
                          makeInstall = makeInstall, inPlace = inPlace,
                          arch = arch, crossCompile = crossCompile)
    pkg.add_package_rules(builder.ruleset,
                          name, role, the_pkg)
    pkg.package_depends_on_checkout(builder.ruleset,
                                    name, role, checkout, the_pkg)


def twolevel(builder, name, role, checkout_dir, checkout_name, linux_dir,
             config_file,
             kernel_version ,
             makeInstall = False, inPlace = False,
             arch = None, crossCompile = None):
    """
    Build a linux kernel with a two-level checkout name.

    * kernel_version - The version of the kernel (e.g. '2.6.30').
    """
    twolevel_checkouts.twolevel(builder, checkout_dir, checkout_name)

    the_pkg = LinuxKernel(name, role, checkout_name, linux_dir, config_file,
                          kernel_version,
                          makeInstall = makeInstall, inPlace = inPlace,
                          arch = arch, crossCompile = crossCompile)
    pkg.add_package_rules(builder.ruleset,
                          name, role, the_pkg)
    pkg.package_depends_on_checkout(builder.ruleset,
                                    name, role, checkout_name, the_pkg)



# End File.




