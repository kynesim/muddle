"""
Some code which sneakily steals binaries from Debian/Ubuntu

Quite a lot of code for embedded systems can be grabbed pretty much
directly from the relevant Ubuntu binary packages - this won't work
with complex packages like exim4 without some external frobulation,
since they have relatively complex postinstall steps, but it works
quite nicely for things like util-linux, and provided you're on a
supported architecture it's a quick route to externally maintained
binaries which actually work and it avoids having to build
absolutely everything in your linux yourself.

This package allows you to 'build' a package from a source file in
a checkout which is a .deb. We run dpkg with enough force options
to install it in the relevant install directory.

You still need to provide any relevant instruction files
(we'll register <filename>.instructions.xml for you automatically
if it exists).

We basically ignore the package database (there is one, but
it's always empty and stored in the object directory)
"""

import muddled.pkg as pkg
from muddled.pkg import PackageBuilder
import muddled.utils as utils
import muddled.checkouts.simple as simple_checkouts
import os

class DebDependable(PackageBuilder):
    """
    Use dpkg to extract debian archives from the given
    checkout into the install directory.
    """

    def __init__(self, name, role, builder, co, pkg_name, pkg_file,
                 instr_name = None, 
                 postInstallMakefile = None):
        """
        @param co  Is the checkout name in which the package resides.
        @param pkg_name is the name of the package (dpkg needs it)
        @param pkg_file is the name of the file the package is in, relative to
                          the checkout directory.
        @param instr_name is the name of the instruction file, if any.
        @param postInstallMakefile if not None, 'make -f postInstallMakefile <pkg-name>'
                          will be run at post-install time to make links, etc.
        """
        PackageBuilder.__init__(self, name, role)
        self.builder = builder
        self.co_name = co
        self.pkg_name = pkg_name
        self.pkg_file = pkg_file
        self.instr_name = instr_name
        self.post_install_makefile = postInstallMakefile


    def ensure_dirs(self, label):
        inv = self.builder.invocation

        if not os.path.exists(inv.checkout_path(self.co_name)):
            raise utils.Failure("Path for checkout %s does not exist."%self.co_name)

        utils.ensure_dir(inv.package_install_path(label.name, label.role))
        utils.ensure_dir(inv.package_obj_path(label.name, label.role))
        
    def build_label(self, label):
        """
        Build the relevant label
        """
        
        self.ensure_dirs(label)
        
        tag = label.tag
        
        if (tag == utils.Tags.PreConfig):
            # Nothing to do.
            pass
        elif (tag == utils.Tags.Configured):
            pass
        elif (tag == utils.Tags.Built):
            pass
        elif (tag == utils.Tags.Installed):
            # Concoct a suitable dpkg command.
            inv = self.builder.invocation
            inst_dir = inv.package_install_path(label.name, label.role)
            co_dir = inv.checkout_path(self.co_name)

            # Using dpkg doesn't work here for many reasons.
            dpkg_cmd = "dpkg-deb -X %s %s"%(os.path.join(co_dir, self.pkg_file), 
                                            inst_dir)
            utils.run_cmd(dpkg_cmd)
            
            # Pick up any instructions that got left behind
            instr_file = self.instr_name
            if (instr_file is None):
                instr_file = "%s.instructions.xml"%(label.name)
            
            instr_path = os.path.join(co_dir, instr_file)

            if (os.path.exists(instr_path)):
                # We have instructions ..
                ifile = db.InstructionFile(instr_path)
                ifile.get()
                builder.instruct(label.name, label.role, ifile)
        elif (tag == utils.Tags.PostInstalled):
            if self.post_install_makefile is not None:
                utils.run_cmd("make -f %s %s-postinstall"%(self.post_install_makefile, 
                                                           label.name))
        elif (tag == utils.Tags.Clean or tag == utils.Tags.DistClean):#
            inv = self.builder.invocation
            admin_dir = os.path.join(inv.package_obj_path(label.name, label.role))
            utils.recursively_remove(admin_dir)
        else:
            raise utils.Error("Invalid tag specified for deb pkg %s"%(label))

def simple(builder, coName, name, roles, 
           depends_on = [ ],
           pkgFile = None, debName = None, instrFile = None, 
           postInstallMakefile = None):
    """
    Build a package called 'name' from co_name / pkg_file with
    an instruction file called instr_file. 

    'name' is the name of the muddle package and of the debian package.
    if you want them different, set deb_name to something other than
    None
    """
    if (debName is None):
        debName = name


    if (pkgFile is None):
        pkgFile = debName

    for r in roles:
        dep = DebDependable(name, r, builder, coName, debName, 
                            pkgFile, instrFile, 
                            postInstallMakefile)
        pkg.add_package_rules(builder.invocation.ruleset, 
                              name, r, dep)
        # We should probably depend on the checkout .. .
        pkg.package_depends_on_checkout(builder.invocation.ruleset, 
                                        name, r, coName, dep)
        # .. and some other packages. Y'know, because we can ..
        pkg.package_depends_on_packages(builder.invocation.ruleset, 
                                        name, r, utils.Tags.PreConfig, 
                                        depends_on)
        
    # .. and that's it.

def deb_prune(h):
    """
    Given a cpiofile heirarchy, prune it so that only the useful 
    stuff is left.
    
    We do this by lopping off directories, which is easy enough in
    cpiofile heirarchies.
    """
    h.erase_target("/usr/share/doc")
    h.erase_target("/usr/share/man")



# End file.


    
    
            

            
                
    

        
        

