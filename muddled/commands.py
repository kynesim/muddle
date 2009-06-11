"""
Muddle commands - these get run more or less directly by 
the main muddle command and are abstracted out here in
case your programs want to run them themselves
"""

import mechanics
from db import Database
import db
import instr
import utils
import test
import depend
import version_control
import env_store
import re
import traceback
import os
import os.path

class Command:
    """
    Abstract base class for muddle commands
    """

    def __init__(self):
        self.options = { }

    def help(self):
        return self.__doc__

    def name(self):
        return None

    def register(self, dict):
        dict[self.name()] = self

    def requires_build_tree(self):
        """
        @return True iff this command requires an initialised
         build tree, False otherwise.
        """
        return True

    def set_options(self, opt_dict):
        """
        Set command options - usually from the options passed to mudddle
        """
        self.options = opt_dict

    def no_op(self):
        """
        Is this is a no-op (just print) operation?
        """
        return ("no_operation" in self.options)


    def with_build_tree(self, builder, local_pkgs, args):
        """
        Run this command with a build tree
        """
        raise utils.Error("Can't run %s with a build tree."%self.name)

    def without_build_tree(self, muddle_binary, root_path, args):
        """
        Run this command without a build tree
        """
        raise utils.Error("Can't run %s without a build tree."%self.name)
        

class Root(Command):
    """
    Syntax: root

    Display the root directory we reckon you're in
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
    Syntax: init [repo] [build_desc]

    Initialise a new build tree with a given repository and
    build description. We check out the build description but
    don't actually build.
    """

    def name(self): 
        return "init"

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, local_pkgs, args):
        raise utils.Error("Can't initialise a build tree " + 
                    "when one already exists (%s)"%builder.invocation.db.root_path)
    
    def without_build_tree(self, muddle_binary, root_path, args):
        """
        Initialise a build tree
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
    Syntax: unit_test

    Run the muddle unit tests
    """
    
    def name(self): 
        return "unit_test"

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, local_pkgs, args):
        return test.unit_test()

    def without_build_tree(self, muddle_binary, root_path, args):
        return test.unit_test()

class ListVCS(Command):
    """
    Syntax: vcs

    List the version control systems supported by this version of muddle
    together with their VCS specifiers
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
    Syntax: depend <[system|user|all]>

    Print the current dependency sets. 

    depend system   Prints only synthetic dependencies produced by the system.
    depend user     Prints only dependencies entered by the build description
    depend all      Prints all dependencies
    """
    
    def name(self):
        return "depend"

    def requires_build_tree(self):
        return True
    
    def without_build_tree(self, muddle_binary, root_path, args):
        raise utils.Error("Cannot run without a build tree")

    def with_build_tree(self, builder, local_pkgs, args):
        if len(args) != 1 and len(args) != 2:
            print "Syntax: depend <[system|user|all]> <[label to match]>"
            print self.__doc__
            return 2
        
        type = args[0]
        if len(args) == 2:
            label = depend.label_from_string(args[1])
        else:
            label = None

        show_sys = False
        show_user = False

        if (type == "system"):
            show_sys = True
        elif (type == "user"):
            show_user = True
        elif (type == "all"):
            show_sys = True
            show_user = True
        else:
            raise utils.Error("Bad dependency type: %s"%(type))

        
        print builder.invocation.ruleset.to_string(matchLabel = label, 
                                                   showSystem = show_sys, showUser = show_user)

class Query(Command):
    """
    Syntax: query [env|rule|deps|results] [label]

    Query aspects of a label - the environment in which it will execute, or
    what it depends on, or what depends on it.

    env            The environment in which this label will be run.
    rule           The rules covering building this label.
    deps           What we need to build to build this label
    results        What this label is required to build
    instructions   The list of currently registered instruction files,
                     in the order in which they will be applied.
    inst-details   The list of actual instructions, in the order in which
                     they will be applied.
    checkouts      Print a list of known checkouts.

    Note that both instructions and inst-details are label-sensitive, so you
    will want to supply a label like 'package:*/myrole'.
    """

    def name(self):
        return "query"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        if len(args) != 2:
            print "Syntax: query <cmd> <label>"
            print self.__doc__
            return 2

        type = args[0]
        label = depend.label_from_string(args[1])
        
        if (label is None):
            print "Putative label %s is not a valid label"%(args[1])
            return 3

        if (type == "env"):
            the_env = builder.invocation.get_environment_for(label)

            local_store = env_store.Store()
            builder.set_default_variables(label, local_store)
            local_store.merge(the_env)

            print "Environment for %s .. "%label
            print local_store.get_setvars_script(label, env_store.EnvLanguage.Sh)
        elif (type == "rule"):
            local_rule = builder.invocation.ruleset.rule_for_target(label)
            if (local_rule is None):
                print "No ruleset for %s"%label
            else:
                print "Rule set for %s .. "%label
                print local_rule
        elif (type == "deps"):
            to_build = depend.needed_to_build(builder.invocation.ruleset, label)
            if (to_build is None):
                print "No dependencies for %s"%label
            else:
                print "Build order for %s .. "%label
                for rule in to_build:
                    print rule.target
        elif (type == "results"):
            result = depend.required_by(builder.invocation.ruleset, label)
            print "Labels which require %s to build .. "%label
            for lbl in result:
                print lbl
        elif (type == "instructions"):
            result = builder.invocation.db.scan_instructions(label)
            for (l, f) in result:
                print "Label: %s  Filename: %s"%(l,f)
        elif (type == "inst-details"):
            loaded = builder.load_instructions(label)
            for (l, f, i) in loaded:
                print " --- Label %s , filename %s --- "%(l, f)
                print i.get_xml()
            print "-- Done --"
        elif (type == "checkouts"):
            cos = builder.invocation.all_checkouts()
            a_list = [ ]
            for c in cos:
                a_list.append(c)
            a_list.sort()
            print "Checkouts: %s"%(" ".join(a_list))
        else:
            print "Unrecognised command '%s'"%type
            print self.__doc__
            return 2

        return 0

class BuildLabel(Command):
    """
    Syntax: buildlabel [labels .. ]

    Builds a set of specified labels, without all the defaulting
    and trying to guess what you mean that Build does.
    
    Mainly used internally to build defaults and the privileged
    half of instruction executions
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
    Syntax: redeploy [deployment .. ]

    Remove all tags for the given deployments, erase their built
    directories and redeploy them.

    You can use cleandeploy to just clean the relevant deployments

    If no deployments are given, we redeploy the default deployment
    list. If _all is given, we redeploy all deployments
    """
    
    def name(self):
        return "redeploy"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_deployment_arguments(builder, args, local_pkgs,
                                             utils.Tags.Deployed)
        rv = build_a_kill_b(builder, labels, utils.Tags.Clean, utils.Tags.Deployed)
        rv = build_labels(builder, labels)
        return rv
        

class Cleandeploy(Command):
    """
    Syntax: cleandeploy [deployment .. ]

    Remove all tags for the given deployments and erase their built
    directories.

    You can use cleandeploy to just clean the relevant deployments

    If no deployments are given, we redeploy the default deployment
    list. If _all is given, we redeploy all deployments
    """
    
    def name(self):
        return "cleandeploy"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_deployment_arguments(builder, args, local_pkgs,
                                             utils.Tags.Clean)
        rv = build_a_kill_b(builder, labels, utils.Tags.Clean, utils.Tags.Deployed)


class Deploy(Command):
    """
    Syntax: deploy [deployment .. ]

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
    Syntax: build [package/role] [package/role]
    
    Build a package. If the package name isn't given, we'll use the
    list of local packages derived from your current directory.

    Unqualified or inferred package names are built in every default
    role (there's a list in the build description)

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
    Syntax: rebuild [package/role] [package/role]

    Just like build except that we clear any built tags first 
    (and their dependencies)
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


class Clean(Command):
    """
    Syntax: clean [package/role] .. 
    
    Just like build except that we clean packages rather than 
    building them. Subsequently, packages are regarded as having
    been configured but not build
    """
    
    def name(self):
        return "clean"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_package_arguments(builder, args, local_pkgs, 
                                          utils.Tags.Built)

        rv = build_a_kill_b(builder, labels, utils.Tags.Clean, utils.Tags.Built)
        return rv

class DistClean(Command):
    """
    Syntax: distclean [package/role] .. 

    Just like clean except that we reduce packages to non-preconfigured
    and invoke make distclean
    """
    
    def name(self):
        return "distclean"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        labels = decode_package_arguments(builder, args, local_pkgs, 
                                          utils.Tags.Built)

        if (self.no_op()):
            print "Would have disctleaned: %s"%(join(" ", map(str, labels)))
            rv = 0
        else:
            rv = build_a_kill_b(builder, labels, utils.Tags.DistClean, utils.Tags.PreConfig)

        return rv

class Instruct(Command):
    """
    Syntax: instruct [pkg/role] <[instruction-file]>

    Sets the instruction file for the given package name and role to 
    the file specified in instruction-file. The role must be explicitly
    given as it's considered more likely that bugs will be introduced by
    the assumption of default roles than they are likely to prove useful.
    
    This command is typically issued by 'make install' for a package, as
    $(MUDDLE_INSTRUCT) [instruction-file]
    
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
            print "Syntax: instruct [pkg/role] <[instruction-file]>"
            print self.__doc__
            return 1

        pkg_role = args[0]
        ifile = None

        # Validate this first - the file check may take a while.
        lbls = labels_from_pkg_args([ pkg_role ], utils.Tags.PreConfig,                                     
                                    [ ])


        if (len(lbls) != 1 or (lbls[0].role is None)):
            raise utils.Failure("instruct takes precisely one package/role pair " +
                                "and the role must be explicit")


        if (len(args) == 2):
            filename = args[1]

            if (not os.path.exists(filename)):
                raise utils.Failure("Attempt to register instructions in " + 
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
            builder.instruct(lbls[0].name, lbls[0].role, ifile)
                                    
class Update(Command):
    """
    Syntax: update [checkouts]

    Update the specified checkouts.

    If no checkouts are given, we'll use those implied by your current
    location.
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
    Syntax: commit [checkouts]

    Commit the specified checkouts.

    If no checkouts are given, we'll use those implied by your current
    location.
    """
    
    def name(self):
        return "commit"

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
    Syntax: commit [checkouts]

    Push the specified checkouts.

    If no checkouts are given, we'll use those implied by your current
    location.
    """
    
    def name(self):
        return "push"

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


class Import(Command):
    """
    Syntax: import [checkout.. ]

    Assert that the given checkout (which may be the builds checkout) has
    been checked out and is up to date. This is mainly used when you've just
    written a package you plan to commit to the central repository - muddle
    obviously can't check it out because it's still being created, but you
    probably want to add it to the build description for testing 
    (and in fact you may want to commit it with muddle push).

    This is really just an implicit version of muddle assert with the right
    magic label names

    Without a checkout, we import the checkout you're in, or the checkouts
    depended on by the package directory you're in.
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
    Syntax: assert [label .. ]

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
    Syntax: retract [label .. ]

    Retract the given labels nd their consequents. 
    Mostly for use by experts and scripts.
    """
    
    def name(self):
        return "retract"

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, local_pkgs, args):
        if len(args) < 1 :
            print "Syntax: retract [label .. ]"
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
    Syntax: changed [pkg .. ]

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
                               tag))
        
    rv.sort()
    return rv


def decode_checkout_arguments(builder, args, local_pkgs, tag):
    """
    Decode arguments into a set of checkout labels with the given tag.

    If there are arguments, they specify checkouts.
    If there aren't, all checkouts dependent on any local_pkgs tag are
     returned

    """

    rv = [ ]

    if (len(args) > 0):
        # Excellent!
        for co in args:
            if (co == "_all"):
                return get_all_checkouts(builder, tag)
            else:
                rv.append(depend.Label(utils.LabelKind.Checkout, 
                                       co, None, tag))

    else:
        out_set = ()
        
        if (local_pkgs is None or len(local_pkgs) == 0):
            # Where are we? If in a checkout, that's what we should do - else
            # all checkouts.
            (what, loc, role) = utils.find_location_in_tree(os.getcwd(),
                                                            builder.invocation.db.root_path)
            if (what == utils.DirType.CheckOut and (loc is not None)):
                rv = [ ]
                rv.append(depend.Label(utils.LabelKind.Checkout, 
                                       loc, None, tag))
                return rv
            else:
                # Everything
                return get_all_checkouts(builder, tag)

        for pkg in local_pkgs:
            my_label = depend.Label(utils.LabelKind.Package,
                                    pkg,
                                    "*",
                                    "*")
            deps = depend.needed_to_build(builder.invocation.ruleset, 
                                          my_label)
            for d in deps:
                if (d.target.tag_kind == utils.LabelKind.Checkout):
                    out_set.add(depend.Label(utils.LabelKind.Checkout, 
                                             d.target.name,
                                             None, 
                                             tag))
        for o in out_set:
            rv.append(o)

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
                               tag)
            return_list.append(lbl)
    
    if len(return_list) == 0:
        # Input was empty - default deployments.
        return default_deployment_labels(builder, tag)


def all_deployment_labels(builder, tag):
    """
    Return all the deployment labels registered with the ruleset.
    """

    # Important not to set tag here - if there's a deployment
    #  which doesn't have the right tag, we want an error, 
    #  not to silently ignore it.
    match_lbl = depend.Label(utils.LabelKind.Deployment,
                             "*", "*", "*")
    matching = builder.invocation.ruleset.rules_for_target(lbl)
    
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
        if (d.tag_kind == utils.LabelKind.Deployment):
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
                                        builder.invocation.default_roles)
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
    


def labels_from_pkg_args(list, tag, default_roles):
    """
    Convert a list of packages expressed as package([/role]?) into
    a set of labels with the given tag. This is basically a 
    cartesian product of all the unqualified packages.
    """

    the_re = re.compile("([A-Za-z0-9*_]+)(/([A-Za-z0-9*_]+))?$")

    result = [ ]

    if (list is None):
        raise utils.Failure("No packages specified")

    for elem in list:
        m = the_re.match(elem)
        if (m is None):
            # Hmm ..
            raise utils.Error("Package list element %s isn't a well-formed package descriptor (pkg(/role)?)"%elem)
        else:
            pkg = m.group(1)
            role = m.group(3)
            if (role is None):
                # Add the default roles
                for r in default_roles:
                    result.append(depend.Label(utils.LabelKind.Package, 
                                               pkg, 
                                               r,
                                               tag))
            else:
                result.append(depend.Label(utils.LabelKind.Package,
                                           pkg, 
                                           role,
                                           tag))
                
    return result
    
    

def register_commands():
    """
    Returns a dictionary of command name to command object for all 
    commands
    """

    the_dict = { }
    Init().register(the_dict)
    Root().register(the_dict)
    UnitTest().register(the_dict)
    ListVCS().register(the_dict)
    Depend().register(the_dict)
    Query().register(the_dict)
    Build().register(the_dict)
    Rebuild().register(the_dict)
    Clean().register(the_dict)
    DistClean().register(the_dict)
    Instruct().register(the_dict)
    BuildLabel().register(the_dict)
    Import().register(the_dict)
    Assert().register(the_dict)
    Retract().register(the_dict)
    Update().register(the_dict)
    Commit().register(the_dict)
    Push().register(the_dict)
    Changed().register(the_dict)
    Deploy().register(the_dict)
    Redeploy().register(the_dict)
    Cleandeploy().register(the_dict)
    
    
    return the_dict

# End file.

    