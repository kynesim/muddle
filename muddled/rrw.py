"""
rrw's development library of _experimental_ muddle entry points.
This file will go away in the next major release of muddle - in
the meantime, it provides a useful library of code for reuse.
"""

import utils
import os

import checkouts.simple as co_simple
import checkouts.twolevel as co_twolevel
import pkgs.make as make
import pkgs.aptget as aptget
import pkg
import depend
import deployments.tools as dep_tools
import deployment

def apt_get_install(builder,
                    pkg_list, 
                    required_by,
                    pkg_name = "dev_pkgs",
                    role = "dev_pkgs"):
    """
    Make sure the host has installed the given packages.

    Uses ``apt-get install`` (or equivalent).

    * 'pkg_list' is the list of the names of the packages to check for.
      The names should be as they are expected by ``apt-get``.
    * 'required_by' is the list of roles that require the development
      packages to be installed.

    This is essentially a convenience wrapper for
    ``muddled.pkgs.aptget.medium()``, with sensible default values for
    'pkg_name' and 'role'.

    For instance::

      apt_get_install(builder, ["bison", "flex", "libtool"], ["text", "graphics"])
    """
    aptget.medium(builder, pkg_name, role, pkg_list, required_by)

def setup_tools(builder, roles_that_use_tools = [ "*" ],
                tools_roles = [ "tools" ] , tools_dep = "tools", 
                tools_path_env = "TOOLS_PATH",
                tools_install = None):
    """
    Setup the "post-build" environment for particular roles.

    This sets up the deployment paths for roles, and also the runtime
    environment variables. This can typicaly be used to distinguish roles which
    run in the host environment (using programs and shared libraries from the
    host) and roles which run in the environment being built (using programs
    and shared libraries from the muddle deployment directories).

    * 'roles_that_use_tools' is a list of the roles that will be *using* the
      named tools. So, if the tools are GCC and its friends, this would
      typically be all of the roles that contain things to be built with (that)
      GCC. These roles will depend on the tools being deployed.
    * 'tools_roles' is a list of the roles that *provide* the tools. These do
      not share libraries with any other roles (so, GCC on the host does not
      use the same libraries as the roles that will be installed on the
      target).
    * 'tools_dep' is the deployment name for this set-of-tools. It corresponds
      to a label "deployment:<name>{}/deployed" in the ruleset.
    * 'tools_path_env' is the name of an environment variable that will be set
      to tell each of the roles in 'roles_that_use_tools' about the location of
      the 'tools_dep' deployment.
    * 'tools_install' is currently ignored.

    Specifically:

    1. Register a tools deployment called 'tools_dep', used by the
       'roles_that_use_this', and provided by packages in the 'tools_roles'.
    2. In each of the 'roles_that_use_tools', set the environment variable
       'tools_path_env' to the deployment path for 'tools_dep'.
    3. In each of the 'roles_that_use_tools', amend the following environment
       variables as follows, where "$role_deploy" is the deployment path for
       'tools_dep':

            * LD_LIBRARY_PATH   - Prepend $role_deployl/lib
            * PATH              - Append $role_deploy/bin
            * PKG_CONFIG_PATH   - Prepend $role_deploy/lib/pkgconfig
            * <role>_TOOLS_PATH  (where <role> is upper-cased) - Prepend
              $role_deploy/bin 

    4. Tell each of the 'tools_roles' that it does not share libraries with
       any other roles.

    .. THE FOLLOWING ARE RICHARD'S ORIGINAL COMMENTS...

    .. 'tools_install' is the path in which host tools will eventually
       be installed (and to which 'tools_path_env' is set). If this isn't
       set, we assume the tools will be used in place wherever this build
       is.

    .. tools_dep_TOOLS_PATH will end up pointing to the tools path, as
       will 'tools_path_env' ("TOOLS_PATH" by default) but tools will also be
       added to PATH and LD_LIBRARY_PATH so you can just run the host
       tools.
    """
    dep_tools.deploy(builder, tools_dep, roles_that_use_tools, tools_roles)
    deployment.inform_deployment_path(builder, tools_path_env,
                                      tools_dep, 
                                      roles_that_use_tools)
    # Tools roles do not share libraries with anyone else.
    for r in tools_roles:
        builder.roles_do_not_share_libraries(r, "*")


def set_gnu_tools(builder, roles, env_prefix, prefix, 
                  cflags = None, ldflags = None, 
                  asflags = None,
                  archspec = None,
                  archname = None, 
                  archroles = [ "*" ], 
                  domain = None, 
                  dirname = None,
                  cppflags = None,
                  cxxflags = None):
    """
    This is a utility function which sets up the given roles to use the given
    compiler prefix (typically the empty string "" for host tools, or something
    like "arm-linux-none-gnueabi-" for ARM)

    Environment variables like:
    
      <env_prefix>GCC
      
    end up with values like:

      <prefix>gcc

    1. If 'env_prefix' is not None, then we set up the following environment
       variables:

       * <env_prefix>CC  is <prefix>gcc
       * <env_prefix>CXX is <prefix>g++
       * <env_prefix>CPP is <prefix>gpp
       * <env_prefix>LD  is <prefix>ld
       * <env_prefix>AR  is <prefix>ar
       * <env_prefix>AS  is <prefix>as
       * <env_prefix>NM  is <prefix>nm
       * <env_prefix>OBJDUMP is <prefix>objdump
       * <env_prefix>OBJCOPY is <prefix>objcopy
       * <env_prefix>PFX is the <prefix> itself
       * if 'archspec' is not None, <env_prefix>ARCHSPEC is set to it
       * if 'cflags' is not None, <env_prefix>CFLAGS is set to it
       * if 'cppflags' is not None, <env_prefix>CPPFLAGS is set to it
       * if 'cxxflags' is not None, <env_prefix>CXXFLAGS is set to it
       * if 'ldflags' is not None, <env_prefix>LDFLAGS is set to it
       * if 'asflags' is not None, <env_prefix>ASFLAGS is set to it
       * if 'dirname' is not None, <env_prefix>COMPILER_TOOLS_DIR is set to it

       in all of the 'roles' named.

       Note that it is perfectly possible to have 'env_prefix' as the empty
       string ("") if one wishes to set ${CC}, etc.

    2. If 'archname' is not None, we also set <archname>_<XX> to the same set
       of values, in all of the roles named in 'archroles'. Thus roles which
       are, for instance, building for the host can access toolchains for other
       processors in the system.

    For instance::

        set_gnu_tools(builder, ['tools'], '', HOST_TOOLS_PREFIX,
                      archname='HOST', archroles=['firmware'])

        set_gnu_tools(builder, ['firmware'], '', ARM_TOOLS_PREFIX)

    After this:
    
    * in role 'tools' ${CC} will refer to the version of gcc in
      HOST_TOOLS_PREFIX.

    * in role 'firmware', ${CC} will refer to the version of gcc in
      ARM_TOOLS_PREFIX, and ${HOST_CC} will refer to the "host" gcc in
      HOST_TOOLS_PREFIX.
    """
    
    prefix_list = [ ]
    if (env_prefix is not None): 
        prefix_list.append( (env_prefix, roles) )

    if (archname is not None):
        prefix_list.append( ("%s_"%(archname), archroles) )

    for (pfx, croles)  in prefix_list:
        binding_list = [ ]
        binding_list.append(utils.get_prefix_pair(pfx, "CC", prefix, "gcc"))
        binding_list.append(utils.get_prefix_pair(pfx, "CXX", prefix, "g++"))
        binding_list.append(utils.get_prefix_pair(pfx, "CPP", prefix, "cpp"))
        binding_list.append(utils.get_prefix_pair(pfx, "LD", prefix, "ld"))
        binding_list.append(utils.get_prefix_pair(pfx, "AR", prefix, "ar"))
        binding_list.append(utils.get_prefix_pair(pfx, "AS", prefix, "as"))
        binding_list.append(utils.get_prefix_pair(pfx, "NM", prefix, "nm"))
        binding_list.append(utils.get_prefix_pair(pfx, "OBJDUMP", prefix, "objdump"))
        binding_list.append(utils.get_prefix_pair(pfx, "OBJCOPY", prefix, "objcopy"))
        binding_list.append(utils.get_prefix_pair(pfx, "PFX", prefix,""))

        if (archspec is not None):
            binding_list.append(utils.get_prefix_pair(pfx, "ARCHSPEC", "", archspec))
        

        if (cflags is not None):
            binding_list.append(utils.get_prefix_pair(pfx, "CFLAGS", "", cflags))

        if (cppflags is not None):
            binding_list.append(utils.get_prefix_pair(pfx, "CPPFLAGS", "", cppflags))

        if (cxxflags is not None):
            binding_list.append(utils.get_prefix_pair(pfx, "CXXFLAGS", "", cxxflags))

        if (ldflags is not None):
            binding_list.append(utils.get_prefix_pair(pfx, "LDFLAGS", "", ldflags))

        if (asflags is not None):
            binding_list.append(utils.get_prefix_pair(pfx, "ASFLAGS", "", asflags))

        if (dirname is not None):
            binding_list.append(utils.get_prefix_pair(pfx, "COMPILER_TOOLS_DIR", "", dirname))

        set_env(builder, croles, binding_list, domain = domain)
    

def set_global_package_env(builder, name, value, 
                                   roles = [ "*" ]):
    """
    Set an environment variable 'name = value' for all of the named roles.

    (The default sets the environment variable globally, i.e., for all roles.)
    """
    for  r in roles:
        lbl = depend.Label(utils.LabelKind.Package, 
                           "*", 
                           r, 
                           "*")
        env = builder.invocation.get_environment_for(lbl)
        env.set(name, value)


def append_to_path(builder, roles, val):
    """
    Append the given value to the PATH for the given roles
    """
    for r in roles:
        lbl = depend.Label(utils.LabelKind.Package,
                           "*", 
                           r, 
                           "*")
        env = builder.invocation.get_environment_for(lbl)
        env.append("PATH", val)


def set_domain_param(builder, domain, name, value):
    """
    A convenience wrapper around builder.invocation.set_domain_parameter().

    It's slightly shorter to type...
    """
    return builder.invocation.set_domain_parameter(domain, name, value)

def get_domain_param(builder, domain, name):
    """
    A convenience wrapper around builder.invocation.get_domain_parameter().

    It's slightly shorter to type...
    """
    return builder.invocation.get_domain_parameter(domain, name)

def set_env(builder, roles, bindings, domain = None):
    """
    Set environment variable <var> = <value> for every package in the given roles
    
    Bindings is a series of (<var>, <value>) pairs.
    """
    for (x,y) in bindings:
        pkg.set_env_for_package(builder, "*", roles, 
                                x,y, domain = domain)

def append_env(builder, roles, bindings, domain = None, 
               setType = None):
    """
    Set environment variable <var> = <value> for every package in the given roles
    
    Bindings is a series of (<var>, <value>) pairs.

    If setType is specified, we set the type of the environment variable to one 
     of the types in env_store.py: the most popular of these is EnvType.SimpleValue
     which marks the variable as not a path-type variable.
    """
    for (x,y) in bindings:
        pkg.append_env_for_package(builder, "*", roles, 
                                   x,y, domain = domain, 
                                   type = setType)


def package_requires(builder, 
                     in_pkg, pkg_roles,
                     reqs):
    """
    Register the information that 'in_pkg', built in all of 'pkg_roles',
    require (depends on) 'reqs', which is a list of pairs (<package_name>,
    <role>) 
    """
    for (req, req_role) in reqs:
        pkg.depend_across_roles(builder.invocation.ruleset,
                                in_pkg, pkg_roles, 
                                [ req ] , req_role)

def setup_helpers(builder, helper_name):
    """
    Set up a helper checkout to be used in subsequent calls to
    build_with_helper

    Basically a wrapper around::
    
      checkouts.simple.relative(builder, helper_name, helper_name)
    """
    co_simple.relative(builder, helper_name, helper_name)

def build_with_helper(builder, helpers, pkg_name, checkout, roles, 
                      makefileName = None, 
                      co_dir = None, 
                      repoRelative = None, 
                      rev = None):
    """
    Builds a package called 'pkg_name' from a makefile in a helpers checkout
    called 'helpers', involving the use of the checkout 'checkout',
    which is a relative checkout with optional second level name
    co_dir, repo relative name repoRelative, and revision rev.

    In other words, declares that 'pkg_name' in the given 'roles' will be built
    with the Makefile called:

        <helpers>/<makefileName>

    If 'co_dir' is None, this will be checked out using
    checkouts.simple.relative(), otherwise it will be checked out using
    checkouts.twolevel.relative(). The 'co_dir', 'repoRelative' and 'rev'
    arguments will be used in the obvious ways.
    """
    
    if (makefileName is None):
        makefileName = os.path.join(pkg_name, "Makefile.muddle")

    make.medium(builder, 
                name = pkg_name, 
                roles = roles, 
                checkout = "helpers", 
                makefileName = makefileName, 
                simpleCheckout = False)

    # Make sure we actually check out .. 
    if (co_dir is None):
        co_simple.relative(builder, checkout, repoRelative, rev)
    else:
        co_twolevel.relative(builder,
                             co_dir = co_dir, 
                             co_name = checkout,
                             repo_relative = repoRelative,
                             rev = rev)

    # Now depend on any additional checkouts .. 
    for r in roles:
        pkg.package_depends_on_checkout(builder.invocation.ruleset,
                                        pkg_name,
                                        r,
                                        checkout, None)


def build_role_on_architecture(builder, role, arch):
    """
    Wraps all the dependables in a given role inside an ArchSpecificDependable generator.

    This requires all the dependables in that role ("package:*{<role>}/*") to
    be built on architecture <arch>.
    """
    lbl = depend.Label(utils.LabelKind.Package,
                       "*",
                       role, 
                       "*",
                       domain = builder.default_domain)
    gen = pkg.ArchSpecificDependableGenerator(arch)
    builder.invocation.ruleset.wrap_dependables(gen, lbl)



# End File.
