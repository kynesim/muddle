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

def attach_env(builder, role, env):
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
    
    role_base = builder.invocation.role_install_path(role)

    env.prepend("LD_LIBRARY_PATH", os.path.join(role_base, "lib"))
    env.prepend("PKG_CONFIG_PATH", os.path.join(role_base, "lib", "pkgconfig"))
    env.append("PATH", os.path.join(role_base, "bin"))
    env.set("%s_TOOLS_PATH"%(role), os.path.join(role_base, "bin"))



def deploy(builder, name, roles, dependentRoles = [ ]):
    """
    Register a tools deployment.

    This actually does nothing but register the appropriate
    environment
    """

    for role in roles:
        lbl = depend.Label(utils.LabelKind.Package,
                           "*",
                           role,
                           "*")
        env = builder.invocation.get_environment_for(lbl)
        attach_env(builder, role, env)

    for dep in dependentRoles:
        deployment.role_depends_on_deployment(builder, dep, name)

    # We actually don't require a role for this.


# End file.

