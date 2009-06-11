"""
Builds a Linux kernel based on a checkout and some data about
where your config file resides.
"""

import muddled.pkg as pkg
from muddled.pkg import PackageBuilder
import muddled.utils as utils
import muddled.checkouts.simple as simple_checkouts
import os

class LinuxKernel(PackageBuilder):
    """
    Build a Linux kernel.
    """

    def __init__(self, name, role, builder, co, linuxSrc, configFile):
        """
        
        @param builder    The builder we're going to use to build this kernel.
        @param linuxSrc   Where the Linux kernel is relative to the co directory 
                            (usually something like 'linux-2.6.30')
        @param configFile Where the configuration file lives, relative to the
                           linuxSrc directory.
        """
        
        PackageBuilder.__init__(self, name, role)
        self.builder = builder
        self.co = co
        self.linux_src = linuxSrc
        self.config_file = configFile

    def ensure_dirs(self, label):
        """
        Make sure the relevant directories exist
        """
        co_path = self.builder.invocation.checkout_path(self.co)
        build_path = self.builder.invocation.package_obj_path(label.name,
                                                              label.role)
        inst_path = self.builder.invocation.package_install_path(label.name,
                                                                 label.role)
        utils.ensure_dir(co_path)
        utils.ensure_dir(build_path)
        utils.ensure_dir(inst_path)


    def build_label(self, label):
        tag = label.tag

        self.ensure_dirs(label)
        
        co_path = self.builder.invocation.checkout_path(self.co)
        build_path = self.builder.invocation.package_obj_path(label.name,
                                                              label.role)
        inst_path = self.builder.invocation.package_install_path(label.name,
                                                                 label.role)

        make_cmd = "make"
        make_cmd = make_cmd + " O=%s"%(self.builder.invocation.package_obj_path(label.name,
                                                                     label.role))


        if (tag == utils.Tags.PreConfig):
            pass
        elif (tag == utils.Tags.Configured):
            # Copy the .config file across and run a distclean
            self.dist_clean(label)
            self.ensure_dirs(label)
            config_src = os.path.join(co_path, self.config_file)
            if not (os.path.exists(config_src)):
                raise utils.Failure("Cannot find kernel config source file %s"%config_src)
            
            dot_config = os.path.join(build_path, ".config")
            utils.copy_file(config_src, dot_config)
        elif (tag == utils.Tags.Built):
            os.chdir(os.path.join(co_path, self.linux_src))
            utils.run_cmd("%s bzImage"%make_cmd)
        elif (tag == utils.Tags.Installed):
            # We'll leave installation for another day
            pass
        elif (tag == utils.Tags.PostInstalled):
            # .. and postinstall
            pass
        elif (tag == utils.Tags.Clean):
            os.chdir(os.path.join(co_path, self.linux_src))
            utils.run_cmd("%s clean"%make_cmd)
        elif (tag == utils.Tags.DistClean):
            self.dist_clean(label)
        else:
            raise utils.Error("Invalid tag specified for " + 
                              "linux kernel build - %s"%(label))

    def dist_clean(self, label):
        # Just wipe out the object file directory
        utils.recursively_remove(self.builder.invocation.package_obj_path(label.name, 
                                                                          label.role))

def simple(builder, name, role, checkout, linux_dir, config_file):
    """
    Build a linux kernel in the given checkout where the kernel sources
    themselves are in checkout/linux_dir and the config file in 
    checkout/config_file
    """
    
    simple_checkouts.relative(builder, checkout)
    the_pkg = LinuxKernel(name, role, builder, checkout, linux_dir, config_file)
    pkg.add_package_rules(builder.invocation.ruleset, 
                          name, role, the_pkg)
    pkg.package_depends_on_checkout(builder.invocation.ruleset, 
                                    name, role, checkout, the_pkg)



# End File.


                                                                 
                                                                
                                      
            
