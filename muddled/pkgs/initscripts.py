"""
Write an initialisation script into 
$(MUDDLE_TARGET_LOCATION)/bin/$(something)

This is really just using utils.subst_file() with the
current environment, on a resource stored in resources/

We also write a setvars script with a suitable set of
variables for running code in the context of the 
deployment, and any variables you've set in the 
environment store retrieved with get_env_store()
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

    def __init__(self, name, role, script_name,  builder, 
                 writeSetvarsSh = True, writeSetvarsPy = False):
        pkg.PackageBuilder.__init__(self, name, role)
        self.builder = builder
        self.script_name = script_name
        self.write_setvars_sh = writeSetvarsSh
        self.write_setvars_py = writeSetvarsPy

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
        
            # Write the setvars script
            env = get_env(self.builder, self.name, self.role)
            
            if (self.write_setvars_sh):
                setenv_file_name = os.path.join(tgt_dir, "setvars")
                sv_script  = env.get_setvars_script(self.script_name, 
                                                    env_store.EnvLanguage.Sh)
                
                out_f = open(setenv_file_name, "w")
                out_f.write(sv_script)
                out_f.close()

            if (self.write_setvars_py):
                # Now the python version .. 
                setenv_file_name = os.path.join(tgt_dir, "setvars.py")
                sv_script = env.get_setvars_script(self.script_name,
                                                   env_store.EnvLanguage.Python)
                out_f = open(setenv_file_name, "w")
                out_f.write(sv_script)
                out_f.close()
        else:
            pass



def simple(builder, name, role, script_name, writeSetvarsSh = True, 
           writeSetvarsPy = False):
    """
    Build an init script for the given role
    """

    the_pkg = InitScriptBuilder(name, role, script_name, builder, 
                                writeSetvarsSh = writeSetvarsSh, 
                                writeSetvarsPy = writeSetvarsPy)
    pkg.add_package_rules(builder.invocation.ruleset, 
                          name, role, the_pkg)
    setup_default_env(builder, get_env(builder, name, role))


def medium(builder, name, roles, script_name, writeSetvarsSh = True, 
           writeSetvarsPy = False):
    """
    Build an init script for the given roles
    """

    for role in roles:
        the_pkg = InitScriptBuilder(name, role, script_name, builder, 
                                    writeSetvarsSh = writeSetvarsSh, 
                                    writeSetvarsPy = writeSetvarsPy)
        pkg.add_package_rules(builder.invocation.ruleset, 
                              name, role, the_pkg)
    setup_default_env(builder, get_env(builder, name, role))


def get_env(builder, name, role):
    """
    Retrieve the runtime environment builder for this initscripts
    package
    """
    return self.builder.invocation.get_environment_for(
                depend.Label(
                    utils.LabelKind.Package,
                    self.name, self.role,
                    utils.Tags.RuntimeEnv))

def setup_default_env(builder, env):
    """
    Set up the default setenv environment for an initscripts run,
    assuming that MUDDLE_TARGET_LOCATION includes the target location
    (which it typically will - it's a convention shared by all the
    deployments we provide and should be shared by yours too)
    """

    env.set_type("LD_LIBRARY_PATH", muddled.env_store.EnvType.Path)
    env.set_type("PATH", muddled.env_store.EnvType.Path)
    env.set_type("PKG_CONFIG_PATH", muddled.env_store.EnvType.Path)
    env.prepend_expr("LD_LIBRARY_PATH", 
                     env_store.append_expr("MUDDLE_TARGET_LOCATION", "/lib"))
    env.prepend_expr("PKG_CONFIG_PATH", 
                     env_store.append_expr("MUDDLE_TARGET_LOCATION", "/lib/pkgconfig")
    env.prepend_expr("PATH", 
                     env_store.append_expr("MUDDLE_TARGET_LOCATION", "/bin"))
                     
    

                                

# End file.


                
    
            env = orig_env.copy()
