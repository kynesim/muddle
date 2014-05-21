"""
Merge depmod databases.

Linux's depmod tool is absurdly stupid. It:

 - Will not merge module databases from more than one location
 - Will not deduce kernel versions from its naming scheme
 - Will not accept absolute directory names in its configuration file
 - Will not document its database format so I can use it directly

This module contains a depmod_merge() package. You create one with
create() and then add every package which produces kernel modules to
it with add_deps()/add_roles()/add() - whichever is most convenient.

By default, we expect your packages to leave their modules in
<pkg_install_dir>/lib/modules/KERNEL_VERSION/... - you can change
this by specifying 'subdir' to the add_XXX() routines and we will
then expect <pkg_install_dir>/<subdir>/KERNEL_VERSION/...

(the KERNEL_VERSION is sadly a requirement of depmod. Go, um,
depmod)

Your modules must have a '.ko' extension.

This package then depends on all those packages and when built
will create a temporary database in its object directory
containing all the .kos from all of the packages it's been
told to look at.

It then scans <objdir>/lib/modules/\d+.\d+.* for all the
kernel versions and depmod's them all.

It then copies module.* (i.e. all the module dependency files
produced) back into <install_dir>/<subdir>/KERNEL_VERSION/ .

The dependency mechanism means that so long as you have your
roles set up correctly, even if your sub-packages attempt to
depmod on their own (as the kernel does), this package will
always run later and overwrite the bad module dependencies
with new, good ones.

If you are deploying multiple roles which each compute their
dependencies separately, you will need to use the cpio ordering
feature to make sure the right module database gets copied into
your final cpio archive - we can't do this for you (yet)
because there are no facilities yet for post-deployment
operations and we can't create the dependency database on the
way because the files don't all exist in the same place that
we'd need them to to run depmod.

Grr. Aargh. *beat head against wall*. Etc.

"""

import muddled.pkg as pkg
from muddled.pkg import PackageBuilder
import muddled.utils as utils
import muddled.depend as depend
from muddled.depend import Label
import os
import re


g_moduledb_re = re.compile(r'modules\..*')
g_kmodule_re  = re.compile(r'.*\.ko')

def predicate_is_module_db(name):
    """
    Decide if a full path name is list modules.*
    """
    global g_moduledb_re

    b = os.path.basename(name)
    if (g_moduledb_re.match(b) is not None):
        return name
    else:
        return None


def predicate_is_kernel_module(name):
    b = os.path.basename(name)
    if g_kmodule_re.match(b) is not None:
        return name
    else:
        return None


class MergeDepModBuilder(PackageBuilder):
    """
    Use depmod_merge to merge several depmod databases into a
     single result. We do this by writing a depmod.conf in
     our object directory and then invoking depmod.

     custom_depmod tells us we want to use a custom depmod.
     """

    def __init__(self, name, role, custom_depmod = None):
        """
        Constructor for the depmod package

        self.components is a list of (label, subdir) pairs which we combine in our
                        object directory to form a unified module database on which
                        we can run depmod.

        """
        PackageBuilder.__init__(self, name, role)
        self.components = [ ]
        self.custom_depmod = custom_depmod


    def add_label(self, label, subdir):
        self.components.append( (label, subdir) )


    def build_label(self, builder, label):
        our_dir = builder.package_obj_path(label)

        dirlist = [ ]
        tag = label.tag

        if (tag == utils.LabelTag.Built or tag == utils.LabelTag.Installed):
            for (l,s) in self.components:
                tmp = Label(utils.LabelType.Package, l.name, l.role, domain=label.domain)
                root_dir = builder.package_install_path(tmp)
                dirlist.append( (root_dir, s) )

                print "dirlist:"
                for (x,y) in dirlist:
                    print "%s=%s \n"%(x,y)


        if (tag == utils.LabelTag.PreConfig):
            pass
        elif (tag == utils.LabelTag.Configured):
            pass
        elif (tag == utils.LabelTag.Built):
            # OK. Building. This is ghastly ..
            utils.recursively_remove(our_dir)
            utils.ensure_dir(our_dir)
            # Now we need to copy all the subdirs in ..
            for (root, sub) in dirlist:
                utils.ensure_dir(utils.rel_join(our_dir, sub))
                # Only bother to copy kernel modules.
                names = utils.find_by_predicate(utils.rel_join(root, sub),
                                                predicate_is_kernel_module)
                utils.copy_name_list_with_dirs(names,
                                               utils.rel_join(root,sub),
                                               utils.rel_join(our_dir, sub))


            # .. and run depmod.
            depmod = "depmod"
            if (self.custom_depmod is not None):
                depmod = self.custom_depmod

            # Because depmod is brain-dead, we need to give it explicit versions.
            names = os.listdir(utils.rel_join(our_dir, "lib/modules"))
            our_re = re.compile(r'\d+\.\d+\..*')
            for n in names:
                if (our_re.match(n) is not None):
                    print "Found kernel version %s in %s .. "%(n, our_dir)
                    utils.run0("%s -b %s %s"%(depmod, our_dir, n))

        elif (tag == utils.LabelTag.Installed):
            # Now we find all the modules.* files in our_dir and copy them over
            # to our install directory
            names = utils.find_by_predicate(our_dir, predicate_is_module_db)
            tgt_dir = builder.package_install_path(label)
            utils.copy_name_list_with_dirs(names, our_dir, tgt_dir)
            for n in names:
                new_n = utils.replace_root_name(our_dir, tgt_dir, n)
                print "Installed: %s"%(new_n)

        elif (tag == utils.LabelTag.Clean):
            utils.recursively_remove(our_dir)
        elif (tag == utils.LabelTag.DistClean):
            utils.recursively_remove(our_dir)


def add(builder, merger, pkg, role, subdir = "/lib/modules"):
    add_roles(builder, merger, pkg, [ role ], subdir)

def add_roles(builder, merger, pkg, roles, subdir = "/lib/modules"):
    lst = [ ]
    for r in roles:
        lst.append( (pkg, r) )
    add_deps(builder, merger, lst, subdir)


def add_deps(builder, merger, deps, subdir = "/lib/modules"):
    """
    Add a set of packages and roles to this merger as packages which create
    linux kernel modules. deps is a list of (pkg,role)
    """
    pkg.do_depend(builder, merger.name, [ merger.role ],
                  deps)

    for (pname, role) in deps:
        lbl = depend.Label(utils.LabelType.Package,
                           pname,
                           role,
                           utils.LabelTag.PostInstalled)
        merger.add_label(lbl, subdir)


def create(builder, name, role,
           pkgs_and_roles,
           custom_depmod = None,
           subdir = "/lib/modules"):
    """
    Create a depmod_merge . It will depend on each of the mentioned packages.

    pkgs is a list of (pkg, role) pairs.

    We return the depmod_merge we've created.
    """

    action = MergeDepModBuilder(name, role, custom_depmod)

    pkg.add_package_rules(builder.ruleset, name, role, action)
    pkg.do_depend(builder, name, [role], pkgs_and_roles)

    for (pname, role) in pkgs_and_roles:
        lbl = depend.Label(utils.LabelType.Package,
                           pname,
                           role,
                           utils.LabelTag.PostInstalled)
        action.add_label(lbl, subdir)

    return action


# End file.
