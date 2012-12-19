"""
Tools deployment. This deployment merely adds the appropriate
environment variables to use the tools in the given role install
directories to everything in another list of deployments.

Instructions are ignored - there's no reason to follow them
(yet) and it's simpler not to.
"""

import os

import muddled
import muddled.env_store
import muddled.depend as depend
import muddled.utils as utils
import muddled.deployment as deployment

from muddled.depend import Action

class ToolsDeploymentBuilder(Action):
    """
    Copy the dependent roles into the tools deployment.
    """

    def __init__(self, dependent_roles):
        self.dependent_roles = dependent_roles

    def build_label(self, builder, label):
        if (label.tag == utils.LabelTag.Deployed):
            self.deploy(builder, label)
        else:
            raise utils.GiveUp("Attempt to build "
                                "unrecognised tools deployment label %s"%(label))

    def deploy(self, builder, label):
        deploy_dir = builder.deploy_path(label)

        utils.recursively_remove(deploy_dir)
        utils.ensure_dir(deploy_dir)

        for role in self.dependent_roles:
            print "> %s: Deploying role %s .."%(label.name, role)
            install_dir = builder.role_install_path(role,
                                                               domain = label.domain)
            # We do want an exact copy here - this is a copy from the install
            #  set to the role deployment and therefore may include symlinks
            #  hardwired to MUDDLE_TARGET_INSTALL. If it were a copy to the install
            #  directory, we'd want an inexact copy.
            # - rrw 2009-11-09
            utils.recursively_copy(install_dir, deploy_dir, object_exactly = True)

        # We don't obey instructions. W00t.

def attach_env(builder, role, env, name):
    """
    Attach suitable environment variables for the given input role
    to the given environment store.

    We set:

    * LD_LIBRARY_PATH   - Prepend $role_installl/lib
    * PATH              - Append $role_install/bin
    * PKG_CONFIG_PATH   - Prepend $role_install/lib/pkgconfig
    * $role_TOOLS_PATH  - Prepend $role_install/bin

    The PATH/TOOLS_PATH stuff is so you can still locate tools which were
    in the path even if they've been overridden with your built tools.
    """

    env.set_type("LD_LIBRARY_PATH", muddled.env_store.EnvType.Path)
    env.set_type("PATH", muddled.env_store.EnvType.Path)
    env.set_type("PKG_CONFIG_PATH", muddled.env_store.EnvType.Path)
    env.set_external("LD_LIBRARY_PATH")
    env.set_external("PATH")
    env.set_external("PKG_CONFIG_PATH")

    deploy_label = depend.Label(utils.LabelType.Deployment, name)
    deploy_base = builder.deploy_path(deploy_label)

    env.ensure_prepended("LD_LIBRARY_PATH", os.path.join(deploy_base, "lib"))
    env.ensure_prepended("PKG_CONFIG_PATH", os.path.join(deploy_base, "lib", "pkgconfig"))
    env.ensure_appended("PATH", os.path.join(deploy_base, "bin"))
    env.set("%s_TOOLS_PATH"%(name.upper()), deploy_base)


def deploy(builder, name, rolesThatUseThis = [ ], rolesNeededForThis = [ ]):
    """
    Register a tools deployment.

    This is used to:

    1. Set the environment for each role in 'rolesThatUseThis' so that
       PATH, LD_LIBRARY_PATH and PKG_CONFIG_PATH include the 'name'
       deployment

    2. Make deployment:<name>/deployed depend upon the 'rolesNeededForThis'

    3. Register cleanup for this deployment

    The intent is that we have a "tools" deployment, which provides useful
    host tools (for instance, something to mangle a file in a particular
    manner). Those roles which need to use such tools in their builds
    (normally in a Makefile.muddle) then need to have the environment set
    appropriately to allow them to find the tools (and ideally, not system
    provided tools which mighth have the same name).
    """

    tgt = depend.Label(utils.LabelType.Deployment,
                       name,
                       None,
                       utils.LabelTag.Deployed)

    for role in rolesThatUseThis:
        for tag in ( utils.LabelTag.PreConfig, utils.LabelTag.Configured, utils.LabelTag.Built,
                     utils.LabelTag.Installed, utils.LabelTag.PostInstalled) :
            lbl = depend.Label(utils.LabelType.Package,
                               "*",
                               role,
                               tag)
            env = builder.get_environment_for(lbl)
            attach_env(builder, role, env, name)

        deployment.role_depends_on_deployment(builder, role, name)

    the_rule = depend.Rule(tgt, ToolsDeploymentBuilder(rolesNeededForThis))
    builder.ruleset.add(the_rule)

    deployment.deployment_depends_on_roles(builder, name, rolesNeededForThis)

    deployment.register_cleanup(builder, name)






# End file.

