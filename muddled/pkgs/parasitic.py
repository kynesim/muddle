"""
A package implementation that relies on a build in another role.

The rationale for this is as follows:

 - Sometimes you have a package that builds quite a lot of stuff
   (example binaries, etc.)
 - You want these binaries in your development builds because they
   are useful.
 - But you don't want them in some other roles because they unnecessarily
   bloat your ROM requirements.
 - .. and you don't want to rebuild the package because it is very big
   (dvsdk, I am looking at you).

What you want is a package which you can build into a separate role,
which invokes a 'make <your-target-here>' to install into that role from
wherever the package was originally built.

This is that package. Our Makefile targets are like:

[your root]-config:
[your root]-install:
[your root]-clean:
[your root]-distclean:

We set:

MUDDLE_SRC  - The original source directory (since we have no checkout of our own)
MUDDLE_ORIG_ROLE - The role of the package on which we are parasitic.
MUDDLE_ORIG_OBJ  - Object directory for that package.
MUDDLE_ORIG_INSTALL - Install directory for that package.
"""

import muddled.pkg as pkg
from muddled.pkg import PackageBuilder
import muddled.utils as utils
import muddled.checkouts.simple as simple_checkouts
import muddled.checkouts.twolevel as twolevel_checkouts
import muddled.checkouts.multilevel as multilevel_checkouts
import muddled.depend as depend
import muddled.rewrite as rewrite

from muddled.depend import Label
import os

DEFAULT_MAKEFILE_NAME = "Makefile.muddle"

class ParasiticBuilder(PackageBuilder):
    """
    Use make on a given external package to generate installation for
    this package.
    """

    def __init__(self, name, role, co, sourceRole,
                 targetName,
                 makefileName = None,
                 rewriteAutoconf = False):
        """
        Constructor for the parasitic package
        """
        PackageBuilder.__init__(self,name,role)
        self.co = co;
        self.source_role = sourceRole;
        self.target_name = targetName;
        self.makefile_name = makefileName;
        self.rewrite_autoconf = rewriteAutoconf;

    def guess_makefile_name(self):
        if (self.makefile_name is None):
            return DEFAULT_MAKEFILE_NAME
        else:
            return self.makefile_name

    def ensure_dirs(self, builder, label):
        """
        Make sure the relevant directories exist - this
        basically just means the install directory
        """
        co_label = Label(utils.LabelType.Package, self.name, self.role, domain=label.domain)
        utils.ensure_dir(inv.package_install_path(co_label))
        utils.ensure_dir(inv.package_obj_path(co_label))

    def _amend_env(self, co_path, label):
        """Amend the environment before building a label
        """
        # XXX Experimentally set MUDDLE_SRC for the "make" here, where we need it
        os.environ["MUDDLE_SRC"] = co_path

        # We really do want PKG_CONFIG_LIBDIR here - it prevents pkg-config
        # from finding system-installed packages.
        if (self.usesAutoconf):
            #print "> setting PKG_CONFIG_LIBDIR to %s"%(os.environ['MUDDLE_PKGCONFIG_DIRS_AS_PATH'])
            os.environ['PKG_CONFIG_LIBDIR'] = os.environ['MUDDLE_PKGCONFIG_DIRS_AS_PATH']
        elif(os.environ.has_key('PKG_CONFIG_LIBDIR')):
            # Make sure that pkg-config uses default if we're not setting it.
            #print "> removing PKG_CONFIG_LIBDIR from environment"
            del os.environ['PKG_CONFIG_LIBDIR']
        
        # Set MUDDLE_ORIG_OBJ to the original object directory.
        orig_label = Label(utils.LabelType.Package, self.name, self.source_role, domain=label.domain)
        os.environ["MUDDLE_ORIG_OBJ"] = inv.package_obj_path(orig_label)
        os.environ["MUDDLE_ORIG_INSTALL"] = inv.package_install_path(orig_label)
        os.environ["MUDDLE_ORIG_ROLE"] = self.source_role;
            
    def build_label(self,builder,label):
        """
        Build the relevant label
        """
        tag = label.tag

        self.ensure_dirs(builder, label)
        tmp = Label(utils.LabelType.Checkout, self.co, domain=label.domain)
        co_path = builder.invocation.checkout_path(tmp)
        with utils.Directory(co_path):
            self._amend_env(co_path)
            makefile_name = self.guess_makefile_name()
            make_args = ' -f %s'%(makefile_name)
            makefile_exists = os.path.exists(makefile_name)

            if (tag == utils.LabelTag.PreConfig):
                pass
            elif (tag == utils.LabelTag.Configured and makefile_exists):
                utils.run_cmd("make %s %s-config"%(make_args, self.target_name))
            elif (tag == utils.LabelTag.Built):
                pass
            elif (tag == utils.LabelTag.Installed and makefile_exists):
                utils.run_cmd("make %s %s-install"%(make_args, self.target_name))
            elif (tag ==utils.LabelTag.PostInstalled):
                if (self.rewrite_autoconf):
                    obj_path = builder.invocation.package_obj_path(label)
                    #print ">obj_path = %s"%(obj_path)
                    if (self.execRelPath is None):
                        sendExecPrefix = None
                    else:
                        sendExecPrefix = os.path.join(obj_path, self.execRelPath)

                    rewrite.fix_up_pkgconfig_and_la(builder, obj_path, execPrefix = sendExecPrefix)
            elif (tag == utils.LabelTag.Clean and makefile_exists):
                utils.run_cmd("make %s %s-clean"%(make_args, self.target_name))
            elif (tag == utils.LabelTag.DistClean and makefile_exists):
                utils.run_cmd("make %s %s-distclean"%(make_args, self.target_name))
            else:
                raise utils.MuddleBug("Invalid tag specified for ParasiticPackage building %s"%(label))

def simple(builder, to_role, target_name, name, role, checkout,
           makefile_name = None):
    """
    Build a package from another package's makefile.
    
    * to_role -  The role to build in.
    * target_name - The makefile target to use - we construct "<target_name>-config" etc. 
    * name - The package name to parasitise.
    * role - Role to parasitise.
    * checkout - Checkout in which the makefile to invoke resides.
    * makefile_name - The name of the makefile to call. If specified but nonexistent,
                      we assume that there are no instructions.
    """
    
                    
    
