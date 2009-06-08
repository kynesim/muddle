"""
Write an initialisation script into 
$(MUDDLE_TARGET_LOCATION)/bin/$(something)

This is really just using utils.subst_file() with the
current environment, on a resource stored in resources/
"""

import muddled
import muddled.pkg as pkg
import muddled.env_store
import muddled.depend as depend
import muddled.utils as utils
import os
import muddled.subst as subst


class InitScriptBuilder(pkg.PackageBuilder):
    """
    Build an init script
    """

    def __init__(self, name, role, script_name,  builder):
        pkg.PackageBuilder.__init__(self, name, role)
        self.builder = builder
        self.script_name = script_name

    def build_label(self, label):
        """
        Install is the only one we care about ..
        """
        
        if (label.tag == utils.Tags.Installed):
            inst_dir = self.builder.invocation.package_install_path(self.name, 
                                                                   self.role)
            
            tgt_dir = os.path.join(inst_dir, "bin")
            src_file = self.builder.resource_file_name("initscript.sh")

            utils.ensure_dir(tgt_dir)
            tgt_file = os.path.join(tgt_dir, self.script_name)
            print "> Writing %s .. "%(tgt_file)
            subst.subst_file(src_file, tgt_file, None, os.environ)
        else:
            pass


def simple(builder, name, role, script_name):
    """
    Build an init script for the given role
    """

    the_pkg = InitScriptBuilder(name, role, script_name, builder)
    pkg.add_package_rules(builder.invocation.ruleset, 
                          name, role, the_pkg)


def medium(builder, name, roles, script_name):
    """
    Build an init script for the given roles
    """

    for role in roles:
        the_pkg = InitScriptBuilder(name, role, script_name, builder)
        pkg.add_package_rules(builder.invocation.ruleset, 
                              name, role, the_pkg)


# End file.


                
