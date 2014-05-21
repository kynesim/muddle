"""
Write an initialisation script into
$(MUDDLE_TARGET_LOCATION)/bin/$(something)

This is really just using utils.subst_file() with the
current environment, on a resource stored in resources/.

We also write a setvars script with a suitable set of
variables for running code in the context of the
deployment, and any variables you've set in the
environment store retrieved with get_env_store().
"""

import muddled.pkg as pkg
import muddled.env_store as env_store
import muddled.depend as depend
import muddled.utils as utils
import muddled.subst as subst
from muddled.depend import Label

import os


class InitScriptBuilder(pkg.PackageBuilder):
    """
    Build an init script.
    """

    def __init__(self, name, role, script_name,
                 deployments,
                 writeSetvarsSh = True, writeSetvarsPy = False):
        pkg.PackageBuilder.__init__(self, name, role)
        self.script_name = script_name
        self.deployments = deployments
        self.write_setvars_sh = writeSetvarsSh
        self.write_setvars_py = writeSetvarsPy

    def build_label(self, builder, label):
        """
        Install is the only one we care about ..
        """

        if (label.tag == utils.LabelTag.Installed):
            tmp = Label(utils.LabelType.Package, self.name, self.role, domain=label.domain)
            inst_dir = builder.package_install_path(tmp)

            tgt_dir = os.path.join(inst_dir, "bin")
            src_file = builder.resource_file_name("initscript.sh")

            utils.ensure_dir(tgt_dir)
            tgt_file = os.path.join(tgt_dir, self.script_name)
            print "> Writing %s .. "%(tgt_file)
            subst.subst_file(src_file, tgt_file, None, os.environ)
            os.chmod(tgt_file, 0755)

            # Write the setvars script
            env = get_effective_env(builder, self.name, self.role,
                                    domain = label.domain)
            effective_env = env.copy()
            env_store.add_install_dir_env(effective_env, "MUDDLE_TARGET_LOCATION")


            for d in self.deployments:
                # Merge in the relevant deployment environments.
                lbl = depend.Label(utils.LabelType.Deployment,
                                   d,
                                   None,
                                   utils.LabelTag.Deployed,
                                   domain = label.domain)
                effective_env.merge(builder.get_environment_for(
                        lbl))

            if (self.write_setvars_sh):
                setenv_file_name = os.path.join(tgt_dir, "setvars")
                sv_script  = effective_env.get_setvars_script(builder,
                                                              self.script_name,
                                                              env_store.EnvLanguage.Sh)

                out_f = open(setenv_file_name, "w")
                out_f.write(sv_script)
                out_f.close()

            if (self.write_setvars_py):
                # Now the python version ..
                setenv_file_name = os.path.join(tgt_dir, "setvars.py")
                sv_script = effective_env.get_setvars_script(builder,
                                                             self.script_name,
                                                   env_store.EnvLanguage.Python)
                out_f = open(setenv_file_name, "w")
                out_f.write(sv_script)
                out_f.close()
        else:
            pass



def simple(builder, name, role, script_name, deployments = [ ],
           writeSetvarsSh = True,
           writeSetvarsPy = False):
    """
    Build an init script for the given role.
    """

    the_pkg = InitScriptBuilder(name, role, script_name,
                                deployments,
                                writeSetvarsSh = writeSetvarsSh,
                                writeSetvarsPy = writeSetvarsPy)
    pkg.add_package_rules(builder.ruleset, name, role, the_pkg)
    setup_default_env(builder, get_env(builder, name, role))


def medium(builder, name, roles, script_name, deployments = [ ],
           writeSetvarsSh = True,
           writeSetvarsPy = False):
    """
    Build an init script for the given roles.
    """

    for role in roles:
        the_pkg = InitScriptBuilder(name, role, script_name,
                                    deployments,
                                    writeSetvarsSh = writeSetvarsSh,
                                    writeSetvarsPy = writeSetvarsPy)
        pkg.add_package_rules(builder.ruleset, name, role, the_pkg)
        setup_default_env(builder, get_env(builder, name, role))


def setup_default_env(builder, env_store):
    """
    Set up the default environment for this initscript.
    """
    # Nothing to do so far ..
    pass

def get_effective_env(builder, name, role, domain = None):
    """
    Retrieve the effective runtime environment for this initscripts
    package. Note that setting variables here will have no effect.
    """
    return builder.effective_environment_for(
                depend.Label(
                    utils.LabelType.Package,
                    name, role,
                    utils.LabelTag.RuntimeEnv,
                    domain = domain))



def get_env(builder, name, role, domain = None):
    """
    Retrieve an environment to which you can make changes which will
    be reflected in the generated init scripts. The actual environment
    used will have extra values inserted from wildcarded environments -
    see get_effective_env() above.
    """
    return builder.get_environment_for(
        depend.Label(
            utils.LabelType.Package,
            name, role,
            utils.LabelTag.RuntimeEnv,
            domain = domain))


# End file.

