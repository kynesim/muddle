"""
This package allows you to force the installation of some packages
from an alternate repository. This accounts for the increasingly
large number of Ubuntu packages where the version available in
Ubuntu is named identically to the correct version,  but is 
too old to use successfully.
"""

import subprocess

import muddled.pkg as pkg
import muddled.depend as depend
import os.path
from muddled.utils import GiveUp, LabelTag, LabelType
from muddled.utils import run2, Choice, get_os_version_name
from muddled.utils import split_debian_version, debian_version_is

class AptAltBuilder(pkg.PackageBuilder):
    """
    Ensure that particular versions of apt packages are installed, from
    particular repositories
    """

    def __init__(self, name, role, pkgs_to_install, os_version = None):
        """
        pkgs_to_install is a list of dicts:
        { name: 'pkg_name', min-version: , max-version: ,exact-version:, 
          repo: }
        """
        super(AptAltBuilder, self).__init__(name, role)
        
        actual_packages = [ ]
        if (os_version is None):
            os_version = get_os_version_name()

        for pkg in pkgs_to_install:
            if isinstance(pkg, Choice):
                # A single choice.
                choice = pkg.choose_to_match_os(os_version)
                if (choice is not None):
                    actual_packages.append(choice)
            else:
                actual_packages.append(pkg)
        self.pkgs_to_install = actual_packages
        
    def current_version(self, pkg):
        retval, stdout = run2([ "dpkg-query", "-W", 
                                "-f=${Status} ${Version}\\n", pkg["name"] ],
                                    show_command=True)
        if retval:
            # Assume it's not installed
            return None

        lines = stdout.splitlines()
        if len(lines) == 0:
            return None

        words = lines[0].split()
        if not (len(words) == 4 and words[2] == 'installed'):
            return None
        
        vsn_text = words[3]
        vsn = split_debian_version(words[3])
        return vsn

    def already_installed(self, pkg):
        """
        Decide if a package is installed and the right version
        """
        retval, stdout = run2([ "dpkg-query", "-W", "-f=${Status} ${Version}\\n", pkg["name"] ],
                                    show_command=True)
        if retval:
            # Assume it's not installed
            return False

        lines = stdout.splitlines()
        if len(lines) == 0:
            return False

        words = lines[0].split()
        if not (len(words) == 4 and words[2] == 'installed'):
            return False
        
        vsn_text = words[3]
        vsn = split_debian_version(words[3])
        if ("exact-version" in pkg):
            r = (debian_version_is(vsn, split_debian_version(pkg['exact-version'])))
            if (r != 0):
                print " %s=%s is not required version %s"%(pkg['name'], vsn_text, 
                                                           pkg['exact-version'])
                return False
            else:
                return True
        if ("min-version" in pkg):
            r = debian_version_is(vsn, split_debian_version(pkg['min-version']))
            if (r < 0):
                print " %s=%s is too old (require %s)"%(pkg['name'], vsn_text, 
                                                        pkg['min-version'])
                return False
            else:
                return True
        if ("max-version" in pkg):
            r = (debian_version_is(vsn, split_debian_version(pkg['max-version'])) < 1)
            if (r > 0):
                print " %s=%s is too new (require <= %s)"%(pkg['name'], vsn_text,
                                                          pkg['min-version'])
                return False
            else:
                return True

        # If no-one cares about the version, then .. 
        return True


    def build_label(self, builder, label):
        """
        This time, build is the only one we care about.
        """

        if (label.tag == LabelTag.Built):
            need_to_install = [ ]

            for cur_pkg in self.pkgs_to_install:
                if (not self.already_installed(cur_pkg)):
                    need_to_install.append(cur_pkg)

            if (len(need_to_install) > 0):
                for q in need_to_install:
                    # Sadly, we need sudo quite a lot here.
                    print ">> Processing %s"%q["name"]
                    print "   : Remove old packages.\n"
                    cmd_list = [ "sudo", "apt-get", "remove", q["name"] ]
                    rv = subprocess.call(cmd_list)
                    if (q["repo"] is not None):
                        if (has_additional_repo(builder, q["repo"])):
                            print "   : Already have repo %s"%q["repo"]
                        else:
                            print "   : Adding repository %s"%q["repo"]
                            cmd_list = [ "sudo", "add-apt-repository",
                                         q["repo"] ]
                            rv = subprocess.call(cmd_list)
                            if (rv != 0):
                                raise GiveUp("Cannot add repo '%s'"%q["repo"])
                    print ">> Update package lists \n"
                    cmd_list = [ "sudo", "apt-get", "update" ]
                    rv = subprocess.call(cmd_list)
                    # Ignore failures - just means some lists couldn't
                    # be got.
                    to_install = q["name"]
                    if ("exact-version" in q):
                        to_install = "%s=%s"%(q["name"], q["exact-version"])                        
                    print ">> Installing %s"%to_install
                    cmd_list = [ "sudo", "apt-get", "install",
                                 "%s"%to_install ]
                    rv = subprocess.call(cmd_list)
                    if (rv != 0):
                        raise GiveUp("Cannot install %s"%to_install)
                    # Now ..
                    if (not self.already_installed(q)):
                        raise GiveUp(("Installed %s, but I still don't " + 
                                      "have the right version - spec %s," + 
                                      "installed:%s")%(q["name"], q, 
                                                 self.current_version(q)))
            print ">> Installed %s"%(" ".join(map(lambda x: x["name"], self.pkgs_to_install)))

def has_additional_repo(builder, repo):
    for additional_sources in [
            "/etc/apt/sources.list.d/additional-repositories.list",
            "/etc/apt/sources.list" ]:
        if (os.path.exists(additional_sources)):
            with open(additional_sources, 'r') as s:
                lines = s.readlines()
                for l in lines:
                    if (l.find(repo) != -1):
                        return True
    return False

def simple(builder, name, role, apt_pkgs, os_version=None):
    """
    Construct an apt-alt package in the given role with the given apt_pkgs, 
    which are dictionaries:
    (name : 'name', min-version : , exact-version : , max-version: , repo : )
    """
    the_pkg = AptAltBuilder(name, role, apt_pkgs, os_version)
    pkg.add_package_rules(builder.ruleset, name, role, the_pkg)


def depends_on_aptalt(builder, name, role, pkg, pkg_role):
    """
    Make a package dependant on a particular apt-builder.

    * pkg - The package we want to add a dependency to. '*' is a good thing to
      add here ..
    """

    tgt_label = depend.Label(LabelType.Package,
                             pkg,  pkg_role,
                             LabelTag.PreConfig)

    the_rule = builder.ruleset.rule_for_target(tgt_label,
                                               createIfNotPresent = True)
    the_rule.add(depend.Label(LabelType.Package,
                              name, role,
                              LabelTag.PostInstalled))


def medium(builder, name, role, apt_pkgs, roles, os_version=None):
    """
    Construct an apt-get package and make every package in the named roles
    depend on it.

    Note that apt_pkgs can be an OS package name or a choices sequence - see
    the documentation for AptGetBuilder.
    """
    simple(builder, name, role, apt_pkgs, os_version=None)
    for dep_role in roles:
        depends_on_aptalt(builder, name, role, "*", dep_role)



# End file.
