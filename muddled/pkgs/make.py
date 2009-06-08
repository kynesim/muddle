"""
Some standard package implementations to cope with packages that
use Make
"""

import muddled.pkg as pkg
from muddled.pkg import PackageBuilder
import muddled.utils as utils
import os

class MakeBuilder(PackageBuilder):
    """
    Use make to build your package from the given checkout.

    We assume that the makefile is smart enough to build in the
    object directory, since any other strategy (e.g. convolutions
    involving cp) will lead to dependency-based disaster.
    """
    
    def __init__(self, name, role, builder, co):
        """
        Constructor for the make package.
        """
        PackageBuilder.__init__(self, name, role)
        self.builder = builder
        self.co = co


    def ensure_dirs(self):
        """
        Make sure all the relevant directories exist
        """
        inv = self.builder.invocation
        if not os.path.exists(inv.checkout_path(self.co)):
            raise utils.Error("Path for checkout %s does not exist"%self.co)

        utils.ensure_dir(inv.package_obj_path(self.name, self.role))
        utils.ensure_dir(inv.package_install_path(self.name, self.role))

    def build_label(self, label):
        """
        Build the relevant label. We'll assume that the
        checkout actually exists
        """
        tag = label.tag

        self.ensure_dirs()
        os.chdir(self.builder.invocation.checkout_path(self.co))

        if (tag == utils.Tags.PreConfig):
            # Preconfigure - nothing need be done
            pass
        elif (tag == utils.Tags.Configured):
            # We should probably do the configure thing ..
            utils.run_cmd("make config")
        elif (tag == utils.Tags.Built):
            utils.run_cmd("make")
        elif (tag == utils.Tags.Installed):
            utils.run_cmd("make install")
        elif (tag == utils.Tags.PostInstalled):
            pass
        elif (tag == utils.Tags.Clean):
            utils.run_cmd("make clean")
        elif (tag == utils.Tags.DistClean):
            utils.run_cmd("make distclean")
        else:
            raise utils.Error("Invalid tag specified for " + 
                              "MakePackage building %s"%(label))
        

def simple(builder, name, role, checkout):
    """
    Build a package controlled by make, called name with role role 
    from the sources in checkout checkout
    """
    the_pkg = MakeBuilder(name, role, builder, checkout)
    # Add the standard dependencies ..
    pkg.add_package_rules(builder.invocation.ruleset, 
                          name, role, the_pkg)
    # .. and make us depend on the checkout.
    pkg.package_depends_on_checkout(builder.invocation.ruleset,
                                    name, role, checkout, the_pkg)


# End file.
            
        
