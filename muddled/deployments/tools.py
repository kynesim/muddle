"""
Tools deployment. This deployment merely adds the appropriate
environment variables to use the tools in the given role install
directories to everything in another list of deployments.

Instructions are ignored - there's no reason to follow them
(yet) and it's simpler not to.
"""

import muddled
import muddled.pkg as pkg
import muddled.env_store
import muddled.depend as depend
import muddled.utils as utils
import muddled.filespec as filespec
import os
import muddled.deployment as deployment

class ToolsDeploymentBuilder(pkg.Dependable):
    """
    Copy the dependent roles into the tools deployment
    """
    
    def __init__(self, builder, dependent_roles):
        self.builder = builder
        self.dependent_roles = dependent_roles

    def build_label(self, label):
        if (label.tag == utils.Tags.Deployed):
            self.deploy(label)
        else:
            raise utils.Failure("Attempt to build " + 
                                "unrecognised tools deployment label %s"%(label))

    def deploy(self, label):
        deploy_dir = self.builder.invocation.deploy_path(label.name)

        utils.recursively_remove(deploy_dir)
        utils.ensure_dir(deploy_dir)

        for role in self.dependent_roles:
            print "> %s: Deploying role %s .."%(label.name, role)
            install_dir = self.builder.invocation.role_install_path(role)
            utils.recursively_copy(install_dir, deploy_dir)

        # We don't obey instructions. W00t.

def attach_env(builder, role, env, name):
    """
    Attach suitable environment variables for the given input role
    to the given environment store.
    
    We set:

    LD_LIBRARY_PATH   - Prepend $role_installl/lib
    PATH              - Append $role_install/bin
    PKG_CONFIG_PATH   - Prepend $role_install/lib/pkgconfig
    $role_TOOLS_PATH  - Prepend $role_install/bin 

    The PATH/TOOLS_PATH stuff is so you can still locate tools which were
    in the path even if they've been overridden with your built tools.
    """
    
    env.set_type("LD_LIBRARY_PATH", muddled.env_store.EnvType.Path)
    env.set_type("PATH", muddled.env_store.EnvType.Path)
    env.set_type("PKG_CONFIG_PATH", muddled.env_store.EnvType.Path)
    env.set_external("LD_LIBRARY_PATH")
    env.set_external("PATH")
    env.set_external("PKG_CONFIG_PATH")

    deploy_base = builder.invocation.deploy_path(name)

    env.ensure_prepended("LD_LIBRARY_PATH", os.path.join(deploy_base, "lib"))
    env.ensure_prepended("PKG_CONFIG_PATH", os.path.join(deploy_base, "lib", "pkgconfig"))
    env.ensure_appended("PATH", os.path.join(deploy_base, "bin"))
    env.set("%s_TOOLS_PATH"%(name.upper()), deploy_base)
    

def deploy(builder, name, rolesThatUseThis = [ ], rolesNeededForThis = [ ]):
    """
    Register a tools deployment.

    This actually does nothing but register the appropriate
    environment
    """

    tgt = depend.Label(utils.LabelKind.Deployment,
                       name, 
                       None,
                       utils.Tags.Deployed)

    for role in rolesThatUseThis:
        for tag in ( utils.Tags.PreConfig, utils.Tags.Configured, utils.Tags.Built, 
                     utils.Tags.Installed, utils.Tags.PostInstalled) :
            lbl = depend.Label(utils.LabelKind.Package,
                               "*",
                               role,
                               tag)
            env = builder.invocation.get_environment_for(lbl)
            attach_env(builder, role, env, name)

        deployment.role_depends_on_deployment(builder, role, name)

    the_rule = depend.Rule(tgt, ToolsDeploymentBuilder(builder, rolesNeededForThis))
    builder.invocation.ruleset.add(the_rule)

    deployment.deployment_depends_on_roles(builder, name, rolesNeededForThis)

    deployment.register_cleanup(builder, name)

    
        
        


# End file.

