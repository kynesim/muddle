"""
Builds a Linux kernel based on a checkout and some data about
where your config file resides.
"""

import muddled.pkg as pkg
from muddled.pkg import PackageBuilder
import muddled.utils as utils
import muddled.checkouts.simple as simple_checkouts
import muddled.checkouts.twolevel as twolevel_checkouts
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
        co_path = builder.invocation.checkout_path(self.co, domain = label.domain)
        build_path = builder.invocation.package_obj_path(label.name,
                                                         label.role, 
                                                         domain = label.domain)
        inst_path = builder.invocation.package_install_path(label.name,
                                                                 label.role,
                                                                 domain = label.domain)
        utils.ensure_dir(co_path)
        utils.ensure_dir(os.path.join(build_path, "obj"))
        utils.ensure_dir(inst_path)
        

        


    def build_label(self, builder, label):
        tag = label.tag

        self.ensure_dirs(builder, label)
        
        co_path = builder.invocation.checkout_path(self.co)
        build_path = builder.invocation.package_obj_path(label.name,
                                                         label.role)
        inst_path = builder.invocation.package_install_path(label.name,
                                                            label.role)

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
        combined_include_path = os.path.join(build_path, "fake-kernel-source")


        if (tag == utils.Tags.PreConfig):
            pass
        elif (tag == utils.Tags.Configured):
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
                raise utils.Failure("Cannot find kernel config source file %s"%config_src)
            utils.copy_file(config_src, dot_config)

        elif (tag == utils.Tags.Built):
            if self.in_place:
	        linux_src_path = os.path.join(build_path, "obj", self.linux_src)
            else:
		linux_src_path = os.path.join(co_path, self.linux_src)
            os.chdir(os.path.join(linux_src_path))
            utils.run_cmd("%s bzImage"%make_cmd)
            utils.run_cmd("%s modules"%make_cmd)
            utils.run_cmd("%s INSTALL_HDR_PATH=\"%s\" headers_install"%(make_cmd, hdr_path))
            utils.run_cmd("%s INSTALL_FW_PATH=\"%s\" firmware_install"%(make_cmd, fw_path))
            utils.run_cmd("%s INSTALL_MOD_PATH=\"%s\" modules_install"%(make_cmd, modules_path))

            # Now link up the kerneldir directory so that other people can build modules which
            # depend on us.
            utils.run_cmd("ln -fs %s %s"%(os.path.join(modules_path, "lib", "modules", 
                                                       self.kernel_version, "build"), 
                                          os.path.join(build_path, "kerneldir")))

            # .. and link kernelsource to the source directory.
            utils.run_cmd("ln -fs %s %s"%(linux_src_path,
                                          os.path.join(build_path, "kernelsource")))

            # This was a doomed idea, and remains here to show you that it's doomed.
            # Really, really doomed.
            #
            # - rrw 2009-06-18

            # Some - really irritating - kernel modules - require an include directory
            # which is the union of source and object kernel includes.
            #utils.run_cmd("rm -rf \"%s\""%combined_include_path)
            
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
            #utils.run_cmd("cp -r -t %s %s"%(os.path.join(actual_inc, "asm"), 
            #                                os.path.join(build_path, "include", "asm", "*")))
                                   
                                   


        elif (tag == utils.Tags.Installed):
            if (self.make_install):
                os.chdir(co_path)
                utils.run_cmd("make install")
        elif (tag == utils.Tags.PostInstalled):
            # .. and postinstall
            pass
        elif (tag == utils.Tags.Clean):
            os.chdir(os.path.join(co_path, self.linux_src))
            utils.run_cmd("%s clean"%make_cmd)
        elif (tag == utils.Tags.DistClean):
            self.dist_clean(builder, label)
        else:
            raise utils.Error("Invalid tag specified for "
                              "linux kernel build - %s"%(label))

    def dist_clean(self, builder, label):
        # Just wipe out the object file directory
        utils.recursively_remove(builder.invocation.package_obj_path(label.name, 
                                                                     label.role))



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
    pkg.add_package_rules(builder.invocation.ruleset, 
                          name, role, the_pkg)
    pkg.package_depends_on_checkout(builder.invocation.ruleset, 
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
    pkg.add_package_rules(builder.invocation.ruleset, 
                          name, role, the_pkg)
    pkg.package_depends_on_checkout(builder.invocation.ruleset, 
                                    name, role, checkout_name, the_pkg)
    


# End File.

                                                                
                                      
            
