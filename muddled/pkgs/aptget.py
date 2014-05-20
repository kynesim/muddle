"""
An apt-get package. When you try to build it, this package
pulls in a pre-canned set of packages via apt-get.
"""

import subprocess

import muddled.pkg as pkg
import muddled.depend as depend

from muddled.utils import GiveUp, LabelTag, LabelType
from muddled.utils import run2, Choice, get_os_version_name


class AptGetBuilder(pkg.PackageBuilder):
    """
    Make sure that particular OS packages have been installed.

    The "build" action for AptGetBuilder uses the Debian tool apt-get
    to ensure that each package is installed.
    """

    def __init__(self, name, role,  pkgs_to_install, os_version=None):
        """Our arguments are:

        * 'name' - the name of this builder
        * 'role' - the role to which it belongs
        * 'pkgs_to_install' - a sequence specifying which packages are to be
          installed.

        Each item in the sequence 'pkgs_to_install' can be:

        * the name of an OS package to install - for instance, 'libxml2-dev'

          (this is backwards compatible with how this class worked in the past)

        * a Choice allowing a particular package to be selected according to
          the operating system.

          See "muddle doc Choice" for details on the Choice class.

          Note that a choice resulting in None (i.e., where the default value
          is None, and the default is selected) will not do anything.

          If 'os_version' is given, then it will be used as the version name,
          otherwise the result of calling utils.get_os_version_name() will be
          used.

        We also allow a single string, or a single Choice, treated as if they
        were wrapped in a list.
        """
        super(AptGetBuilder, self).__init__(name, role)

        actual_packages = []

        if os_version is None:
            os_verson = get_os_version_name()

        if isinstance(pkgs_to_install, basestring):
            # Just a single package
            actual_packages.append(pkgs_to_install)
        elif isinstance(pkgs_to_install, Choice):
            # Just a single Choice
            # Make a choice according to the OS info
            choice = pkgs_to_install.choose_to_match_os(os_version)
            if choice is not None:
                actual_packages.append(choice)
        else:
            for pkg in pkgs_to_install:
                if isinstance(pkg, basestring):
                    actual_packages.append(pkg)
                elif isinstance(pkg, Choice):
                    # Make a choice according to the OS info
                    choice = pkg.choose_to_match_os(os_version)
                    if choice is not None:
                        actual_packages.append(choice)
                else:
                    raise GiveUp('%r is not a string or a Choice'%pkg)

        self.pkgs_to_install = actual_packages

    def already_installed(self, pkg):
        """
        Decide if the quoted debian package is already installed.

        We use dpkg-query::

            $ dpkg-query -W -f=\${Status}\\n libreadline-dev
            install ok installed

        That third word means what it says (installed). Contrast with a package
        that is either not recognised or has not been downloaded at all::

            $ dpkg-query -W -f=\${Status}\\n a0d
            dpkg-query: no packages found matching a0d

        So we do some fairly simple processing of the output...
        """
        retval, stdout = run2([ "dpkg-query", "-W", "-f=\${Status}\\n'", pkg ],
                                    show_command=False)
        if retval:
            # Assume it's not installed
            return False

        lines = stdout.splitlines()
        if len(lines) == 0:
            return False

        words = lines[0].split()
        if len(words) == 3 and words[2] == 'installed':
            return True
        else:
            return False


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
                cmd_list = [ "sudo", "apt-get", "install" ]
                cmd_list.extend(need_to_install)
                print "> %s"%(" ".join(cmd_list))
                rv = subprocess.call(cmd_list)
                if rv != 0:
                    raise GiveUp("Couldn't install required packages")

            print ">> Installed %s"%(" ".join(self.pkgs_to_install))


def simple(builder, name, role, apt_pkgs, os_version=None):
    """
    Construct an apt-get package in the given role with the given apt_pkgs.

    Note that apt_pkgs can be an OS package name or a Choice - see
    the documentation for AptGetBuilder for more details.

    For instance (note: not a real example - the dependencies don't make
    sense!)::

        from muddled.utils import Choice
        from muddled.pkgs import aptget
        aptget.simple(builder, "host_packages", "host_environment",
               [
               "gcc-multilib",
               "g++-multilib",
               "lib32ncurses5-dev",
               "lib32z1-dev",
               "bison",
               "flex",
               "gperf",
               "libx11-dev",
               # On Ubuntu 11 or 12, choose icedtea-7, otherwise icedtea-6
               Choice([ ("ubuntu 1[12].*", "icedtea-7-jre"),
                        ("ubuntu *", "icedtea-6-jre") ]),
               # On Ubuntu 10 or later, use libgtiff5
               # On Ubuntu 3 through 9, use libgtiff4
               # Otherwise, just don't try to use libgtiff
               Choice([ ("ubuntu 1?", "libgtiff5"),
                        ("ubuntu [3456789]", "libgtiff4"),
                        None ])
               ])
    """

    the_pkg = AptGetBuilder(name, role, apt_pkgs, os_version)
    pkg.add_package_rules(builder.ruleset,
                          name, role, the_pkg)


def depends_on_aptget(builder, name, role, pkg, pkg_role):
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
        depends_on_aptget(builder, name, role, "*", dep_role)




# End file.

