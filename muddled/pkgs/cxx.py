import muddled.pkg as pkg
from muddled.pkgs.make import deduce_makefile_name, DEFAULT_MAKEFILE_NAME, MakeBuilder
import muddled.utils as utils
import muddled.checkouts.simple as simple_checkouts
import muddled.checkouts.twolevel as twolevel_checkouts

class CxxBuilder(MakeBuilder):
    def __init__(self, name, role, co, config = True, perRoleMakefiles = False,
            makefileName = DEFAULT_MAKEFILE_NAME):
        MakeBuilder.__init__(
                self, name, role, co, config, perRoleMakefiles, makefileName)

    def _make_command(self, builder, makefile_name):
        cmd = MakeBuilder._make_command(self, builder, makefile_name)
        cmd.extend(['-I', builder.resource_file_name("cxx")])
        return cmd

def simple(builder, name, role,
        checkout, rev = None, branch = None, simpleCheckout = False,
        config = True, perRoleMakefiles = False, makefileName = DEFAULT_MAKEFILE_NAME):
    """
    Build a package controlled by our simplified C/C++ make rules, called name
    with role role from the sources in checkout checkout.

    * simpleCheckout - If True, register the checkout too.
    * config         - If True, we have make config. If false, we don't.
    * perRoleMakefiles - If True, we run 'make -f Makefile.<rolename>' instead
      of just make.
    """

    if (simpleCheckout):
        simple_checkouts.relative(builder, checkout, rev=rev, branch=branch)

    the_pkg = CxxBuilder(name, role, checkout, config = config,
                          perRoleMakefiles = perRoleMakefiles,
                          makefileName = makefileName)
    # Add the standard dependencies ..
    pkg.add_package_rules(builder.ruleset, name, role, the_pkg)
    # .. and make us depend on the checkout.
    pkg.package_depends_on_checkout(builder.ruleset, name, role, checkout, the_pkg)

def twolevel(builder, name, roles,
             co_dir = None, co_name = None, rev=None, branch=None,
             deps = None, dep_tag = utils.LabelTag.PreConfig,
             simpleCheckout = True, config = True, perRoleMakefiles = False,
             makefileName = DEFAULT_MAKEFILE_NAME,
             repo_relative=None):
    """
    Build a package controlled by our simplified C/C++ make rules, in the given
    roles with the given dependencies in each role.

    * simpleCheckout - If True, register the checkout as simple checkout too.
    * dep_tag        - The tag to depend on being installed before you'll build.
    * perRoleMakefiles - If True, we run 'make -f Makefile.<rolename>' instead
      of just make.
    """

    if (co_name is None):
        co_name = name

    if (simpleCheckout):
        twolevel_checkouts.twolevel(builder, co_dir, co_name,
                                    repo_relative=repo_relative,
                                    rev=rev, branch=branch)

    if deps is None:
        deps = []


    for r in roles:
        simple(builder, name, r, co_name, config = config,
               perRoleMakefiles = perRoleMakefiles,
               makefileName = makefileName)
        pkg.package_depends_on_packages(builder.ruleset,
                                       name, r, dep_tag,
                                       deps)
