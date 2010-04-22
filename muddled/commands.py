"""
Muddle commands - these get run more or less directly by 
the main muddle command and are abstracted out here in
case your programs want to run them themselves
"""

# The use of Command subclass docstrings as "help" texts relies on the
# non-PEP8-standard layout of the docstrings, with the opening triple
# quote on a line by itself, and the text starting on the next line.
#
#    (This is "house style" in the muddled package anyway.)
#
# XXX It also means that a firm decision needs to be made about those
# XXX same docstrings. For "help" purposes, as unadorned (by markup)
# XXX as possible is good, whilst for sphix/reStructuredText purposes,
# XXX somewhat more markup would make the generated documentation better
# XXX (and more consistent with other muddled modules).

from db import Database
import db
import depend
import env_store
import instr
import mechanics
import pkg
import test
import time
import utils
import version_control

import difflib
import re
import traceback
import os
import xml.dom.minidom
import subst
import subprocess
import sys
import urllib
from urlparse import urlparse
from ConfigParser import RawConfigParser


class Command:
    """
    Abstract base class for muddle commands

    Each subclass is a ``muddle`` command, and its docstring is the "help"
    text for that command.
    """

    def __init__(self):
        self.options = { }

    def help(self):
        return self.__doc__

    def name(self):
        """
        The name of this command - ``muddle <name>`` is used to run it.
        """
        return None

    def aliases(self):
        """
        A list of any aliases for this command. Be sparing in its use.
        """
        return []

    def requires_build_tree(self):
        """
        Returns True iff this command requires an initialised
        build tree, False otherwise.
        """
        return True

    def set_options(self, opt_dict):
        """
        Set command options - usually from the options passed to mudddle.
        """
        self.options = opt_dict

    def set_old_env(self, old_env):
        """
        Take a copy of the environment before muddle sets its own
        variables - used by commands like subst to substitute the
        variables in place when muddle was called rather than those
        that would apply when the susbt command was executed.
        """
        self.old_env = old_env
        
     
    def no_op(self):
        """
        Is this is a no-op (just print) operation?
        """
        return ("no_operation" in self.options)


    def with_build_tree(self, builder, local_pkgs, args):
        """
        Run this command with a build tree.
        """
        raise utils.Error("Can't run %s with a build tree."%self.name())

    def without_build_tree(self, muddle_binary, root_path, args):
        """
        Run this command without a build tree.
        """
        raise utils.Error("Can't run %s without a build tree."%self.name())
        

class Root(Command):
    """
    :Syntax: root

    Display the root directory we reckon you're in.
    """
    
    def name(self): 
        return "root"

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, local_pkgs, args):
        print "%s"%(builder.invocation.db.root_path)
        
    def without_build_tree(self, muddle_binary, root_path, args):
        print "<uninitialized> %s"%(root_path)


class Init(Command):
    """
    :Syntax: init <repository> <build_description>

    Initialise a new build tree with a given repository and build description.
    We check out the build description but don't actually build.

    For instance::

      $ cd /somewhere/convenient
      $ muddle init  file+file:///somewhere/else/examples/d  builds/01.py

    This initialises a muddle build tree with::

      file+file:///somewhere/else/examples/d

    as its repository and a build description of "builds/01.py".

    The astute will notice that you haven't told muddle which actual repository
    the build description is in - you've only told it where the repository root
    is and where the build description file is.

    Muddle assumes that builds/01.py means repository
    "file+file:///somewhere/else/examples/d/builds" and file "01.py" therein.
    """

    def name(self): 
        return "init"

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, local_pkgs, args):
        raise utils.Error("Can't initialise a build tree " 
                    "when one already exists (%s)"%builder.invocation.db.root_path)
    
    def without_build_tree(self, muddle_binary, root_path, args):
        """
        Initialise a build tree.
        """
        if len(args) != 2:
            raise utils.Error(self.__doc__)

        repo = args[0]
        build = args[1]

        if (not self.no_op()):
            db = Database(root_path)
            db.repo.set(repo)
            db.build_desc.set(build)
            db.commit()

        print "Initialised build tree in %s "%root_path
        print "Repository: %s"%repo
        print "Build description: %s"%build
        print "\n"

        if (not self.no_op()):
            print "Checking out build description .. \n"
            mechanics.load_builder(root_path, muddle_binary)

        print "Done.\n"
        
        return 0

class UnitTest(Command):
    """
    :Syntax: unit_test

    Run the muddle unit tests.
    """
    
    def name(self): 
        return "unit_test"

    def aliases(self):
        return ["unittest"]             # because other commands don't have "_"

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, local_pkgs, args):
        return test.unit_test()

    def without_build_tree(self, muddle_binary, root_path, args):
        return test.unit_test()

class ListVCS(Command):
    """
    :Syntax: vcs

    List the version control systems supported by this version of muddle,
    together with their VCS specifiers.
    """

    def name(self):
        return "vcs"

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, local_pkgs, args):
        return self.do_command()

    def without_build_tree(self, muddle_binary, root_path, args):
        return self.do_command()

    def do_command(self):
        str_list = [ ]
        str_list.append("Available version control systems:\n\n")
        str_list.append(version_control.list_registered())

        str = "".join(str_list)
        print str
        return 0

class Depend(Command):
    """
    :Syntax: depend <what>
    :or:     depend <what> <label>

    Print the current dependency sets. Not specifying a label is the same as
    specifying "_all".

    In order to show all dependency sets, even those where a given label does
    not actually depend on anything, <what> can be:

    * system       - Print synthetic dependencies produced by the system
    * user         - Print dependencies entered by the build description
    * all          - Print all dependencies

    To show only those dependencies where there *is* a dependency, add '-short'
    to <what>, i.e.:

    * system-short - Print synthetic dependencies produced by the system
    * user-short   - Print dependencies entered by the build description
    * all-short    - Print all dependencies
    """
    
    def name(self):
        return "depend"

    def aliases(self):
        return ["depends"]      # because I can never remember which it is

    def requires_build_tree(self):
        return True
    
    def without_build_tree(self, muddle_binary, root_path, args):
        raise utils.Error("Cannot run without a build tree")

    def with_build_tree(self, builder, local_pkgs, args):
        if len(args) != 1 and len(args) != 2:
            print "Syntax: depend [system|user|all][-short] <label to match>"
            print self.__doc__
            return 2
        
        type = args[0]
        if len(args) == 2:
            label = depend.label_from_string(args[1])
        else:
            label = None

        show_sys = False
        show_user = False

        if type.endswith("-short"):
            # Show only those rules with a dependency
            ignore_empty = True
            type = type[:-len("-short")]
        else:
            # Show *all* rules, even those which don't depend on anything
            ignore_empty = False

        if type == "system":
            show_sys = True
        elif type == "user":
            show_user = True
        elif type == "all":
            show_sys = True
            show_user = True
        else:
            raise utils.Error("Bad dependency type: %s"%(type))

        
        print builder.invocation.ruleset.to_string(matchLabel = label, 
                                                   showSystem = show_sys, showUser = show_user,
                                                   ignore_empty = ignore_empty)

class Query(Command):
    """
    :Syntax: query <cmd1>
    :or:     query <cmd2> <label>

    'query <cmd1>' prints out information that doesn't need a label. <cmd1> may
    be any of:

    * checkouts    - Print a list of known checkouts.
    * packages     - Print a list of known packages.
                     If there is a rule for "package:*{}/*" (for instance),
                     then '*' will be included in the names returned.
    * roles        - Print a list of known roles.
    * root         - Print the root path and default domain
    * name         - Print the build name, as specified in the build description.
                     This prints just the name, so that one can use it in the
                     shell - for instance in bash::

                          export PROJECT_NAME=$(muddle query name)

                     'query <cmd2> <label>' prints information about the label
                     - the environment in which it will execute, or what it
                     depends on, or what depends on it.

    <cmd2> may be any of:

    * deps         - Print what we need to build to build this label
    * dir          - Print a directory: for checkout labels, the checkout dir.
                     For package labels, the install dir. For deployment labels
                     the deployment dir.
    * env          - Print the environment in which this label will be run.
    * envs         - Print a list of the environments that will be merged
                     to create the resulting environment for this 
    * inst-details - Print the list of actual instructions,
                     in the order in which they will be applied.
    * instructions - Print the list of currently registered instruction files,
                     in the order in which they will be applied.
    * objdir       - Print the object directory for a label,
                     used to extract object directories for configure options
                     in builds.
    * preciseenv   - Print the environment pertaining to exactly this label
                     (no fuzzy matches)
    * results      - Print what this label is required to build
    * rule         - Print the rules covering building this label.
    * targets      - Print the targets that would be built
                     by an attempt to build this label.

    The label needs to specify at least <type>:<name>/<tag> (although the
    <name> and <tag> are often most useful when wildcarded).
    """

    def name(self):
        return "query"

    def requires_build_tree(self):
        return True

    def _query_objdir(self, builder, label):
        print builder.invocation.package_obj_path(label.name, label.role, 
                                                  domain = label.domain)

    def _query_preciseenv(self, builder, label):
        the_env = builder.invocation.get_environment_for(label)

        local_store = env_store.Store()
        builder.set_default_variables(label, local_store)
        local_store.merge(the_env)

        print "Environment for %s .. "%label
        print local_store.get_setvars_script(builder, label, env_store.EnvLanguage.Sh)

    def _query_envs(self, builder, label):
        a_list = builder.invocation.list_environments_for(label)
        
        for (lvl, label, env) in a_list:
            print "-- %s [ %d ] --\n%s\n"%(label, lvl, 
                                            env.get_setvars_script
                                            (builder, 
                                             label,
                                             env_store.EnvLanguage.Sh))
        print "---"

    def _query_env(self, builder, label):
        the_env = builder.invocation.effective_environment_for(label)
        print "Effective environment for %s .. "%label
        print the_env.get_setvars_script(builder, label, env_store.EnvLanguage.Sh)

    def _query_rule(self, builder, label):
        local_rule = builder.invocation.ruleset.rule_for_target(label)
        if (local_rule is None):
            print "No ruleset for %s"%label
        else:
            print "Rule set for %s .. "%label
            print local_rule

    def _query_targets(self, builder, label):
        local_rules = builder.invocation.ruleset.targets_match(label, useMatch = True)
        print "Targets that match %s .. "%(label)
        for i in local_rules:
            print "%s"%i

    def _query_deps(self, builder, label):
        to_build = depend.needed_to_build(builder.invocation.ruleset, label, useMatch = True)
        if (to_build is None):
            print "No dependencies for %s"%label
        else:
            print "Build order for %s .. "%label
            for rule in to_build:
                print rule.target

    def _query_results(self, builder, label):
        result = depend.required_by(builder.invocation.ruleset, label)
        print "Labels which require %s to build .. "%label
        for lbl in result:
            print lbl

    def _query_instructions(self, builder, label):
        result = builder.invocation.db.scan_instructions(label)
        for (l, f) in result:
            print "Label: %s  Filename: %s"%(l,f)

    def _query_inst_details(self, builder, label):
        loaded = builder.load_instructions(label)
        for (l, f, i) in loaded:
            print " --- Label %s , filename %s --- "%(l, f)
            print i.get_xml()
        print "-- Done --"

    def _query_checkouts(self, builder, label):
        cos = builder.invocation.all_checkouts()
        a_list = [ ]
        for c in cos:
            a_list.append(c)
        a_list.sort()
        print "Checkouts: %s"%(" ".join(a_list))

    def _query_packages(self, builder, label):
        cos = builder.invocation.all_packages()
        a_list = [ ]
        for c in cos:
            a_list.append(c)
        a_list.sort()
        print "Packages: %s"%(" ".join(a_list))

    def _query_roles(self, builder, label):
        cos = builder.invocation.all_roles()
        a_list = [ ]
        for c in cos:
            a_list.append(c)
        a_list.sort()
        print "Roles: %s"%(" ".join(a_list))

    def _query_root(self, builder, label):
        print "Root: %s"%builder.invocation.db.root_path
        print "Default domain: %s"%builder.get_default_domain()

    def _query_name(self, builder, label):
        print builder.build_name


    def _query_dir(self, builder, label):
            dir = None

            if (label.role == "*"):
                role = None
            else:
                role = label.role


            if label.type == utils.LabelKind.Checkout:
                dir = builder.invocation.db.get_checkout_path(label.name,
                        domain=label.domain)
            elif label.type == utils.LabelKind.Package:
                dir = builder.invocation.package_install_path(label.name, role,
                        domain=label.domain)
            elif label.type == utils.LabelKind.Deployment:
                dir = builder.invocation.deploy_path(label.name,
                        domain=label.domain)
                
            if dir is not None:
                print dir
            else:
                print None

    # Key is <cmd> name, value is (<does it need a label?>, <method>)
    queries = {
            'checkouts' : (False, _query_checkouts),
            'packages' : (False, _query_packages),
            'roles' : (False, _query_roles),
            'deps' : (True, _query_deps),
            'dir' : (True, _query_dir),
            'env' : (True, _query_env),
            'envs' : (True, _query_envs),
            'inst-details' : (True, _query_inst_details),
            'instructions' : (True, _query_instructions),
            'name' : (False, _query_name),
            'objdir' : (True, _query_objdir),
            'preciseenv' : (True, _query_preciseenv),
            'results' : (True, _query_results),
            'root' : (False, _query_root),
            'rule' : (True, _query_rule),
            'targets' : (True, _query_targets),
            }

    def with_build_tree(self, builder, local_pkgs, args):
        if len(args) < 1:
            print "Syntax: query <cmd> [<label>]"
            print self.__doc__
            return 2

        type = args[0]

        if type not in Query.queries.keys():
            print "Unrecognised query type '%s'"%type
            print self.__doc__
            return 2

        needs_label, fn = Query.queries[type]

        if needs_label:
            if len(args) != 2:
                print "Syntax: query %s <label>"%type
                print self.__doc__
                return 2

            label = depend.label_from_string(args[1])
            if (label is None):
                print "'%s' is not a valid label"%(args[1])
                print "It should contain at least <type>:<name>/<tag>"
                return 3

            if (label.domain is None):
                label.domain = builder.get_default_domain()

            label = builder.invocation.apply_unifications(label)
        else:
            label = None

        fn(self, builder, label)

        return 0


class RunIn(Command):
    """
    :Syntax: runin <label> <command> [ ... ]

    Run the command "<command> [ ...]" in the directory corresponding to every
    label matching <label>.

    * Checkout labels are run in the directory corresponding to their checkout.
    * Package labels are run in the directory corresponding to their object files.
    * Deployment labels are run in the directory corresponding to their deployments.

    We only ever run the command in any directory once.
    """
    
    def name(self):
        return "runin"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        if (len(args) < 2):
            print "Syntax: runin <label> <command> [ ... ]"
            print self.__doc__
            return 2

        labels = decode_labels(builder, args[0:1] );
        command = " ".join(args[1:])
        dirs_done = set()
        orig_environ = os.environ

        for l in labels:
            matching = builder.invocation.ruleset.rules_for_target(l)

            for m in matching:
                lbl = m.target

                dir = None
                if (lbl.name == "*"):
                    # If it's a wildcard, don't bother.
                    continue

                if (lbl.type == utils.LabelKind.Checkout):
                    dir = builder.invocation.checkout_path(lbl.name)
                elif (lbl.type == utils.LabelKind.Package):
                    if (lbl.role == "*"): 
                        continue
                    dir = builder.invocation.package_obj_path(lbl.name, lbl.role)
                elif (lbl.type == utils.LabelKind.Deployment):
                    dir = builder.invocation.deploy_path(lbl.name)
                    
                if (dir in dirs_done):
                    continue

                dirs_done.add(dir)
                if (os.path.exists(dir)):
                    # We want to run the command with our muddle environment
                    # Start with a copy of the "normal" environment
                    env = os.environ.copy()
                    # Add the default environment variables for building this label
                    local_store = env_store.Store()
                    builder.set_default_variables(lbl, local_store)
                    local_store.apply(env)
                    # Add anything the rest of the system has put in.
                    builder.invocation.setup_environment(lbl, env)

                    os.chdir(dir)
                    print "> %s"%dir
                    subprocess.call(command, shell=True, env=env)
                else:
                    print "! %s does not exist."%dir


class BuildLabel(Command):
    """
    :Syntax: buildlabel <label> [ <label> ... ]

    Builds a set of specified labels, without all the defaulting and trying to
    guess what you mean that Build does.
    
    Mainly used internally to build defaults and the privileged half of
    instruction executions.
    """
    
    def name(self):
        return "buildlabel"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_labels(builder, args)
        build_labels(builder, labels)

class Redeploy(Command):
    """
    :Syntax: redeploy <deployment> [<deployment> ... ]

    Remove all tags for the given deployments, erase their built directories
    and redeploy them.

    You can use cleandeploy to just clean the relevant deployments.

    If no deployments are given, we redeploy the default deployment list.
    If _all is given, we redeploy all deployments.
    """
    
    def name(self):
        return "redeploy"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_deployment_arguments(builder, args, local_pkgs,
                                             utils.Tags.Deployed)
        rv = build_a_kill_b(builder, labels, utils.Tags.Clean,
                            utils.Tags.Deployed)
        rv = build_labels(builder, labels)
        return rv
        

class Cleandeploy(Command):
    """
    :Syntax: cleandeploy <deployment> [<deployment> ... ]

    Remove all tags for the given deployments and erase their built
    directories.

    You can use cleandeploy to just clean the relevant deployments.

    If no deployments are given, we redeploy the default deployment list.
    If _all is given, we redeploy all deployments.
    """
    
    def name(self):
        return "cleandeploy"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_deployment_arguments(builder, args, local_pkgs,
                                             utils.Tags.Clean)
        if (labels is None):
            raise utils.Failure("No deployments specified or implied (this may well be a bug).")
        rv = build_a_kill_b(builder, labels, utils.Tags.Clean, utils.Tags.Deployed)


class Deploy(Command):
    """
    :Syntax: deploy <deployment> [<deployment> ... ]

    Build appropriate tags for deploying the given deployments.

    If no deployments are given we will use the default deployment list.
    If _all is given, we'll use all deployments.
    """
    def name(self):
        return "deploy"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_deployment_arguments(builder, args, local_pkgs, 
                                             utils.Tags.Deployed)

        build_labels(builder, labels)



class Build(Command):
    """
    :Syntax: build [ <package>{<role>} ... ]
    
    Build a package. If the package name isn't given, we'll use the
    list of local packages derived from your current directory.

    Unqualified or inferred package names are built in every default
    role (there's a list in the build description).

    If you're in a checkout directory, we'll build every package
    which uses that checkout.

    _all is a special package meaning build everything.
    """
    
    def name(self):
        return "build"

    def requires_build_tree(self):
        return True
    
    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_package_arguments(builder, args, local_pkgs, 
                                          utils.Tags.PostInstalled)
        
        build_labels(builder, labels)


class Rebuild(Command):
    """
    :Syntax: rebuild [ <package>{<role>} ... ]

    Just like build except that we clear any built tags first 
    (and their dependencies).
    """
    
    def name(self):
        return "rebuild"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_package_arguments(builder, args, local_pkgs,
                                          utils.Tags.PostInstalled)

        # OK. Now we have our labels, retag them, and kill them and their
        # consequents
        to_kill = depend.retag_label_list(labels, 
                                          utils.Tags.Built)
        rv = kill_labels(builder, to_kill)
        if rv != 0:
            return rv

        rv = build_labels(builder, labels)
        return rv


class Reinstall(Command):
    """
    :Syntax: reinstall [ <package>{<role>} ... ]

    Reinstall the given packages (but don't rebuild them).
    """
    
    def name(self):
        return "reinstall"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_package_arguments(builder, args, local_pkgs,
                                          utils.Tags.PostInstalled)

        # OK. Now we have our labels, retag them, and kill them and their
        # consequents
        to_kill = depend.retag_label_list(labels, 
                                          utils.Tags.Installed)
        rv = kill_labels(builder, to_kill)
        if rv != 0:
            return rv

        rv = build_labels(builder, labels)
        return rv



class Distrebuild(Command):
    """
    :Syntax: distrebuild [ <package>{<role>} ... ]

    A rebuild that does a distclean before attempting the rebuild.
    """
    
    def name(self):
        return "distrebuild"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_package_arguments(builder, args, local_pkgs,
                                          utils.Tags.PostInstalled)

        if (self.no_op()):
            print "Would have distrebuilt: %s"%(" ".join(map(str, labels)))
        else:
            rv = build_a_kill_b(builder, labels, utils.Tags.DistClean,
                                utils.Tags.PreConfig)
            
            if rv:
                return rv

            rv = build_labels(builder, labels)
            return rv


class Clean(Command):
    """
    :Syntax: clean [ <package>{<role>} ... ]
    
    Just like build except that we clean packages rather than 
    building them. Subsequently, packages are regarded as having
    been configured but not build.
    """
    
    def name(self):
        return "clean"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_package_arguments(builder, args, local_pkgs, 
                                          utils.Tags.Built)
        if (self.no_op()):
            print "Would have cleaned: %s"%(" ".join(map(str, labels)))
            rv = 0
        else:
            rv = build_a_kill_b(builder, labels, utils.Tags.Clean, utils.Tags.Built)

        return rv

class DistClean(Command):
    """
    :Syntax: distclean [ <package>{<role>} ... ]

    Just like clean except that we reduce packages to non-preconfigured
    and invoke 'make distclean'.
    """
    
    def name(self):
        return "distclean"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_package_arguments(builder, args, local_pkgs, 
                                          utils.Tags.Built)

        if (self.no_op()):
            print "Would have disctleaned: %s"%(" ".join(map(str, labels)))
            rv = 0
        else:
            rv = build_a_kill_b(builder, labels, utils.Tags.DistClean, utils.Tags.PreConfig)

        return rv

class Instruct(Command):
    """
    :Syntax: instruct <package>{<role>} <instruction-file>
    :or:     instruct (<domain>)<package>{<role>} <instruction-file>

    Sets the instruction file for the given package name and role to 
    the file specified in instruction-file. The role must be explicitly
    given as it's considered more likely that bugs will be introduced by
    the assumption of default roles than they are likely to prove useful.
    
    This command is typically issued by 'make install' for a package, as::

       $(MUDDLE_INSTRUCT) <instruction-file>
    
    If you don't specify an instruction file, we will unregister instructions
    for this package and role.

    If you want to clear all instructions, you'll have to edit the muddle
    database directly - this leaves the database in an inconsistent state -
    there's no guarantee that the instruction files will ever be rebuilt
    correctly - so it is not a command.

    You can list instruction files and their ordering with the query command.
    """

    def name(self):
        return "instruct"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        if (len(args) != 2 and len(args) != 1):
            print "Syntax: instruct [pkg{role}] <[instruction-file]>"
            print self.__doc__
            return 1

        pkg_role = args[0]
        ifile = None

        # Validate this first - the file check may take a while.
        lbls = labels_from_pkg_args([ pkg_role ], utils.Tags.PreConfig,
                                    [ ], builder.get_default_domain())

        lbls = builder.invocation.map_unifications(lbls)

        if (len(lbls) != 1 or (lbls[0].role is None)):
            raise utils.Failure("instruct takes precisely one package{role} pair "
                                "and the role must be explicit")


        if (len(args) == 2):
            filename = args[1]

            if (not os.path.exists(filename)):
                raise utils.Failure("Attempt to register instructions in " 
                                    "%s: file does not exist"%filename)

            if (self.no_op()):
                print "Register instructions in %s"%(filename)
            else:
                # Try loading it.
                ifile = db.InstructionFile(filename, instr.factory)
                ifile.get()

            # If we got here, it's obviously OK

        
        # Last, but not least, do the instruction ..
        if (not self.no_op()):
            builder.instruct(lbls[0].name, lbls[0].role, ifile, domain=lbls[0].domain)
                                    
class Update(Command):
    """
    :Syntax: update <checkout> [ <checkout> ... ]

    Update the specified checkouts.

    That is, bring each checkout up-to-date with respect to its remote
    repository.

    Each <checkout> should be the name of a checkout, and muddle will obey
    the rule associated with "checkout:<checkout>{}/up_to_date" for each.

    The special <checkout> name _all means all checkouts.

    If no <checkouts> are given, we'll use those implied by your current
    location.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """
    
    def name(self):
        return "update"

    def requires_build_tree(self):
        return True
    
    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_checkout_arguments(builder, args, local_pkgs,
                                              utils.Tags.UpToDate)
        # Forcibly retract all the updated tags.
        if (self.no_op()):
            print "Updating checkouts: %s "%(depend.label_list_to_string(checkouts))
        else:
            for co in checkouts:
                builder.kill_label(co)
                builder.build_label(co)


class Commit(Command):
    """
    :Syntax: commit <checkout> [ <checkout> ... ]

    Commit the specified checkouts to their local repositories.

    For a centralised VCS (e.g., Subversion) where the repository is remote,
    this will not do anything. See the update command.

    If no checkouts are given, we'll use those implied by your current
    location.

    Each <checkout> should be the name of a checkout, and muddle will obey
    the rule associated with "checkout:<checkout>{}/changes_committed" for each.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """
    
    def name(self):
        return "commit"

    def aliases(self):
        return ["dep-commit"]

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_checkout_arguments(builder, args, local_pkgs,
                                              utils.Tags.ChangesCommitted)
        # Forcibly retract all the updated tags.
        if (self.no_op()):
            print "Committing checkouts: %s"%(depend.label_list_to_string(checkouts))
        else:
            for co in checkouts:
                builder.kill_label(co)
                builder.build_label(co)



class Push(Command):
    """
    :Syntax: push <checkout> [ <checkout> ... ]

    Push the specified checkouts to their remote repositories.

    This updates the content of the remote repositories to match the local
    checkout.

    If no checkouts are given, we'll use those implied by your current
    location.

    Each <checkout> should be the name of a checkout, and muddle will obey
    the rule associated with "checkout:<checkout>{}/changes_pushed" for each.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """
    
    def name(self):
        return "push"

    def aliases(self):
        return ["dep-push"]

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_checkout_arguments(builder, args, local_pkgs,
                                              utils.Tags.ChangesPushed)
        # Forcibly retract all the updated tags.
        if (self.no_op()):
            print "Pushing checkouts: %s"%(depend.label_list_to_string(checkouts))
        else:
            for co in checkouts:
                builder.invocation.db.clear_tag(co)
                builder.build_label(co)


class Pull(Command):
    """
    :Syntax: pull <checkout> [ <checkout> ... ]

    Pull the specified checkouts from their remote repositories.

    This updates the content of the local checkouts to match their remote
    repositories.

    If no checkouts are given, we'll use those implied by your current
    location.

    Each <checkout> should be the name of a checkout, and muddle will obey
    the rule associated with "checkout:<checkout>{}/pulled" for each.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """
    
    def name(self):
        return "pull"

    def aliases(self):
        return ["dep-pull"]

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_checkout_arguments(builder, args, local_pkgs,
                                              utils.Tags.Pulled)
        # Forcibly retract all the updated tags.
        if (self.no_op()):
            print "Pull checkouts: %s"%(depend.label_list_to_string(checkouts))
        else:
            for co in checkouts:
                builder.invocation.db.clear_tag(co)
                builder.build_label(co)


class Reparent(Command):
    """
    :Syntax: reparent [-f[orce]] <checkout> [ <checkout> ... ]

    Re-associate the specified checkouts with their remote repositories.

    Some distributed VCSs (notably, Bazaar) can "forget" the remote repository
    for a checkout. In Bazaar, this typically means not remembering the
    "parent" repository, and thus not being able to pull. It appears to be
    possible to end up in this situation if network disconnection happens in an
    inopportune manner.

    This command attempts to reassociate each checkout to the remote repository
    as named in the muddle build description. If '-force' is given, then this
    will be done even if the remote repository is already known, otherwise it
    will only be done if it is necessary.

        For Bazaar: Reads and (maybe) edits .bzr/branch/branch.conf.

        * If "parent_branch" is unset, sets it.
        * With '-force', sets "parent_branch" regardless, and also unsets
          "push_branch".

    If no checkouts are given, we'll use those implied by your current
    location.

    Each <checkout> should be the name of a checkout.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """
    
    def name(self):
        return "reparent"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):

        if args and args[0] in ('-f', '-force'):
            args = args[1:]
            force = True
        else:
            force = False

        checkouts = decode_checkout_arguments(builder, args, local_pkgs,
                                              utils.Tags.Pulled)
        if (self.no_op()):
            print "Reparent checkouts: %s"%(depend.label_list_to_string(checkouts))
        else:
            for co in checkouts:
                rule = builder.invocation.ruleset.rule_for_target(co)
                try:
                    vcs = rule.obj.vcs
                except AttributeError:
                    print "Rule for label '%s' has no VCS - cannot reparent, ignored"%co
                    continue
                vcs.reparent(force=force, verbose=True)



class PkgUpdate(Command):
    """
    :Syntax: pkg-update <package> [ <package> ... ]

    Update the checkouts on which the specified packages depend.

    That is, bring each such checkout up-to-date with respect to its remote
    repository.

    This is effectively equivalent to:

    1. Using ``muddle query deps 'package:<package>{}/postinstalled`` to find
       all of the checkouts that each <package> depends on.
    2. Using ``muddle update`` to update all of those checkouts.

    The special <package> name _all means all packages.

    If no <packages> are given, we'll use those implied by your current
    location.
    """
    
    def name(self):
        return "pkg-update"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_dep_checkout_arguments(builder, args, local_pkgs,
                                              utils.Tags.UpToDate)
        # Forcibly retract all the updated tags.
        if (self.no_op()):
            print "Updating checkouts: %s "%(depend.label_list_to_string(checkouts))
        else:
            for co in checkouts:
                builder.kill_label(co)
                builder.build_label(co)


class PkgCommit(Command):
    """
    :Syntax: pkg-commit <package> [ <package> ... ]

    Commit the checkouts on which the specified packages depend.

    That is, commit the each such checkout to its local repository.

    For a centralised VCS (e.g., Subversion) where the repository is remote,
    this will not do anything. See the pkg-update command.

    This is effectively equivalent to:

    1. Using ``muddle query deps 'package:<package>{}/postinstalled`` to
       find all of the checkouts that each <package> depends on.
    2. Using ``muddle commit`` to commit all of those checkouts.

    The special <package> name _all means all packages.

    If no <packages> are given, we'll use those implied by your current
    location.
    """
    
    def name(self):
        return "pkg-commit"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_dep_package_arguments(builder, args, local_pkgs,
                                              utils.Tags.ChangesCommitted)
        # Forcibly retract all the updated tags.
        if (self.no_op()):
            print "Committing checkouts: %s"%(depend.label_list_to_string(checkouts))
        else:
            for co in checkouts:
                builder.kill_label(co)
                builder.build_label(co)


class PkgPush(Command):
    """
    :Syntax: pkg-push <checkout> [ <checkout> ... ]

    Push the checkouts on which the specified packages depend.

    That is, update the content of the remote repositories to match each such
    local checkout.

    This is effectively equivalent to:

    1. Using ``muddle query deps 'package:<package>{}/postinstalled`` to
       find all of the checkouts that each <package> depends on.
    2. Using ``muddle push`` to push all of those checkouts.

    The special <package> name _all means all packages.

    If no <packages> are given, we'll use those implied by your current
    location.
    """
    
    def name(self):
        return "pkg-push"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_dep_package_arguments(builder, args, local_pkgs,
                                              utils.Tags.ChangesPushed)
        # Forcibly retract all the updated tags.
        if (self.no_op()):
            print "Pushing checkouts: %s"%(depend.label_list_to_string(checkouts))
        else:
            for co in checkouts:
                builder.invocation.db.clear_tag(co)
                builder.build_label(co)

class Removed(Command):
    """
    :Syntax: removed <checkout> [ <checkout> ... ]

    Signal to muddle that the given checkouts have been removed and will
    need to be checked out again before they can be used.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """
    
    def name(self):
        return "removed"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_checkout_arguments(builder, args, local_pkgs,
                                              utils.Tags.CheckedOut)

        if (self.no_op()):
            print "Signalling checkout removal for: "%(depend.label_list_to_string(checkouts))
        else:
            for c in checkouts:
                builder.kill_label(c)


        

class Unimport(Command):
    """
    :Syntax: unimport <checkout> [ <checkout> ... ]

    Assert that the given checkouts haven't been checked out and must therefore
    be checked out.

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """

    def name(self):
        return "unimport"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_checkout_arguments(builder, args, 
                                              local_pkgs,
                                              utils.Tags.CheckedOut)

        if (self.no_op()):
            print "Unimporting checkouts: %s"%(depend.label_list_to_string(checkouts))
        else:
            for c in checkouts:
                builder.invocation.db.clear_tag(c)


class Import(Command):
    """
    :Syntax: import <checkout> [ <checkout> ... ]

    Assert that the given checkout (which may be the builds checkout) has
    been checked out and is up to date. This is mainly used when you've just
    written a package you plan to commit to the central repository - muddle
    obviously can't check it out because it's still being created, but you
    probably want to add it to the build description for testing 
    (and in fact you may want to commit it with muddle push).

    This is really just an implicit version of muddle assert with the right
    magic label names

    The special <checkout> name _all means all checkouts.

    Without a <checkout>, we use the checkout you're in, or the checkouts
    below the current directory.
    """
    
    def name(self):
        return "import"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_checkout_arguments(builder, args, local_pkgs,
                                              utils.Tags.CheckedOut)
        if (self.no_op()):
            print "Importing checkouts: %s"%(depend.label_list_to_string(checkouts))
        else:
            for c in checkouts:
                builder.invocation.db.set_tag(c)
                d = c.re_tag(utils.Tags.UpToDate)
                builder.invocation.db.set_tag(d)

class Assert(Command):
    """
    :Syntax: assert <label> [ <label> ... ]

    Assert the given labels. Mostly for use by experts and scripts.
    """

    def name(self):
        return "assert"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        if (len(args) < 1):
            print "Syntax: assert [label.. ]"
            print __doc__
            return 1

        labels = decode_labels(builder, args)
        if self.no_op():
            print "Asserting: %s"%(depend.label_list_to_string(labels))
        else:
            for l in labels:
                builder.invocation.db.set_tag(l)

class Retract(Command):
    """
    :Syntax: retract <label> [ <label> ... ]

    Retract the given labels and their consequents. 
    Mostly for use by experts and scripts.
    """
    
    def name(self):
        return "retract"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        if len(args) < 1 :
            print "Syntax: retract [label ... ]"
            print __doc__
            return 1

        labels = decode_labels(builder, args)
        if (self.no_op()):
            print "Retracting: %s"%(depend.label_list_to_string(labels))
        else:
            for l in labels:
                builder.kill_label(l)

class Changed(Command):
    """
    :Syntax: changed <package> [ <package> ... ]

    Mark packages as having been changed so that they will later
    be rebuilt by anything that needs to. The usual package name
    guessing logic is used to guess the names of your packages if
    you don't provide them.
    
    Note that we don't reconfigure (or indeed clean) packages - 
    we just clear the tags asserting that they've been built.
    """

    def name(self):
        return "changed"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_package_arguments(builder, args, local_pkgs,
                                          utils.Tags.Built)
        if (self.no_op()):
            print "Marking changed: %s"%(depend.label_list_to_string(labels))
        else:
            for l in labels:
                builder.kill_label(l)


class Env(Command):
    """
    :Syntax: env <language> <mode> <name> <label> [ <label> ... ]
    
    Produce a setenv script in the requested language listing all the
    runtime environment variables bound to label.

    * language may be 'sh', 'c', or 'py'/'python'
    * mode may be 'build' (build time variables) or 'run' (run-time variables)
    """

    def name(self):
        return "env"

    def requires_build_tree(self):
        return True

    def with_build_tree(self,builder, local_pkgs, args):
        if (len(args) < 3):
            raise utils.Failure("Syntax: env [language] [build|run] [name] [label ... ]")

        lang = args[0]
        mode = args[1]
        name = args[2]

        if (mode == "build"):
            tag = utils.Tags.Built
        elif (mode == "run"):
            tag = utils.Tags.RuntimeEnv
        else:
            raise utils.Failure("Mode '%s' is not understood - use build or run."%mode)


        labels = decode_package_arguments(builder, args[3:], local_pkgs, 
                                          tag)
        if (self.no_op()):
            print "> Environment for labels %s"%(depend.label_list_to_string(labels))
        else:
            env = env_store.Store()

            for lbl in labels:
                x_env = builder.invocation.effective_environment_for(lbl)
                env.merge(x_env)
                
                if (mode == "run"):
                    # If we have a MUDDLE_TARGET_LOCATION, use it.
                    if (not env.empty("MUDDLE_TARGET_LOCATION")):
                        env_store.add_install_dir_env(env, "MUDDLE_TARGET_LOCATION")
    
                        
            if (lang == "sh"):
                script = env.get_setvars_script(builder, name, env_store.EnvLanguage.Sh)
            elif (lang == "py" or lang == "python"):
                script = env.get_setvars_script(builder, name, env_store.EnvLanguage.Python)
            elif (lang == "c"):
                script = env.get_setvars_script(builder, name, env_store.EnvLanguage.C)
            else:
                raise utils.Failure("Language must be sh, py, python or c, not %s"%lang)
            
            print script

        return 0
    
class UnCheckout(Command):
    """
    :Syntax: uncheckout <checkout> [ <checkout> ... ]

    Tells muddle that the given checkouts no longer exist in the src directory
    and should be pulled from version control again.

    The special <checkout> name _all means all checkouts.

    If no <checkouts> are given, we'll use those implied by your current
    location.

    This does not actually delete the checkout directory. If you try to do::

        muddle unckeckout fred
        muddle checkout   fred

    then you will probably get an error, as the checkout still exists, and the
    VCS will detect this. As it says, this is to tell muddle that the checkout
    has already been removed.
    """
    
    def name(self):
        return "uncheckout"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_checkout_arguments(builder, args, local_pkgs, 
                                              utils.Tags.CheckedOut)
        if (self.no_op()):
            print "Uncheckout: %s"%(depend.label_list_to_string(checkouts))
        else:
            for co in checkouts:
                builder.kill_label(co)


class Checkout(Command):
    """
    :Syntax: checkout <checkout> [ <checkout> ... ]

    Checks out the given series of checkouts.

    That is, copies (clones/branches) the content of each checkout from its
    remote repository.

    'checkout _all' means checkout all checkouts.
    """
    
    def name(self):
        return "checkout"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        checkouts = decode_checkout_arguments(builder, args, local_pkgs, 
                                              utils.Tags.CheckedOut)
        if (self.no_op()):
            print "Checkout: %s"%(depend.label_list_to_string(checkouts))
        else:
            for co in checkouts:
                builder.build_label(co)

class CopyWithout(Command):
    """
    :Syntax: copywithout <src> <dst> [ <without> ... ]

    Many VCSs use '.XXX' directories to hold metadata. When installing
    files in a makefile, it's often useful to have an operation which
    copies a heirarchy from one place to another without these dotfiles.

    This is that operation. We copy everything from src into dst without
    copying anything which is in [ <without> ... ].  If you omit without, 
    we just copy - this is a useful, working, version of 'cp -a'
    """
    
    def name(self):
        return "copywithout"

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, local_pkgs, args):
        return self.do_copy(args)

    def without_build_tree(self, muddle_binary, root_path, args):
        return self.do_copy(args)

    def do_copy(self, args):
        if (len(args) < 2):
            raise utils.Failure("Bad syntax for copywithout command")
        
        src_dir = args[0]
        dst_dir = args[1]
        without = args[2:]

        if (self.no_op()):
            print "Copy from: %s"%(src_dir)
            print "Copy to  : %s"%(dst_dir)
            print "Excluding: %s"%(" ".join(without))
        else:
            utils.copy_without(src_dir, dst_dir, without, object_exactly=True, preserve=True)

class Retry(Command):
    """
    :Syntax: retry <label> [ <label> ... ]

    Removes just the labels in question and then tries to build them.
    Useful when you're messing about with package rebuild rules.
    """
    
    def name(self):
        return "retry"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_labels(builder, args)
        if (self.no_op()):
            print "Retry: %s"%(depend.label_list_to_string(labels))
        else:
            print "Clear: %s"%(depend.label_list_to_string(labels))
            for l in labels:
                builder.invocation.db.clear_tag(l)
            
            print "Build: %s"%(depend.label_list_to_string(labels))
            for l in labels:
                builder.build_label(l)


class Subst(Command):
    """
    :Syntax: subst <src_file> <xml_file> <dst_file>

    Substitute (with ${.. }) src file into dst file using data from
    the environment or from the given xml file. 
    """
    
    def name (self):
        return "subst"

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, local_pkgs, args):
        self.do_subst(args)

    def without_build_tree(self, muddle_binary, root_path, args):
        self.do_subst(args)

    def do_subst(self, args):
        if len(args) != 3:
            raise utils.Failure("Syntax: subst [src] [xml] [dst]")
        
        src = args[0]
        xml_file = args[1]
        dst = args[2]

        f = open(xml_file, "r")
        xml_doc = xml.dom.minidom.parse(f)
        f.close()

        subst.subst_file(src, dst, xml_doc, self.old_env)
        return 0

class Stamp(Command):
    """
    :Syntax: stamp save [-f[orce]|-h[ead]] [<file>]
    :or:     stamp version [-f[orce]]
    :or:     stamp restore <url_or_file>
    :or:     stamp diff [-u[nified]|-c[ontext]|-n|-h[tml]] <file1> <file2> [<output_file>]

    * Saving: ``stamp save [<switches>] [<file>]``

      Go through each checkout, and save its remote repository and current
      revision id/number to a file.

      This is intended to be enough information to allow reconstruction of the
      entire build tree, as-is.

      If a <file> is specified, then output will be written to that file.
      If its name does not end in '.stamp', then '.stamp' will be appended to it.

      If a <file> is not specified, then a name of the form <sha1-hash>.stamp
      will be used, where <sha1-hash> is a hexstring representation of the hash
      of the content of the file.

      If it is not possible to write a full stamp file (revisions could not be
      determined for all checkouts, and neither '-force' nor '-head' was
      specified) then the extension ".partial" will be used instead of ".stamp".
      An attempt will be made to give useful information about what the problems
      are.

      If a file already exists with the name ultimately chosen, that file will
      be overwritten.

      If '-f' or '-force' is specified, then attempt to "force" a revision id,
      even if it is not necessarily correct. For instance, if a local working
      directory contains uncommitted changes, then ignore this and use the
      revision id of the committed data. If it is actually impossible to
      determine a sensible revision id, then use the revision specified by the
      build description (which defaults to HEAD). For really serious problems,
      this may refuse to guess a revision id, in which case the 'stamp save'
      process should stop with the relevant checkout.

          (Typical use of '-f' is expected to be when a 'stamp save' reports
          problems in particular checkouts, but inspection shows that these
          are artefacts that may be ignored, such as an executable built in
          the source directory.)

      If '-h' or '-head' is specified, then HEAD will be used for all checkouts.
      In this case, the repository specified in the build description is used,
      and the revision id and status of each checkout is not checked.

    * Saving: ``stamp version [<switches>]``

      This is similar to "stamp save", but using a pre-determined stamp filename.

      Specifically, the stamp file written will be called:

          versions/<build_name>.stamp

      The "versions/" directory is at the build root (i.e., it is a sibling of
      the ".muddle/" and "src/" directories). If it does not exist, it will be
      created.

      <build_name> is the name of this build, as specified by the build
      description (by setting ``builder.build_name``). If the build description
      does not set the build name, then the name will be taken from the build
      description file name. You can use "muddle query name" to find the build
      name for a particular build.

      If a full stamp file cannot be written (i.e., if the result would have
      extension ".partial"), then the version stamp file will not be written.

      Note that '-f' is supported (although perhaps not recommended), but '-h' is
      not.

    * Restoring: ``stamp restore <url_or_file>``

      This is an experimental synonym for "unstamp". For the moment, see that
      for documentation.

    * Comparing: ``stamp diff [<switches>] <file1> <file2> [<output_file>]``

      Compare two stamp files.

      The two (existing) stamp files named are compared. If <output_file> is
      given, then the output is written to it (overwriting any previous file of
      that name), otherwise output is to standard output.

      If '-u' is specified, then the output is a unified difference. This is the
      default.

      If '-c' is specified, then the output is a context difference. This uses a
      "before/after" style of presentation.

      If '-n' is specified, then the output is from "ndiff" - this is normally
      a more human-friendly set of differences, but outputs the parts of the files
      that match as well as those that do not.

      If '-h' is specified, then the output is an HTML page, displaying
      differences in two columns (with colours).
    """
    
    def name(self):
        return "stamp"

    def print_syntax(self):
        print """
    :Syntax: stamp save [-f[orce]|-h[ead]] [<file>]
    :or:     stamp version [-f[orce]]
    :or:     stamp restore <url_or_file>
    :or:     stamp diff [-u[nified]|-n|-h[tml]] <file1> <file2> [<output_file>]

("stamp restore" is an experimental synonym for "unstamp", which see)

Try 'muddle help stamp' for more information."""

    def requires_build_tree(self):
        """
        Sort of.

        Although ``muddle stamp save`` *does* require a build tree, other
        "sub commands" such as ``muddle stamp diff`` do not.
        """
        return False

    def without_build_tree(self, muddle_binary, root_path, args):
        """
        Run this command without a build tree.
        """

        if not args:
            self.print_syntax()
            return 2

        word = args[0]
        rest = args[1:]
        if word in ('save', 'version'):
            print "Can't do 'muddle stamp save' without a build tree"
            return 2
        elif word == 'restore':
            unstamp = UnStamp()
            unstamp.without_build_tree(muddle_binary, root_path, rest)
        elif word == 'diff':
            self.compare_stamp_files(rest)
        else:
            print "Unexpected 'stamp %s'"%word
            self.print_syntax()
            return 2

    def with_build_tree(self, builder, local_pkgs, args):
        force = False
        just_use_head = False
        filename = None

        if not args:
            self.print_syntax()
            return 2

        word = args[0]
        rest = args[1:]
        if word == 'save':
            self.write_stamp_file(builder, rest)
        elif word == 'version':
            self.write_version_file(builder, rest)
        elif word == 'diff':
            self.compare_stamp_files(rest)
        elif word == 'restore':
            print "Can't do 'muddle stamp restore' with a build tree"
            return 2
        else:
            print "Unexpected 'stamp %s'"%word
            self.print_syntax()
            return 2

    def compare_stamp_files(self, args):
        diff_style = 'unified'
        file1 = file2 = output_file = None

        while args:
            word = args[0]
            args = args[1:]
            if word in ('-u', '-unified'):
                diff_style = 'unified'
            elif word == '-n':
                diff_style = 'ndiff'
            elif word in ('-c', '-context'):
                diff_style = 'context'
            elif word in ('-h', '-html'):
                diff_style = 'html'
            elif word.startswith('-'):
                print "Unexpected switch '%s'"%word
                self.print_syntax()
                return 2
            else:
                if file1 is None:
                    file1 = word
                elif file2 is None:
                    file2 = word
                elif output_file is None:
                    output_file = word
                else:
                    print "Unexpected '%s'"%word
                    self.print_syntax()
                    return 2
        self.diff(file1, file2, diff_style, output_file)

    def write_stamp_file(self, builder, args):
        force = False
        just_use_head = False
        filename = None

        while args:
            word = args[0]
            args = args[1:]
            if word in ('-f', '-force'):
                force = True
                just_use_head = False
            elif word in ('-h', '-head'):
                just_use_head = True
                force = False
            elif word.startswith('-'):
                print "Unexpected switch '%s'"%word
                self.print_syntax()
                return 2
            elif filename is None:
                filename = word
            else:
                print "Unexpected '%s'"%word
                self.print_syntax()
                return 2

        if just_use_head:
            print 'Using HEAD for all checkouts'
        elif force:
            print 'Forcing original revision ids when necessary'

        # Some of the following operations may change directory, so
        start_dir = os.getcwd()

        revisions, domains, problems = self.calculate_stamp(builder,
                                                            force,
                                                            just_use_head)

        # Make sure we're where the user thinks we are, since some of the
        # muddle mechanisms change directory under our feet
        os.chdir(start_dir)
        if not self.no_op():
            working_filename = 'working.stamp'
            print 'Writing to',working_filename
            with utils.HashFile(working_filename,'w') as fd:
                self.write_rev_data(revisions, fd,
                                    root_repo=builder.invocation.db.repo.get(),
                                    root_desc=builder.invocation.db.build_desc.get(),
                                    domains=domains,
                                    problems=problems)
            print 'Wrote revision data to %s'%working_filename
            print 'File has SHA1 hash %s'%fd.hash()

            final_name = self.decide_hash_filename(filename, fd.hash(), problems)
            print 'Renaming %s to %s'%(working_filename, final_name)
            os.rename(working_filename, final_name)

    def write_version_file(self, builder, args):
        force = False
        while args:
            word = args[0]
            args = args[1:]
            if word in ('-f', '-force'):
                force = True
            elif word.startswith('-'):
                print "Unexpected switch '%s'"%word
                self.print_syntax()
                return 2
            else:
                print "Unexpected '%s'"%word
                self.print_syntax()
                return 2

        if force:
            print 'Forcing original revision ids when necessary'

        # Some of the following operations may change directory, so
        start_dir = os.getcwd()

        revisions, domains, problems = self.calculate_stamp(builder,
                                                            force,
                                                            just_use_head=False)

        if problems:
            raise utils.Failure('Problems prevent writing version stamp file')

        if not self.no_op():
            version_dir = os.path.join(builder.invocation.db.root_path, 'versions')
            if not os.path.exists(version_dir):
                print 'Creating directory %s'%version_dir
                os.mkdir(version_dir)


            working_filename = os.path.join(version_dir, '_temporary.stamp')
            print 'Writing to',working_filename
            with utils.HashFile(working_filename,'w') as fd:
                self.write_rev_data(revisions, fd,
                                    root_repo=builder.invocation.db.repo.get(),
                                    root_desc=builder.invocation.db.build_desc.get(),
                                    domains=domains,
                                    problems=problems)
            print 'Wrote revision data to %s'%working_filename
            print 'File has SHA1 hash %s'%fd.hash()

            version_filename = "%s.stamp"%builder.build_name
            final_name = os.path.join(version_dir, version_filename)
            print 'Renaming %s to %s'%(working_filename, final_name)
            os.rename(working_filename, final_name)

    def calculate_stamp(self, builder, force, just_use_head):
        """
        Work out the content of our stamp file.

        Returns <revisions>, <domains>, <problems>

        <revisions> is a sorted dictionary with key the checkout label and
        value a tuple of (repository, checkout_dir, rev, rel)

        <domains> is a (possibly empty) set of tuples of (domain_name,
        domain_repo, domain_desc)

        <problems> is a (possibly empty) list of problem summaries. If
        <problems> is empty then the stamp was calculated fully.
        """

        print 'Finding all checkouts...',
        checkout_rules = list(builder.invocation.all_checkout_rules())
        print 'found %d'%len(checkout_rules)

        revisions = utils.MuddleSortedDict()
        problems = []
        domains = set()
        checkout_rules.sort()
        for rule in checkout_rules:
            try:
                label = rule.target
                try:
                    vcs = rule.obj.vcs
                except AttributeError:
                    problems.append("Rule for label '%s' has no VCS"%(label))
                    print problems[-1]
                    continue
                print "%s checkout '%s'"%(vcs.__class__.__name__,
                                          '(%s)%s'%(label.domain,label.name) if label.domain
                                          else label.name)
                if label.domain:
                    domain_name = label.domain
                    domain_repo, domain_desc = builder.invocation.db.get_subdomain_info(domain_name)
                    domains.add((domain_name, domain_repo, domain_desc))

                if just_use_head:
                    print 'Forcing head'
                    rev = "HEAD"
                else:
                    rev = vcs.revision_to_checkout(force=force, verbose=True)
                revisions[label] = (vcs.repository, vcs.checkout_dir, rev, vcs.relative)
            except utils.Failure as exc:
                print exc
                problems.append(exc)

        if domains:
            print 'Found domains:',domains

        if len(revisions) != len(checkout_rules):
            print
            print 'Unable to work out revision ids for all the checkouts'
            if revisions:
                print '- although we did work out %d of %s'%(len(revisions),
                        len(checkout_rules))
            if problems:
                print 'Problems were:'
                for item in problems:
                    print '* %s'%utils.truncate(str(item),less=2)

        return revisions, domains, problems

    def decide_hash_filename(self, hash, basename=None, partial=False):
        """
        Return filename, given a SHA1 hash hexstring, and maybe a basename.

        If 'partial', then the returned filename will have extension '.partial',
        otherwise '.stamp'.

        If the basename is not given, then the main part of the filename will
        be <hash>.

        If the basename is given, then if it ends with '.stamp' or '.partial'
        then that will be removed before it is used.
        """
        if partial:
            extension = '.partial'
        else:
            extension = '.stamp'
        if not basename:
            return '%s%s'%(hash, extension)
        else:
            head, ext = os.path.splitext(basename)
            if ext in ('.stamp', '.partial'):
                return '%s%s'%(head, extension)
            else:
                return '%s%s'%(basename, extension)

    def write_rev_data(self, revisions, fd, root_repo=None, root_desc=None,
                       domains=None, problems=None):
        from ConfigParser import RawConfigParser

        # The following makes sure we write the [ROOT] out first, otherwise
        # things will come out in some random order (because that's how a
        # dictionary works, and that's what its using)
        config = RawConfigParser()
        config.add_section("ROOT")
        config.set("ROOT", "repository", root_repo)
        config.set("ROOT", "description", root_desc)
        config.write(fd)

        if domains:
            config = RawConfigParser(None, dict_type=utils.MuddleSortedDict)
            for domain_name, domain_repo, domain_desc in domains:
                section = "DOMAIN %s"%domain_name
                config.add_section(section)
                config.set(section, "name", domain_name)
                config.set(section, "repository", domain_repo)
                config.set(section, "description", domain_desc)
            config.write(fd)

        config = RawConfigParser(None, dict_type=utils.MuddleSortedDict)
        for label, (repo, dir, rev, rel) in revisions.items():
            if label.domain:
                section = 'CHECKOUT (%s)%s'%(label.domain,label.name)
            else:
                section = 'CHECKOUT %s'%label.name
            config.add_section(section)
            if label.domain:
                config.set(section, "domain", label.domain)
            config.set(section, "name", label.name)
            config.set(section, "repository", repo)
            config.set(section, "revision", rev)
            if rel:
                config.set(section, "relative", rel)
            if dir:
                config.set(section, "directory", dir)
        config.write(fd)

        if problems:
            config = RawConfigParser(None, dict_type=utils.MuddleSortedDict)
            section = 'PROBLEMS'
            config.add_section(section)
            for index, item in enumerate(problems):
                config.set(section, 'problem%d'%(index+1),
                           utils.truncate(str(item), columns=100))
            config.write(fd)

    def diff(self, file1, file2, diff_style='unified', output_file=None):
        """
        Output a comparison of file1 and file2 to html_file.
        """
        with open(file1) as fd1:
            file1_lines = fd1.readlines()
        with open(file2) as fd2:
            file2_lines = fd2.readlines()

        if diff_style == 'html':
            diff = difflib.HtmlDiff().make_file(file1_lines, file2_lines,
                                                file1, file2)
        elif diff_style == 'ndiff':
            diff = difflib.ndiff(file1_lines, file2_lines)
            file1_date = time.ctime(os.stat(file1).st_mtime)
            file2_date = time.ctime(os.stat(file2).st_mtime)
            help = ["#First character indicates provenance:\n"
                    "# '-' only in %s of %s\n"%(file1, file1_date),
                    "# '+' only in %s of %s\n"%(file2, file2_date),
                    "# ' ' in both\n",
                    "# '?' pointers to intra-line differences\n"
                    "#---------------------------------------\n"]
            diff = help + list(diff)
        elif diff_style == 'context':
            file1_date = time.ctime(os.stat(file1).st_mtime)
            file2_date = time.ctime(os.stat(file2).st_mtime)
            diff = difflib.context_diff(file1_lines, file2_lines,
                                        file1, file2,
                                        file1_date, file2_date)
        else:
            file1_date = time.ctime(os.stat(file1).st_mtime)
            file2_date = time.ctime(os.stat(file2).st_mtime)
            diff = difflib.unified_diff(file1_lines, file2_lines,
                                        file1, file2,
                                        file1_date, file2_date)

        if output_file:
            with open(output_file,'w') as fd:
                fd.writelines(diff)
        else:
            sys.stdout.writelines(diff)


class UnStamp(Command):
    """
    :Syntax: unstamp <file>
    :or:     unstamp <url>
    :or:     unstamp <vcs>+<url>
    :or:     unstamp <vcs>+<repo_url> <version_desc>

    The "unstamp" command reads the contents of a "stamp" file, as produced by
    the "muddle stamp" command, and:

    1. Retrieves each checkout mentioned
    2. Reconstructs the corresponding muddle directory structure
    3. Confirms that the muddle build description is compatible with
       the checkouts.


    The file may be specified as:

    * The local path to a stamp file.

      For instance::

          muddle stamp  thing.stamp
          mkdir /tmp/thing
          cp thing.stamp /tmp/thing
          cd /tmp/thing
          muddle unstamp  thing.stamp

    * The URL for a stamp file. In this case, the file will first be copied to
      the current directory.

      For instance::

          muddle unstamp  http://some.url/some/path/thing.stamp

      which would first copy "thing.stamp" to the current directory, and then
      use it. If the file already exists, it will be overwritten.

    * The "revision control specific" URL for a stamp file. This names the
      VCS to use as part of the URL - for instance::

          muddle unstamp  bzr+ssh://kynesim.co.uk/repo/thing.stamp

      This also copies the stamp file to the current directory before using it.
      Note that not all VCS mechanisms support this (at time of writing, muddle's
      git support does not). If the file already exists, it will be overwritten.

    * The "revision control specific" URL for a repository, and the path to
      the version stamp file therein.

      For instance::

          muddle unstamp  bzr+ssh://kynesim.co.uk/repo  versions/ProjectThing.stamp

      This is intended to act somewhat similarly to "muddle init", in that
      it will checkout::

          bzr+ssh://kynesim.co.uk/repo/versions

      and then unstamp the ProjectThing.stamp file therein.

    """
    
    def name(self):
        return "unstamp"

    def print_syntax(self):
        print """
    :Syntax: unstamp <file>
    :or:     unstamp <url>
    :or:     unstamp <vcs>+<url>
    :or:     unstamp <vcs>+<repo_url> <version_desc>

Try 'muddle help unstamp' for more information."""

    def requires_build_tree(self):
        return False

    def without_build_tree(self, muddle_binary, root_path, args):
        # Strongly assume the user wants us to work in the current directory
        current_dir = os.getcwd()

        # In an ideal world, we'd only be called if there really was no muddle
        # build tree. However, in practice, the top-level script may call us
        # because it can't find an *intact* build tree. So it's up to us to
        # know that we want to be a bit more careful...
        dir, domain = utils.find_root(current_dir)
        if dir:
            print
            print 'Found a .muddle directory in %s'%dir
            if dir == current_dir:
                print '(which is the current directory)'
            else:
                print 'The current directory is     %s'%current_dir
            print
            got_src = os.path.exists(os.path.join(dir,'src'))
            got_dom = os.path.exists(os.path.join(dir,'domains'))
            if got_src or got_dom:
                extra = ', and also the '
                if got_src: extra += '"src/"'
                if got_src and got_dom: extra += ' and '
                if got_dom: extra += '"domains/"'
                if got_src and got_dom:
                    extra += ' directories '
                else:
                    extra += ' directory '
                extra += 'alongside it'
            else:
                extra = ''
            print utils.wrap('This presumably means that the current directory is'
                             ' inside a broken or partial build. Please fix this'
                             ' (e.g., by deleting the ".muddle/" directory%s)'
                             ' before retrying the "unstamp" command.'%extra)
            return 4

        if len(args) == 1:
            self.unstamp_from_file(muddle_binary, root_path, current_dir, args[0])
        elif len(args) == 2:
            self.unstamp_from_repo(muddle_binary, root_path, current_dir, args[0], args[1])
        else:
            self.print_syntax()
            return 2


    def unstamp_from_file(self, muddle_binary, root_path, current_dir, thing):
        """
        Unstamp from a file (local, over the network, or from a repository)
        """

        data = None

        # So what is our "thing"?
        vcs_name, just_url = version_control.split_vcs_url(thing)
        if vcs_name:
            print 'Retrieving %s'%thing
            data = version_control.vcs_get_file_data(thing)
            # We could do various things here, but it actually seems like
            # quite a good idea to store the data *as a file*, so the user
            # can do stuff with it, if necessary (and as an audit trail of
            # sorts)
            parts = urlparse(thing)
            path, filename = os.path.split(parts.path)
            print 'Saving data as %s'%filename
            with open(filename,'w') as fd:
                fd.write(data)
        elif os.path.exists(thing):
            filename = thing
        else:
            # Hmm - maybe a plain old URL
            parts = urlparse(thing)
            path, filename = os.path.split(parts.path)
            print 'Retrieving %s'%filename
            data = urllib.urlretrieve(thing, filename)

        repo_location, build_desc, domains, checkouts = self.read_file(filename)

        if self.no_op():
            return

        builder = mechanics.minimal_build_tree(muddle_binary, current_dir,
                                               repo_location, build_desc)

        self.restore_stamp(builder, root_path, domains, checkouts)

        # Once we've checked everything out, we should ideally check
        # if the build description matches what we've checked out...
        return self.check_build(current_dir, checkouts, builder, muddle_binary)

    def unstamp_from_repo(self, muddle_binary, root_path, current_dir, repo,
                          version_path):
        """
        Unstamp from a repository and version path.
        """

        version_dir, version_file = os.path.split(version_path)

        if not version_file:
            raise utils.Failure("'unstamp <vcs+url> %s' does not end with"
                    " a filename"%version_path)

        # XXX I'm not entirely sure about this check - is it overkill?
        if os.path.splitext(version_file)[1] != '.stamp':
            raise utils.Failure("Stamp file specified (%s) does not end"
                    " .stamp"%version_file)

        actual_url = '%s/%s'%(repo, version_dir)
        print 'Retrieving %s'%actual_url

        if self.no_op():
            return

        # Restore to the current directory
        os.chdir(current_dir)
        version_control.vcs_get_directory(actual_url)

        repo_location, build_desc, domains, checkouts = self.read_file(version_path)

        builder = mechanics.minimal_build_tree(muddle_binary, current_dir,
                                               repo_location, build_desc)

        self.restore_stamp(builder, root_path, domains, checkouts)

        # Once we've checked everything out, we should ideally check
        # if the build description matches what we've checked out...
        return self.check_build(current_dir, checkouts, builder, muddle_binary)

    def read_file(self, filename):
        """
        Read the stamp file, and return its data

        Returns (repo_location, build_desc, domains, checkouts)
        """
        print 'Reading stamp file %s'%filename
        fd = utils.HashFile(filename)

        config = RawConfigParser()
        config.readfp(fd)

        repo_location = config.get("ROOT", "repository")
        build_desc = config.get("ROOT", "description")

        domains = []
        checkouts = []
        sections = config.sections()
        sections.remove("ROOT")
        for section in sections:
            if section.startswith("DOMAIN"):
                domain_name = config.get(section, 'name')
                domain_repo = config.get(section, 'repository')
                domain_desc = config.get(section, 'description')
                domains.append((domain_name, domain_repo, domain_desc))
            elif section.startswith("CHECKOUT"):
                name = config.get(section, 'name')
                repo = config.get(section, 'repository')
                rev = config.get(section, 'revision')
                if config.has_option(section, "relative"):
                    rel = config.get(section, 'relative')
                else:
                    rel = None
                if config.has_option(section, "directory"):
                    dir = config.get(section, 'directory')
                else:
                    dir = None
                if config.has_option(section, "domain"):
                    domain = config.get(section, 'domain')
                else:
                    domain = None
                checkouts.append((name, repo, rev, rel, dir, domain))
            else:
                print 'Ignoring configuration section [%s]'%section

        print 'File has SHA1 hash %s'%fd.hash()
        return repo_location, build_desc, domains, checkouts

    def restore_stamp(self, builder, root_path, domains, checkouts):
        """
        Given the information from our stamp file, restore things.
        """
        for domain_name, domain_repo, domain_desc in domains:
            print "Adding domain %s"%domain_name

            domain_root_path = os.path.join(root_path, 'domains', domain_name)
            os.makedirs(domain_root_path)

            domain_builder = mechanics.minimal_build_tree(muddle_binary,
                                                          domain_root_path,
                                                          domain_repo, domain_desc)

            # Tell the domain's builder that it *is* a domain
            domain_builder.invocation.mark_domain(domain_name)

        checkouts.sort()
        for name, repo, rev, rel, dir, domain in checkouts:
            if domain:
                print "Unstamping checkout (%s)%s"%(domain,name)
            else:
                print "Unstamping checkout %s"%name
            # So try registering this as a normal build, in our nascent
            # build system
            vcs_handler = version_control.vcs_handler_for(builder, name,  repo,
                                                          rev, rel, dir)
            vcs = pkg.VcsCheckoutBuilder(name, vcs_handler)
            pkg.add_checkout_rules(builder.invocation.ruleset, name, vcs)

            # Then need to mimic "muddle checkout" for it
            label = depend.Label(utils.LabelKind.Checkout,
                                 name, None, utils.Tags.CheckedOut,
                                 domain=domain)
            builder.build_label(label, silent=False)

    def check_build(self, current_dir, checkouts, builder, muddle_binary):
        """
        Check that the build tree we now have on disk looks a bit like what we want...
        """
        # So reload as a "new" builder
        print
        print 'Checking that the build is restored correctly...'
        print
        (build_root, build_domain) = utils.find_root(current_dir)

        b = mechanics.load_builder(build_root, muddle_binary, default_domain=build_domain)

        local_pkgs = utils.find_local_packages(current_dir, build_root, 
                                               builder.invocation)

        q = Query()
        q.with_build_tree(b, local_pkgs, ["root"]) 
        q.with_build_tree(b, local_pkgs, ["checkouts", "checkout:*/*"]) 

        # Check our checkout names match
        s_checkouts = set([name for name, repo, rev, rel, dir, domain in checkouts])
        b_checkouts = b.invocation.all_checkouts()
        s_difference = s_checkouts.difference(b_checkouts)
        b_difference = b_checkouts.difference(s_checkouts)
        if s_difference or b_difference:
            print 'There is a mismatch between the checkouts in the stamp' \
                  ' file and those in the build'
            if s_difference:
                print 'Checkouts only in the stamp file:'
                for name in s_difference:
                    print '    %s'%name
            if b_difference:
                print 'Checkouts only in the build:'
                for name in b_difference:
                    print '    %s'%name
            return 4
        else:
            print
            print '...the checkouts present match those in the stamp file.'
            print 'The build looks as if it restored correctly.'

def get_all_checkouts(builder, tag):
    """
    Return a list of labels corresponding to all checkouts 
    in the system, with the given tag
    """
    rv = [ ]
    all_cos = builder.invocation.all_checkouts()
    
    for co in all_cos:
        rv.append(depend.Label(utils.LabelKind.Checkout, 
                               co, None, 
                               tag,
                               domain = builder.get_default_domain()))
        
    rv.sort()
    return rv


def decode_checkout_arguments(builder, args, local_pkgs, tag):
    """
    Decode checkout label arguments.
    
    Use this to decode arguments when you're expecting to refer to a
    checkout rather than a package.

    If 'args' is given, it is a list of command line arguments:

      * "_all" means all checkouts with the given 'tag'
      * "<name>" means the label "checkout:<name>{}/<tag>" in the current
        default domain

    otherwise all checkouts with directories below the current directory are
    returned.

    The 'local_pkgs' argument is ignored (it is present for compatibility with
    other similar functions).

    Returns a list of checkout labels.
    """
    
    rv = [ ]

    if (len(args) > 0):
        # Excellent!
        for co in args:
            if (co == "_all"):
                return get_all_checkouts(builder, tag)
            else:
                rv.append(depend.Label(utils.LabelKind.Checkout, 
                                       co, None, tag, 
                                       domain = builder.get_default_domain()))

    else:
        # We resolutely ignore local_pkgs...
        # Where are we? If in a checkout, that's what we should do - else
        # all checkouts.
        (what, loc, role) = utils.find_location_in_tree(os.getcwd(),
                                                        builder.invocation.db.root_path)
        
        
        if (what == utils.DirType.CheckOut):
            cos_below = utils.get_all_checkouts_below(builder, os.getcwd())
            for c in cos_below:
                rv.append(depend.Label(utils.LabelKind.Checkout, 
                                       c, None, tag, 
                                       domain = builder.get_default_domain()))
    return rv


def decode_dep_checkout_arguments(builder, args, local_pkgs, tag):
    """
    Any arguments given are package names - we return their dependent 
    checkouts.

    If there are arguments, they specify checkouts.

    If there aren't, all checkouts dependent on any local_pkgs tag are
    returned.
    """
    
    labels = decode_package_arguments(builder, args, local_pkgs, 
                                      utils.Tags.PostInstalled)
    
    rv = [ ]
    out_set = set()

    for my_label in labels:
        deps = depend.needed_to_build(builder.invocation.ruleset, my_label)
        for d in deps:
            if (d.target.type == utils.LabelKind.Checkout):
                out_set.add(depend.Label(utils.LabelKind.Checkout, 
                                         d.target.name,
                                         None, 
                                         tag))

    rv = list(out_set)
    rv.sort()

    return rv
    

def decode_labels(builder, in_args):
    """
    Each argument is a label - convert each to a proper label
    object and then return the resulting list
    """
    rv = [ ]
    for arg in in_args:
        lbl = depend.label_from_string(arg)
        if (lbl is None):
            raise utils.Failure("Putative label '%s' does not parse as a label"%arg)
        rv.append(lbl)

    return rv
 
def decode_deployment_arguments(builder, args, local_pkgs, tag):
    """
    Look through args for deployments. _all means all deployments
    registered.
    
    If args is empty, we use the default deployments registered with the
    builder.
    """
    return_list = [ ]
    
    for dep in args:
        if (dep == "_all"):
            # Everything .. 
            return all_deployment_labels(builder, tag)
        else:
            lbl = depend.Label(utils.LabelKind.Deployment, 
                               dep, 
                               "*",
                               tag, domain = builder.get_default_domain())
            return_list.append(lbl)
    
    if len(return_list) == 0:
        # Input was empty - default deployments.
        return default_deployment_labels(builder, tag)

    return return_list


def all_deployment_labels(builder, tag):
    """
    Return all the deployment labels registered with the ruleset.
    """

    # Important not to set tag here - if there's a deployment
    #  which doesn't have the right tag, we want an error, 
    #  not to silently ignore it.
    match_lbl = depend.Label(utils.LabelKind.Deployment,
                             "*", "*", "*", domain = builder.get_default_domain())
    matching = builder.invocation.ruleset.rules_for_target(match_lbl)
    
    return_set = set()
    for m in matching:
        return_set.add(m.target.name)

    return_list = [ ]
    for r in return_set:
        lbl = depend.Label(utils.LabelKind.Deployment, 
                           r, 
                           "*", 
                           tag)
        return_list.append(lbl)

    return return_list

def default_deployment_labels(builder, tag):
    """
    Return labels tagged with tag for all the default deployments.
    """
    
    default_labels = builder.invocation.default_labels
    return_list = [ ]
    for d in default_labels:
        if (d.type == utils.LabelKind.Deployment):
            return_list.append(depend.Label(utils.LabelKind.Deployment,
                                            d.name, 
                                            d.role,
                                            tag))

    return return_list
    

def decode_package_arguments(builder, args, local_pkgs, tag):
    """
    Given your builder, a set of package arguments and the tag you'd
    like your list of labels to end up with, this function scans your
    argument list and builds a list of labels which describe your
    package arguments.

    If args is of zero length, we use local_pkgs instead. There's
    no logical reason for this, but it eliminates a bit of common
    logic from the command functions.

    It then checks for special targets (specifically, _all).

    If _all is specified, it returns a list of all labels with any
    of the roles specified in the argument list (or the default
    role set if there weren't any).
    """

    effective_args = args
    if len(effective_args) == 0:
        effective_args = local_pkgs

    to_build = labels_from_pkg_args(effective_args, tag, 
                                    builder.invocation.default_roles,
                                    builder.get_default_domain())
    
    to_build = builder.invocation.map_unifications(to_build)

    all_roles = process_labels_all_spec(to_build, 
                                        builder.invocation.default_roles)
    if len(all_roles) > 0:
        result = [ ]
        for role in all_roles:
            result.extend(builder.invocation.labels_for_role(utils.LabelKind.Package,
                                                             role, 
                                                             tag))
        return result
    else:
        return to_build
    

def build_a_kill_b(builder, labels, build_this, kill_this):
    """
    For every label in labels, build the label formed by replacing
    tag in label with build_this and then kill the tag in label with
    kill_this.

    We have to interleave these operations so an error doesn't
    lead to too much or too little of a kill.
    """
    try:
        for lbl in labels:
            l_a = lbl.copy()
            l_a.tag = build_this
            print "Building: %s .. "%(l_a)
            builder.build_label(l_a)

            l_b = lbl.copy()
            l_b.tag = kill_this
            print "Killing: %s .. "%(l_b)
            builder.kill_label(l_b)
    except utils.Failure, e:
        print "Can't build %s - %s"%(str(lbl), e)
        return 1
    
    return 0

def kill_labels(builder, to_kill):
    print "Killing %s "%(" ".join(map(str, to_kill)))

    try:
        for lbl in to_kill:
            builder.kill_label(lbl)
    except utils.Failure, e:
        print "Can't build %s - %s"%(str(lbl), e)
        #traceback.print_exc()
        return 1

    return 0


def build_labels(builder, to_build):
    print "Building %s "%(" ".join(map(str, to_build)))
        
    try:
        for lbl in to_build:
            builder.build_label(lbl)
    except utils.Failure,e:
        print "Can't build %s - %s"%(str(lbl), e)
        #traceback.print_exc()
        return 1

    return 0

def process_labels_all_spec(label_list, default_roles):
    """
    Go through the label_list and if any has an _any, add its role (or the
    default roles if it doesn't have one) to a set.

    Return an arbitrarily ordered list of the elements of the set. If there
    are no _all specifiers, return None.
    """
    r_set = set()
    for l in label_list:
        if (l.name == "_all"):
            if (l.role is not None):
                r_set.add(l.role)
            else:
                for x in default_roles:
                    r_set.add(x)

    r_list = [ ]
    for r in r_set:
        r_list.append(r)

    return r_list
    

pkg_args_re = re.compile(r"""
                         (\(
                             (?P<domain>%s)         # <domain>
                         \))?                       # in optional ()
                         (?P<name>%s)               # <name>
                         (\{
                            (?P<role>%s)?           # optional <role>
                          \})?                      # in optional {}
                          $                         # and nothing more
                          """%(depend.Label.domain_part,
                               depend.Label.label_part,
                               depend.Label.label_part),
                         re.VERBOSE)

def labels_from_pkg_args(list, tag, default_roles, default_domain):
    """
    Convert a list of packages expressed as package([{role}]?) into
    a set of labels with the given tag. This is basically a 
    cartesian product of all the unqualified packages.
    
    All tags will inherit the default domain.

    NB: also allows (domain) type specifications before the package name.
    If you know what a domain is, you should be able to work that out.

    For example:

        >>> x = labels_from_pkg_args( [ 'fred', 'bob{}', 'william{jim}', '(here)fred{jim}' ],
        ...                           'pobble',
        ...                           [ 'this', 'that' ], None )
        >>> for l in x:
        ...    print l
        package:fred{this}/pobble
        package:fred{that}/pobble
        package:bob{this}/pobble
        package:bob{that}/pobble
        package:william{jim}/pobble
        package:(here)fred{jim}/pobble
    """

    result = [ ]

    if (list is None):
        raise utils.Failure("No packages specified")

    for elem in list:
        m = pkg_args_re.match(elem)
        if (m is None):
            # Hmm ..
            raise utils.Error("Package spec '%s' is wrong,\n    expecting " 
                    "'name', 'name{}', 'name{role}' or '(domain}name{role}'"%elem)
        else:
            domain = m.group('domain')    # None if not present
            if (domain is None):
                domain = default_domain
            name   = m.group('name')
            role   = m.group('role')      # None if not present
            if (role is None):
                if (len(default_roles) > 0):
                    # Add the default roles
                    for r in default_roles:
                        result.append(depend.Label(utils.LabelKind.Package, 
                                                   name, r, tag,
                                                   domain=domain))
                else:
                    result.append(depend.Label(utils.LabelKind.Package, 
                                               name, "*", tag,
                                               domain=domain))
            else:
                result.append(depend.Label(utils.LabelKind.Package,
                                           name, role, tag,
                                           domain=domain))
    return result
    
    

import inspect
import types

# Following Richard's naming conventions...
# A dictionary of <command name> : <command instance>
# Note that more than one name may give the same instance
g_command_dict = {}
# A list of all of the known commands, by their "main" name
# (so one name per command, only)
g_command_names = []
# A dictionary of <command alias> : <command name>
# (of course, the keys are then the list of things that *are* aliases)
g_command_aliases = {}

def _register_commands():
    """
    Find all of the Command classes and register them.

    Looks for any subclass of Command in this module (not including Command
    itself) and registers it as a command.
    """
    def predicate(obj):
        """
        Return True if obj is a subclass of Command (but not Command itself)
        """
        #print 'Checking',type(obj),obj,
        if type(obj) not in (types.ClassType, types.TypeType):
            #print 'NOT CLASS'
            return False
        ok = issubclass(obj,Command) and obj is not Command
        #print 'OK' if ok else 'IGNORE'
        return ok

    # There are various ways of getting the current module
    # - this is but one
    this_module = inspect.getmodule(Command)

    commands = inspect.getmembers(this_module, predicate)
    for klass_name, klass in commands:
        cmd = klass()
        name = cmd.name()
        g_command_dict[name] = cmd
        g_command_names.append(name)
        aliases = cmd.aliases()
        if aliases:
            for alias in aliases:
                g_command_aliases[alias] = name
                g_command_dict[alias] = cmd

    g_command_names.sort()


def register_commands():
    """
    Returns a dictionary of command name to command object for all 
    commands.
    """

    # Maybe we should cache this...
    _register_commands()

    return g_command_dict

# End file.

    
