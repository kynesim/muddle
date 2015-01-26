"""
Some standard package implementations to cope with packages that use Make
"""

import muddled.pkg as pkg
from muddled.pkg import PackageBuilder
import muddled.utils as utils
import muddled.checkouts.simple as simple_checkouts
import muddled.checkouts.twolevel as twolevel_checkouts
import muddled.checkouts.multilevel as multilevel_checkouts
import muddled.depend as depend
import muddled.rewrite as rewrite

from muddled.depend import Label
from muddled.withdir import Directory

import os

DEFAULT_MAKEFILE_NAME = "Makefile.muddle"

def deduce_makefile_name(makefile_name, per_role, role):
    """Deduce our actual muddle Makefile name.

    'makefile_name' is the base name. If it is None, then we use
    DEFAULT_MAKEFILE_NAME.

    If 'per_role' is true, and 'role' is not None, then we add the
    extension '.<role>' to the end of the makefile name.

    Abstracted here so that it can be used outside this module as well.
    """
    if makefile_name is None:
        makefile_name = DEFAULT_MAKEFILE_NAME

    if per_role and role is not None:
        makefile_name = "%s.%s"%(makefile_name, role)

    return makefile_name

class MakeBuilder(PackageBuilder):
    """
    Use make to build your package from the given checkout.

    We assume that the makefile is smart enough to build in the
    object directory, since any other strategy (e.g. convolutions
    involving cp) will lead to dependency-based disaster.
    """

    def __init__(self, name, role, co, config = True,
                 perRoleMakefiles = False,
                 makefileName = DEFAULT_MAKEFILE_NAME,
                 rewriteAutoconf = False,
                 usesAutoconf = False,
                 execRelPath = None):
        """
        Constructor for the make package.
        """
        PackageBuilder.__init__(self, name, role)
        self.co = co
        self.has_make_config = config
        self.per_role_makefiles = perRoleMakefiles
        self.makefile_name = makefileName
        self.rewriteAutoconf = rewriteAutoconf
        self.usesAutoconf = usesAutoconf
        self.execRelPath = execRelPath



    def ensure_dirs(self, builder, label):
        """
        Make sure all the relevant directories exist.
        """

        co_label = Label(utils.LabelType.Checkout, self.co, domain=label.domain)
        if not os.path.exists(builder.db.get_checkout_path(co_label)):
            raise utils.GiveUp("Missing source directory\n"
                               "  %s depends on %s\n"
                               "  Directory %s does not exist"%(label, co_label,
                                   builder.db.get_checkout_path(co_label)))

        co_label = Label(utils.LabelType.Package, self.name, self.role, domain=label.domain)
        utils.ensure_dir(builder.package_obj_path(co_label))
        utils.ensure_dir(builder.package_install_path(co_label))

    def _amend_env(self, co_path):
        """Amend the environment before building a label
        """
        # XXX Experimentally set MUDDLE_SRC for the "make" here, where we need it
        os.environ["MUDDLE_SRC"] = co_path
        # XXX

        # We really do want PKG_CONFIG_LIBDIR here - it prevents pkg-config
        # from finding system-installed packages.
        if (self.usesAutoconf):
            #print "> setting PKG_CONFIG_LIBDIR to %s"%(os.environ['MUDDLE_PKGCONFIG_DIRS_AS_PATH'])
            os.environ['PKG_CONFIG_LIBDIR'] = os.environ['MUDDLE_PKGCONFIG_DIRS_AS_PATH']
        elif(os.environ.has_key('PKG_CONFIG_LIBDIR')):
            # Make sure that pkg-config uses default if we're not setting it.
            #print "> removing PKG_CONFIG_LIBDIR from environment"
            del os.environ['PKG_CONFIG_LIBDIR']

    def _make_command(self, builder, makefile_name):
        return ['make', '-f', makefile_name]

    def build_label(self, builder, label):
        """
        Build the relevant label. We'll assume that the
        checkout actually exists.
        """
        tag = label.tag

        self.ensure_dirs(builder, label)

        # XXX We have no way of remembering a checkout in a different domain
        # XXX (from the label we're building) so for the moment we won't even
        # XXX try...
        tmp = Label(utils.LabelType.Checkout, self.co, domain=label.domain)
        co_path =  builder.db.get_checkout_path(tmp)
        with Directory(co_path):
            self._amend_env(co_path)

            makefile_name = deduce_makefile_name(self.makefile_name,
                                                 self.per_role_makefiles,
                                                 label.role)

            make_cmd = self._make_command(builder, makefile_name)

            if (tag == utils.LabelTag.PreConfig):
                # Preconfigure - nothing need be done
                pass
            elif (tag == utils.LabelTag.Configured):
                # We should probably do the configure thing ..
                if (self.has_make_config):
                    utils.run0(make_cmd + ["config"])
            elif (tag == utils.LabelTag.Built):
                utils.run0(make_cmd)
            elif (tag == utils.LabelTag.Installed):
                utils.run0(make_cmd + ["install"])
            elif (tag == utils.LabelTag.PostInstalled):
                if (self.rewriteAutoconf):
                    #print "> Rewrite autoconf for label %s"%(label)
                    obj_path = builder.package_obj_path(label)
                    #print ">obj_path = %s"%(obj_path)
                    if (self.execRelPath is None):
                        sendExecPrefix = None
                    else:
                        sendExecPrefix = os.path.join(obj_path, self.execRelPath)

                    rewrite.fix_up_pkgconfig_and_la(builder, obj_path, execPrefix = sendExecPrefix)
            elif (tag == utils.LabelTag.Clean):
                utils.run0(make_cmd + ["clean"])
            elif (tag == utils.LabelTag.DistClean):
                utils.run0(make_cmd + ["distclean"])
            else:
                raise utils.MuddleBug("Invalid tag specified for "
                                  "MakePackage building %s"%(label))


def simple(builder, name, role, checkout, rev=None, branch=None,
	   simpleCheckout = False, config = True,
           perRoleMakefiles = False,
           makefileName = DEFAULT_MAKEFILE_NAME,
           usesAutoconf = False,
           rewriteAutoconf = False,
           execRelPath = None):
    """
    Build a package controlled by make, called name with role role
    from the sources in checkout checkout.

    * simpleCheckout - If True, register the checkout too.
    * config         - If True, we have make config. If false, we don't.
    * perRoleMakefiles - If True, we run 'make -f Makefile.<rolename>' instead
      of just make.
    * usesAutoconf    - If True, this package is given access to .la and .pc
                          files from things it depends on.
    * rewriteAutoconf  - If True, we will rewrite .la and .pc files in the
      output directory so that packages which use autoconf continue to
      depend correctly. Intended for use with the MUDDLE_PKGCONFIG_DIRS
      environment variable.
    * execRelPath    - Where, relative to the object directory, do we find
                        binaries for this package?
    """
    if (simpleCheckout):
        simple_checkouts.relative(builder, checkout, rev=rev, branch=branch)

    the_pkg = MakeBuilder(name, role, checkout, config = config,
                          perRoleMakefiles = perRoleMakefiles,
                          makefileName = makefileName,
                          usesAutoconf = usesAutoconf,
                          rewriteAutoconf = rewriteAutoconf,
                          execRelPath = execRelPath)
    # Add the standard dependencies ..
    pkg.add_package_rules(builder.ruleset, name, role, the_pkg)
    # .. and make us depend on the checkout.
    pkg.package_depends_on_checkout(builder.ruleset, name, role, checkout, the_pkg)
    ###attach_env(builder, name, role, checkout)

def medium(builder, name, roles, checkout, rev=None, branch=None,
	   deps = None, dep_tag = utils.LabelTag.PreConfig,
           simpleCheckout = True, config = True, perRoleMakefiles = False,
           makefileName = DEFAULT_MAKEFILE_NAME,
           usesAutoconf = False,
           rewriteAutoconf = False,
           execRelPath = None):
    """
    Build a package controlled by make, in the given roles with the
    given dependencies in each role.

    * simpleCheckout - If True, register the checkout as simple checkout too.
    * dep_tag        - The tag to depend on being installed before you'll build.
    * perRoleMakefiles - If True, we run 'make -f Makefile.<rolename>' instead
      of just make.
    """
    if (simpleCheckout):
        simple_checkouts.relative(builder, checkout, rev=rev, branch=branch)

    if deps is None:
        deps = []

    for r in roles:
        simple(builder, name, r, checkout, config = config,
               perRoleMakefiles = perRoleMakefiles,
               makefileName = makefileName,
               usesAutoconf = usesAutoconf,
               rewriteAutoconf = rewriteAutoconf,
               execRelPath = execRelPath)
        pkg.package_depends_on_packages(builder.ruleset,
                                       name, r, dep_tag,
                                       deps)
        ###attach_env(builder, name, r, checkout)

def twolevel(builder, name, roles,
             co_dir = None, co_name = None, rev=None, branch=None,
             deps = None, dep_tag = utils.LabelTag.PreConfig,
             simpleCheckout = True, config = True, perRoleMakefiles = False,
             makefileName = DEFAULT_MAKEFILE_NAME,
             repo_relative=None,
             usesAutoconf = False,
             rewriteAutoconf = False,
             execRelPath = None):
    """
    Build a package controlled by make, in the given roles with the
    given dependencies in each role.

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
               makefileName = makefileName,
               usesAutoconf = usesAutoconf,
               rewriteAutoconf = rewriteAutoconf,
               execRelPath = execRelPath)
        pkg.package_depends_on_packages(builder.ruleset,
                                       name, r, dep_tag,
                                       deps)
        ###attach_env(builder, name, r, co_name)

def multilevel(builder, name, roles,
               co_dir = None, co_name = None, rev=None, branch=None,
               deps = None, dep_tag = utils.LabelTag.PreConfig,
               simpleCheckout = True, config = True, perRoleMakefiles = False,
               makefileName = DEFAULT_MAKEFILE_NAME,
               repo_relative=None,
               usesAutoconf = False,
               rewriteAutoconf = False,
               execRelPath = None):
    """
    Build a package controlled by make, in the given roles with the
    given dependencies in each role.

    * simpleCheckout - If True, register the checkout as simple checkout too.
    * dep_tag        - The tag to depend on being installed before you'll build.
    * perRoleMakefiles - If True, we run 'make -f Makefile.<rolename>' instead
      of just make.
    """

    if (co_name is None):
        co_name = name

    if (simpleCheckout):
        multilevel_checkouts.relative(builder, co_dir, co_name,
                                      repo_relative=repo_relative,
                                      rev=rev, branch=branch)

    if deps is None:
        deps = []


    for r in roles:
        simple(builder, name, r, co_name, config = config,
               perRoleMakefiles = perRoleMakefiles,
               makefileName = makefileName,
               usesAutoconf = usesAutoconf,
               rewriteAutoconf = rewriteAutoconf,
               execRelPath = execRelPath)
        pkg.package_depends_on_packages(builder.ruleset,
                                       name, r, dep_tag,
                                       deps)
        ###attach_env(builder, name, r, co_name)





def single(builder, name, role, deps = None,
           usesAutoconf = False,
           rewriteAutoconf = False,
           execRelPath = None):
    """
    A simple make package with a single checkout named after the package and
    a single role.
    """
    medium(builder, name, [ role ], name, deps,
           usesAutoconf = usesAutoconf,
           rewriteAutoconf = rewriteAutoconf,
           execRelPath = execRelPath)

def attach_env(builder, name, role, checkout, domain=None):
    """
    Write the environment which attaches MUDDLE_SRC to makefiles.

    We retrieve the environment for ``package:<name>{<role>}/*``, and
    set MUDDLE_SRC therein to the checkout path for 'checkout:<checkout>'.
    """
    env = builder.get_environment_for(
        depend.Label(utils.LabelType.Package,
                     name, role, "*"))
    tmp = Label(utils.LabelType.Checkout, checkout, domain=domain)
    env.set("MUDDLE_SRC", builder.db.get_checkout_path(tmp))

# Useful extensions

class ExpandingMakeBuilder(MakeBuilder):
    """
    A MakeBuilder that first expands an archive file.
    """

    def __init__(self, name, role, co_name, archive_file, archive_dir,
                 makefile=DEFAULT_MAKEFILE_NAME):
        """
        A MakeBuilder that first expands an archive file.

        For package 'name' in role 'role', look in checkout 'co_name' for archive
        'archive_file'. Unpack that into $MUDDLE_OBJ, as 'archive_dir', with 'obj/'
        linked to it, and use 'makefile' to build it.
        """
        MakeBuilder.__init__(self, name, role, co_name, config=True,
                             perRoleMakefiles=False,
                             makefileName=makefile,
                             # Always "correct" any pkg-config files
                             rewriteAutoconf=True, usesAutoconf=True)
        self.co_name = co_name # equivalent to self.co, but simpler to remmeber
        self.archive_file = archive_file
        self.archive_dir  = archive_dir

    def unpack_archive(self, builder, label):
        # Since we're going to unpack into the obj/ directory, make sure we
        # have one
        self.ensure_dirs(builder, label)

        try:
            # muddle 2
            checkout_dir = builder.db.get_checkout_path(self.co, domain=label.domain)
            obj_dir = builder.package_obj_path(self.name, self.role, domain=label.domain)
        except TypeError:
            # muddle 3
            checkout_label = Label(utils.LabelType.Checkout, self.co,
                                   domain=label.domain)
            checkout_dir = builder.db.get_checkout_path(checkout_label)
            package_label = Label(utils.LabelType.Package, self.name, self.role,
                                  domain=label.domain)
            obj_dir = builder.package_obj_path(package_label)

        archive_path = os.path.join(checkout_dir, self.archive_file)

        # Make sure to remove any previous unpacking of the archive
        dest_dir = os.path.join(obj_dir, self.archive_dir)
        if os.path.exists(dest_dir):
            utils.run0(['rm', '-rf', dest_dir])

        utils.run0(['tar', '-C', obj_dir, '-xf', archive_path])

        # Ideally, we'd have unpacked the directory as obj/, so that we can
        # refer to it as $(MUDDLE_OBJ_OBJ). However, with a little cunning...

        with Directory(obj_dir):
            utils.run0(['ln', '-sf', self.archive_dir, 'obj'],
                       show_command=True, show_output=True)

    def build_label(self, builder, label):
        """Build our label.

        Cleverly, Richard didn't define anything for MakeBuilder to do at
        the PreConfigure step, which means we can safely do whatever we
        need to do in this subclass...
        """
        if (label.tag == utils.LabelTag.PreConfig):
            # unpack stuff ready to build
            self.unpack_archive(builder, label)
        else:
            # let the normal Make stuff do its thing
            # - it does too much clever stuff for us to want to copy it
            # (but nothing for preconfig)
            MakeBuilder.build_label(self, builder, label)

def expanding_package(builder, name, archive_dir,
                      role, co_name, co_dir,
                      makefile=DEFAULT_MAKEFILE_NAME, deps=None,
                      archive_file=None, archive_ext='.tar.bz2',):
    """Specify how to expand and build an archive file.

    As normal, 'name' is the package name, 'role' is the role to build it in,
    'co_name' is the name of the checkout, and 'co_dir' is the directory in
    which that lives.

    We expect to unpack an archive

        <co_dir>/<co_name>/<archive_dir><archive_ext>

    into $(MUDDLE_OBJ)/<archive_dir>. (NB: if the archive file does not expand into
    a directory of the obvious name, you can specify the archive file name separately,
    using 'archive_file').

    So, for instance, all of our X11 "stuff" lives in checkout "X11R7.5" which is
    put into directory "x11" -- i.e., "src/X11/X11R7.5".

    That lets us keep stuff together in the repository, without leading to
    a great many packages that are of no direct interest to anyone else.

    Within that we then have various muddle makefiles, and a set of .tar.bz
    archive files.

    1. The archive file expands into a directory called 'archive_dir'
    2. It is assumed that the archive file is named 'archive_dir' + 'archive_ext'.
       If this is not so, then specify 'archive_file' (and/or 'archive_ext')
       appropriately.

    This function is used to say: take the named archive file, use package name
    'name', unpack the archive file into $(MUDDLE_OBJ_OBJ), and build it using
    the named muddle makefile.

    This allows various things to be build with the same makefile, which is useful
    for (for instance) X11 proto[type] archives.

    Note that in $(MUDDLE_OBJ), 'obj' (i.e., $(MUDDLE_OBJ_OBJ)) will be a soft link
    to the expanded archive directory.
    """
    if archive_file is None:
        archive_file = archive_dir + archive_ext

    # Define how to build our package
    dep = ExpandingMakeBuilder(name, role, co_name, archive_file, archive_dir, makefile)
    pkg.add_package_rules(builder.ruleset, name, role, dep)

    # It depends on the checkout
    pkg.package_depends_on_checkout(builder.ruleset, name, role, co_name)

    # And maybe on other packages
    if deps:
        pkg.do_depend(builder, name, [role], deps)


# End file.
