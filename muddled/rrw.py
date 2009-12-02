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
    Make sure the host has apt-get install'd the given packages.

    required_by is the list of roles that require the development
    packages to be installed.
    """
    aptget.medium(builder, pkg_name, role, pkg_list, required_by)

def setup_tools(builder, roles_that_use_tools = [ "*" ],
                tools_roles = [ "tools" ] , tools_dep = "tools", 
                tools_path_env = "TOOLS_PATH",
                tools_install = None):
    """
    Mark a given role and deployment as building host tools. We set
    tools_path_env to this location.

    tools_install is the path in which host tools will eventually
    be installed (and to which tools_path_env is set). If this isn't
    set, we assume the tools will be used in place wherever this build
    is.

    tools_dep_TOOLS_PATH will end up pointing to the tools path, as
    will tools_path_env (TOOLS_PATH by default) but tools will also be
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
                  dirname = None):
    """
    This is a utility function which sets up the given
    roles to use the given compiler prefix (empty for host tools,
    or something like arm-linux-none-gnueabi- for eg. ARM)

    Environment variable like %sGCC (%s = env_prefix) end up
    with values like %sgcc (%s = prefix).

    We set up the following environment variables:

    CC - points to gcc
    CPP - points to g++
    LD - points to ld
    AR - points to ar

    If archname is not None, we also set archname_XX to the same set of
    values, in archroles, so roles which are e.g. building for the host
    can access toolchains for other processors in the system.

    If you set env_prefix to None, we'll only set up an architecture 
    prefix.

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
    Set an environment variable 'name = value' globally.
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
    Append the given value to the path for the given roles
    """
    for r in roles:
        lbl = depend.Label(utils.LabelKind.Package,
                           "*", 
                           r, 
                           "*")
        env = builder.invocation.get_environment_for(lbl)
        env.append("PATH", val)


def set_domain_param(builder, domain, name, value):
    return builder.invocation.set_domain_parameter(domain, name, value)

def get_domain_param(builder, domain, name):
    return builder.invocation.get_domain_parameter(domain, name)

def set_env(builder, roles, bindings, domain = None):
    """
    
    Utility: set var = value for every package in the given roles
    
    Bindings is a series of (var, value) pairs.
    """
    for (x,y) in bindings:
        pkg.set_env_for_package(builder, "*", roles, 
                                x,y, domain = domain)

def package_requires(builder, 
                     in_pkg, pkg_roles,
                     reqs):
    """
    Register the information that pkg, built in all of pkg_roles,
    requires reqs, which is a list of pairs (pkg, role) 
    """
    for (req, req_role) in reqs:
        pkg.depend_across_roles(builder.invocation.ruleset,
                                in_pkg, pkg_roles, 
                                [ req ] , req_role)

def setup_helpers(builder, helper_name):
    """
    Set up a helper checkout to be used in subsequent calls
    to build_with_helper
    """
    co_simple.relative(builder, helper_name, helper_name)

def build_with_helper(builder, helpers, pkg_name, checkout, roles, 
                      makefileName = None, 
                      co_dir = None, 
                      repoRelative = None, 
                      rev = None):
    """
    Builds a package called pkg_name from a makefile in a helpers checkout
    called 'helpers', involving the use of the checkout 'checkout',
    which is a relative checkout with optional second level name
    co_dir, repo relative name repoRelative, and revision rev.
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
    Wraps all the dependables in a given role inside ArchSpecificDependable s
    requiring them to be built on arch.
    """
    lbl = depend.Label(utils.LabelKind.Package,
                       "*",
                       role, 
                       "*",
                       domain = builder.default_domain)
    gen = pkg.ArchSpecificDependableGenerator(arch)
    builder.invocation.ruleset.wrap_dependables(gen, lbl)



# End File.
