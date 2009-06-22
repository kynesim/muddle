"""
Some standard package implementations to cope with packages that
use Make
"""

import muddled.pkg as pkg
from muddled.pkg import PackageBuilder
import muddled.utils as utils
import muddled.checkouts.simple as simple_checkouts
import muddled.checkouts.twolevel as twolevel_checkouts
import muddled.depend as depend
import os

class MakeBuilder(PackageBuilder):
    """
    Use make to build your package from the given checkout.

    We assume that the makefile is smart enough to build in the
    object directory, since any other strategy (e.g. convolutions
    involving cp) will lead to dependency-based disaster.
    """
    
    def __init__(self, name, role, builder, co, config = True, 
                 perRoleMakefiles = False, 
                 makefileName = None):
        """
        Constructor for the make package.
        """
        PackageBuilder.__init__(self, name, role)
        self.builder = builder
        self.co = co
        self.has_make_config = config
        self.per_role_makefiles = perRoleMakefiles
        self.makefile_name = makefileName


    def ensure_dirs(self):
        """
        Make sure all the relevant directories exist
        """
        inv = self.builder.invocation
        if not os.path.exists(inv.checkout_path(self.co)):
            raise utils.Error("Path %s for checkout %s does not exist"%
                              (inv.checkout_path(self.co), self.co))

        utils.ensure_dir(inv.package_obj_path(self.name, self.role))
        utils.ensure_dir(inv.package_install_path(self.name, self.role))

    def build_label(self, label):
        """
        Build the relevant label. We'll assume that the
        checkout actually exists
        """
        tag = label.tag

        self.ensure_dirs()
        
        co_path = self.builder.invocation.checkout_path(self.co)
        os.chdir(co_path)

        if self.makefile_name is None:
            makefile_name = "Makefile"
        else:
            makefile_name = self.makefile_name

        if self.per_role_makefiles and label.role is not None:
            make_args = " -f %s.%s"%(makefile_name,label.role)
        else:
            make_args = " -f %s"%(makefile_name)

        if (tag == utils.Tags.PreConfig):
            # Preconfigure - nothing need be done
            pass
        elif (tag == utils.Tags.Configured):
            # We should probably do the configure thing ..
            if (self.has_make_config):
                utils.run_cmd("make %s config"%make_args)
        elif (tag == utils.Tags.Built):
            utils.run_cmd("make %s"%make_args)
        elif (tag == utils.Tags.Installed):
            utils.run_cmd("make %s install"%make_args)
        elif (tag == utils.Tags.PostInstalled):
            pass
        elif (tag == utils.Tags.Clean):
            utils.run_cmd("make %s clean"%make_args)
        elif (tag == utils.Tags.DistClean):
            utils.run_cmd("make %s distclean"%make_args)
        else:
            raise utils.Error("Invalid tag specified for " + 
                              "MakePackage building %s"%(label))
        

def simple(builder, name, role, checkout, simpleCheckout = False, config = True, 
           perRoleMakefiles = False, 
           makefileName = None):
    """
    Build a package controlled by make, called name with role role 
    from the sources in checkout checkout
    
    @param simpleCheckout If True, register the checkout too.
    @param config   If True, we have make config. If false, we don't.
    @param perRoleMakefiles  If True, we run 'make -f Makefile.<rolename>' instead of 
                              just make.

    """
    if (simpleCheckout):
        simple_checkouts.relative(builder, checkout)

    the_pkg = MakeBuilder(name, role, builder, checkout, config = config, 
                          perRoleMakefiles = perRoleMakefiles,
                          makefileName = makefileName)
    # Add the standard dependencies ..
    pkg.add_package_rules(builder.invocation.ruleset, 
                          name, role, the_pkg)
    # .. and make us depend on the checkout.
    pkg.package_depends_on_checkout(builder.invocation.ruleset,
                                    name, role, checkout, the_pkg)
    attach_env(builder, name, role, checkout)

def medium(builder, name, roles, checkout, deps, dep_tag = utils.Tags.PreConfig, 
           simpleCheckout = True, config = True, perRoleMakefiles = False, 
           makefileName = None):
    """
    Build a package controlled by make, in the given roles with the
    given dependencies in each role.
    
    @param simpleCheckout  If True, register the checkout as simple checkout too.
    @param dep_tag         The tag to depend on being installed before you'll build.
    @param perRoleMakefiles  If True, we run 'make -f Makefile.<rolename>' instead of 
                              just make.
    """
    if (simpleCheckout):
        simple_checkouts.relative(builder, checkout)
        
    for r in roles:
        simple(builder, name, r, checkout, config = config, 
               perRoleMakefiles = perRoleMakefiles,
               makefileName = makefileName)
        pkg.package_depends_on_packages(builder.invocation.ruleset,
                                       name, r, dep_tag, 
                                       deps)
        attach_env(builder, name, r, checkout)

def twolevel(builder, name, roles, 
             co_dir, co_name, 
             deps, dep_tag = utils.Tags.PreConfig, 
             simpleCheckout = True, config = True, perRoleMakefiles = False, 
             makefileName = None):
    """
    Build a package controlled by make, in the given roles with the
    given dependencies in each role.
    
    @param simpleCheckout  If True, register the checkout as simple checkout too.
    @param dep_tag         The tag to depend on being installed before you'll build.
    @param perRoleMakefiles  If True, we run 'make -f Makefile.<rolename>' instead of 
                              just make.
    """
    if (simpleCheckout):
        twolevel_checkouts.twolevel(builder, co_dir, co_name)
        
    for r in roles:
        simple(builder, name, r, co_name, config = config, 
               perRoleMakefiles = perRoleMakefiles,
               makefileName = makefileName)
        pkg.package_depends_on_packages(builder.invocation.ruleset,
                                       name, r, dep_tag, 
                                       deps)
        attach_env(builder, name, r, co_name)

                                       

def single(builder, name, role, deps):
    """
    A simple make package with a single checkout named after the package and
    a single role
    """
    medium(builder, name, [ role ], name, deps)
    
def attach_env(builder, name, role, checkout):
    """
    Write the environment which attaches MUDDLE_SRC to makefiles.
    """
    env = builder.invocation.get_environment_for(
        depend.Label(utils.LabelKind.Package, 
                     name, role, "*"))
    env.set("MUDDLE_SRC", builder.invocation.checkout_path(checkout))



# End file.
            
        
