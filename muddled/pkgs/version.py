"""
Write a version.xml file containing version information for the
current build
"""

import muddled.pkg as pkg
from muddled.pkg import PackageBuilder
import muddled.utils as utils
import muddled.depend as depend
import os

class VersionBuilder(PackageBuilder):
    """
    Write a version number file
    """

    def __init__(self, name, role, 
                 filename,
                 swname = None,
                 version = None,
                 build = None,
                 withDate = True,
                 withUser = True,
                 withMachine= True):
        """
        Constructor for the version package type
        """
        PackageBuilder.__init__(self, name, role)
        self.filename = filename
        self.swname = swname
        self.version = version
        self.build = build
        self.withDate = withDate
        self.withUser = withUser
        self.withMachine = withMachine

    def dir_name(self):
        file = self.file_name()
        (fst,snd) =  os.path.split(file)
        return fst

    def file_name(self):
        inst_path = self.builder.invocation.package_install_path(self.name, self.role)
        ret = utils.rel_join(inst_path, self.filename)
        return ret

    def erase_version_file(self):
        """
        Erase the version file.
        """
        os.remove(self.file_name())

    def write_elem(self, f, elem, val):
        if (val is not None):
            f.write(" <%s>%s</%s>\n"%(elem,val,elem))

    def write_version_file(self):
        """
        Write the version file
        """

        utils.ensure_dir(self.dir_name())
        print "dir %s ensured."%(self.dir_name())
        f = open(self.file_name(), 'w')
        f.write("<?xml version=\"1.0\" ?>\n")
        f.write("\n")
        f.write("<version>\n")
        self.write_elem(f, "name", self.swname)
        self.write_elem(f, "version", self.version)
        self.write_elem(f, "build", self.build)
        if (self.withDate):
            self.write_elem(f, "built-at", utils.iso_time())
            self.write_elem(f, "built-time", utils.unix_time())
        if (self.withUser):
            self.write_elem(f, "built-by", utils.current_user())
        if (self.withMachine):
            self.write_elem(f, "built-on", utils.current_machine_name())
        f.write("</version>\n")
        f.close()

        
    def build_label(self, builder, label):
        """
        Build the version.xml file.
        """
        tag = label.tag

        if (tag == utils.Tags.Installed):
            # Write our version file.
            self.write_version_file()
        elif (tag == utils.Tags.Clean):
            self.erase_version_file()
        elif (tag == utils.Tags.DistClean):
            self.erase_version_file()


def simple(builder, name, roles, 
           filename = "/version.xml",
           swname = None,
           version = None,
           build = None,
           withDate = True,
           withUser = True,
           withMachine = True):

    for r in roles:
        the_pkg = VersionBuilder(name, r, filename,
                                 swname, version, build, withDate, withUser, withMachine)
        pkg.add_package_rules(builder.invocation.ruleset,
                              name, r, the_pkg)
    


# End File.
                
    
