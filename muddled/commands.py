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
# XXX as possible is good, whilst for sphinx/reStructuredText purposes,
# XXX somewhat more markup would make the generated documentation better
# XXX (and more consistent with other muddled modules).

import difflib
import errno
import os
import posixpath
import pydoc
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import urllib
import xml.dom.minidom
from urlparse import urlparse

import muddled.depend as depend
import muddled.env_store as env_store
import muddled.instr as instr
import muddled.mechanics as mechanics
import muddled.pkg as pkg
import muddled.subst as subst
import muddled.utils as utils
import muddled.version_control as version_control
import muddled.docreport

from muddled.db import Database, InstructionFile
from muddled.depend import Label, label_list_to_string
from muddled.utils import GiveUp, MuddleBug, Unsupported, \
        DirType, LabelTag, LabelType, find_label_dir, sort_domains
from muddled.utils import split_vcs_url
from muddled.version_control import checkout_from_repo
from muddled.repository import Repository
from muddled.version_stamp import VersionStamp, ReleaseStamp, ReleaseSpec
from muddled.licenses import print_standard_licenses, get_gpl_checkouts, \
        get_not_licensed_checkouts, get_implicit_gpl_checkouts, \
        get_license_clashes, licenses_in_role, get_license_clashes_in_role
from muddled.distribute import distribute, the_distributions, \
        get_distribution_names, get_used_distribution_names
from muddled.withdir import Directory, NewDirectory

# Following Richard's naming conventions...
# A dictionary of <command name> : <command class>
# If a command has aliases, then they will also be entered as keys
# in the dictionary, with the same <command instance> as their value.
# If a command has subcommands, then it will be entered in this dictionary,
# but its <command instance> will be None.
g_command_dict = {}
# A list of all of the known commands, by their "main" name
# (so one name per command, only)
g_command_names = []
# A dictionary of <category name> : [<command name>]
g_command_categories = {}
# A dictionary of <command alias> : <command name>
# (of course, the keys are then the list of things that *are* aliases)
g_command_aliases = {}

# The categories, and an order for them
CAT_INIT='init'
CAT_CHECKOUT='checkout'
CAT_PACKAGE='package'
CAT_DEPLOYMENT='deployment'
CAT_ANYLABEL='any label'
CAT_QUERY='query'
CAT_EXPORT='export'
CAT_MISC='misc'
g_command_categories_in_order = [CAT_INIT, CAT_CHECKOUT, CAT_PACKAGE,
        CAT_DEPLOYMENT, CAT_ANYLABEL, CAT_QUERY, CAT_EXPORT, CAT_MISC]

def in_category(command_name, category):
    if category not in g_command_categories_in_order:
        raise GiveUp("Command %s cannot be added to unexpected"
                     " category %s"%(command_name, category))

    if category in g_command_categories:
        g_command_categories[category].add(command_name)
    else:
        g_command_categories[category] = set([command_name])

def command(command_name, category, aliases=None):
    """A simple decorator to remmember a class by its command name.

    'category' indicates which type of command this is
    """
    if command_name in g_command_dict:
        raise GiveUp("Command '%s' is already defined"%command_name)
    def rememberer(klass):
        g_command_dict[command_name] = klass
        if aliases:
            for alias in aliases:
                g_command_aliases[alias] = command_name
                g_command_dict[alias] = klass
        klass.cmd_name = command_name
        return klass

    g_command_names.append(command_name)
    in_category(command_name, category)

    return rememberer

# A dictionary of the form <command_name> : <sub_command_dict>,
# where each <sub_command_dict> is a dictionary of
# <sub_command_name : <subcommand class>
g_subcommand_dict = {}
# A dictionary of subcommand aliases, arranged as
# <command_name> : <sub_command_dict> where each <sub_command_dict>
# is a dictionary of <alias> : <subcommand>.
g_subcommand_aliases = {}
# A list of all of the known commands, by their "main" name
# (so one name per command, only) each as a tuple of (<cmd>, <subcmd>)
g_subcommand_names = []

def subcommand(main_command, sub_command, category, aliases=None):
    """Remember the class for <main_command> <subcommand>.
    """
    if main_command not in g_command_dict:
        g_command_dict[main_command] = None
        sub_dict = {}
        g_subcommand_dict[main_command] = sub_dict
    else:
        sub_dict = g_subcommand_dict[main_command]
        if sub_command in sub_dict:
            raise GiveUp("Command '%s %s' is already defined"%(main_command,sub_command))
    g_subcommand_names.append((main_command, sub_command))
    in_category(main_command, category)
    def rememberer(klass):
        sub_dict[sub_command] = klass
        klass.cmd_name = '%s %s'%(main_command, sub_command)
        if aliases:
            if main_command not in g_subcommand_aliases:
                g_subcommand_aliases[main_command] = {}
            alias_dict = g_subcommand_aliases[main_command]
            for alias in aliases:
                alias_dict[alias] = sub_command
                sub_dict[alias] = klass
        return klass
    return rememberer

class Command(object):
    """
    Abstract base class for muddle commands. Stuffed with helpful functionality.

    Each subclass is a ``muddle`` command, and its docstring is the "help"
    text for that command.
    """

    cmd_name = '<Undefined>'

    # Subclasses should override this to specify any switches that
    # are allowed after the command word.
    #
    # This mechanism is VERY primitive, and does not allow ordering
    # of switches (so it doesn't cope with a switch overriding a previous
    # switch), or switches with arguments. Perhaps I should be using
    # whatever switch mechanism Python 2.6 and above support - except
    # that getopt and optparse are both awful, and Python 2.7's argparse
    # doesn't seem much better (and, anyway, isn't in Python 2.6)
    #
    # Our switches are held as a dictionary whose keys are the allowed
    # switches, and whose values are the token to put into self.switches
    # if we encounter that switch
    allowed_switches = {}

    # A list of the switches we were given, held as the first element
    # from one of the 'allowed_switches' tuples
    switches = []

    def __init__(self):
        self.options = { }

    def help(self):
        return self.__doc__

    def requires_build_tree(self):
        """
        Returns True iff this command requires an initialised
        build tree, False otherwise.
        """
        return True

    def allowed_in_release_build(self):
        """
        Returns True iff this command is allowed in a release build
        (a build tree that has been created using "muddle release").
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

    def remove_switches(self, args, allowed_more=True):
        """Find any switches, remember them, return the remaining arguments.

        Switches are assumed to all come before any labels. We stop with
        an exception if we encounter something starting with '-' that is not a
        recognised switch.

        If 'allowed_more' is False, then the command line must end after any
        switches.
        """
        self.switches = []              # In case we're called again
        while args:
            word = args[0]
            if word[0] == '-':
                if word in self.allowed_switches:
                    self.switches.append(self.allowed_switches[word])
                else:
                    raise GiveUp('Unexpected switch "%s"'%word)
            else:
                break
            args = args[1:]

        if args and not allowed_more:
            raise GiveUp('Unexpected trailing arguments "%s"'%' '.join(args))
        return args

    def with_build_tree(self, builder, current_dir, args):
        """
        Run this command with a build tree.

        Arguments are:

        * 'builder' is the Builder instance, as constructed from the build
          tree we are in.

        * 'current_dir' is the current directory.

        * 'args' - this is any other arguments given to muddle, that occurred
          after the command name.
        """
        raise GiveUp("Can't run %s with a build tree."%self.cmd_name)

    def without_build_tree(self, muddle_binary, current_dir, args):
        """
        Run this command without a build tree.

        Arguments are:

        * 'muddle_binary' is the location of the muddle binary - this is only
          needed if "muddle" is going to be run explicitly, or if a
          Makefile.muddle is going to use $(MUDDLE_BINARY)

        * 'current_dir' is the current directory.

        * 'args' - this is any other arguments given to muddle, that occurred
          after the command name.
        """
        raise GiveUp("Can't run %s without a build tree."%self.cmd_name)

    def check_for_broken_build(self, current_dir):
        """Check to see if there is a "partial" build in the current directory.

        Intended for use in 'without_build_tree()', in classes such as UnStamp,
        which want to operate in an empty directory (or, at least, one without
        a muddle build tree in it).

        The top-level muddle code does a simple check for whether there is a
        build tree in the current directory before calling a
        'without_build_tree()' method, but sometimes we want to be a bit more
        careful and check for a "partial" build tree, presumably left by a
        previous, failed, command.

        If it finds a problem, it prints out a description of the problem,
        and raises a GiveUp error with retcode 4, so that muddle will exit
        with exit code 4.
        """
        dir, domain = utils.find_root_and_domain(current_dir)
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
                             ' before retrying the "%s" command.'%(extra, self.cmd_name))
            raise GiveUp(retcode=4)


class CPDCommand(Command):
    """
    A command that takes checkout, package or deployment arguments.

    This is purely an intermediate class for common code for the
    classes using it (I coult have done a mixin class instead)
    """

    # It may be useful to remember the contents of the command line after
    # switches have been removed, but before labels (e.g., _all) have been
    # expanded
    original_labels = []

    # We would also like to remember our "current" directory, i.e., our
    # top-level directory, in case a subclass wants it
    current_dir = None

    # Subclasses should override the following as necessary
    required_tag = None
    required_type = LabelType.Checkout

    def expand_labels(self, builder, args):
        if args:
            # Expand out any labels that need it
            labels = self.decode_args(builder, args, self.current_dir)
        else:
            # Decide what to do based on where we are
            labels = self.default_args(builder, self.current_dir)
        # We promised a sorted list
        labels.sort()
        return labels

    def with_build_tree(self, builder, current_dir, args):

        args = self.remove_switches(args)

        self.original_labels = args[:]
        self.current_dir = current_dir

        labels = self.expand_labels(builder, args)

        if self.no_op():
            print 'Asked to %s:\n  %s'%(self.cmd_name,
                    label_list_to_string(labels, join_with='\n  '))
            return

        self.build_these_labels(builder, labels)

    def decode_args(self, builder, args, current_dir):
        """
        Interpret 'args' as partial labels, and return a list of proper labels.
        """

        result_set = set()
        # Build up an initial list from the arguments given
        # Make sure we have a one-for-one correspondence between the input
        # list and the result
        initial_list = []
        label_from_fragment = builder.label_from_fragment
        expand_underscore_arg = builder.expand_underscore_arg
        for word in args:
            if word[0] == '_':
                initial_list.extend(expand_underscore_arg(word, self.required_type))
            else:
                labels = label_from_fragment(word, default_type=self.required_type)

                used_labels = []
                # We're only interested in any labels that are actually used
                for label in labels:
                    if builder.target_label_exists(label):
                        used_labels.append(label)

                # But it's an error if none of them were wanted
                if not used_labels:
                    raise GiveUp(builder.diagnose_unused_labels(labels, word,
                                                                self.required_type,
                                                                self.required_tag))

                # Don't forget to remember those we do want!
                initial_list.extend(used_labels)

        #print 'Initial list:', label_list_to_string(initial_list)

        if not initial_list:
            raise GiveUp('Expanding "%s" does not give any target labels'%' '.join(args))

        # Now take those full labels and turn them into just checkouts,
        # packages or deployments, according to what we want
        intermediate_set = self.interpret_labels(builder, args, initial_list)

        #print 'Intermediate set:', label_list_to_string(intermediate_set)

        if self.required_tag:
            # Regardless of the actual dependency, use the required tag.
            # I believe this makes sense, as we're asking to do a
            # particular command on the checkout, and that *means* moving
            # to the required tag
            result_set = set()
            for l in intermediate_set:
                if l.tag != self.required_tag:
                    l = l.copy_with_tag(self.required_tag)
                result_set.add(l)
        else:
            result_set = intermediate_set

        #print 'Result set', label_list_to_string(result_set)
        return list(result_set)

    def default_args(self, builder, current_dir):
        """
        Decide on default labels, based on where we are in the build tree.
        """
        raise MuddleBug('No "default_args" method provided for command "%s"'%self.cmd_name)

    def interpret_labels(self, builder, args, initial_list):
        """
        Turn 'initial_list' into a list of labels of the required type.

        This method should attempt to GiveUp with a useful message if it
        would otherwise return an empty list.
        """
        raise MuddleBug('No "interpret_labels" method provided for command "%s"'%self.cmd_name)

    def build_these_labels(self, builder, checkouts):
        """
        Do whatever is necessary to each label
        """
        raise MuddleBug('No "build_these_labels" method provided for command "%s"'%self.cmd_name)

class CheckoutCommand(CPDCommand):
    """
    A Command that takes checkout arguments. Always requires a build tree.

    If no explicit labels are given, then the default is to find all the
    checkouts below the current directory.
    """

    required_type = LabelType.Checkout
    # Subclasses should override the following as necessary
    required_tag = LabelTag.CheckedOut

    # In general, these commands are not allowed in release builds
    def allowed_in_release_build(self):
        return False

    def interpret_labels(self, builder, args, initial_list):
        """
        Turn 'initial_list' into a list of labels of the required type.
        """
        potential_problems = []
        intermediate_set = set()
        for index, label in enumerate(initial_list):
            found = False
            if label.type == LabelType.Checkout:
                found = True
                intermediate_set.add(label)
            elif label.type in LabelType.Package:
                # All the checkouts that are used *directly* by this package
                checkouts = builder.checkouts_for_package(label)
                if checkouts:
                    found = True
                    intermediate_set.update(checkouts)
            elif label.type in LabelType.Deployment:
                # All the checkouts needed for this particular deployment
                # XXX I don't think we need to specify useMatch=True, because we
                # XXX should already have expanded any wildcards
                rules = depend.needed_to_build(builder.ruleset, label)
                for r in rules:
                    l = r.target
                    if l.type == LabelType.Checkout:
                        found = True
                        intermediate_set.add(l)
            else:
                raise GiveUp("Cannot cope with label '%s', from arg '%s'"%(label, args[index]))

            if not found:
                potential_problems.append('%s does not depend on any checkouts'%label)

        if not intermediate_set:
            text = []
            if len(initial_list) == 1:
                text.append('Label %s exists, but does not give'
                             ' a target for "muddle %s"'%(initial_list[0], self.cmd_name))
            else:
                text.append('The labels\n  %s\nexist, but none gives a'
                            ' target for "muddle %s"'%(label_list_to_string(initial_list,
                                join_with='\n  '), self.cmd_name))
            if potential_problems:
                text.append('Perhaps because:')
                for problem in potential_problems:
                    text.append('  %s'%problem)
            raise GiveUp('\n'.join(text))

        return intermediate_set

    def default_args(self, builder, current_dir):
        """
        Decide on default labels, based on where we are in the build tree.
        """
        what, label, domain = builder.find_location_in_tree(current_dir)
        arg_list = []

        if label:       # Since we know our label, use it (of whatever type)
            arg_list.append(label)
        elif what == DirType.Checkout:
            # We've got checkouts below us - use those
            arg_list.extend(builder.get_all_checkout_labels_below(current_dir))

        if not arg_list:
            raise GiveUp('Not sure what you want to %s'%self.cmd_name)

        # And just pretend that was what the user asked us to do
        return self.decode_args(builder, map(str, arg_list), current_dir)

class PackageCommand(CPDCommand):
    """
    A Command that takes package arguments. Always requires a build tree.
    """

    required_type = LabelType.Package
    # Subclasses should override the following as necessary
    required_tag = LabelTag.PostInstalled

    def interpret_labels(self, builder, args, initial_list):
        """
        Turn 'initial_list' into a list of labels of the required type.
        """
        potential_problems = []
        intermediate_set = set()
        default_roles = builder.default_roles
        for index, label in enumerate(initial_list):
            if label.type == LabelType.Package:
                intermediate_set.add(label)
            elif label.type == LabelType.Checkout:
                # Experience seems to show that it makes more sense to go for
                # just the *immediate* package dependencies - i.e., the packages
                # that are actually built from this checkout.
                # And the documentation says we should only use package labels
                # with the default roles
                package_labels = builder.packages_using_checkout(label)
                found = False
                for l in package_labels:
                    if l.role in default_roles:
                        found = True
                        intermediate_set.add(l)
                if not found:
                    if package_labels:
                        potential_problems.append('  None of the packages in the'
                                                  ' default roles use %s'%label)
                        # XXX Hmm, this gives a bit too much detail
                        package_labels = list(package_labels)
                        package_labels.sort()
                        potential_problems.append('  It is used by\n    %s'%label_list_to_string(package_labels, join_with='\n    '))
                    else:
                        potential_problems.append('  It is not used by any packages')
            elif label.type in (LabelType.Deployment):
                # If they specified a deployment label, then find all the
                # packages that depend on this deployment.
                if True:
                    # Here I think we definitely want any depth of dependency.
                    # XXX I don't think we need to specify useMatch=True, because we
                    # XXX should already have expanded any wildcards
                    rules = depend.needed_to_build(builder.ruleset, label)
                    found = False
                    for r in rules:
                        l = r.target
                        if l.type == LabelType.Package:
                            found = True
                            intermediate_set.add(l)
                    if not found:
                        potential_problems.append('  Deployment %s does not use any packages'%label)
                else:
                    # Just get the packages we immediately depend on
                    packages = builder.packages_for_deployment(label)
                    if packages:
                        intermediate_set.update(packages)
                    else:
                        potential_problems.append('  Deployment %s does not use any packages'%label)
            else:
                raise GiveUp("Cannot cope with label '%s', from arg '%s'"%(label, args[index]))

        if not intermediate_set:
            text = []
            if len(initial_list) == 1:
                text.append('Label %s exists, but does not give'
                             ' a target for "muddle %s"'%(initial_list[0], self.cmd_name))
            else:
                text.append('The labels\n  %s\nexist, but none gives a'
                            ' target for "muddle %s"'%(label_list_to_string(initial_list,
                                join_with='\n  '), self.cmd_name))
            if potential_problems:
                text.append('Perhaps because:')
                for problem in potential_problems:
                    text.append('%s'%problem)
            raise GiveUp('\n'.join(text))

        return intermediate_set

    def default_args(self, builder, current_dir):
        """
        Decide on default labels, based on where we are in the build tree.
        """
        what, label, domain = builder.find_location_in_tree(current_dir)
        arg_list = []

        if label:
            # We're somewhere that knows its label, so can probably work
            # out what to do
            arg_list.append(label)
        elif what == DirType.Checkout:
            # We've got checkouts below us - use those
            arg_list.extend(builder.get_all_checkout_labels_below(current_dir))

        if not arg_list:
            raise GiveUp('Not sure what you want to %s'%self.cmd_name)

        # And just pretend that was what the user asked us to do
        return self.decode_args(builder, map(str, arg_list), current_dir)

class DeploymentCommand(CPDCommand):
    """
    A Command that takes deployment arguments. Always requires a build tree.
    """

    required_type = LabelType.Deployment
    # Subclasses should override the following as necessary
    required_tag = LabelTag.Deployed

    def interpret_labels(self, builder, args, initial_list):
        """
        Turn 'initial_list' into a list of labels of the required type.
        """
        potential_problems = []
        intermediate_set = set()
        for index, label in enumerate(initial_list):
            found = False
            if label.type == LabelType.Deployment:
                found = True
                intermediate_set.add(label)
            elif label.type in (LabelType.Checkout, LabelType.Package):
                required_labels = depend.required_by(builder.ruleset, label)
                for l in required_labels:
                    if l.type == LabelType.Deployment:
                        found = True
                        intermediate_set.add(l)
            else:
                raise GiveUp("Cannot cope with label '%s', from arg '%s'"%(label, args[index]))

            if not found:
                potential_problems.append('No deployments depend on %s'%label)

        if not intermediate_set:
            text = []
            if len(initial_list) == 1:
                text.append('Label %s exists, but does not give'
                             ' a target for "muddle %s"'%(initial_list[0], self.cmd_name))
            else:
                text.append('The labels\n  %s\nexist, but none gives a'
                            ' target for "muddle %s"'%(label_list_to_string(initial_list,
                                join_with='\n  '), self.cmd_name))
            if potential_problems:
                text.append('Perhaps because:')
                for problem in potential_problems:
                    text.append('  %s'%problem)
            raise GiveUp('\n'.join(text))

        return intermediate_set

    def default_args(self, builder, current_dir):
        """
        Decide on default labels, based on where we are in the build tree.
        """
        # Can we guess what to do from where we are?
        what, label, domain = builder.find_location_in_tree(current_dir)
        arg_list = []

        if label:
            arg_list.append(label)
        elif what == DirType.Checkout:
            # We've got checkouts below us - use those
            arg_list.extend(builder.get_all_checkout_labels_below(current_dir))

        if not arg_list:
            raise GiveUp('Not sure what you want to %s'%self.cmd_name)

        # And just pretend that was what the user asked us to do
        return self.decode_args(builder, map(str, arg_list), current_dir)

class AnyLabelCommand(Command):
    """
    A Command that takes any sort of label. Always requires a build tree.

    We don't try to turn one sort of label into another, and we don't alter
    the order of the labels given. At least one label must be provided.
    """

    def with_build_tree(self, builder, current_dir, args):
        if args:
            # Expand out any labels that need it
            labels = self.decode_args(builder, args, current_dir)
        else:
            raise GiveUp('Nothing to do: no label given')

        # We don't sort the list - we keep it in the order given

        if self.no_op():
            print 'Asked to %s:\n  %s'%(self.cmd_name,
                    label_list_to_string(labels, join_with='\n  '))
            return
        elif not args:
            print '%s %s'%(self.cmd_name, label_list_to_string(labels))

        self.build_these_labels(builder, labels)

    def decode_args(self, builder, args, current_dir):
        """
        Turn the arguments into full labels.
        """
        # Build up an initial list from the arguments given
        # Make sure we have a one-for-one correspondence between the input
        # list and the result
        result_list = []
        label_from_fragment = builder.label_from_fragment
        for word in args:
            if word[0] == '_':
                raise GiveUp('Command %s does not allow %s as an argument'%(self.cmd_name, word))

            labels = label_from_fragment(word, default_type=LabelType.Package)

            used_labels = []
            # We're only interested in any labels that are actually used
            for label in labels:
                if builder.target_label_exists(label):
                    used_labels.append(label)

            # But it's an error if none of them were wanted
            if not used_labels:
                # XXX =====================================
                if args:
                    print 'Arguments (shown one per line) were:'
                    for arg in args:
                        print '  ', arg
                else:
                    print 'There were no arguments,implicit or explicit'
                # XXX =====================================
                if len(labels) == 1:
                    raise GiveUp("Label %s, from argument '%s', is"
                                 " not a target"%(labels[0], word))
                elif len(labels) == 0:
                    raise GiveUp("Argument '%s' does not expand into anything"%(word))
                else:
                    # XXX This isn't a great error message, but it's OK
                    # XXX for now, and significantly better than nothing
                    raise GiveUp("None of the labels %s, from argument '%s', is"
                                 " a target"%(label_list_to_string(labels,
                                     join_with=', '), word))

            # Don't forget to remember those we do want!
            result_list.extend(used_labels)

        return result_list

    def build_these_labels(self, builder, checkouts):
        """
        Do whatever is necessary to each label
        """
        raise MuddleBug('No action provided for command "%s"'%self.cmd_name)

# -----------------------------------------------------------------------------
# Actions
# -----------------------------------------------------------------------------

def build_a_kill_b(builder, labels, build_this, kill_this):
    """
    For every label in labels, build the label formed by replacing
    tag in label with build_this and then kill the tag in label with
    kill_this.

    We have to interleave these operations so an error doesn't
    lead to too much or too little of a kill.
    """
    for lbl in labels:
        try:
            l_a = lbl.copy_with_tag(build_this)
            print "Building: %s .. "%(l_a)
            builder.build_label(l_a)
        except GiveUp as e:
            raise GiveUp("Can't build %s: %s"%(l_a, e))

        try:
            l_b = lbl.copy_with_tag(kill_this)
            print "Killing: %s .. "%(l_b)
            builder.kill_label(l_b)
        except GiveUp as e:
            raise GiveUp("Can't kill %s: %s"%(l_b, e))

def kill_labels(builder, to_kill):
    if len(to_kill) == 1:
        print "Killing %s"%to_kill[0]
    else:
        print "Killing %d labels"%len(to_kill)

    try:
        for lbl in to_kill:
            builder.kill_label(lbl)
    except GiveUp, e:
        raise GiveUp("Can't kill %s - %s"%(str(lbl), e))

def build_labels(builder, to_build):
    if len(to_build) == 1:
        print "Building %s"%to_build[0]
    else:
        print "Building %d labels"%len(to_build)

    try:
        for lbl in to_build:
            builder.build_label(lbl)
    except GiveUp,e:
        raise GiveUp("Can't build %s - %s"%(str(lbl), e))

# =============================================================================
# Actual commands
# =============================================================================
# -----------------------------------------------------------------------------
# Help - this is a query command, but it's nice to have it easy to find
# -----------------------------------------------------------------------------

@command('help', CAT_QUERY)
class Help(Command):
    """
    To get help on commands, use:

      muddle help [<switch>] [<command>]

    specifically::

      muddle help <cmd>          for help on a command
      muddle help <cmd> <subcmd> for help on a subcommand
      muddle help _all           for help on all commands
      muddle help <cmd> _all     for help on all <cmd> subcommands
      muddle help commands       just list the (top level) commands
      muddle help categories     shows command names sorted by category
      muddle help labels         for help on using labels
      muddle help subdomains     for help on subdomains
      muddle help aliases        says which commands have more than one name
      muddle help vcs [name]     name the supported version control systems,
                                 or give details about one in particular
      muddle help environment    list the environment variables muddle defines
                                 for use in muddle Makefiles

    <switch> may be::

        -p[ager] <pager>    to specify a pager through which the help will be piped.
                            The default is $PAGER (if set) or else 'more'.
        -nop[ager]          don't use a pager, just print the help out.
    """

    command_line_help = """\
Usage:

  muddle [<options>] <command> [<arg> ...]

Available <options> are:

  --help, -h, -?      This help text
  --tree <dir>        Use the muddle build tree at <dir>.
  --just-print, -n    Just print what muddle would have done. For commands that
                      'do something', just print out the labels for which that
                      action would be performed. For commands that "enquire"
                      (or "find out") something, this switch is ignored.
   --version          Show the version of muddle and the directory it is
                      being run from. Note that this uses git to interrogate
                      the .git/ directory in the muddle source directory.

Muddle always starts by looking for a build tree, signified by the presence of
a .muddle directory. If you give --tree, then it will look in the directory
given, otherwise, it will traverse directories from the current directory up
to the root.
"""

    help_label_summary = """\
More complete documentation on labels is available in the muddle documentation
at http://muddle.readthedocs.org/. Information on the label class itself can
be obtained with "muddle doc depend.Label". This is a summary.

(Nearly) everything in muddle is described by a label. A label looks like:

    <type>:<name>{<role>}/<tag>

All label components are made up of the characters [A-Z0-9a-z-_].
<name>, <role> and <tag> may also be '*' (a wildcard), meaning all values.
A <name> may not start with an underscore.

  (If your build tree contains *subdomains* then there is another label
  component - see "help subdomains" for more information if you need it.)

<type> is one of checkout, package or deployment.

* A checkout is checked out of version control. It lives (somewhere) under
 'src/'.
* A package is built (under 'obj/<name>/<role>') and installed (under
  'install/<role>).
* A deployment is deployed (ready for putting onto the target), and is found
  under 'deploy/<name>'.

Labels of type checkout and deployment do not use roles. Package labels
always need a role (although muddle will sometimes try to guess one for you).

* For checkouts, <tag> is typically 'checked_out', meaning the checkout has
  been checked out (cloned, branched, etc.). A checkout will be in a directory
  under the src/ directory, with the directory name given by the <name> from
  the checkout label.

* For packages, <tag> is typically one of 'preconfig', 'configured', 'built',
  'installed' or 'postinstalled'.

  - preconfig - preconfiguration checks have been made on the package
  - configured - the package has been configured. The 'config' target in its
    muddle Makefile has been run. This may have involved running GNU
    autotools './configure', and perhaps copying source code if the checkout
    does not support building out-of-tree.
  - built - the package has been built (e.g., compiled and linked). The 'all'
    target in its muddle Makefile has been run. The results of building end up
    in directory obj/<package-name>/<role>
  - installed - the package has been installed. The 'install' target in its
    muddle Makefile has been run. All packages in a particular <role> install
    their results to somewhere in install/<role>
  - postinstalled - the package has been postinstalled. This is often an empty
    step.

* For deployments, <tag> is typically 'deployed', meaning a deployment has been
  created. This normally involves collecting files from particular
  install/<role> directories, and placing the result in
  deploy/<deployment-name>.

Some muddle commands only operate on particular types of label. For instance,
commands in category "checkout" (see "muddle help categories") only operate
on checkout: labels.
"""

    help_label_fragments = """\
Label fragments
---------------
Typing all of a label on the command line can be onerous. Muddle thus allows
appropriate fragments of a label to be used, according to the particular
command. In general, the aim is to require the label name, have a sensible
default for the label type and tag, and (for packages) try all the default
roles if none is specified.

Each command says, in its help text, if it defaults to "checkout:", "package:"
or "deployment".

Checkout and deployment labels may not have roles.

If a package role is not given, then the label will be expanded into
package:<name>{<role>} for each <role> in the default roles. Default roles
are defined in the build description. You can use "muddle query default-roles"
to find out what they are.

If a tag is not given, then the "end tag" for the particular type of label will
be used. This is:

* for checkout, '/checked_out'
* for package, '/postinstalled'
* for deployment, '/deployed'

Checkout, package and deployment commands typically ignore the label tag
of any checkout, package or deployment label they are given (whether because
you gave it exactly, or because it was deduced). Instead, they have a
requried tag, which is documented in their help text.

Other commands default to the "end tag" for that particular label type.

You can always used "muddle -n <command> <fragment>" to see what labels the
<command> will actually end up using.
"""

    help_label_absent = """\
"muddle" with no label arguments
--------------------------------
Muddle tries quite hard to do the sensible thing if you type it without any
arguments, depending on the current directory. Specifically, for commands
that "build" a label (whether checkout, package or deployment):

* at the very top of the build tree:

    muddle buildlabel _default_deployments _default_roles

* within a 'src/' directory, or within a non-checkout subdirectory inside
  'src'/,  "muddle build" for each checkout that is below the current
  directory (i.e., build all packages using the checkouts below the
  current directory).
* within a checkout directory, "muddle build" for the package(s) that use
  that checkout.
* within an 'obj/' directory, no defined action
* within an 'obj/<package>' directory, "muddle rebuild" for the named
  <package> in each of the default roles.
* within an 'obj/<package>/<role>' directory (or one of its subdirectories),
  "muddle rebuild package:<package>{<role>}".
* within an 'install/' directory, no defined action.
* within an 'install/<role>' directory (or one of its subdirectories),
  "muddle rebuild package:*{<role>}".
* within a 'deploy/' directory, no defined action.
* within a 'deploy/<deployment>' directory, "muddle redeploy <deployment>"
  (note, "redeploy" rather than "deploy", as this seems more likely to be
  useful).

If you have subdomains (see "muddle help subdomains"), then:

* within a 'domains/' directory, "muddle buildlabel" with arguments
  "deployment:(<domain>)*/deployed" and "package:(<domain>)*{*}/postinstalled"
  for each <domain> that has a directory (directly within) that 'domains/'
  directory.
* within a 'domains/<domain>' directory, "muddle buildlabel" with arguments
  "deployment:(<domain>)*/deployed" and "package:(<domain>)*{*}/postinstalled".

where <domain> is replaced by the subdomain's name (as given by "muddle where"
in that directory).

Anywhere else, "muddle" will say "Not sure what you want to build".

"muddle <command>" with no label arguments
------------------------------------------
Again, muddle tries to decide what to do based on the current directory.

For any command that "builds" a label (whether checkout, package or
deployment):

* if "muddle where" gives a label, then that label will be used as the
  argument.
* if the current directory is within 'src/', then all the checkouts below
  the current directory will be found, and a checkout: label constructed
  for each, and those will be used as the arguments.

Otherwise, muddle will say "Not sure what you want to build".
"""

    help_label_wrong = """\
How "muddle" commands intepret labels of the "wrong" type
---------------------------------------------------------
Most muddle commands that want label arguments actually want labels of a
particular type. For instance, "muddle checkout" wants to operate on one
or more checkout: labels.

Sometimes, however, it is more convenient to specify a label of a different
type. For instance: "muddle checkout package:fred", to checkout the checkouts
needed by package "fred".

Labels of particular types are interpreted as follows:

* in a checkout command:

  - checkout: -> itself
  - package: -> all the checkouts used *directly* by this package
  - deployment: -> all the checkouts needed by this deployment
    (this can be a bit slow to calculate)

* in a package command:

  - checkout: -> the packages that depend directly upon this checkout
    (i.e., those that are "built" from it), but only if they are in one
    of the default roles.
  - package: -> itself
  - deployment: -> all the packages used *directly* by this deployment

* in a deployment command

  - checkout: -> any deployments that depend upon this checkout (at any depth)
  - package: -> any deployments that depend upon this package (at any depth)
  - deployment: -> itself
"""

    help_label_all_and_friends = """\
_all and friends
----------------
There are some special command line arguments that represent a set of labels.

* _all represents all target labels of the appropriate type for the command.
  For example, in "muddle checkout _all" it expands to all "checkout:" labels.
* _all_checkouts, _all_packages and _all_deployments repesent all labels of
  the appropriate type.
* _default_roles represents package labels for all of the default roles, as
  given in the build description. Specifically, package:*{<role>}/postinstalled
  for each such <role>. You can find out what the default roles are with
  "muddle query default-roles".
* _default_deployments represents deployment labels for each of the default
  deployments, as given in the build description. You can find out what the
  default deployments are with "muddle query default-deployments".
* _just_pulled represents the checkouts that were (actually) pulled by the
  last "muddle pull" or "muddle merge" command.
* _release represents the labels to be built for a release build, as set
  in the build description with "builder.add_to_release_build".

The help for particular commands will indicate if these values can be used,
but they are generally valid for all commands that "build" checkout, package
or deployment labels. As normal, you can use "muddle -n <command> _xxx" to
see exactly what labels the "_xxx" value would expand to.
"""

    help_label_star = """\
Unexpected results
------------------
Note: at a Unix shell, typing:

    $ muddle build *

is unlikely to give the required result. The shell will expand the "*" to the
contents of the current directory, and if at top level of the built tree,
muddle will then typically complain that there is no package called 'deploy'.
Instead, escape the "*", for instance:

    $ muddle build '*'
"""

    subdomains_help = """\
Your build contains subdomains if "muddle query domains" prints out subdomain
names. In this case, you will also have a top-level 'domains/' directory, and
the top-level build description will contain calls to 'include_domain()'.

In builds with subdomains, labels in the top-level build still look like:

    <type>:<name>{<role>}/<tag>

but labels from the subdomains will contain their domain name:

    <type>:(<domain>)<name>{<role>}/<tag>

For instance:

    * package:busybox{x86}/installed is in the toplevel build
    * package:(webkit)webkit{x86}/installed is in the 'webkit' subdomain
    * package:(webkit(x11))xfonts{x11}/installed is in the 'x11' subdomain,
      which in turn is a subdomain of 'webkit'.

Note that when typing labels containing domain names within Bash, it wil
be necessary to quote the whole label, otherwise Bash will try to interpret
the parentheses. So, for instance, use:

    $ muddle build '(x11)xfonts{x11}'
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        self.print_help(args)

    def without_build_tree(self, muddle_binary, current_dir, args):
        self.print_help(args)

    def print_help(self, args):
        pager = os.environ.get('PAGER', 'more')
        if args:
            if args[0] in ('-p', '-pager'):
                pager = args[1]
                args = args[2:]
            elif args[0] in ('-nop', '-nopager'):
                pager = None
                args = args[1:]

        help_text = self.get_help(args)
        try:
            utils.page_text(pager, help_text)
        except IOError: # For instance, a pipe error due to "q" at the prompt
            pass

    def get_help(self, args):
        """Return help for args, or a summary of all commands.
        """
        if not args:
            return self.help_summary()

        if args[0] == "_all":
            return self.help_all()   # and ignore the rest of the command line

        if args[0] == "aliases":
            return self.help_aliases()

        if args[0] == "categories":
            return self.help_categories()

        if args[0] in ("label", "labels"):
            return self.help_labels(args[1:])

        if args[0] == "subdomains":
            return self.help_subdomains()

        if args[0] == "commands":
            return self.help_command_list()

        if args[0] == "vcs":
            return self.help_vcs(args[1:])

        if args[0] == "environment":
            return self.help_environment(args[1:])

        if len(args) == 1:
            cmd = args[0]
            try:
                v = g_command_dict[cmd]
                if v is None:
                    keys = g_subcommand_dict[cmd].keys()
                    keys.sort()
                    keys_text = ", ".join(keys)
                    return utils.wrap("Subcommands of '%s' are: %s"%(cmd,keys_text),
                                      # I'd like to do this, but it's not in Python 2.6.5
                                      #break_on_hyphens=False,
                                      subsequent_indent='              ')
                else:
                    return "%s\n%s"%(cmd, v().help())
            except KeyError:
                return "There is no muddle command '%s'"%cmd
        elif len(args) == 2:
            cmd = args[0]
            subcmd = args[1]
            try:
                sub_dict = g_subcommand_dict[cmd]
            except KeyError:
                if cmd in g_command_dict:
                    return "Muddle command '%s' does not take a subcommand"%cmd
                else:
                    return "There is no muddle command '%s %s'"%(cmd, subcmd)

            if subcmd == "_all":
                return self.help_subcmd_all(cmd, sub_dict)

            try:
                v = sub_dict[subcmd]
                return "%s %s\n%s"%(cmd, subcmd, v().help())
            except KeyError:
                return "There is no muddle command '%s %s'"%(cmd, subcmd)
        else:
            return "There is no muddle command '%s'"%' '.join(args)
        result_array = []
        for cmd in args:
            try:
                v = g_command_dict[cmd]
                result_array.append("%s\n%s"%(cmd, v().help()))
            except KeyError:
                result_array.append("There is no muddle command '%s'\n"%cmd)

        return "\n".join(result_array)

    def help_summary(self):
        """
        Return a summary of usage and a list of all commands
        """
        result_array = []
        result_array.append(textwrap.dedent(Help.command_line_help))
        result_array.append(textwrap.dedent(Help.__doc__))
        result_array.append("\n")

        result_array.append(self.help_command_list())

        return "".join(result_array)

    def help_command_list(self):
        """Return a list of the top-level commands.
        """
        # Use the entire set of command names, including any aliases
        keys = g_command_dict.keys()
        keys.sort()
        keys_text = ", ".join(keys)

        result_array = []
        result_array.append(utils.wrap('Commands are: %s'%keys_text,
                                       # I'd like to do this, but it's not in Python 2.6.5
                                       #break_on_hyphens=False,
                                       subsequent_indent='              '))

        # XXX Temporarily
        result_array.append("\n\n"+utils.wrap('Please note that "muddle pull" is '
            'preferred to "muddle fetch" and "muddle update", which are deprecated.'))
        # XXX Temporarily

        return "".join(result_array)

    def help_categories(self):
        result_array = []
        result_array.append("Commands by category:\n")

        categories_dict = g_command_categories
        categories_list = g_command_categories_in_order

        maxlen = len(max(categories_list, key=len)) +1  # +1 for a colon
        indent = ' '*(maxlen+3)

        for name in categories_list:
            cmd_list = list(categories_dict[name])
            cmd_list.sort()
            line = "  %-*s %s"%(maxlen, '%s:'%name, ' '.join(cmd_list))
            result_array.append(utils.wrap(line, subsequent_indent=indent))

        return "\n".join(result_array)

    def help_labels(self, args):
        """
        Help on labels within muddle.

        "muddle help label" and "muddle help labels" are equivalent.

        help label            - show this text
        help label summary    - a summary of how labels work
        help label fragments  - using partial labels in commands
        help label fragment   - the same
        help label absent     - what "muddle" or "muddle <cmd>" does with no label
                                arguments
        help label wrong      - what "muddle <cmd>" does with a label of the "wrong"
                                type (e.g., "muddle build checkout:something")
        help label _all
        help label <any name starting with underscore>
                              - these explain the "special" command line arguments
        help label star       - the unexpected result of "muddle build *" and its like
        help label everything - all the "muddle help label" subtopics
        """
        if args and len(args) > 1:
            raise GiveUp('"muddle help label" only takes one argument.')

        if not args:
            return textwrap.dedent(Help.help_labels.__doc__)

        subtopic = args[0]
        if subtopic == "summary":
            help_text = Help.help_label_summary
        elif subtopic in ("fragment", "fragments"):
            help_text = Help.help_label_fragments
        elif subtopic == "absent":
            help_text = Help.help_label_absent
        elif subtopic == "wrong":
            help_text = Help.help_label_wrong
        elif subtopic[0] == "_":
            help_text = Help.help_label_all_and_friends
        elif subtopic == "star":
            help_text = Help.help_label_star
        elif subtopic == "everything":
            parts = []
            parts.append(Help.help_label_summary)
            parts.append(Help.help_label_fragments)
            parts.append(Help.help_label_absent)
            parts.append(Help.help_label_wrong)
            parts.append(Help.help_label_all_and_friends)
            parts.append(Help.help_label_star)
            help_text = '\n'.join(parts)
        else:
            raise GiveUp('Unrecognised help label subtopic "%s" -'
                         ' see "muddle help label"'%subtopic)

        return textwrap.dedent(help_text)

    def help_subdomains(self):
        """
        Return help on how to use subdomains
        """
        return textwrap.dedent(Help.subdomains_help)

    def help_vcs(self, args):
        """
        Return help on supported VCS
        """
        if args:
            if len(args) != 1:
                raise GiveUp("'muddle help vcs' takes zero or one arguments")
            vcs = args[0]
            return version_control.get_vcs_docs(vcs)
        else:
            str_list = [ ]
            str_list.append("Available version control systems:\n\n")
            str_list.append(version_control.list_registered(indent='  '))
            str_list.append('\nUse "help vcs <name>" for more information on VCS <name>')
            return "".join(str_list)

    def help_environment(self, args):
        """
        Return help on MUDDLE_xxx environment variables
        """
        text = mechanics.Builder.set_default_variables.__doc__
        text = textwrap.dedent(text)
        text = text.replace("``", "'")
        return ('Muddle environment variables\n'
                '============================\n'
                '%s'%text)

    def help_all(self):
        """
        Return help for all commands
        """
        result_array = []
        result_array.append("Commands:\n")

        cmd_list = []

        # First, all the main command names (without any aliases)
        for name in g_command_names:
            v = g_command_dict[name]
            cmd_list.append((name, v()))

        # Then, all the subcommands (ditto)
        for main, sub in g_subcommand_names:
            v = g_subcommand_dict[main][sub]
            cmd_list.append(('%s %s'%(main, sub), v()))

        cmd_list.sort()

        for name, obj in cmd_list:
            result_array.append("%s\n%s"%(name, v().help()))

        return "\n".join(result_array)

    def help_subcmd_all(self, cmd_name, sub_dict):
        """
        Return help for all commands in this dictionary
        """
        result_array = []
        result_array.append("Subcommands for '%s' are:\n"%cmd_name)

        keys = sub_dict.keys()
        keys.sort()

        for name in keys:
            v = sub_dict[name]
            result_array.append('%s\n%s'%(name, v().help()))

        return "\n".join(result_array)

    def help_aliases(self):
        """
        Return a list of all commands with aliases
        """
        result_array = []
        result_array.append("Commands aliases are:\n")

        aliases = g_command_aliases

        keys = aliases.keys()
        keys.sort()

        for alias in keys:
            result_array.append("  %-10s  %s"%(alias, aliases[alias]))

        aliases = g_subcommand_aliases
        if aliases:
            result_array.append("\nSubcommand aliases are:\n")

            main_keys = aliases.keys()
            main_keys.sort()
            for cmd in main_keys:
                sub_keys = aliases[cmd].keys()
                sub_keys.sort()
                for alias in sub_keys:
                    result_array.append("  %-20s %s"%("%s %s"%(cmd, alias),
                                                            "%s %s"%(cmd, aliases[cmd][alias])))

        return "\n".join(result_array)

# -----------------------------------------------------------------------------
# Init commands
# -----------------------------------------------------------------------------
@command('init', CAT_INIT)
class Init(Command):
    """
    :Syntax: muddle init <repository> <build_description>
    :or:     muddle init -b[ranch] <branch_name> <repository> <build_description>

    Initialise a new build tree with a given repository and build description.
    We check out the build description but don't actually build anything.
    It is traditional to create a new muddle build tree in an empty directory.

    For instance::

      $ mkdir project32
      $ cd project32
      $ muddle init  git+file:///somewhere/else/examples/d  builds/01.py

    This initialises a muddle build tree, creating two new directories:

    * '.muddle/', which contains the build tree state, and
    * 'src/', which contains the build description in 'src/builds/01.py'
      (complex build desscriptions may use multiple Python files, and so
      other files may have been checked out into 'src/builds/')

    You haven't told muddle which actual repository the build description is in
    - you've only told it where the repository root is and where the build
    description file is. Muddle assumes that <repository>
    "git+file:///somewhere/else/examples/d" and <build_description>
    "builds/01.py" means repository "git+file:///somewhere/else/examples/d/builds"
    and file "01.py" therein.

    If the -branch switch is given, then the named branch of the build
    description will be checked out. It thus an error if either the muddle
    support for the build description VCS does not support this (at the moment,
    that probably means "not git"), or if there is no such branch.

    Note: if you find yourself trying to "muddle init" a subdomain, don't.
    Instead, add the subdomain to the current build description (using a call
    of 'include_domain()'), and it will automatically get checked out during
    the "muddle init" of the top-level build. Or see "muddle bootstrap -subdomain".
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        raise GiveUp("Can't initialise a build tree "
                    "when one already exists (%s)"%builder.db.root_path)

    def without_build_tree(self, muddle_binary, current_dir, args):
        """
        Initialise a build tree.
        """

        # The Commands class switch mechanism doesn't handle switches with
        # arguments, which is a pity, as it means we have to do our -branch
        # switch by hand...
        branch_name = None

        if len(args) != 2 and len(args) != 4:
            raise GiveUp(self.__doc__)

        if len(args) == 4:
            if args[0] not in ('-b', '-branch'):
                raise GiveUp(self.__doc__)
            else:
                branch_name = args[1]
                args = args[2:]

        repo = args[0]
        build = args[1]

        print "Initialising build tree in %s "%current_dir
        print "Repository: %s"%repo
        print "Build description: %s"%build

        if branch_name:
            print "Build description branch: %s"%branch_name

        if self.no_op():
            return

        db = Database(current_dir)
        db.setup(repo, build, branch=branch_name)

        print
        print "Loading build description .. \n"
        builder = mechanics.load_builder(current_dir, muddle_binary)

        # If our top level build description wants things to follow its
        # branch, and there are subdomains, we need to adjust the subdomain
        # branches. Why? Well, if the "builder.follow_build_desc_branch=True"
        # occurs *after* any of the "include_domain" calls, then the relevant
        # subdomain could not have known it was meant to be following the
        # top-level build description, so we can only guarantee to sort this
        # out after the build description is "finished".
        if builder.follow_build_desc_branch:
            subdomain_build_descs = []
            for domain in sort_domains(builder.all_domains()):
                if domain == "":    # Nothing to do for the top-level
                    continue
                build_desc = builder.db.get_domain_build_desc_label(domain)
                subdomain_build_descs.append(build_desc)
            if subdomain_build_descs:
                print 'Making subdomain build descriptions "follow" top-level build description'
                print 'for', label_list_to_string(subdomain_build_descs)
                sync = Sync()
                sync.with_build_tree(builder, current_dir, map(str, subdomain_build_descs))

        print "Done.\n"


@command('bootstrap', CAT_INIT)
class Bootstrap(Command):
    """
    :Syntax: muddle bootstrap [-subdomain] <repo> <build_name>

    Create a new build tree, from scratch, in the current directory.
    The current directory should ideally be empty.

    * <repo> should be the root URL for the repository which you will be using
      as the default remote location. It is assumed that it will contain a
      'builds' and a 'versions' repository/subdirectory/whatever (this depends
      a bit on version control system being used).

      <repo> should be the same value that you would give to the 'init'
      command, if that was being used instead.

    * <build_name> is the name for the build. This should be a simple string,
      usable as a filename. It is strongly recommended that it contain only
      alphanumerics, underline, hyphen and dot (or period). Ideally it should
      be a meaningful (but not too long) description of the build.

    For instance::

      $ cd project33
      $ muddle bootstrap git+http://example.com/fred/ build-27

    You will end up with a build tree of the form::

      .muddle/
          RootRepository      -- containing "git+http://example/com/fred/"
          Description         -- containing "builds/01.py"
          VersionsRepository  -- containing "git+http://example/com/fred/versions/"
      src/
          builds/
              .git/           -- assuming "http://example/com/fred/builds/"
              01.py           -- wth a bare minimum of content
      versions/
              .git/           -- assuming "http://example/com/fred/versions/"

    Note that 'src/builds/01.py' will have been *added* to the VCS (locally),
    but will not have been committed (this may change in a future release).

    Also, muddle cannot currently set up VCS support for Subversion in the
    subdirectories.

    If you try to do this in a directory that is itself within an existing
    build tree (i.e., there's a parent directory somewhere with a ``.muddle``
    directory), then it will normally fail because you are trying to create a
    build within an existing build. If you are actually doing this because you
    are bootstrapping a subdomain, then specify the ``-subdomain`` switch.

    Note that this command will never bootstrap a new build tree in the same
    directory as an existing ``.muddle`` directory.
    """

    def requires_build_tree(self):
        return False

    def allowed_in_release_build(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        if args[0] != '-subdomain':
            raise GiveUp("Can't bootstrap a build tree when one already"
                               " exists (%s)\nTry using '-bootstrap' if you"
                               " want to bootstrap a subdomain"%builder.db.root_path)
        args = args[1:]

        if os.path.exists('.muddle'):
            raise GiveUp("Even with '-subdomain', can't bootstrap a build"
                               " tree in the same directory as an existing"
                               " tree (found .muddle)")

        self.bootstrap(current_dir, args)

    def without_build_tree(self, muddle_binary, current_dir, args):
        """
        Bootstrap a build tree.
        """

        if args and args[0] == '-subdomain':
            print 'You are not currently within a build tree. "-subdomain" ignored'
            args = args[1:]

        self.bootstrap(current_dir, args)

    def bootstrap(self, root_path, args):
        if len(args) != 2:
            raise GiveUp(self.__doc__)

        repo = args[0]
        build_name = args[1]

        mechanics.check_build_name(build_name)

        build_desc_filename = "01.py"
        build_desc = "builds/%s"%build_desc_filename
        build_dir = os.path.join("src","builds")

        print "Bootstrapping build tree in %s "%root_path
        print "Repository: %s"%repo
        print "Build description: %s"%build_desc

        if self.no_op():
            return

        print
        print "Setting up database"
        db = Database(root_path)
        db.setup(repo, build_desc, versions_repo=os.path.join(repo,"versions"))

        print "Setting up build description"
        build_desc_text = '''\
                             #! /usr/bin/env python
                             """Muddle build description for {name}
                             """

                             def describe_to(builder):
                                 builder.build_name = '{name}'

                             def release_from(builder, release_dir):
                                 pass
                             '''.format(name=build_name)
        with NewDirectory(build_dir):
            with open(build_desc_filename, "w") as fd:
                fd.write(textwrap.dedent(build_desc_text))

            # TODO: (a) do this properly and (b) do it for other VCS as necessary
            vcs_name, just_url = version_control.split_vcs_url(repo)
            if vcs_name == 'git':
                print 'Hack for git: ignore .pyc files in src/builds'
                with open('.gitignore', "w") as fd:
                    fd.write('*.pyc\n')

            if vcs_name != 'svn':
                print 'Adding build description to VCS'
                version_control.vcs_init_directory(vcs_name, ["01.py"])
                if vcs_name == 'git':
                    version_control.vcs_init_directory(vcs_name, [".gitignore"])

        print 'Telling muddle the build description is checked out'
        build_desc_label = Label.from_string('checkout:builds/checked_out')
        db.set_tag(build_desc_label)

        # Now let's actually load the build description
        print 'Loading it'
        builder = mechanics.load_builder(root_path, None)

        # And we can make sure that the build description is correctly
        # associated with its remote repository
        vcs_handler = builder.db.get_checkout_vcs(build_desc_label)
        vcs_handler.reparent(builder, build_desc_label)

        print 'Setting up versions directory'
        with NewDirectory("versions"):
            # We shan't try to do anything more (than create the directory) for
            # subversion, firstly because the versions repository is not (yet)
            # defined (because we're using SVN), and secondly because it may
            # mean doing an import, or somesuch, which we don't have a
            # "general" mechanism for.
            if vcs_name != 'svn':
                print 'Adding versions directory to VCS'
                version_control.vcs_init_directory(vcs_name)

        print "Done.\n"

# -----------------------------------------------------------------------------
# Proper query commands (not help)
# -----------------------------------------------------------------------------
class QueryCommand(Command):
    """
    The base class for 'query' commands
    """

    def requires_build_tree(self):
        return True

    def get_label_from_fragment(self, builder, args, default_type=LabelType.Package):
        if len(args) != 1:
            raise GiveUp("Command '%s' needs a (single) label"%(self.cmd_name))

        label = Label.from_fragment(args[0], default_type=default_type)

        if label.type == LabelType.Package and not label.role:
            raise GiveUp('A package label needs a role, not just %s'%label)

        return builder.apply_unifications(label)

    def get_label(self, builder, args):
        if len(args) != 1:
            raise GiveUp("Command '%s' needs a (single) label"%(self.cmd_name))

        try:
            label = Label.from_string(args[0])
        except GiveUp as exc:
            raise GiveUp("%s\nIt should contain at least <type>:<name>/<tag>"%exc)

        return builder.apply_unifications(label)

@subcommand('query', 'dependencies', CAT_QUERY, ['depend', 'depends'])
class QueryDepend(QueryCommand):
    """
    :Syntax: muddle query dependencies <what>
    :or:     muddle query dependencies <what> <label>

    Print the current dependency sets.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.

    If no label is given, then all dependencies in the current build tree will
    be shown.

    In order to show all dependency sets, even those where a given label does
    not actually depend on anything, <what> can be:

    * system       - Print synthetic dependencies produced by the system
    * user         - Print dependencies entered by the build description
    * all          - Print all dependencies

    To show only those dependencies where there *is* a dependency, add '-short'
    (or '_short') to <what>, i.e.:

    * system-short - Print synthetic dependencies produced by the system
    * user-short   - Print dependencies entered by the build description
    * all-short    - Print all dependencies
    """

    def with_build_tree(self, builder, current_dir, args):
        if len(args) != 1 and len(args) != 2:
            print "Syntax: muddle query dependencies [system|user|all][-short] [<label>]"
            print self.__doc__
            return

        type = args[0]
        if len(args) == 2:
            # We don't just call self.get_label_from_fragment() because we
            # don't want to apply unifications
            label = Label.from_fragment(args[1], default_type=LabelType.Package)
            if label.type == LabelType.Package and not label.role:
                raise GiveUp('A package label needs a role, not just %s'%label)
        else:
            label = None

        show_sys = False
        show_user = False

        if type.endswith("-short") or type.endswith("_short"):
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
            raise GiveUp("Bad dependency type: %s\n%s"%(type, self.__doc__))

        if label:
            print 'Dependencies for %s'%label
        else:
            print 'All dependencies'
        print builder.ruleset.to_string(matchLabel = label,
                                                   showSystem = show_sys, showUser = show_user,
                                                   ignore_empty = ignore_empty)

@subcommand('query', 'distributions', CAT_QUERY)
class QueryDistributions(QueryCommand):
    """
    :Syntax: muddle query distributions

    List the names of the distributions defined by the build description,
    and the license categories that each distributes.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        all_names = get_distribution_names()
        used_names = get_used_distribution_names(builder)
        maxlen = len(max(all_names, key=len))
        print 'Distributions are:'
        for name in sorted(all_names):
            print '  %s %-*s  (%s)'%('*' if name in used_names else ' ',
                                     maxlen, name,
                                     ', '.join(the_distributions[name]))
        print '(those marked with a "*" have content set by this build)'

    def without_build_tree(self, muddle_binary, current_dir, args):
        names = get_distribution_names()
        print 'Standard distributions are:\n'
        maxlen = len(max(names, key=len))
        for name in sorted(names):
            print '  %-*s  (%s)'%(maxlen, name,
                                  ', '.join(the_distributions[name]))

@subcommand('query', 'vcs', CAT_QUERY)
class QueryVCS(QueryCommand):
    """
    :Syntax: muddle query vcs

    List the version control systems supported by this version of muddle,
    together with their VCS specifiers.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        self.do_command()

    def without_build_tree(self, muddle_binary, current_dir, args):
        self.do_command()

    def do_command(self):
        str_list = [ ]
        str_list.append("Available version control systems:\n\n")
        str_list.append(version_control.list_registered(indent='  '))

        str = "".join(str_list)
        print str
        return 0

@subcommand('query', 'checkouts', CAT_QUERY)
class QueryCheckouts(QueryCommand):
    """
    :Syntax: muddle query checkouts [-j]

    Print the names of all the checkouts described in the build description.

    With '-j', print them all on one line, separated by spaces.
    """

    allowed_switches = {'-j':'join'}

    def with_build_tree(self, builder, current_dir, args):
        args = self.remove_switches(args, allowed_more=False)

        joined = ('join' in self.switches)

        cos = builder.all_checkout_labels(LabelTag.CheckedOut)
        a_list = list(cos)
        a_list.sort()
        out_list = []
        for lbl in a_list:
            if lbl.domain:
                out_list.append('(%s)%s'%(lbl.domain,lbl.name))
            else:
                out_list.append(lbl.name)
        if joined:
            print '%s'%" ".join(out_list)
        else:
            print '%s'%"\n".join(out_list)

@subcommand('query', 'checkout-dirs', CAT_QUERY)
class QueryCheckoutDirs(QueryCommand):
    """
    :Syntax: muddle query checkout-dirs

    Print the known checkouts and their checkout paths (relative to 'src/')
    """

    def with_build_tree(self, builder, current_dir, args):
        builder.db.dump_checkout_paths()

@subcommand('query', 'upstream-repos', CAT_QUERY)
class QueryUpstreamRepos(QueryCommand):
    """
    :Syntax: muddle query upstream-repos [-u[rl]] [<co_label>]

    Print information about upstream repositories.

    If <co_label> is given then it should be a checkout label or label fragment
    (see "muddle help labels").

    If a label or labels are given, then the repositories, and any upstream
    repositories, for those labels are reported. Otherwise, those
    repositories that have upstream repositories are reported.

    With '-u' or '-url', print repository URLs. Otherwise, print the
    full spec of each Repository instance.

    XXX Examples to be provided
    """

    allowed_switches = {'-u':'url', '-url':'url'}

    def with_build_tree(self, builder, current_dir, args):
        if len(args) not in (0, 1, 2):
            print "Syntax: muddle query upstream-repos [-u[rl]] [<label>]"
            print self.__doc__
            return

        args = self.remove_switches(args, allowed_more=True)
        just_url = ('url' in self.switches)

        if args:
            co_label = self.get_label_from_fragment(builder, args,
                                                    default_type=LabelType.Checkout)
            if co_label.type != LabelType.Checkout:
                raise GiveUp('"muddle query upstream-repos" takes a checkout:'
                             ' label as argument, not %s'%co_label)

            orig_repo = builder.db.get_checkout_repo(co_label)
            builder.db.print_upstream_repo_info(orig_repo, [co_label], just_url)
        else:
            # Report on all the upstream repositories
            builder.db.dump_upstream_repos(just_url=just_url)

@subcommand('query', 'checkout-repos', CAT_QUERY)
class QueryCheckoutRepos(QueryCommand):
    """
    :Syntax: muddle query checkout-repos [-u[rl]]

    Print the known checkouts and their checkout repositories

    With '-u' or '-url', print the repository URL. Otherwise, print the
    full spec of the Repository instance that represents the repository.

    So, for instance, the standard printout produces lines of the form::

        checkout:kernel/* -> Repository('git', 'ssh://git@server/project99/src', 'kernel', prefix='linuxbase', branch='linux-3.2.0')

    but with '-u' one would instead see::

        checkout:kernel/* -> ssh://git@server/project99/src/linuxbase/kernel
    """

    allowed_switches = {'-u':'url', '-url':'url'}

    def with_build_tree(self, builder, current_dir, args):
        args = self.remove_switches(args, allowed_more=False)

        just_url = ('url' in self.switches)
        builder.db.dump_checkout_repos(just_url=just_url)

@subcommand('query', 'checkout-branches', CAT_QUERY)
class QueryCheckoutBranches(QueryCommand):
    """
    :Syntax: muddle query checkout-branches

    Print the known checkouts and their branches.

    For each checkout, reports its current branch, and the branch implied (or
    explicitly requested) by the build description, and the branch it is
    "following" (if the build description has set this).

    For instance::

        --------  --------------  ---------------  ----------------
        Checkout  Current branch  Original branch  Branch to follow
        --------  --------------  ---------------  ----------------
        builds    master          <none>           <not following>
        co1       master          <none>           <not following>
        co2       <can't tell>    <none>           <not following>

    In this example, both checkouts are in git (which is the only VCS for which
    muddle really supports branches), and on master.

    The "original branches" are both <none>. The "builds" checkout contains the
    build description, and its original checkout is <none> because "muddle
    init" did not specify a branch. The original checkouts for "co1" and "co2"
    are <none> because the build description did not specify explicit branches
    for them. We can't tell what the current branch is for co2, which normally
    means that it has not yet been checked out.

    Since the build description does not set "builder.follow_desc_build_branch
    = True", all the checkouts show as <not following>.

    Here is a slightly more complicated case::

        --------  --------------   ---------------  ----------------
        Checkout  Current branch   Original branch  Branch to follow
        --------  --------------   ---------------  ----------------
        builds    test-v0.1        branch0          <it's own>
        co1       test-v0.1        <none>           test-v0.1
        co2       branch1          branch1          <none>
        co3       <none>           <none>           <none>
        co4       <none>           branch1          <none>
        co5       <not supported>  ...              <not following>

    This build tree was created using "muddle init -branch branch0", so the
    builds checkout shows "branch0" as its original branch. We can tell that
    the build description *does* have "builder.follow_desc_build_branch = True"
    because there are values in the "Branch to follow" column. The build
    description always follows itself.

    "co1" doesn't specify a particular branch in the build description,
    so its "original branch" is <none>. However, it does follow the build
    description, so has "test-v0.1" in the "Branch to follow" column.

    "co2" explicitly specifies "branch1" in the build description. It got
    checked out on "branch1", and is still on it. Having an explicit branch
    means it does not follow the build description.

    "co3" explicitly specified a *revision" in the build description. This
    means that it got checked out on a detached HEAD, and thus its current
    branch is <none> - it really isn't on a branch.

    "co4" explicitly specified a branch ("branch1") and a revision in the
    build description. The revision id specified didn't correspond to HEAD
    of the branch, so it too is on a detached HEAD. However, "branch1" still
    shows up as its original branch.

    Finally, "co5" is not using git (it was actually using bzr), and thus
    muddle does not support branching it. However, it has set the "no_follow"
    VCS option in the build description, and thus the "Branch to follow"
    column shows as "<not following>" instead of "...".

    (You can use "muddle query checkout-vcs" to see which VCS is being used
    for which checkout.)
    """

    def with_build_tree(self, builder, current_dir, args):

        def co_name(co):
            if co.domain:
                return '(%s)%s'%(co.domain, co.name)
            else:
                return co.name

        labels = sorted(builder.all_checkout_labels())
        column_headers = ('Checkout', 'Current branch', 'Original branch', 'Branch to follow')
        maxlen = []
        for ii, heading in enumerate(column_headers):
            maxlen.append(len(heading))

        for co_label in labels:
            l = len(co_name(co_label))
            if l > maxlen[0]:
                maxlen[0] = l

        lines = []
        for co_label in labels:
            co_data = builder.db.get_checkout_data(co_label)
            repo = co_data.repo
            vcs_handler = co_data.vcs_handler
            if vcs_handler.vcs.supports_branching():
                try:
                    actual_branch = vcs_handler.get_current_branch(builder, co_label)
                except GiveUp:
                    actual_branch = "<can't tell>"
                if actual_branch is None:
                    actual_branch = '<none>'
                original_branch = repo.branch
                if original_branch is None:
                    original_branch = '<none>'
                if builder.follow_build_desc_branch:
                    if builder.build_desc_label.match_without_tag(co_label):
                        follow_branch = "<it's own>"
                    else:
                        follow_branch = vcs_handler.branch_to_follow(builder, co_label)
                        if follow_branch is None:
                            follow_branch = '<none>'
                else:
                    follow_branch = '<not following>'
            else:
                actual_branch = '<not supported>'
                original_branch = '...'
                options = builder.db.get_checkout_vcs_options(co_label)
                if "no_follow" in options:
                    follow_branch = '<not following>'
                else:
                    follow_branch = '...'

            line = (co_name(co_label), actual_branch, original_branch, follow_branch)
            for ii, word in enumerate(line):
                if len(word) > maxlen[ii]:
                    maxlen[ii] = len(word)
            lines.append(line)

        format = '%%-%ds  %%-%ds  %%-%ds  %%-%ds'%tuple(maxlen)
        line = format%(maxlen[0]*'-', maxlen[1]*'-', maxlen[2]*'-', maxlen[3]*'-')
        print line
        print format%('Checkout', 'Current branch', 'Original branch', 'Branch to follow')
        print line
        for line in lines:
            print format%tuple(line)


@subcommand('query', 'checkout-vcs', CAT_QUERY)
class QueryCheckoutVcs(QueryCommand):
    """
    :Syntax: muddle query checkout-vcs

    Print the known checkouts and their version control systems. Also prints
    the VCS options for the checkout, if there are any.
    """

    def with_build_tree(self, builder, current_dir, args):
        builder.db.dump_checkout_vcs()

@subcommand('query', 'checkout-licenses', CAT_QUERY)
class QueryCheckoutLicenses(QueryCommand):
    """
    :Syntax: muddle query checkout-licenses

    Print information including:

    * the known checkouts and their licenses
    * which checkouts (if any) have GPL licenses of some sort
    * which checkouts are "implicitly" GPL licensed because of depending
      on a GPL-licensed checkout
    * which packages have declared that they don't actually need to be
      "implicitly" GPL
    * which checkouts have irreconcilable clashes between "implicit" GPL
      licenses and their actual license.

    Note that "irreconcilable clashes" are only important if you intend to
    distribute the clashing items to third parties.

    See also "muddle query role-licenses" for licenses applying to (packages
    in) each role.
    """

    def with_build_tree(self, builder, current_dir, args):

        builder.db.dump_checkout_licenses(just_name=False)

        not_licensed = get_not_licensed_checkouts(builder)
        if not_licensed:
            print
            print 'The following checkouts do not have a license:'
            print
            for label in sorted(not_licensed):
                print '* %s'%label

        # Hackery
        def calc_maxlen(keys):
            maxlen = 0
            for label in keys:
                length = len(str(label))
                if length > maxlen:
                    maxlen = length
            return maxlen

        maxlen = calc_maxlen(builder.db.checkout_licenses.keys())

        gpl_licensed = get_gpl_checkouts(builder)
        get_co_license = builder.db.get_checkout_license
        if gpl_licensed:
            print
            print 'The following checkouts have some sort of GPL license:'
            print
            for label in sorted(gpl_licensed):
                print '* %-*s %r'%(maxlen, label, get_co_license(label))

        if builder.db.license_not_affected_by or \
           builder.db.nothing_builds_against:
            print
            print 'Exceptions to "implicit" GPL licensing are:'
            print
            for co_label in sorted(builder.db.nothing_builds_against):
                print '* nothing builds against %s'%co_label
            for key, value in sorted(builder.db.license_not_affected_by.items()):
                print '* %s is not affected by %s'%(key,
                                    label_list_to_string(sorted(value), join_with=', '))

        implicit_gpl_licensed, because = get_implicit_gpl_checkouts(builder)
        if implicit_gpl_licensed:
            print
            print 'The following are "implicitly" GPL licensed for the given reasons:'
            print
            for label in sorted(implicit_gpl_licensed):
                license = get_co_license(label, absent_is_None=True)
                reasons = because[label]
                license = get_co_license(label, absent_is_None=True)
                print '* %s  (was %r)'%(label, license)
                #print '* %-*s (was %r)'%(maxlen, label, license)
                for reason in sorted(reasons):
                    print '  - %s'%(reason)

        bad_binary, bad_private = get_license_clashes(builder, implicit_gpl_licensed)
        if bad_binary or bad_private:
            print
            print 'This means that the following have irreconcilable clashes:'
            print
            for label in sorted(bad_binary):
                print '* %-*s %r'%(maxlen, label, get_co_license(label))
            for label in sorted(bad_private):
                print '* %-*s %r'%(maxlen, label, get_co_license(label))

@subcommand('query', 'role-licenses', CAT_QUERY)
class QueryRoleLicenses(QueryCommand):
    """
    :Syntax: muddle query role-licenses [-no-clashes]

    Print the known roles and the licenses used within them
    (i.e., by checkouts used by packages with those roles).

    If -no-clashes is given, then don't report binary/private license clashes
    (which might cause problems when doing a "_by_license" distribution).

    See also "muddle query checkout-licenses" for information on licenses
    with respect to checkouts.
    """

    allowed_switches = {'-no-clashes': 'no-clashes'}

    def with_build_tree(self, builder, current_dir, args):

        args = self.remove_switches(args, allowed_more=False)

        report_clashes = not ('no-clashes' in self.switches)

        roles = builder.all_roles()

        print 'Licenses by role:'
        print
        for role in sorted(roles):
            print '* %s'%role
            role_licenses = licenses_in_role(builder, role)
            for license in sorted(role_licenses):
                print '  - %r'%( license)

        if report_clashes:
            # Hackery
            def calc_maxlen(keys):
                maxlen = 0
                for label in keys:
                    length = len(str(label))
                    if length > maxlen:
                        maxlen = length
                return maxlen

            clashes = {}
            for role in roles:
                binary_items, private_items = get_license_clashes_in_role(builder, role)
                if binary_items and private_items:
                    # We have a clash in the licensing of the "install/" directory
                    clashes[role] = (binary_items, private_items)
            if clashes:
                print
                print 'The following roles have both "binary" and "private" licenses,'
                print 'which would cause problems with a "_by_license" distribution:'
                print
                for role, (bin, sec) in sorted(clashes.items()):
                    print '* %s, where the following licenses may cause problems:'%role
                    maxlen1 = calc_maxlen(sec)
                    maxlen2 = calc_maxlen(bin)
                    maxlen = max(maxlen1, maxlen2)
                    for key, item in sorted(bin.items()):
                        print '  - %-*s %r'%(maxlen, key, item)
                    for key, item in sorted(sec.items()):
                        print '  - %-*s %r'%(maxlen, key, item)

@subcommand('query', 'licenses', CAT_QUERY)
class QueryLicenses(QueryCommand):
    """
    :Syntax: muddle query licenses

    Print the standard licenses we know about.

    See "muddle query checkout-licenses" to find out about any licenses
    defined, and used, in the build description.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        print_standard_licenses()

    def without_build_tree(self, muddle_binary, current_dir, args):
        print_standard_licenses()

@subcommand('query', 'domains', CAT_QUERY)
class QueryDomains(QueryCommand):
    """
    :Syntax: muddle query domains [-j]

    Print the names of all the subdomains described in the build description
    (and recursively in the subdomain build descriptions).

    Note that it does not report the '' (top level) domain, as that is assumed.

    With '-j', print them all on one line, separated by spaces.
    """

    allowed_switches = {'-j':'join'}

    def with_build_tree(self, builder, current_dir, args):
        args = self.remove_switches(args, allowed_more=False)

        joined = ('join' in self.switches)

        domains = builder.all_domains()
        if '' in domains:
            domains.remove('')
        domains = sort_domains(domains)
        if joined:
            print '%s'%" ".join(domains)
        else:
            print '%s'%"\n".join(domains)

@subcommand('query', 'packages', CAT_QUERY)
class QueryPackages(QueryCommand):
    """
    :Syntax: muddle query packages [-j]

    Print the names of all the packages described in the build description.

    Note that if there is a rule for a package with a wildcarded name, like
    "package:*{x86}/*", then '*' will be included in the names printed.

    With '-j', print them all on one line, separated by spaces.
    """

    allowed_switches = {'-j':'join'}

    def with_build_tree(self, builder, current_dir, args):
        args = self.remove_switches(args)

        joined = ('join' in self.switches)

        packages = builder.all_packages()
        a_list = list(packages)
        a_list.sort()
        if joined:
            print '%s'%" ".join(a_list)
        else:
            print '%s'%"\n".join(a_list)

@subcommand('query', 'package-roles', CAT_QUERY)
class QueryPackageRoles(QueryCommand):
    """
    :Syntax: muddle query package-roles [-j]

    Print the names of all the packages, and their roles, as described in the
    build description.

    Note that if there is a rule for a package with a wildcarded name, like
    "package:*{x86}/*", then '*' will be included in the names printed.

    With '-j', print them all on one line, separated by spaces.
    """

    allowed_switches = {'-j':'join'}

    def with_build_tree(self, builder, current_dir, args):
        args = self.remove_switches(args, allowed_more=False)

        joined = ('join' in self.switches)

        packages = builder.all_packages_with_roles()
        a_list = list(packages)
        a_list.sort()
        if joined:
            print '%s'%" ".join(a_list)
        else:
            print '%s'%"\n".join(a_list)

@subcommand('query', 'deployments', CAT_QUERY)
class QueryDeployments(QueryCommand):
    """
    :Syntax: muddle query deployments [-j]

    Print the names of all the deployments described in the build description.

    With '-j', print them all on one line, separated by spaces.
    """

    allowed_switches = {'-j':'join'}

    def with_build_tree(self, builder, current_dir, args):
        args = self.remove_switches(args, allowed_more=False)

        joined = ('join' in self.switches)

        roles = builder.all_deployments()
        a_list = list(roles)
        a_list.sort()
        if joined:
            print '%s'%" ".join(a_list)
        else:
            print '%s'%"\n".join(a_list)

@subcommand('query', 'default-deployments', CAT_QUERY)
class QueryDefaultDeployments(QueryCommand):
    """
    :Syntax: muddle query default-deployments [-j]

    Print the names of the default deployments described in the build
    description (as defined using 'builder.by_default_deploy()').

    With '-j', print them all on one line, separated by spaces.
    """

    allowed_switches = {'-j':'join'}

    def with_build_tree(self, builder, current_dir, args):
        args = self.remove_switches(args, allowed_more=False)

        joined = ('join' in self.switches)

        default_deployments = builder.default_deployment_labels
        a_list = map(str, default_deployments)
        a_list.sort()
        if joined:
            print '%s'%" ".join(a_list)
        else:
            print '%s'%"\n".join(a_list)

@subcommand('query', 'roles', CAT_QUERY)
class QueryRoles(QueryCommand):
    """
    :Syntax: muddle query roles [-j]

    Print the names of all the roles described in the build description.

    With '-j', print them all on one line, separated by spaces.
    """

    allowed_switches = {'-j':'join'}

    def with_build_tree(self, builder, current_dir, args):
        args = self.remove_switches(args, allowed_more=False)

        joined = ('join' in self.switches)

        roles = builder.all_roles()
        a_list = list(roles)
        a_list.sort()
        if joined:
            print '%s'%" ".join(a_list)
        else:
            print '%s'%"\n".join(a_list)

@subcommand('query', 'default-roles', CAT_QUERY)
class QueryDefaultRoles(QueryCommand):
    """
    :Syntax: muddle query default-roles [-j]

    Print the names of the default roles described in the build
    description (as defined using 'builder.add_default_role()').

    These are the roles that will be assumed for 'package:' label fragments.

    With '-j', print them all on one line, separated by spaces.
    """

    allowed_switches = {'-j':'join'}

    def with_build_tree(self, builder, current_dir, args):
        args = self.remove_switches(args, allowed_more=False)

        joined = ('join' in self.switches)

        default_roles = list(builder.default_roles) # use a copy!
        default_roles.sort()
        if joined:
            print '%s'%" ".join(default_roles)
        else:
            print '%s'%"\n".join(default_roles)

@subcommand('query', 'root', CAT_QUERY)
class QueryRoot(QueryCommand):
    """
    :Syntax: muddle query root

    Print the root path, the path of the directory containing the '.muddle/'
    directory.

    For a build containing subdomains, this means the root directory of the
    top-level build.

    The root is where "muddle where" will print "Root of the build tree".
    """

    def with_build_tree(self, builder, current_dir, args):
        print builder.db.root_path

@subcommand('query', 'name', CAT_QUERY)
class QueryName(QueryCommand):
    """
    :Syntax: muddle query name

    Print the build name, as specified in the build description with::

        builder.build_name = "Project32"

    This prints just the name, so that one can use it in the shell - for
    instance in bash::

        export PROJECT_NAME=$(muddle query name)

    or in a muddle Makefile::

        build_name:=$(shell $(MUDDLE) query name)
    """

    def with_build_tree(self, builder, current_dir, args):
        print builder.build_name

@subcommand('query', 'needed-by', CAT_QUERY)     # it used to be 'deps'
class QueryNeededBy(QueryCommand):
    """
    :Syntax: muddle query needed-by <label>

    Print what we need to build to build this label.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        to_build = depend.needed_to_build(builder.ruleset, label, useMatch = True)
        if to_build:
            print "Build order for %s .. "%label
            for rule in to_build:
                print rule.target
        else:
            print "Nothing else needs building to build %s"%label

@subcommand('query', 'checkout-id', CAT_QUERY)
class QueryCheckoutId(QueryCommand):
    """
    :Syntax: muddle query checkout-id [<label>]

    Report the VCS revision id (or equivalent) for the named checkout.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'checkout:'. If the label is a 'package:' label, and
    that package depends upon a single checkout, then report the id for that
    checkout.

    If <label> is not given, and the current directory is within a checkout
    directory, then use that checkout.

    The id returned is that which would be written to a stamp file as the
    checkout's revision id.
    """

    def with_build_tree(self, builder, current_dir, args):
        if args:
            label = self.get_label_from_fragment(builder, args,
                                                 default_type=LabelType.Checkout)
        else:
            what, label, domain = builder.find_location_in_tree(current_dir)
            if not label:
                raise GiveUp('Cannot decide on which checkout is wanted')

        if label.type == LabelType.Deployment:
            raise GiveUp('Cannot work with a deployment label')
        if label.type == LabelType.Package:
            checkouts = builder.checkouts_for_package(label)
            if len(checkouts) < 1:
                raise GiveUp('No checkouts associated with %s'%label)
            elif len(checkouts) > 1:
                raise GiveUp('More than one checkout associated with %s'%label)
            else:
                label = checkouts[0]

        # Figure out its VCS
        vcs_handler = builder.db.get_checkout_vcs(label)

        print vcs_handler.revision_to_checkout(builder, label, show_pushd=False)

@subcommand('query', 'build-desc-branch', CAT_QUERY)
class QueryBuildDescBranch(QueryCommand):
    """
    :Syntax: muddle query build-desc-branch

    Report the branch of the build description, and whether it is being used
    as the (default) branch for other checkouts.

    If there are sub-domains in the build tree, then this reports the branch
    of the top-level build description, which is the only build description
    that can request checkouts to "follow" its branch.
    """

    def with_build_tree(self, builder, current_dir, args):

        build_desc_branch = builder.get_build_desc_branch()
        print 'Build description %s is on branch %s'%(builder.build_desc_label,
                                                      build_desc_branch)
        if builder.follow_build_desc_branch:
            print '  This WILL be used as the default branch for other checkouts'
        else:
            print '  This will NOT be used as the default branch for other checkouts'


@subcommand('query', 'dir', CAT_QUERY)
class QueryDir(QueryCommand):
    """
    :Syntax: muddle query dir <label>

    Print a directory:

    * for checkout labels, the checkout directory
    * for package labels, the install directory
    * for deployment labels, the deployment directory

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.

    Typically used in a muddle Makefile, as for instance::

        KBUS_INSTALLDIR:=$(shell $(MUDDLE) query dir package:kbus{*})
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)

        dir = find_label_dir(builder, label)

        if dir is not None:
            print dir
        else:
            print None

@subcommand('query', 'localroot', CAT_QUERY)
class QueryLocalRoot(QueryCommand):
    """
    :Syntax: muddle query localroot <label>

    Print the "local root" directory for a label.

    For a label representing a checkout, package or deployment in the
    top-level, prints out the normal root directory (as "muddle query root").

    For a label in a subdomain, printes out the root directory for said
    subdomain (i.e., the directory containing its .muddle/ directory).

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)

        dir = utils.find_local_root(builder, label)

        if dir is not None:
            print dir
        else:
            print None

        # =====================================================================
        # XXX EXTRA TEMPORARY DEBUGGING XXX
        # =====================================================================
        wild = label.copy_with_tag('*')     # Once with /*
        print 'Instructions for', wild
        for lbl, path in builder.db.scan_instructions(wild):
            print lbl, path
        wild = wild.copy_with_role('*')     # Once with {*}/*
        print 'Instructions for', wild
        for lbl, path in builder.db.scan_instructions(wild):
            print lbl, path
        # =====================================================================
        inst_subdir = os.path.join('instructions', label.name)
        inst_src_dir = os.path.join(builder.db.root_path, '.muddle', inst_subdir)

        if label.role and label.role != '*':    # Surely we always have a role?
            src_name = '%s.xml'%label.role
            src_file = os.path.join(inst_src_dir, src_name)
            if os.path.exists(src_file):
                print 'Found', src_file

        src_file = os.path.join(inst_src_dir, '_default.xml')
        if os.path.exists(src_file):
            print 'Found', src_file
        # =====================================================================

@subcommand('query', 'env', CAT_QUERY)
class QueryEnv(QueryCommand):
    """
    :Syntax: muddle query env <label>

    Print the environment in which this label will be run.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        the_env = builder.effective_environment_for(label)
        print "Effective environment for %s .. "%label
        print the_env.get_setvars_script(builder, label, env_store.EnvLanguage.Sh)

@subcommand('query', 'all-env', CAT_QUERY, ['envs'])       # It used to be 'env'
class QueryEnvs(QueryCommand):
    """
    :Syntax: muddle query all-env <label>

    Print a list of the environments that will be merged to create the
    resulting environment for this label.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        a_list = builder.list_environments_for(label)

        for (lvl, label, env) in a_list:
            script = env.get_setvars_script
            print "-- %s [ %d ] --\n%s\n"%(label, lvl,
                                           script(builder, label,
                                                  env_store.EnvLanguage.Sh))
        print "---"

@subcommand('query', 'inst-details', CAT_QUERY)
class QueryInstDetails(QueryCommand):
    """
    :Syntax: muddle query inst-details <label>

    Print the list of actual instructions for this label, in the order in which
    they will be applied.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        loaded = builder.load_instructions(label)
        for (l, f, i) in loaded:
            print " --- Label %s , filename %s --- "%(l, f)
            print i.get_xml()
        print "-- Done --"

@subcommand('query', 'inst-files', CAT_QUERY)    # It used to be 'instructions'
class QueryInstFiles(QueryCommand):
    """
    :Syntax: muddle query inst-files <label>

    Print the list of currently registered instruction files, in the order
    in which they will be applied.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        result = builder.db.scan_instructions(label)
        for (l, f) in result:
            print "Label: %s  Filename: %s"%(l,f)

@subcommand('query', 'match', CAT_QUERY)
class QueryMatch(QueryCommand):
    """
    :Syntax: muddle query match <label>

    Print out any labels that match the label given. If the label is not
    wildcarded, this just reports if the label is known.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.
    """

    def with_build_tree(self, builder, current_dir, args):
        # XXX # Can this be get_label_from_fragment() instead?
        # XXX # label = self.get_label(builder, args)
        label = self.get_label_from_fragment(builder, args)
        wildcard_label = Label("*", "*", "*", "*", domain="*")
        all_rules = builder.ruleset.rules_for_target(wildcard_label)
        all_labels = set()
        for r in all_rules:
            all_labels.add(r.target)
        if label.is_definite():
            #print list(all_labels)[0], '..', list(all_labels)[-1]
            if label in all_labels:
                print 'Label %s exists'%label
            else:
                print 'Label %s does not exist'%label
        else:
            found = False
            for item in all_labels:
                if label.match(item):
                    print 'Label %s matches %s'%(label, item)
                    found = True
            if not found:
                print 'Label %s does not match any labels'%label

@subcommand('query', 'make-env', CAT_QUERY)   # It used to be 'makeenv'
class QueryMakeEnv(QueryCommand):
    """
    :Syntax: muddle query make-env <label>

    Print the environment in which "make" will be called for this label.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.

    Specifically, print what muddle adds to the environment (so it leaves
    out anything that was already in the environment when muddle was
    called).  Note that various things (lists of directories) only get set
    up when the directories actually exists - so, for instance,
    MUDDLE_INCLUDE_DIRS will only include directories for the packages
    depended on *that have already been built*. This means that this
    command shows the environment actually as would be used if one did
    ``muddle buildlabel``, but not necessarily as it would be for ``muddle
    build``, when the dependencies themselves would be built first. (It
    would be difficult to do otherwise, as the environment built is always
    as small as possible, and it is not until a package has been built that
    muddle can tell which directories will be present.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        rule_set = builder.ruleset.rules_for_target(label,
                                                               useTags=True,
                                                               useMatch=True)
        if len(rule_set) == 0:
            print 'No idea how to build %s'%label
            return
        elif len(rule_set) > 1:
            print 'Multiple rules for building %s'%label
            return

        # Amend the environment as if we were about to build
        old_env = os.environ
        try:
            os.environ = {}
            rule = list(rule_set)[0]
            builder._build_label_env(label, env_store)
            build_action = rule.action
            tmp = Label(LabelType.Checkout, build_action.co, domain=label.domain)
            co_path = builder.db.get_checkout_path(tmp)
            try:
                build_action._amend_env(co_path)
            except AttributeError:
		# The kernel builder, for instance, does not have _amend_env
		# Of course, it also doesn't use any of the make.py classes...
                pass
            keys = os.environ.keys()
            keys.sort()
            for key in keys:
                print '%s=%s'%(key,os.environ[key])
        finally:
            os.environ = old_env

@subcommand('query', 'objdir', CAT_QUERY)
class QueryObjdir(QueryCommand):
    """
    :Syntax: muddle query objdir <label>

    Print the object directory for a label.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.

    Typically used in a muddle Makefile, as for instance::

        KBUS_OBJDIR:=$(shell $(MUDDLE) query objdir package:kbus{*})
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        print builder.package_obj_path(label)

@subcommand('query', 'precise-env', CAT_QUERY) # It used to be 'preciseenv'
class QueryPreciseEnv(QueryCommand):
    """
    :Syntax: muddle query precise-env <label>

    Print the environment pertaining to exactly this label (no fuzzy matches)
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        the_env = builder.get_environment_for(label)

        local_store = env_store.Store()
        builder.set_default_variables(label, local_store)
        local_store.merge(the_env)

        print "Environment for %s .. "%label
        print local_store.get_setvars_script(builder, label, env_store.EnvLanguage.Sh)

@subcommand('query', 'needs', CAT_QUERY)      # It used to be 'results'
class QueryNeeds(QueryCommand):
    """
    :Syntax: muddle query needs <label>

    Print what this label is required to build.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        result = depend.required_by(builder.ruleset, label)
        print "Labels which require %s to build .. "%label
        for lbl in result:
            print lbl

@subcommand('query', 'rules', CAT_QUERY, ['rule'])        # It used to be 'rule'
class QueryRules(QueryCommand):
    """
    :Syntax: muddle query rules <label>

    Print the rules covering building this label.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        local_rule = builder.ruleset.rule_for_target(label)
        if (local_rule is None):
            print "No ruleset for %s"%label
        else:
            print "Rule set for %s .. "%label
            print local_rule

@subcommand('query', 'targets', CAT_QUERY)
class QueryTargets(QueryCommand):
    """
    :Syntax: muddle query targets <label>

    Print the targets that would be built by an attempt to build this label.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        local_rules = builder.ruleset.targets_match(label, useMatch = True)
        print "Targets that match %s .. "%(label)
        for i in local_rules:
            print "%s"%i

@subcommand('query', 'unused', CAT_QUERY)
class QueryUnused(QueryCommand):
    """
    :Syntax: muddle query unused [<label> [...]]

    Report on labels that are defined in the build description, but are not
    "used" by the targets. With no arguments, the targets are the default
    deployables. The argument "_all" means all available deployables (not
    just the defaults).  Otherwise, arguments are labels.
    """

    def with_build_tree(self, builder, current_dir, args):
        def all_deployables(builder):
            search_label = Label(LabelType.Deployment,
                                 "*", None, LabelTag.Deployed, domain="*")
            all_rules = builder.ruleset.rules_for_target(search_label)
            deployables = set()
            for r in all_rules:
                deployables.add(r.target)
            return deployables

        targets = set()
        if args:
            for thing in args:
                if thing == '_all':
                    targets = targets.union(all_deployables(builder))
                else:
                    targets.add(Label.from_string(thing))
            print 'Finding labels unused by:'
        else:
            print 'Finding labels unused by the default deployables:'
            targets = set(builder.default_deployment_labels)

        targets = list(targets)
        targets.sort()
        for label in targets:
            print '    %s'%label

        all_needed_labels = set()
        for label in targets:
            print '>>> Processing %s'%label
            needed = depend.needed_to_build(builder.ruleset, label)
            for r in needed:
                all_needed_labels.add(r.target)

        print 'Number of "needed" labels is %d.'%len(all_needed_labels)

        search_label = Label("*", "*", "*", "*", domain="*")
        all_rules = builder.ruleset.rules_for_target(search_label)
        all_labels = set()
        for r in all_rules:
            all_labels.add(r.target)

        if len(all_labels) == 1:
            print 'There is just 1 label in total'
        else:
            print 'There are %d labels in total'%len(all_labels)

        all_not_needed = all_labels.difference(all_needed_labels)
        if len(all_not_needed) == 1:
            print 'There is thus 1 label that is not "needed"'
        else:
            print 'There are thus %d labels that are not "needed"'%len(all_not_needed)

        wildcarded = set()
        pulled     = set()
        merged     = set()
        missing    = set()
        num_transient = 0
        for l in all_not_needed:
            if l.transient:
                num_transient += 1
            elif not l.is_definite():
                wildcarded.add(l)
            elif l.tag == LabelTag.Pulled:
                pulled.add(l)
            elif l.tag == LabelTag.Merged:
                merged.add(l)
            else:
                missing.add(l)

        print '    Transient  %d'%num_transient
        print '    Wildcarded %d'%len(wildcarded)
        print '    /pulled    %d'%len(pulled)
        print '    /merged    %d'%len(merged)
        print '    Missing    %d'%len(missing)
        print 'Transient labels are (internally) generated by muddle, and can be ignored.'
        print 'We ignore wildcarded labels - this should be OK.'
        print 'We ignore /pulled and /merged checkout labels.'

        erk = all_needed_labels.difference(all_labels)
        if len(erk):
            print 'Number of "needed" labels that are not in "all" is %d'%len(erk)
            print 'This is worrying. The labels concerned are:'
            for l in erk:
                print '    %s'%l

        if len(missing) == 0:
            print '>>> Otherwise, there are no "unused" labels'
            return

        checkouts = {}
        packages = {}
        deployments = {}
        other = {}

        def label_key(l):
            key_parts = ['%s:'%l.type]
            if l.domain:
                key_parts.append('(%s)'%l.domain)
            key_parts.append(l.name)
            if l.role:
                key_parts.append('{%s}'%l.role)
            return ''.join(key_parts)

        def add_label(d, l):
            key = label_key(l)
            if key in d:
                d[key].append(l.tag)
            else:
                d[key] = [l.tag]

        for l in missing:
            if l.type == LabelType.Checkout:
                add_label(checkouts,l)
            elif l.type == LabelType.Package:
                add_label(packages,l)
            elif l.type == LabelType.Deployment:
                add_label(deployments,l)
            else:
                add_label(other,l)

        def print_labels(d):
            keys = d.keys()
            keys.sort()
            for k in keys:
                tags = d[k]
                tags.sort()
                tags = ', '.join(tags)
                print '    %s/%s'%(k, tags)

        print '>>> Unused (missing) labels are thus:'
        print_labels(checkouts)
        print_labels(packages)
        print_labels(deployments)
        print_labels(other)

@subcommand('query', 'kernelver', CAT_QUERY)
class QueryKernelver(QueryCommand):
    """
    :Syntax: muddle query kernelver <label>

    Determine the Linux kernel version.

    <label> is a label or label fragment (see "muddle help labels"). The
    default type is 'package:'.

    <label> should be the package label for the kernel version. This command
    looks in <obj>/obj/include/linux/version.h (where <obj> is the directory
    returned by "muddle query objdir <label>") for the LINUX_VERSION_CODE
    definition, and attempts to decode that.

    It prints out the Linux version, e.g.::

      muddle query kernelver package:linux_kernel{boot}/built
      2.6.29
    """

    def kernel_version(self, builder, kernel_pkg):
        """Given the label for the kernel, determine its version.
        """
        kernel_root = builder.package_obj_path(kernel_pkg)
        include_file = os.path.join(kernel_root, 'obj', 'include', 'linux', 'version.h')
        with open(include_file) as fd:
            line1 = fd.readline()
        parts = line1.split()
        if parts[0] != '#define' or parts[1] != 'LINUX_VERSION_CODE':
            raise GiveUp('Unable to determine kernel version: first line of %s is %s'%(include_file,
                         line1.strip()))
        version = int(parts[2])
        a = (version & 0xFF0000) >> 16
        b = (version & 0x00FF00) >> 8
        c = (version & 0x0000FF)
        return '%d.%d.%d'%(a,b,c)

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        print self.kernel_version(builder, label)

@subcommand('query', 'release', CAT_QUERY)
class QueryRelease(QueryCommand):
    """
    :Syntax: muddle query release [-labels]

    Print information about this build as a release, including the release
    specification, and the "translation" of the special "_release" argument.

        (That content, what is to be released, is defined in the build
        description, using 'builder.add_to_release_build()'.)

    For instance::

        $ muddle query release
        This is a release build
        Release spec:
          name        = simple
          version     = v1.0
          archive     = tar
          compression = gzip
          hash        = c7c10cf4d6da4519714ac334a983ab518c68c5d1
        What to release (the meaning of "_release", before expansion):
          _default_deployments
          package:(subdomain2)second_pkg{x86}/*

    or::

        $ muddle query release
        This is NOT a release build
        Release spec:
          name        = None
          version     = None
          archive     = tar
          compression = gzip
          hash        = None
        What to release (the meaning of "_release", before expansion):
          _default_deployments
          package:(subdomain2)second_pkg{x86}/*

    If nothing has been designated for release, then that final clause will be
    replaced with::

        What to release (the meaning of "_release"):
          <nothing defined>

    With the '-labels' switch, just prints out that last list of "what to
    release"::

         $ muddle query release -labels
         _default_deployments
         package:(subdomain2)second_pkg{x86}/*

    The '-labels' variant prints nothing out if nothing has been designated
    for release.
    """

    allowed_switches = {'-labels': 'labels'}

    def with_build_tree(self, builder, current_dir, args):

        args = self.remove_switches(args, allowed_more=False)

        what_to_release = builder.what_to_release
        if 'labels' in self.switches:
            if what_to_release:
                for thing in sorted(map(str,what_to_release)):
                    print '%s'%thing
        else:
            if builder.is_release_build():
                print 'This is a release build'
            else:
                print 'This is NOT a release build'
            print 'Release spec:'
            print '  name        = %s'%builder.release_spec.name
            print '  version     = %s'%builder.release_spec.version
            print '  archive     = %s'%builder.release_spec.archive
            print '  compression = %s'%builder.release_spec.compression
            print '  hash        = %s'%builder.release_spec.hash
            print 'What to release (the meaning of "_release", before expansion):'
            if what_to_release:
                for thing in sorted(map(str,what_to_release)):
                    print '  %s'%thing
            else:
                print '  <nothing defined>'

@command('where', CAT_QUERY, ['whereami'])
class Whereami(Command):
    """
    :Syntax: muddle where [-detail]
    :or:     muddle whereami [-detail]

    Looks at the current directory and tries to identify where it is within the
    enclosing muddle build tree. If it can calculate a label corresponding to
    the location, it will also report that (as <name> and, if appropriate,
    <role>).

    For instance::

        $ muddle where
        Root of the build tree
        $ cd src; muddle where
        Checkout directory
        $ cd main_co; muddle where
        Checkout directory for checkout:main_co/*
        $ cd ../../obj/main_pkg; muddle where
        Package object directory for package:main_pkg{*}/*

    If you're not in a muddle build tree, it will say so::

        You are here. Here is not in a muddle build tree.

    If the '-detail' switch is given, output suitable for parsing is output, in
    the form:

        <what> <label> <domain>

    i.e., a space-separated triple of items that don't themselves contain
    whitespace.  For instance::

        $ muddle where
        Checkout directory for checkout:screen-4.0.3/*
        $ muddle where -detail
        Checkout checkout:screen-4.0.3/* None
    """

    def requires_build_tree(self):
        return False

    def want_detail(self, args):
        detail = False
        if args:
            if len(args) == 1 and args[0] == '-detail':
                detail = True
            else:
                raise GiveUp('Syntax: whereami [-detail]\n'
                             '    or: where [-detail]')
        return detail

    def with_build_tree(self, builder, current_dir, args):
        detail = self.want_detail(args)
        r = builder.find_location_in_tree(current_dir)
        if r is None:
            raise utils.MuddleBug('Unable to determine location in the muddle build tree:\n'
                                  'Build tree is at  %s\n'
                                  'Current directory %s'%(builder.db.root_path,
                                                          current_dir))
        (what, label, domain) = r

        if detail:
            print '%s %s %s'%(utils.ReverseDirTypeDict[what], label, domain)
            return

        if what is None:
            raise utils.MuddleBug('Unable to determine location in the muddle build tree:\n'
                                  "'Directory type' returned as None")

        if what == DirType.DomainRoot:
            print 'Root of subdomain %s'%domain
        else:
            rv = "%s"%what
            if label:
                rv = '%s for %s'%(rv, label)
            elif domain:
                rv = '%s in subdomain %s'%(rv, domain)
            print rv

    def without_build_tree(self, muddle_binary, current_dir, args):
        detail = self.want_detail(args)
        if detail:
            print 'None None None'
        else:
            print "You are here. Here is not in a muddle build tree."


@command('doc', CAT_QUERY)
class Doc(Command):
    """
    :Syntax: muddle doc [<switch> ...] [<what>]

    To get documentation on modules, classes, methods or functions in muddle,
    use::

        muddle doc <name>               for help on <name>
        muddle doc -contains <what>     to list all names that contain <what>

    There are also (mainly for use in debugging muddle itself - beware,
    they all produce long output)::

        muddle doc -duplicates     to list all duplicate (partial) names
        muddle doc -list           to list all the "full" names we know
        muddle doc -dump           to dump the internal map of names/values

    <switch> may also be::

        -p[ager] <pager>    to specify a pager through which the text will be
                            piped. The default is $PAGER (if set) or else
                            'more'.
        -nop[ager]          don't use a pager, just print the text out.
        -pydoc              Use pydoc's rendering to output the text about the
                            item. This tends to produce more information. It
                            is also (more or less) the format that the older
                            "muddle doc" command used.

    The plain "muddle doc <name>" can be used to find out about any muddle
    module, class, method or function. Leading parts of the name can be
    omitted ("Builder" and "mechanics.Builder" and "muddled.mechanics.Builder"
    are all the same), provided that doesn't make <name> ambiguous, and if it
    does, you will be given a list of the possible alternatives. So, for
    instance::

        $ muddle doc Builder

    will report on muddled.mechanics.Builder, but::

        $ muddle doc simple

    will give a list of all the names that contain 'simple'.

    If you're not sure of a name, then "-contains" can be used to look for all
    the (full names - i.e., starting with "muddled.") that contain that string.
    For instance::

        $ muddle doc -contains absolute
        The following names contain "absolute":
          muddled.checkouts.multilevel.absolute
          muddled.checkouts.simple.absolute
          muddled.checkouts.twolevel.absolute

    and one can then safely do::

        $ muddle doc simple.absolute

    For a module, the module docstring is reported, and then a list of the
    names of all the classes and functions in that module.

    For a class, the classes it inherits from, its docstring and its __init__
    method are all reported, followed by a list of the methods in that class.

    For a method or function, its argument list (signature) and docstring are
    reported.

    If "-pydoc" is specified, then the layout of various things will be
    different, and also the full documentation of internal items (methods
    inside classes, etc.) will be reported - this can lead to substantially
    longer output.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        muddled.docreport.report(args)

    def without_build_tree(self, muddle_binary, current_dir, args):
        muddled.docreport.report(args)

# -----------------------------------------------------------------------------
# Stamp commands
# -----------------------------------------------------------------------------
@subcommand('stamp', 'save', CAT_EXPORT)
class StampSave(Command):
    """
    :Syntax: muddle stamp save [<switches>] [<filename>]

    Go through each checkout, and save its remote repository and current
    brach/revision id/number to a file.

    This is intended to be enough information to allow reconstruction of the
    entire build tree, as-is.

    <switches> may be:

    * -before <when> - use the (last) revision id at or before <when>
    * -f, -force - "force" a revision id
    * -h, -head - use HEAD for all checkouts
    * -v <version>, -version <version>  - specify the version of stamp file

    These are explained more below. Switches may occur before or after
    <filename>.

    If a <filename> is specified, then output will be written to a file called
    either <filename>.stamp or <filename>.partial. If <filename> already ended
    in '.stamp' or '.partial', then the old extension will be removed before
    deciding on whether to use '.stamp' or '.partial'.

    If a <filename> is not specified, then a file called <sha1-hash>.stamp or
    <sha1-hash>.partial will be used, where <sha1-hash> is a hexstring
    representation of the hash of the content of the file.

    The '.partial' extension will be used if it was not possible to write a
    full stamp file (revisions could not be determined for all checkouts, and
    neither '-force' nor '-head' was specified). An attempt will be made to
    give useful information about what the problems are.

    If a file already exists with the name ultimately chosen, that file will
    be overwritten.

    If '-before' is specified, then use the (last) revision id at or before
    that date and time. <when> is left a bit unspecified at the moment, and
    thus this feature is experimental.

       | XXX At the moment '-before' is only supported for git and bzr, and
       | XXX thus any form of date/time/revision id that git and/or will accept
       | XXX may be used for <when>. The simple for "yyyy-mm-dd hh:mm:ss" seems
       | XXX acceptabl to both.

    For instance::

        muddle stamp save -before "2012-06-26 23:00:00"

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

    Note that if '-before' is specified, '-force' will be ignored.

    If '-h' or '-head' is specified, then HEAD will be used for all checkouts.
    In this case, the repository specified in the build description is used,
    and the revision id and status of each checkout is not checked.

    By default, a version 2 stamp file will be created. This is equivalent
    to specifying '-version 2'. If '-version 1' is specified, then a version
    1 stamp file will be created instead. This is the version of stamp file
    understood by muddle before it was able to create version 2 stamp files
    (see 'muddle help stamp save' to see if this is the case for a particular
    version of muddle or not). Note that the version 1 stamp file created
    by muddle 2.3 and above is not absolutely guaranteed to be correct.

    See "muddle unstamp" for restoring from stamp files.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        force = False
        just_use_head = False
        filename = None
        when = None
        version = 2

        while args:
            word = args.pop(0)
            if word in ('-f', '-force'):
                force = True
                just_use_head = False
            elif word in ('-h', '-head'):
                just_use_head = True
                force = False
            elif word == '-before':
                when = args.pop(0)
            elif word in ('-v', '-version'):
                try:
                    version = int(args.pop(0))
                except IndexError:
                    raise GiveUp("-version must be followed by 1 or 2, for 'stamp save'")
                except ValueError as e:
                    raise GiveUp("-version must be followed by 1 or 2, not '%s'"%args[0])
                if version not in (1, 2):
                    raise GiveUp("-version must be followed by 1 or 2, not '%s'"%args[0])
            elif word.startswith('-'):
                raise GiveUp("Unexpected switch '%s' for 'stamp save'"%word)
            elif filename is None:
                filename = word
            else:
                raise GiveUp("Unexpected argument '%s' for 'stamp save'"%word)

        if just_use_head:
            print 'Using HEAD for all checkouts'
        elif force:
            print 'Forcing original revision ids when necessary'

        if self.no_op():
            return

        stamp, problems = VersionStamp.from_builder(builder, force, just_use_head, before=when)

        working_filename = '_temporary.stamp'
        print 'Writing to',working_filename
        hash = stamp.write_to_file(working_filename, version=version)
        print 'Wrote revision data to %s'%working_filename
        print 'File has SHA1 hash %s'%hash

        final_name = self.decide_stamp_filename(hash, filename, problems)
        print 'Renaming %s to %s'%(working_filename, final_name)
        os.rename(working_filename, final_name)

    def decide_stamp_filename(self, hash, basename=None, partial=False):
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

@subcommand('stamp', 'version', CAT_EXPORT)
class StampVersion(Command):
    """
    :Syntax: muddle stamp version [-f[orce]|-v[ersion] <version>]

    This is similar to "stamp save", but using a pre-determined stamp filename.

    Specifically, the stamp file written will be called:

        versions/<build_name>.stamp

    or, if the build description has asked for checkouts to follow its branch
    with ``builder.follow_build_desc_branch = True``::

        versions/<build_name>.<branch_name>.stamp

    The "versions/" directory is at the build root (i.e., it is a sibling of
    the ".muddle/" and "src/" directories). If it does not exist, it will be
    created.

      If the VersionsRepository is set (in the .muddle/ directory), and it is
      a distributed VCS (e.g., git or bzr) then ``git init`` (or ``bzr init``,
      or the equivalent) will be done in the directory if necessary, and then
      the file will be added to the local working set in that directory.
      For subversion, the file adding will be done, but no attempt will be
      made to initialise the directory.

    <build_name> is the name of this build, as specified by the build
    description (by setting ``builder.build_name``). If the build description
    does not set the build name, then the name will be taken from the build
    description file name. You can use "muddle query name" to find the build
    name for a particular build.

    If a full stamp file cannot be written (i.e., if the result would have
    extension ".partial"), then the version stamp file will not be written.

    Note that '-f' is supported (although perhaps not recommended), but '-h' is
    not.

    By default, a version 2 stamp file will be created. This is equivalent
    to specifying '-version 2'. If '-version 1' is specified, then a version
    1 stamp file will be created instead. This is the version of stamp file
    understood by muddle before it was able to create version 2 stamp files
    (see 'muddle help stamp version' to see if this is the case for a
    particular version of muddle or not). Note that the version 1 stamp file
    created by muddle 2.3 and above is not absolutely guaranteed to be correct.

    See "muddle unstamp" for restoring from stamp files.
    """

    def requires_build_tree(self):
        return True

    # We don't allow this in a release build because it wants to add the
    # stamp file to the VCS in the versions/ directory
    def allowed_in_release_build(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        force = False
        version = 2

        while args:
            word = args[0]
            args = args[1:]
            if word in ('-f', '-force'):
                force = True
            elif word in ('-v', '-version'):
                try:
                    version = int(args[0])
                except IndexError:
                    raise GiveUp("-version must be followed by 1 or 2, for 'stamp save'")
                except ValueError as e:
                    raise GiveUp("-version must be followed by 1 or 2, not '%s'"%args[0])
                if version not in (1, 2):
                    raise GiveUp("-version must be followed by 1 or 2, not '%s'"%args[0])
                args = args[1:]
            elif word.startswith('-'):
                raise GiveUp("Unexpected switch '%s' for 'stamp version'"%word)
            else:
                raise GiveUp("Unexpected argument '%s' for 'stamp version'"%word)

        if force:
            print 'Forcing original revision ids when necessary'

        if self.no_op():
            return

        stamp, problems = VersionStamp.from_builder(builder, force,
                                                    just_use_head=False)

        if problems:
            print problems
            raise GiveUp('Problems prevent writing version stamp file')

        version_dir = os.path.join(builder.db.root_path, 'versions')
        if not os.path.exists(version_dir):
            print 'Creating directory %s'%version_dir
            os.mkdir(version_dir)

        working_filename = os.path.join(version_dir, '_temporary.stamp')
        print 'Writing to',working_filename
        hash = stamp.write_to_file(working_filename, version=version)
        print 'Wrote revision data to %s'%working_filename
        print 'File has SHA1 hash %s'%hash

        if builder.follow_build_desc_branch:
            # Note that we don't ask for builder.build_desc_repo.branch, as
            # if we've only just done "muddle branch-tree" that will still be
            # set to the *original* branch of the build description. Instead
            # we should do what the code does that tries to follow the build
            # description, which is to use:
            branch = builder.get_build_desc_branch()
            if branch is None:
                branch = 'master'
            version_filename = "%s.%s.stamp"%(builder.build_name, branch)
        else:
            version_filename = "%s.stamp"%(builder.build_name)

        final_name = os.path.join(version_dir, version_filename)
        print 'Renaming %s to %s'%(working_filename, final_name)
        os.rename(working_filename, final_name)

        db = builder.db
        versions_url = db.VersionsRepository_pathfile.from_disc()
        if versions_url:
            with Directory(version_dir):
                vcs_name, just_url = version_control.split_vcs_url(versions_url)
                if vcs_name:
                    print 'Adding version stamp file to VCS'
                    version_control.vcs_init_directory(vcs_name, [version_filename])

@subcommand('stamp', 'release', CAT_EXPORT)
class StampRelease(Command):
    """
    :Syntax: muddle stamp release [<switches>] <release-name> <release-version>
    :Syntax: muddle stamp release [<switches>] <release-name> -next
    :or:     muddle stamp release [<switches>] -template

    This is similar to "stamp version", but saves a release stamp file - a
    stamp file that describes a release of the build tree.

    The release stamp file written will be called::

        versions/<release_name>_<release_version>.release

    The "versions/" directory is at the build root (i.e., it is a sibling of
    the ".muddle/" and "src/" directories). If it does not exist, it will be
    created.

      If the VersionsRepository is set (in the .muddle/ directory), and it is
      a distributed VCS (e.g., git or bzr) then ``git init`` (or ``bzr init``,
      or the equivalent) will be done in the directory if necessary, and then
      the file will be added to the local working set in that directory.
      For subversion, the file adding will be done, but no attempt will be
      made to initialise the directory.

    If the ``-next`` option is used, then the version number will be guessed.
    Muddle will look in the "versions/" directory for all the ".release" files
    whose names start with ``<release_name>_v``, and will work out the last
    version number (as <major>.minor>) present (not that 1.01 is the same as
    1.1). It will then use 0.0 if it didn't find anything, or will use the next
    <minor> value. So if the user asked for ``muddle stamp release Fred -next``
    and the files in "versions/" were::

        Fred_v1.1.release
        Fred_v3.02.release
        Graham_v9.9.release

    then the next version number would be guessed as v3.3.

    If the ``-template`` option is used, then the file created will be called::

        versions/this-is-not-a-file-name.release

    and both the release name and release version values in the file will be
    set to ``<REPLACE THIS>``. The user will have to rename the file, and edit
    both of those to sensible values, before using it (well, we don't enforce
    renaming the file, but...).

    <switches> may be:

    * -archive <name>

      This specifies how the release will be archived. At the moment the only
      permitted value is "tar".

    * -compression <name>

       This specifies how the archive will be compressed. The default is
       "gzip", and at the moment the only other alternative is "bzip2".

    See "muddle release" for using release files to build a release.

    Note that release files are also valid stamp files, so "muddle unstamp"
    can be used to retore a build tree from them.
    """

    def requires_build_tree(self):
        return True

    # We don't allow this in a release build because it already is a release
    # build, and we thus *have* a release stamp file somewhere
    def allowed_in_release_build(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        name = None
        version = None
        archive = None
        compression = None
        is_template = False
        guess_version = False

        while args:
            word = args.pop(0)
            if word == '-template':
                is_template = True
            elif word == '-next':
                guess_version = True
            elif word == '-archive':
                archive = args.pop(0)
            elif word == '-compression':
                compression = args.pop(0)
            elif word.startswith('-'):
                raise GiveUp("Unexpected switch '%s' for 'stamp release'"%word)
            elif name is None:
                name = word
            elif version is None:
                version = word
            else:
                raise GiveUp("Unexpected argument '%s' for 'stamp release'"%word)

        if is_template and (name or version):
            raise GiveUp('Cannot specify -template and release name or version')
        if is_template and guess_version:
            raise GiveUp('Cannot specify -template and -next')
        if not is_template and (name is None or not (version or guess_version)):
            raise GiveUp('Must specify one of -template, or a release name and version, or -next')

        if self.no_op():
            return

        release = ReleaseSpec(name, version, archive, compression)
        builder.release_spec = release

        stamp, problems = ReleaseStamp.from_builder(builder)

        if problems:
            print problems
            raise GiveUp('Problems prevent writing release stamp file')

        version_dir = os.path.join(builder.db.root_path, 'versions')
        if not os.path.exists(version_dir):
            print 'Creating directory %s'%version_dir
            os.mkdir(version_dir)

        if guess_version:
            vnum = self.guess_next_version_number(version_dir, name)
            version = 'v%s'%vnum
            print "Pretending you said 'muddle stamp",
            if archive:
                print "-archive %s"%archive,
            if compression:
                print "-compression %s"%compression,
            print "release %s %s'"%(name, version)

        working_filename = os.path.join(version_dir, '_temporary.stamp')
        print 'Writing to',working_filename
        hash = stamp.write_to_file(working_filename)
        print 'Wrote revision data to %s'%working_filename
        print 'File has SHA1 hash %s'%hash

        if is_template:
            version_filename = 'this-is-not-a-file-name.release'
        else:
            version_filename = "%s_%s.release"%(name, version)

        final_name = os.path.join(version_dir, version_filename)
        print 'Renaming %s to %s'%(working_filename, final_name)
        os.rename(working_filename, final_name)

        db = builder.db
        versions_url = db.VersionsRepository_pathfile.from_disc()
        if versions_url:
            with Directory(version_dir):
                vcs_name, just_url = version_control.split_vcs_url(versions_url)
                if vcs_name:
                    print 'Adding release stamp file to VCS'
                    version_control.vcs_init_directory(vcs_name, [version_filename])

    def guess_next_version_number(self, version_dir, name):
        """Return our best guess as to the next (minor) version number.
        """
        print
        print 'Looking in versions directory for previous releases of "%s"'%name
        max_vnum = utils.VersionNumber.unset()
        files = os.listdir(version_dir)
        for filename in sorted(files):
            base, ext = os.path.splitext(filename)
            if ext != '.release':
                continue
            if not base.startswith(name+'_v'):
                print 'Ignoring release file %s (wrong release name)'%filename
                continue
            print 'Found release file %s'%filename
            version = base[len(name)+2:]
            try:
                vnum = utils.VersionNumber.from_string(version)
            except GiveUp as e:
                print 'Ignoring release file %s (cannot parse version number: %s'%(filename, e)
                continue
            if vnum > max_vnum:
                max_vnum = vnum
        return max_vnum.next()

@subcommand('stamp', 'diff', CAT_EXPORT)
class StampDiff(Command):
    """
    :Syntax: muddle stamp diff [<style>] <path1> <path2> [<output_file>]

    Compare two builds, as version stamps.

    Each of <path1> and <path2> may be an existing stamp file, or the top-level
    directory of a muddle build tree (i.e., the directory that contains the
    '.muddle' and 'src' directories).

    If <output_file> is given, then the results of the comparison will be
    written to it, otherwise they will be written to standard output.

    <style> specifies the way the comparison is done:

    * -u, -unified - output a unified difference between stamp files.
    * -c, -context - output a context difference between stamp files. This
      uses a "before/after" style of presentation.
    * -n, -ndiff - use Python's "ndiff" to output the difference between stamp
      files. This is normally a more human-friendly set of differences, but
      outputs the parts of the files that match as well as those that do not.
    * -h, -html - output the difference between stamp files as an HTML page,
      displaying the files in two columns, with differences highlighted by
      colour.
    * -d, -direct - output the difference between two VersionStamp
      datastructures (this is the datastructure used to hold a stamp file
      internally within muddle). This is the default.

    NOTE that at the moment '-d' only compares checkout information, not
    repository and domain information. It also ignores any "problems" in
    the stamp file.

    For textual comparisons between stamp files, "muddle stamp diff" will
    first generate a temporary stamp file, if necessary (i.e., if <path1>
    or <path2> is a build tree), using the equivalent of "muddle stamp save".

    For direct ('-d') comparison, a VersionStamp will be created from the
    build tree or read from the stamp file, as appropriate.
    """

    def requires_build_tree(self):
        return False

    def print_syntax(self):
        print ':Syntax: muddle stamp diff [<style>] <path1> <path2> [<output_file>]'

    def without_build_tree(self, muddle_binary, current_dir, args):
        if not args:
            raise GiveUp("'stamp diff' needs two paths (stamp file or build tree) to compare")
        self.compare_stamps(muddle_binary, args)

    def with_build_tree(self, builder, current_dir, args):
        self.without_build_tree(builder.muddle_binary, current_dir, args)

    def compare_stamps(self, muddle_binary, args):

        path1 = path2 = output_file = None
        # The default is to compare using VersionStamp
        diff_style = 'direct'
        # Which doesn't *need* explicit text files
        requires_text_filess = False

        while args:
            word = args.pop(0)
            if word in ('-u', '-unified'):
                diff_style = 'unified'
                requires_text_filess = True
            elif word in ('-n', '-ndiff'):
                diff_style = 'ndiff'
                requires_text_filess = True
            elif word in ('-c', '-context'):
                diff_style = 'context'
                requires_text_filess = True
            elif word in ('-h', '-html'):
                diff_style = 'html'
                requires_text_filess = True
            elif word in ('-d', '-direct'):
                diff_style = 'direct'
                requires_text_filess = False
            elif word.startswith('-'):
                print "Unexpected switch '%s'"%word
                self.print_syntax()
                return 2
            else:
                if path1 is None:
                    path1 = word
                elif path2 is None:
                    path2 = word
                elif output_file is None:
                    output_file = word
                else:
                    print "Unexpected '%s'"%word
                    self.print_syntax()
                    return 2

        # What sort of things are we comparing?
        if os.path.isdir(path1) and os.path.exists(os.path.join(path1, '.muddle')):
            path1_is_build = True
        elif os.path.isfile(path1):
            path1_is_build = False
        else:
            raise GiveUp('"%s" is not a file or a build tree - cannot compare it'%path1)

        if os.path.isdir(path2) and os.path.exists(os.path.join(path2, '.muddle')):
            path2_is_build = True
        elif os.path.isfile(path2):
            path2_is_build = False
        else:
            raise GiveUp('"%s" is not a file or a build tree - cannot compare it'%path2)

        if self.no_op():
            parts = ['Comparing']
            if path1_is_build:
                parts.append('build tree')
            else:
                parts.append('stamp file')
            parts.append('"%s"'%path1)
            parts.append('and')
            if path2_is_build:
                parts.append('build tree')
            else:
                parts.append('stamp file')
            parts.append('"%s"'%path2)
            print ' '.join(parts)
            return

        path1 = utils.normalise_path(path1)
        path2 = utils.normalise_path(path2)

        if requires_text_filess:
            if path1_is_build:
                file1 = self._generate_stamp_file(path1, muddle_binary)
            else:
                file1 = path1

            if path2_is_build:
                file2 = self._generate_stamp_file(path2, muddle_binary)
            else:
                file2 = path2

            if output_file:
                print 'Writing output to %s'%output_file
                with open(output_file, 'w') as fd:
                    self.diff(path1, path2, file1, file2, diff_style, fd)
            else:
                self.diff(path1, path2, file1, file2, diff_style, sys.stdout)

        else:
            if path1_is_build:
                stamp1 = self._calculate_stamp(path1, muddle_binary)
            else:
                stamp1 = VersionStamp.from_file(path1)

            if path2_is_build:
                stamp2 = self._calculate_stamp(path2, muddle_binary)
            else:
                stamp2 = VersionStamp.from_file(path2)

            if output_file:
                print 'Writing output to %s'%output_file
                with open(output_file, 'w') as fd:
                    self.diff_direct(path1_is_build, path2_is_build,
                                     path1, path2, stamp1, stamp2, fd)
            else:
                self.diff_direct(path1_is_build, path2_is_build,
                                 path1, path2, stamp1, stamp2, sys.stdout)

    def _calculate_stamp(self, path, muddle_binary):
        """Calculate the stamp for the build at 'path'

        We probably don't strictly *need* 'muddle_binary' for our purposes,
        but since we know our caller has it to hand, we might as well use it.

        Note that we ignore any problems reported in generating the stamp.
        """
        (build_root, build_domain) = utils.find_root_and_domain(path)
        b = mechanics.load_builder(build_root, muddle_binary, default_domain=build_domain)
        print 'Calculating stamp for %s'%path
        stamp, problems = VersionStamp.from_builder(b, quiet=True)
        return stamp

    def _generate_stamp_file(self, path, muddle_binary):
        """Generate a stamp file for the build at 'path'

        We probably don't strictly *need* 'muddle_binary' for our purposes,
        but since we know our caller has it to hand, we might as well use it.

        Generates a stamp (ignoring any problems), and then writes the stamp
        file from that.
        """
        stamp = self._calculate_stamp(path, muddle_binary)
        with tempfile.NamedTemporaryFile(suffix='.stamp', mode='w', delete=False) as fd:
            filename = fd.name
            print 'Writing stamp for %s to %s'%(path, filename)
            stamp.write_to_file_object(fd)
        return filename

    def diff_direct(self, path1_is_build, path2_is_build, path1, path2, stamp1, stamp2, fd):
        """
        Output comparison using VersionStamp instances.

        Currently, only compares the checkouts.

        XXX TODO It *should* compare everything (including any problems!)
        """
        fd.write('Comparing version stamps\n')
        fd.write('Source 1: %s %s\n'%('build tree' if path1_is_build else 'stamp file', path1))
        fd.write('Source 2: %s %s\n'%('build tree' if path2_is_build else 'stamp file', path2))
        fd.write('\n')
        deleted, new, changed, problems = stamp1.compare_checkouts(stamp2)
        if deleted:
            fd.write('\n')
            fd.write('The following were deleted in the second stamp file:\n')
            for co_label, co_dir, co_leaf, repo in deleted:
                fd.write('  %s\n'%co_label)
        if new:
            fd.write('\n')
            fd.write('The following were new in the second stamp file:\n')
            for co_label, co_dir, co_leaf, repo in new:
                fd.write('  %s\n'%co_label)
        if changed:
            fd.write('\n')
            fd.write('The following were changed:\n')
            for co_label, rev1, rev2 in changed:
                fd.write('  %s went from revision %s to %s\n'%(co_label, rev1, rev2))
        if problems:
            fd.write('\n')
            fd.write('The following problems were found:\n')
            for co_label, problem in problems:
                fd.write('  %s\n'%(problem))
        if not (deleted or new or changed or problems):
            fd.write('\n')
            fd.write("The checkouts in the stamp files appear to be the same\n")

    def diff(self, path1, path2, file1, file2, diff_style='unified', fd=sys.stdout):
        """
        Output a comparison of two stamp files
        """
        with open(file1) as fd1:
            file1_lines = fd1.readlines()
        with open(file2) as fd2:
            file2_lines = fd2.readlines()

        # Ensure it is obvious in the output which stamp files were compared,
        # and, if we generated them, where we made them from
        if path1 == file1:
            name1 = path1
        else:
            name1 = '%s from %s'%(file1, path1)
        if path2 == file2:
            name2 = path2
        else:
            name2 = '%s from %s'%(file2, path2)

        if diff_style == 'html':
            diff = difflib.HtmlDiff().make_file(file1_lines, file2_lines,
                                                name1, name2)
        elif diff_style == 'ndiff':
            diff = difflib.ndiff(file1_lines, file2_lines)
            file1_date = time.ctime(os.stat(file1).st_mtime)
            file2_date = time.ctime(os.stat(file2).st_mtime)
            help = ["#First character indicates provenance:\n"
                    "# '-' only in %s of %s\n"%(name1, file1_date),
                    "# '+' only in %s of %s\n"%(name2, file2_date),
                    "# ' ' in both\n",
                    "# '?' pointers to intra-line differences\n"
                    "#---------------------------------------\n"]
            diff = help + list(diff)
        elif diff_style == 'context':
            file1_date = time.ctime(os.stat(file1).st_mtime)
            file2_date = time.ctime(os.stat(file2).st_mtime)
            diff = difflib.context_diff(file1_lines, file2_lines,
                                        name1, name2,
                                        file1_date, file2_date)
        else:
            file1_date = time.ctime(os.stat(file1).st_mtime)
            file2_date = time.ctime(os.stat(file2).st_mtime)
            diff = difflib.unified_diff(file1_lines, file2_lines,
                                        name1, name2,
                                        file1_date, file2_date)

        fd.writelines(diff)

@subcommand('stamp', 'push', CAT_EXPORT)
class StampPush(Command):
    """
    :Syntax: muddle stamp push [<repository_url>]

    This performs a VCS "push" operation for the "versions/" directory. This
    assumes that the versions repository is defined in
    ``.muddle/VersionsRepository``.

    If a <repository_url> is given, then that is used as the remote repository
    for the push, and also saved as the "current" remote repository in
    ``.muddle/VersionsRepository``.

    (If the VCS being used is Subversion, then <repository> is ignored
    by the actual "push", but will still be used to update the
    VersionsRepository file. So be careful.)

    If a <repository_url> is not given, then the repository URL named
    in ``.muddle/VersionsRepository`` is used. If there is no repository
    specified there, then the operation will fail.

    'stamp push' does not (re)create a stamp file in the "versions/"
    directory - use 'stamp version' to do that separately.

    See 'unstamp' for restoring from stamp files.
    """

    def requires_build_tree(self):
        return True

    # In general, VCS operations are not allowed in release builds
    def allowed_in_release_build(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        if len(args) > 1:
            raise GiveUp("Unexpected argument '%s' for 'stamp push'"%' '.join(args))

        db = builder.db

        if args:
            versions_url = args[0]
        else:
            # Make sure we always look at the *actual* value in the
            # '.muddle/VersionsRepository file, in case someone has edited it
            versions_url = db.VersionsRepository_pathfile.from_disc()

        if not versions_url:
            raise GiveUp("Cannot push 'versions/' directory, as there is no repository specified\n"
                                "Check the contents of '.muddle/VersionsRepository',\n"
                                "or give a repository on the command line")

        versions_dir = os.path.join(db.root_path, "versions")
        if not os.path.exists(versions_dir):
            raise GiveUp("Cannot push 'versions/' directory, as it does not exist.\n"
                                'Have you done "muddle stamp version"?')

        if self.no_op():
            print 'Push versions directory to', versions_url
            return

        with Directory(versions_dir):
            version_control.vcs_push_directory(versions_url)

        if args:
            print 'Remembering versions repository %s'%versions_url
            db.VersionsRepository_pathfile.set(versions_url)
            db.VersionsRepository_pathfile.commit()

@subcommand('stamp', 'pull', CAT_EXPORT)
class StampPull(Command):
    """
    :Syntax: muddle stamp pull [<repository_url>]

    This performs a VCS "pull" operation for the "versions/" directory. This
    assumes that the versions repository is defined in
    ``.muddle/VersionsRepository``.

    If a <repository_url> is given, then that is used as the remote repository
    for the pull, and also saved as the "current" remote repository in
    ``.muddle/VersionsRepository``.

    (If the VCS being used is Subversion, then <repository> is ignored by the
    actual "pull", but will still be used to update the VersionsRepository
    file. So be careful.)

    If a <repository_url> is not given, then the repository URL named
    in ``.muddle/VersionsRepository`` is used. If there is no repository
    specified there, then the operation will fail.

    See 'unstamp' for restoring from stamp files.
    """

    def requires_build_tree(self):
        return True

    def allowed_in_release_build(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        if len(args) > 1:
            raise GiveUp("Unexpected argument '%s' for 'stamp pull'"%' '.join(args))

        db = builder.db

        if args:
            versions_url = args[0]
        else:
            # Make sure we always look at the *actual* value in the
            # '.muddle/VersionsRepository file, in case someone has edited it
            versions_url = db.VersionsRepository_pathfile.from_disc()

        if not versions_url:
            raise GiveUp("Cannot pull 'versions/' directory, as there is no repository specified\n"
                                "Check the contents of '.muddle/VersionsRepository',\n"
                                "or give a repository on the command line")

        versions_dir = os.path.join(db.root_path, "versions")

        if self.no_op():
            if os.path.exists(versions_dir):
                print 'Pull versions directory from', versions_url
            else:
                print 'Clone versions directory from', versions_url
            return

        if os.path.exists(versions_dir):
            with Directory(versions_dir):
                version_control.vcs_pull_directory(versions_url)
        else:
            print "'versions/' directory does not exist - cloning instead"
            with Directory(db.root_path):
                # Make sure we always clone to a directory of the right name...
                version_control.vcs_get_directory(versions_url, "versions")

        if args:
            print 'Remembering versions repository %s'%versions_url
            db.VersionsRepository_pathfile.set(versions_url)
            db.VersionsRepository_pathfile.commit()

@command('unstamp', CAT_EXPORT)
class UnStamp(Command):
    """
    To create a build tree from a stamp file:

    :Syntax: muddle unstamp <file>
    :or:     muddle unstamp <url>
    :or:     muddle unstamp <vcs>+<url>
    :or:     muddle unstamp <vcs>+<repo_url> <version_desc>

    To update a build tree from a stamp file:

    :Syntax: muddle unstamp -u[pdate] <file>

    Creating a build tree from a stamp file
    ---------------------------------------
    The normal "unstamp" command reads the contents of a "stamp" file, as
    produced by the "muddle stamp" command, and:

    1. Retrieves each checkout mentioned
    2. Reconstructs the corresponding muddle directory structure
    3. Confirms that the muddle build description is compatible with
       the checkouts.

    This form of the command cannot be used within an existing muddle build
    tree, as its intent is to create a new build tree.

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

    Updating a build tree from a stamp file
    ---------------------------------------
    The "-update" form ("unstamp -update" or "unstamp -u") also reads the
    contents of a "stamp" file, but it then tries to amend the current build
    tree to match the stamp file.

    This form of the command must be used within an existing muddle build tree,
    as its intent is to alter it.

    The stamp file must be specified as a local path - the URL forms are not
    supported.

    The command looks up each checkout described in the stamp file. If it
    already exists, then it sets it to the correct revision, using "muddle
    pull". This last means that the value "_just_pulled" will be set to
    those checkouts which have been pulled, so one can do, for instance,
    "muddle distrebuild _just_pulled".

        XXX Future versions of this command will also be able to change
        the branch of a checkout. This is not yet supported.

    If the checkout does not exist, then it will be cloned, using "muddle
    checkout". Newly cloned checkouts will not be represented in
    "_just_pulled".

    In the simplest case, the "unstamp -update" operation may just involve
    choosing different revisions on some checkouts.

    Before using this form of the command, it is probably worth using::

        muddle stamp diff . <file>

    to determine what changes will be made.

    After using this form of the command, it is highly recommended to use::

        muddle veryclean

    to delete the directories built from the checkout sources.
    """

    def print_syntax(self):
        print """
    To create a build tree:

    :Syntax: muddle unstamp <file>
    :or:     muddle unstamp <url>
    :or:     muddle unstamp <vcs>+<url>
    :or:     muddle unstamp <vcs>+<repo_url> <version_desc>

    To update a build tree:

    :Syntax: muddle unstamp -u[pdate] <file>

    Try "muddle help unstamp" for more information."""

    allowed_switches = {
            '-u' : 'update',
            '-update' : 'update',
            }

    def requires_build_tree(self):
        return False

    def allowed_in_release_build(self):
        return False

    def with_build_tree(self, builder, current_dir, args):

        args = self.remove_switches(args)

        if 'update' not in self.switches:
            raise GiveUp('Plain "muddle unstamp" does not work in a build tree.\n'
                         'Did you mean "muddle unstamp -update"?\n'
                         'See "muddle help unstamp for more information.')

        if len(args) != 1:
            raise GiveUp('"muddle unstamp -update" takes a single stamp file as argument')

        self.update_from_file(builder, args[0])

    def without_build_tree(self, muddle_binary, current_dir, args):

        args = self.remove_switches(args)

        if 'update' in self.switches:
            raise GiveUp('"muddle unstamp -update" needs a build tree to update')

        # In an ideal world, we'd only be called if there really was no muddle
        # build tree. However, in practice, the top-level script may call us
        # because it can't find an *intact* build tree. So it's up to us to
        # know that we want to be a bit more careful...
        self.check_for_broken_build(current_dir)

        if len(args) == 1:
            self.unstamp_from_file(muddle_binary, current_dir, args[0])
        elif len(args) == 2:
            self.unstamp_from_repo(muddle_binary, current_dir, args[0], args[1])
        else:
            self.print_syntax()
            return 2

    def unstamp_from_file(self, muddle_binary, current_dir, thing):
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

        if self.no_op():
            return

        stamp = VersionStamp.from_file(filename)

        self.unstamp_from_stamp(muddle_binary, current_dir, stamp)

    def unstamp_from_repo(self, muddle_binary, current_dir, repo, version_path):
        """
        Unstamp from a repository and version path.
        """

        version_dir, version_file = os.path.split(version_path)

        if not version_file:
            raise GiveUp("'unstamp <vcs+url> %s' does not end with"
                    " a filename"%version_path)

        # XXX I'm not entirely sure about this check - is it overkill?
        if os.path.splitext(version_file)[1] != '.stamp':
            raise GiveUp("Stamp file specified (%s) does not end"
                    " .stamp"%version_file)

        actual_url = '%s/%s'%(repo, version_dir)
        print 'Retrieving %s'%actual_url

        if self.no_op():
            return

        # Restore to the "versions" directory, regardless of the URL
        version_control.vcs_get_directory(actual_url, "versions")

        stamp = VersionStamp.from_file(os.path.join("versions", version_file))

        self.unstamp_from_stamp(muddle_binary, current_dir, stamp, versions_repo=actual_url)

    def unstamp_from_stamp(self, muddle_binary, current_dir, stamp, versions_repo=None):
        """Given a stamp file, do our work.
        """
        builder = mechanics.minimal_build_tree(muddle_binary, current_dir,
                                               stamp.repository,
                                               stamp.description,
                                               desc_branch=stamp.description_branch,
                                               versions_repo=versions_repo)

        self.restore_stamp(builder, current_dir, stamp.domains, stamp.checkouts)

        # Once we've checked everything out, we should ideally check
        # if the build description matches what we've checked out...
        return self.check_build(current_dir, stamp.checkouts, muddle_binary)

    def update_from_file(self, builder, filename):
        """
        Update our build from the given stamp file.
        """

        if self.no_op():
            return

        stamp = VersionStamp.from_file(filename)
        self.update_from_stamp(builder, stamp.domains, stamp.checkouts)

        # Once we've checked everything out, we should ideally check
        # if the build description matches what we've checked out...
        return self.check_build(builder.db.root_path,
                                stamp.checkouts,
                                builder.muddle_binary)

    def _domain_path(self, root_path, domain_name):
        """Turn a domain name into its path.

        Perhaps should be in utils.py...
        """
        return os.path.join(root_path, utils.domain_subpath(domain_name))

    def restore_stamp(self, builder, current_dir, domains, checkouts):
        """
        Given the information from our stamp file, restore things.
        """
        domain_names = domains.keys()
        domain_names = sort_domains(domain_names)
        for domain_name in domain_names:
            domain_repo, domain_desc = domains[domain_name]

            print "Adding domain %s"%domain_name

            # Take care to allow for multiple parts
            # Thus domain 'fred(jim)' maps to <root>/domains/fred/domains/jim
            domain_root_path = self._domain_path(current_dir, domain_name)

            os.makedirs(domain_root_path)

            domain_builder = mechanics.minimal_build_tree(builder.muddle_binary,
                                                          domain_root_path,
                                                          domain_repo, domain_desc)

            # Tell the domain's builder that it *is* a domain
            domain_builder.mark_domain(domain_name)

        co_labels = checkouts.keys()
        co_labels.sort()
        for label in co_labels:
            co_dir, co_leaf, repo = checkouts[label]
            if label.domain:
                domain_root_path = self._domain_path(current_dir, label.domain)
                print "Unstamping checkout (%s)%s"%(label.domain,label.name)
                if co_dir:
                    actual_co_dir = os.path.join(domain_root_path, 'src', co_dir)
                else:
                    actual_co_dir = os.path.join(domain_root_path, 'src')
                checkout_from_repo(builder, label, repo, actual_co_dir, co_leaf)
            else:
                print "Unstamping checkout %s"%label.name
                checkout_from_repo(builder, label, repo, co_dir, co_leaf)


            # Then need to mimic "muddle checkout" for it
            new_label = label.copy_with_tag(LabelTag.CheckedOut)
            builder.build_label(new_label, silent=False)

    def update_from_stamp(self, builder, domains, checkouts):
        """
        Given the information from our stamp file, update the current build.
        """
        domain_names = domains.keys()
        domain_names = sort_domains(domain_names)
        root_path = builder.db.root_path
        for domain_name in domain_names:
            domain_repo, domain_desc = domains[domain_name]

            # Take care to allow for multiple parts
            # Thus domain 'fred(jim)' maps to <root>/domains/fred/domains/jim
            domain_root_path = self._domain_path(root_path, domain_name)

            if not os.path.exists(domain_root_path):
                print "Adding domain %s"%domain_name
                os.makedirs(domain_root_path)
                domain_builder = mechanics.minimal_build_tree(builder.muddle_binary,
                                                              domain_root_path,
                                                              domain_repo, domain_desc)
                # Tell the domain's builder that it *is* a domain
                domain_builder.mark_domain(domain_name)

        co_labels = checkouts.keys()
        co_labels.sort()
        changed_checkouts = []

        get_checkout_repo = builder.db.get_checkout_repo

        for label in co_labels:
            # Determine if the checkout has changed, and if so, update its
            # information and add its label to the list of changed checkouts.
            co_dir, co_leaf, repo = checkouts[label]
            if label.domain:
                domain_root_path = self._domain_path(root_path, label.domain)
                print "Inspecting checkout (%s)%s"%(label.domain,label.name)
                if co_dir:
                    actual_co_dir = os.path.join(domain_root_path, 'src', co_dir)
                else:
                    actual_co_dir = os.path.join(domain_root_path, 'src')
            else:
                print "Inspecting checkout %s"%label.name
                if co_dir:
                    actual_co_dir = os.path.join(root_path, 'src', co_dir)
                else:
                    actual_co_dir = os.path.join(root_path, 'src')

            if not os.path.exists(os.path.join(actual_co_dir, co_leaf)):
                # First check - do we have a directory for the checkout?
                # No, we've never heard of it. So add it in...
                print 'No directory for %s: %s'%(label, os.path.join(actual_co_dir, co_leaf))
                checkout_from_repo(builder, label, repo, actual_co_dir, co_leaf)
                changed_checkouts.append(str(label))
            else:
                # It's there. Does it match?
                #
                # XXX Ideally, we'd have way to get the "effective" repository
                # XXX information for this checkout in the current build,
                # XXX including its actual revision and branch, so we could
                # XXX compare that directly. For the moment, we have to do
                # XXX it in stages...
                #
                print 'Found directory for %s - checking repositories'%label
                builder_repo = get_checkout_repo(label)
                if not builder_repo.same_ignoring_revision(repo):
                    # It's not the identical repository.
                    print '..repositories do not match'
                    print '  build: %r'%builder_repo
                    print '  stamp: %r'%repo
                    # Overwrite its information
                    checkout_from_repo(builder, label, repo, actual_co_dir, co_leaf)
                    changed_checkouts.append(str(label))
                else:
                    l = label.copy_with_tag(LabelTag.CheckedOut)
                    try:
                        vcs_handler = builder.db.get_checkout_vcs(l)
                    except AttributeError:
                        raise GiveUp("Rule for label '%s' has no VCS - cannot find its id"%l)
                    old_revision = vcs_handler.revision_to_checkout(builder, l, show_pushd=False)
                    new_revision = repo.revision
                    if old_revision != new_revision:
                        print '.. revisions do not match'
                        print '   build: %s'%old_revision
                        print '   stamp: %s'%new_revision
                        # Overwrite its information
                        checkout_from_repo(builder, label, repo, actual_co_dir, co_leaf)
                        changed_checkouts.append(str(label))

        # Then use "muddle pull" to update them - this has the advantage
        # of reporting problems properly, and also updates _just_pulled
        # for us. NB: We *could* propagate a '-stop' switch if we cared,
        # but currently we don't provide such...
        had_problems = False
        if changed_checkouts:
            print 'Updating the changed checkouts'
            try:
                p = Pull()
                # Demand that it just pulls the labels we give it, without
                # trying to pull any build descriptions first. If we pull the
                # build description *and reload it* then we will lose the build
                # tree we have lovingly created above, which rather defeats
                # the purpose.
                p.with_build_tree(builder, root_path, ['-noreload'] + changed_checkouts)
            except GiveUp as e:
                had_problems = True

        if had_problems:
            # Do we need the message? Or should we just raise GiveUp()
            # (to set the muddle exit code) as "muddle pull" itself does.
            raise GiveUp('Problems occurred updating some of the checkouts')

    def check_build(self, current_dir, checkouts, muddle_binary):
        """
        Check that the build tree we now have on disk looks a bit like what we want...
        """
        # So reload as a "new" builder
        print
        print 'Checking that the build is restored correctly...'
        print
        (build_root, build_domain) = utils.find_root_and_domain(current_dir)

        b = mechanics.load_builder(build_root, muddle_binary, default_domain=build_domain)

        qr = QueryRoot()
        qr.with_build_tree(b, current_dir, None)

        qc = QueryCheckouts()
        qc.with_build_tree(b, current_dir, [])

        # Check our checkout labels match
        s_checkouts = set(checkouts.keys())
        b_checkouts = b.all_checkout_labels(LabelTag.CheckedOut)
        s_difference = s_checkouts.difference(b_checkouts)
        b_difference = b_checkouts.difference(s_checkouts)
        if s_difference or b_difference:
            print 'There is a mismatch between the checkouts in the stamp' \
                  ' file and those in the build'
            if s_difference:
                print 'Checkouts only in the stamp file:'
                for label in s_difference:
                    print '    %s'%label
            if b_difference:
                print 'Checkouts only in the build:'
                for label in b_difference:
                    print '    %s'%label
            return 4
        else:
            print
            print '...the checkouts present match those in the stamp file.'
            print 'The build looks as if it restored correctly.'

# -----------------------------------------------------------------------------
# Distribute
# -----------------------------------------------------------------------------
@command('distribute', CAT_EXPORT)
class Distribute(CPDCommand):
    """
    :Syntax: muddle distribute [<switches>|-no-muddle-makefile] <name> <target_directory> [<label> ...]

    - <switches> may be any of:

        * -with-versions
        * -with-vcs
        * -no-muddle-makefile

      See below for more information on each.

    - <name> is a distribution name.

      Several special distribution names exist:

        * "_source_release" is a distribution of all checkouts, without their
          VCS directories.

          "muddle distribute _source_release" is typically useful for
          generating a directory to archive with tar and send out as a
          source code release.

          "muddle distribute -with-vcs _source_release" is a way to get a
          "clean copy" of the current build tree, although perhaps not as clean
          as starting over again from "muddle init",

        * "_binary_release" - this is a distribution of all the install
          directories, as well as the build description checkout(s) implied by
          the packages distributed and (unless -no-muddle-makefiles is given)
          the muddle Makefiles needed by each package (as the only file in
          each appropriate checkout directory)

        * "_deployment" - this is a distribution of the deploy directory,
          and all its subdirectories, as well as a version stamp. It can be
          useful for customers who do not yet have the ability to use muddle
          (as is necessary with a _binary_release).

          It is generally necessary to specify the deployment labels as
          <label> arguments, and the labels used will be written to a
          MANIFEST.txt file.

          Note that it is done by a different mechanism than the other
          commands, specificaly more or less as if the user had done::

              muddle deploy <label> ...
              mkdir -p <target_directory>
              cp -a deploy <target_directory>
              muddle stamp save <target_directory>/`muddle query name`.stamp
              cat "muddle distribute _deployment <target_directory> <labels>" \
                      > <target_directory>/MANIFEST.txt

          Consequently, the switches are not allowed with this variant.

        * "_for_gpl" is a distribution that satisfies the GPL licensing
          requirements. It is all checkouts that have an explicit GPL
          license (including LGPL), plus any licenses which depend on them,
          and do not explicitly state that they do not need distributing
          under the GPL terms, plus appropriate build descriptions.

          It will fail if "propagated" GPL-ness clashes with declared "binary"
          or "private" licenses for any checkouts.

        * "_all_open" is a distribution of all open-source licensed checkouts.
          It contains everything from "_for_gpl", plus any other open source
          licensed checkouts.

          It will fail for the same reasons that _for_gpl" fails.

        * "_by_license" is a distribution of everything that is not licensed
          with a "private" license. It is equivalent to "_all_open" plus
          any proprietary source checkouts plus those parts of a
          "_binary_release" that are not licensed "private".

          It will fail if "_all_open" would fail, or if any of the install
          directories to be distributed could contain results from building
          "private" packages (as determined by which packages are in the
          appropriate role).

    - <target_directory> is where to distribute to. If it already exists,
      it should preferably be an empty directory.

    - If given, each <label> is a label fragment specifying a deployment,
      package or checkout, or one of _all and friends. The <type> defaults
      to "deployment". See "muddle help labels" for more information.

    If specific labels are given, then the distribution will only concern those
    labels and those they depend on. Deployment labels will be expanded to all
    of the packages that the deployment depends upon. Package labels (including
    those implied by deployment labels) will be remembered, and also expanded
    to the checkouts that they depend directly upon. Checkout labels (including
    those implied by packages) will be remembered. When the distribution is
    calculated, only packages and checkouts that have been remembered will be
    candidates for distribution.

    If no labels are given, then the whole of the build tree is considered.

    If the -with-versions switch is specified, then if there is a stamp
    "versions/" directory it will also be copied. By default it is not.

    If the -with-vcs switch is specified, then VCS "special" files (that is,
    ".git", ".gitignore", ".gitmodules" for git, and so on) are requested:

      - for the build description directories
      - for the "versions/" directory, if it is being copied
      - to all checkouts in a "_source_release" distribution

    It does not apply to checkouts specified with "distribute_checkout" in
    the build description, as they use the "copy_vcs_dirs" argument to that
    function instead.

    If the -no-muddle-makefile switch is specified, then the _binary_release
    distribution will not include Muddle makefiles for each package
    distributed. It does not override the setting of the "with_muddle_makefile"
    argument explicitly set in any calls of "distribute_package" in the build
    description, nor does it stop distribution of any extra files explicitly
    chosen with "distribute_checkout_files" in the build description. It also
    does not affect the "_by_license" distribution.

    Note that "muddle -n distribute" can be used in the normal manner to see
    what the command would do. It shows the labels that would be distributed,
    and the actions that would be used to do so. This is especially useful for
    the "_source_release" and "_binary_release" commands. Output will typically
    be something like::

        $ m3 -n distribute -with-vcs _binary_release ../fred
        Writing distribution _binary_release to ../fred
        checkout:builds/distributed        DistributeBuildDescription: _binary_release[vcs]
        checkout:main_co/distributed       DistributeCheckout: _binary_release[1], role-x86[*]
        package:main_pkg{arm}/distributed  DistributePackage: _binary_release[install]
        package:main_pkg{x86}/distributed  DistributePackage: _binary_release[install], role-x86[obj,install]

    * For each action, all the available distribution names are listed.
    * Each distribution name may be followed by values in [..], depending on
      what action it is associated with.
    * For a DistributeBuildDescription, the value may be [vcs], or [-<n>], or
      [vcs, -<n>]. 'vcs' means that VCS files will be distributed. A negative
      number indicates the number of "private" files that will not be
      distributed.
    * For a DistributeCheckout, the values are [*], [<n>], [*,vcs] or [<n>,vcs].
      '*' means that all files will be distributed, a single integer (<n>) that
      just that many specific files have been selected for distribution. [1]
      typically means the muddle Makefile, or perhaps a license file. A 'vcs'
      means that the VCS files will be distributed.
    * For a DistributePackage, the values are [obj], [install] or [obj,install],
      indicating if "obj" or "install" directories are being distributed. It's
      also possible (but not much use) to have a DistributePackage distribution
      name that doesn't do either.

    See also "muddle query checkout-licenses" for general information on the
    licenses in the current build, and "muddle query role-licenses" for how
    licenses are distributed between the roles in the build. Both of these
    will report on license clashes that appear to exist.

    BEWARE: THIS COMMAND IS STILL NEW, AND DETAILS MAY CHANGE

        In particular, the "-no-muddle-makefile" switch may go away, the
        details of use of the "-copy-vcs" switch may change. and the standard
        distribution names may change.
    """

    allowed_switches = {'-with-vcs':'with-vcs',
                        '-with-versions':'with-versions',
                        '-no-muddle-makefile':'no-muddle-makefile'}

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        """We're sufficiently unlike other commands to do this ourselves.
        """
        name = None
        target_dir = None

        args = self.remove_switches(args)

        with_versions_dir = ('with-versions' in self.switches)
        with_vcs = ('with-vcs' in self.switches)
        no_muddle_makefile = ('no-muddle-makefile' in self.switches)
        fragments = []

        while args:
            word = args[0]
            args = args[1:]
            if word.startswith('-'):
                raise GiveUp("Unexpected switch '%s' for 'distribute'"%word)
            elif name is None:
                name = word
            elif target_dir is None:
                target_dir = word
            else:
                fragments.append(word)

        if name is None or target_dir is None:
            raise GiveUp("Syntax: muddle distribute [<switches>] <name> <target_directory>")

        if name == '_deployment':
            self.deployment(builder, current_dir, target_dir, fragments)
            return

        if fragments:
            co_labels, pkg_labels = self.decode_args(builder, fragments, current_dir)
            #print 'Package labels chosen:', label_list_to_string(pkg_labels, join_with=', ')
            #print 'Checkout labels chosen:', label_list_to_string(co_labels, join_with=', ')
        else:
            pkg_labels = None
            co_labels = None

        distribute(builder, name, target_dir,
                   with_versions_dir=with_versions_dir,
                   with_vcs=with_vcs,
                   no_muddle_makefile=no_muddle_makefile,
                   no_op=self.no_op(),
                   package_labels=pkg_labels, checkout_labels=co_labels)

    def interpret_labels(self, builder, args, initial_list):
        """Return selected packages and checkouts.
        """
        potential_problems = []
        package_set = set()
        checkout_set = set()
        default_roles = builder.default_roles
        for index, label in enumerate(initial_list):
            if label.type == LabelType.Package:
                # If they specify a package, then we want that package and
                # also all the checkouts that it (directly) depends on
                package_set.add(label.copy_with_tag('*'))
                checkouts = builder.checkouts_for_package(label)
                if checkouts:
                    for co_label in checkouts:
                        checkout_set.add(co_label.copy_with_tag('*'))
            elif label.type == LabelType.Checkout:
                checkout_set.add(label.copy_with_tag(LabelTag.CheckedOut))
            elif label.type == LabelType.Deployment:
                # If they specified a deployment label, then find all the
                # packages that depend on this deployment.
                # Here I think we definitely want any depth of dependency.
                # XXX I don't think we need to specify useMatch=True, because we
                # XXX should already have expanded any wildcards
                rules = depend.needed_to_build(builder.ruleset, label)
                found = False
                for r in rules:
                    l = r.target
                    if l.type == LabelType.Package:
                        # If they specify a package, then we want that package and
                        # also all the checkouts that it (directly) depends on
                        package_set.add(l.copy_with_tag('*'))
                        checkouts = builder.checkouts_for_package(l)
                        if checkouts:
                            for co_label in checkouts:
                                checkout_set.add(co_label.copy_with_tag('*'))
                    elif l.type == LabelType.Checkout:
                        # Can this happen?
                        checkout_set.add(l.copy_with_tag('*'))
                if not found:
                    potential_problems.append('  Deployment %s does not use any packages'%label)
            else:
                raise GiveUp("Cannot cope with label '%s', from arg '%s'"%(label, args[index]))

        if not package_set and not checkout_set:
            text = []
            if len(initial_list) == 1:
                text.append('Label %s exists, but does not give'
                             ' a target for "muddle %s"'%(initial_list[0], self.cmd_name))
            else:
                text.append('The labels\n  %s\nexist, but none gives a'
                            ' target for "muddle %s"'%(label_list_to_string(initial_list,
                                join_with='\n  '), self.cmd_name))
            if potential_problems:
                text.append('Perhaps because:')
                for problem in potential_problems:
                    text.append('%s'%problem)
            raise GiveUp('\n'.join(text))

        return checkout_set, package_set

    def deployment(self, builder, current_dir, target_dir, fragments):
        """Do "muddle distribute _deployment".
        """
        if self.switches:
            raise GiveUp('"muddle distribute _deployment" does not take any of the normal'
                         ' "muddle distribute" switches')

        # As it says in the help text...
        deploy = Deploy()
        deploy.with_build_tree(builder, current_dir, fragments)
        os.makedirs(target_dir)
        utils.copy_without(os.path.join(builder.db.root_path, 'deploy'),
                           os.path.join(target_dir, 'deploy'),
                           preserve=True)   # definitely want to preserve executable flag
        stamper = StampSave()
        stamper.with_build_tree(builder, current_dir,
                                [os.path.join(target_dir, '%s.stamp'%(builder.build_name))])
        with open(os.path.join(target_dir, "MANIFEST.txt"), 'w') as fd:
            fd.write("muddle distribute _deployment %s %s\n"%(target_dir, ' '.join(fragments)))

# -----------------------------------------------------------------------------
# Release
# -----------------------------------------------------------------------------

@command('release', CAT_EXPORT)
class Release(Command):
    """
    Produce a customer release from a release stamp file.

    :Syntax: muddle release <release-file>
    :or:     muddle release -test <release-file>

    For example::

      $ muddle release project99-1.2.3.release

    This:

    1. Checks the current directory is empty, and refuses to proceed if it
       is not.

       We always recommend doing ``muddle init`` or ``muddle bootstrap`` in an
       empty directory, but muddle insists that ``muddle release`` must be done
       in an empty directory.

    2. Does ``muddle unstamp <release-file>``,

    3. Copies the release file to ``.muddle/Release``.

       The existence of this file indicates that this is a release build tree,
       and "normal" muddle will refuse to build in it.

    4. Copies the release specification to ``.muddle/ReleaseSpec``.

    5. Sets some extra environment variables, which can be used in the normal
       manner in muddle Makefiles:

       * ``MUDDLE_RELEASE_NAME`` is the release name, from the release file.
       * ``MUDDLE_RELEASE_VERSION`` is the release version, from the release
         file.
       * ``MUDDLE_RELEASE_HASH`` is the SHA1 hash of the release file

       "Normal" muddle will also create those environment variables, but they
       will be set to ``(unset)``.

    6. Does ``mudddle build _release``.

       The meaning of "_release" is defined in the build description, using
       ``builder.add_to_release_build()``. See::

           $ muddle doc mechanics.Builder.add_to_release_build

       for more information on that method, and "muddle query release" for the
       current setting.

       Note that, if youi have subdomains, only calls of
       ``add_to_release_build()`` in the top-level build description  will be
       effective.

    7. Creates the release directory, which will be called
       ``<release-name>_<release-version>_<release-sha1>``.
       It copies the release file therein.

    8. Calls the ``release_from(builder, release_dir)`` function in the build
       description, which is responsible for copying across whatever else needs
       to be put into the release directory.

       (Obviously it is an error if the build description does not have such
       a function.)

       Note that, if you have subdomains, only the ``release_from()`` function
       in the top-level build will be called.

    9. Creates a compressed tarball of the release directory, using the
       compression mechanism specified in the release file. It will have
       the same basename as the release directory.

    If the -test switch is given, then items 1..2 are not done. This allows
    testing a release build in the current build directory. The produce of
    such a test *must not* be treated as a proper release, as it has not
    involved a clean build of the build tree. Note that if you want to make
    your build tree back into a normal muddle build tree, then you will need
    to delete the .muddle/Release file yourself, by hand.
    """

    allowed_switches = {'-test':'test'}

    def requires_build_tree(self):
        # We have to say that we do allow this command in a build tree,
        # because we do if we have the '-test' switch (and this method
        # is called before post-command switches are interpreted)
        return False

    def with_build_tree(self, builder, current_dir, args):
        args = self.remove_switches(args)
        if 'test' not in self.switches:
            raise GiveUp("A real release cannot be done within a build tree.\n"
                         "Use 'muddle release -test' if you're trying to test a release.")

        if len(args) != 1:
            print 'Syntax: muddle release [-test] <release-file>'
            return 2

        self.do_release(builder.muddle_binary, current_dir, args[0], True)

    def without_build_tree(self, muddle_binary, current_dir, args):

        args = self.remove_switches(args)

        if 'test' in self.switches:
            raise GiveUp("'muddle release -test' can only be done in a build tree")

        if len(args) != 1:
            print 'Syntax: muddle release [-test] <release-file>'
            return 2

        self.do_release(muddle_binary, current_dir, args[0], False)


    def do_release(self, muddle_binary, current_dir, release_file, testing):

        # Check we can read the release file as such
        release = ReleaseStamp.from_file(release_file)

        # Are we a proper release build?
        if not testing:
            # Check the current directory is empty
            if len(os.listdir(current_dir)):
                raise GiveUp('Cannot release into %s, it is not empty'%current_dir)

            # Let the unstamp command do the unstamping for us...
            unstamp = UnStamp()
            unstamp.unstamp_from_stamp(muddle_binary, current_dir, release)

        # Immediately mark ourselves as a release build by copying the release
        # file into the .muddle directory. Some muddle commands will refuse to
        # work in a release build.
        shutil.copyfile(release_file, os.path.join(current_dir, '.muddle', 'Release'))

        # Also store our release spec in a simple format - this is hopefully
        # rather quicker to re-read (every muddle command!) than the actual
        # release stamp file
        release.release_spec.write_to_file(os.path.join(current_dir, '.muddle', 'ReleaseSpec'))

        # Next do "muddle build _release"
        builder = mechanics.load_builder(current_dir, muddle_binary)
        build_cmd = Build()
        build_cmd.with_build_tree(builder, current_dir, ['_release'])

        # Create the directory from which the release tarball will be created
        release_dir = '%s_%s_%s'%(release.release_spec.name,
                                  release.release_spec.version,
                                  release.release_spec.hash)
        release_path = os.path.join(current_dir, release_dir)

        # If we're doing 'muddle release -test', it is possible that that
        # directory might already exist, from a previous attempt
        if os.path.isdir(release_path):
            raise GiveUp('Release directory %s already exists'%release_dir)

        print 'Creating %s'%release_path
        os.mkdir(release_path)
        # And we always want the release stamp file in the release tarball
        release_filename = os.path.split(release_file)[-1]
        shutil.copyfile(release_file, os.path.join(release_dir, release_filename))

        # Call the 'release_from()' function in our (top level) build
        # description, passing it the path to the release tarball directory
        print 'Running the "release_from" function...'
        mechanics.run_release_from(builder, release_path)

        # Finally, tar up the tarball directory, and then compress it
        print 'Making the tarball'
        tf_name, mode = self.calc_tf_name(release, release_dir)
        tf = tarfile.open(tf_name, mode)
        tf.add(release_dir, recursive=True)
        tf.close()

        if testing:
            print
            print '********************************************************'
            print '* This build tree is now marked as a release tree.      *'
            print '* This means various muddle operations are not allowed. *'
            print '* To make it a normal build tree again, do:             *'
            print '*   rm .muddle/Release                                  *'
            print '********************************************************'

    def calc_tf_name(self, release, release_dir):
        """Work out the name and mode of the archive file we want to generate.
        """
        if release.release_spec.compression == 'gzip':
            tf_name = '%s.tgz'%release_dir
            mode = 'w:gz'
        elif release.release_spec.compression == 'bzip2':
            tf_name = '%s.tar.bz2'%release_dir        # is this the best name?
            mode = 'w:bz2'
        else:
            tf_name = '%s.tar'%release_dir          # should never happen
            mode = 'w'                              # but better than crashing...
        return tf_name, mode


# =============================================================================
# Checkout, package and deployment commands
# =============================================================================
# -----------------------------------------------------------------------------
# Deployment commands
# -----------------------------------------------------------------------------
@command('redeploy', CAT_DEPLOYMENT)
class Redeploy(DeploymentCommand):
    """
    :Syntax: muddle redeploy [<deployment> ... ]

    Clean the named deployments (deleting their 'deploy/' directory), remove
    their '/deployed' tags, and then rebuild (deploy) them.

    This is exactly equivalent to doing "muddle cleandeploy" for all the
    labels, followed by "muddle deploy" for them all.

    <deployment> should be a label fragment specifying a deployment, or one of
    _all and friends, as for any deployment command. The <type> defaults to
    "deployment", and the deployment <tag> will be "/deployed". See "muddle
    help labels" for more information.

    If no deployments are named, what we do depends on where we are in the
    build tree. See "muddle help labels".
    """

    def build_these_labels(self, builder, labels):
        build_a_kill_b(builder, labels, LabelTag.Clean, LabelTag.Deployed)
        build_labels(builder, labels)

@command('cleandeploy', CAT_DEPLOYMENT)
class Cleandeploy(DeploymentCommand):
    """
    :Syntax: muddle cleandeploy [<deployment> ... ]

    Clean the named deployments, and remove their '/deployed' tags.

    Note that this also deletes the 'deploy/<deployment>' directory for each
    deployment named (but it does not delete the overall 'deploy/' directory).

    It also sets the 'clean' tag for each deployment.

    <deployment> should be a label fragment specifying a deployment, or one of
    _all and friends, as for any deployment command. The <type> defaults to
    "deployment", and the deployment <tag> will be "/clean". See "muddle help
    labels" for more information.

    If no deployments are named, what we do depends on where we are in the
    build tree. See "muddle help labels".
    """

    def build_these_labels(self, builder, labels):
        build_a_kill_b(builder, labels, LabelTag.Clean, LabelTag.Deployed)

@command('deploy', CAT_DEPLOYMENT)
class Deploy(DeploymentCommand):
    """
    :Syntax: muddle deploy <deployment> [<deployment> ... ]

    Build (deploy) the named deployments.

    <deployment> should be a label fragment specifying a deployment, or one of
    _all and friends, as for any deployment command. The <type> defaults to
    "deployment", and the deployment <tag> will be "/deployed". See "muddle
    help labels" for more information.

    If no deployments are named, what we do depends on where we are in the
    build tree. See "muddle help labels".
    """

    def build_these_labels(self, builder, labels):
        build_labels(builder, labels)

# -----------------------------------------------------------------------------
# Package commands
# -----------------------------------------------------------------------------

@command('configure', CAT_PACKAGE)
class Configure(PackageCommand):
    """
    :Syntax: muddle configure [ <package> ... ]

    Configure packages.

    <package> should be a label fragment specifying a package, or one of
    _all and friends, as for any package command. The <type> defaults to
    "package", and the package <tag> will be "/configured". See "muddle help
    labels" for more information.

    If no packages are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    What is done depends upon the tags set for the package:

    1. If the package has not yet been preconfigured, any preconfigure
       actions will be done.
    2. If the package has not yet been configured, then it will be
       configured. This normally involves performing the actions for
       the "config" target in the muddle Makefile.
    """

    required_tag = LabelTag.Configured

    def build_these_labels(self, builder, labels):
        build_labels(builder, labels)

@command('reconfigure', CAT_PACKAGE)
class Reconfigure(PackageCommand):
    """
    :Syntax: muddle reconfigure [ <package> ... ]

    Reconfigure packages. Just like configure except that we clear any
    '/configured' tags first (and their dependencies).

    <package> should be a label fragment specifying a package, or one of
    _all and friends, as for any package command. The <type> defaults to
    "package", and the package <tag> will be "/configured". See "muddle help
    labels" for more information.

    If no packages are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    1. For each label, clear its '/configured' tag, and then clear the tags for
       all the labels that depend on it. Note that this will include the same
       label with its '/built', '/installed' and '/postinstalled' tags.
    2. Do "muddle configure" for each label.
    """

    required_tag = LabelTag.Configured

    def build_these_labels(self, builder, labels):
        # OK. Now we have our labels, retag them, and kill them and their
        # consequents
        kill_labels(builder, labels)
        build_labels(builder, labels)

@command('build', CAT_PACKAGE)
class Build(PackageCommand):
    """
    :Syntax: muddle build [ <package> ... ]

    Build packages.

    <package> should be a label fragment specifying a package, or one of
    _all and friends, as for any package command. The <type> defaults to
    "package", and the package <tag> will be "/postinstalled". See "muddle help
    labels" for more information.

    If no packages are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    What is done depends upon the tags set for the package:

    1. If the package has not yet been preconfigured, any preconfigure
       actions will be done (for most packages, this is an empty step).
    2. If the package has not yet been configured, then it will be
       configured. This normally involves performing the actions for
       the "config" target in the muddle Makefile.
    3. If the package has not yet been built, then it will be built.
       This normally involves performing the actions for the "all" target
       in the muddle Makefile.
    4. If the package has not yet been installed, then it will be installed.
       This normally involves performing the actions for the "install" target
       in the muddle Makefile.
    5. If the package has not yet been post-installed, then it will be
       post-installed (for most packages, this is an empty step).

    Steps 1. and 2. are identical to those in "muddle configure".

    This sequence is why a dependency on a package should normally be made
    on package:<name>{<role>}/postinstalled - that is the final stage of
    building any package.
    """

    def build_these_labels(self, builder, labels):
        build_labels(builder, labels)

@command('rebuild', CAT_PACKAGE)
class Rebuild(PackageCommand):
    """
    :Syntax: muddle rebuild [ <package> ... ]

    Rebuild packages. Just like build except that we clear any '/built' tags
    first (and their dependencies).

    <package> should be a label fragment specifying a package, or one of
    _all and friends, as for any package command. The <type> defaults to
    "package", and the package <tag> will be "/postinstalled". See "muddle
    help labels" for more information.

    If no packages are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    1. For each label, clear its '/built' tag, and then clear the tags for all
       the labels that depend on it. Note that this will include the same
       label with its '/installed' and '/postinstalled' tags.
    2. For each label, build its '/postinstalled' tag (so essentially, do
       the equivalent of "muddle build").
    """

    def build_these_labels(self, builder, labels):
        # OK. Now we have our labels, retag them, and kill them and their
        # consequents
        to_kill = depend.retag_label_list(labels, LabelTag.Built)
        kill_labels(builder, to_kill)
        build_labels(builder, labels)

@command('reinstall', CAT_PACKAGE)
class Reinstall(PackageCommand):
    """
    :Syntax: muddle reinstall [ <package> ... ]

    Reinstall packages (but don't rebuild them).

    <package> should be a label fragment specifying a package, or one of
    _all and friends, as for any package command. The <type> defaults to
    "package", and the package <tag> will be "/postinstalled". See "muddle
    help labels" for more information.

    If no packages are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    1. For each label, clear its '/installed' tag, and then clear the tags for
       all the labels that depend on it. Note that this will include the same
       label with its '/postinstalled' tag.
    2. For each label, build its '/postinstalled' tag (so essentially, do
       the equivalent of "muddle build").
    """

    def build_these_labels(self, builder, labels):
        # OK. Now we have our labels, retag them, and kill them and their
        # consequents
        to_kill = depend.retag_label_list(labels, LabelTag.Installed)
        kill_labels(builder, to_kill)
        build_labels(builder, labels)

@command('distrebuild', CAT_PACKAGE)
class Distrebuild(PackageCommand):
    """
    :Syntax: muddle distrebuild [ <package> ... ]

    A rebuild that does a distclean before attempting the rebuild.

    <package> should be a label fragment specifying a package, or one of
    _all and friends, as for any package command. The <type> defaults to
    "package", and the package <tag> will be "/postinstalled". See "muddle help
    labels" for more information.

    If no packages are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    1. Do a "muddle distclean" for all the labels
    2. Do a "muddle build" for all the labels
    """

    def build_these_labels(self, builder, labels):
        build_a_kill_b(builder, labels, LabelTag.DistClean, LabelTag.PreConfig)
        build_labels(builder, labels)

@command('clean', CAT_PACKAGE)
class Clean(PackageCommand):
    """
    :Syntax: muddle clean [ <package> ... ]

    Clean packages. Subsequently, packages are regarded as having been
    configured but not built.

    <package> should be a label fragment specifying a package, or one of
    _all and friends, as for any package command. The <type> defaults to
    "package", and the package <tag> will be "/built". See "muddle help labels"
    for more information.

    If no packages are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    For each label:

    1. Build the label with its tag set to '/clean'. This normally involves
       performing the actions for the "clean" target in the muddle Makefile.
    2. Unset the '/built' tag for the label, and the tags of any labels that
       depend on it. Note that this will include the same label with its
       '/installed' and '/postinstalled' tags.
    """

    # XXX Is this correct?
    required_tag = LabelTag.Built

    def build_these_labels(self, builder, labels):
        build_a_kill_b(builder, labels, LabelTag.Clean, LabelTag.Built)

@command('distclean', CAT_PACKAGE)
class DistClean(PackageCommand):
    """
    :Syntax: muddle distclean [ <package> ... ]

    Distclean packages. Subsequently, packages are regarded as not having been
    configured or built.

    <package> should be a label fragment specifying a package, or one of
    _all and friends, as for any package command. The <type> defaults to
    "package", and the package <tag> will be "/built". See "muddle help labels"
    for more information.

    If no packages are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    For each label:

    1. Build the label with its tag set to '/distclean'. This normally involves
       performing the actions for the "distclean" target in the muddle Makefile.
    2. Unset the '/preconfig' tag for the label, and the tags of any labels that
       depend on it. Note that this will include the same label with its
       '/configured','/built', '/installed' and '/postinstalled' tags.

    Notes:

    * The "distclean" target in the Makefile is independent of the "clean"
      target - "muddle distclean" does not trigger the "clean" target.
    * "muddle distclean" itself does not delete the 'obj/' directory,
      although this is normally sensible. Muddle makefiles are thus
      recommended to do this themselves - for instance::

          .PHONY: distclean
          distclean:
              @rm -rf $(MUDDLE_OBJ)

      It is possible, though, that future versions of muddle might perform
      this deletion.
    """

    # XXX Is this correct?
    required_tag = LabelTag.Built

    def build_these_labels(self, builder, labels):
        build_a_kill_b(builder, labels, LabelTag.DistClean, LabelTag.PreConfig)

@command('changed', CAT_PACKAGE)
class Changed(PackageCommand):
    """
    :Syntax: muddle changed <package> [ <package> ... ]

    Mark packages as having been changed so that they will later be rebuilt by
    anything that needs to.

    <package> should be a label fragment specifying a package, or one of
    _all and friends, as for any package command. The <type> defaults to
    "package", and the package <tag> will be "/built". See "muddle help labels"
    for more information.

    If no packages are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    For each label, unset the '/built' tag for the label, and the tags of any
    labels that depend on it. Note that this will include the same label with
    its '/installed' and '/postinstalled' tags.

    Note that we don't reconfigure (or indeed clean) packages - we just clear
    the tags asserting that they've been built.
    """

    required_tag = LabelTag.Built

    def build_these_labels(self, builder, labels):
        for l in labels:
            builder.kill_label(l)

# -----------------------------------------------------------------------------
# Checkout commands
# -----------------------------------------------------------------------------
@command('commit', CAT_CHECKOUT)
class Commit(CheckoutCommand):
    """
    :Syntax: muddle commit [ <checkout> ... ]

    Commit the specified checkouts to their local repositories.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/changes_committed". See
    "muddle help labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    For a centralised VCS (e.g., Subversion) where the repository is remote,
    this will not do anything. See the update command.
    """

    # XXX Is this correct?
    required_tag = LabelTag.ChangesCommitted

    def build_these_labels(self, builder, labels):
        # Forcibly retract all the updated tags.
        for co in labels:
            builder.kill_label(co)
            builder.build_label(co)

@command('push', CAT_CHECKOUT)
class Push(CheckoutCommand):
    """
    :Syntax: muddle push [-s[top]] [ <checkout> ... ]

    Push the specified checkouts to their remote repositories.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/changes_pushed". See "muddle
    help labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    This updates the content of the remote repositories to match the local
    checkout.

    If '-s' or '-stop' is given, then we'll stop at the first problem,
    otherwise an attempt will be made to process all the checkouts, and any
    problems will be re-reported at the end.

    "muddle push" will refuse to push if the checkout is not on the expected
    branch, either an explicit branch from the build description, or the
    build description branch if we are "following" it, or "master".
    """

    required_tag = LabelTag.ChangesPushed
    allowed_switches = {'-s': 'stop', '-stop':'stop'}

    def build_these_labels(self, builder, labels):

        if 'stop' in self.switches:
            stop_on_problem = True
        else:
            stop_on_problem = False

        problems = []

        for co in labels:
            try:
                builder.db.clear_tag(co)
                builder.build_label(co)
            except GiveUp as e:
                if stop_on_problem:
                    raise
                else:
                    print e
                    problems.append(e)

        if problems:
            print '\nThe following problems occurred:\n'
            for e in problems:
                print str(e).rstrip()
                print
            raise GiveUp()

@command('pull', CAT_CHECKOUT, ['fetch', 'update'])   # we want to settle on one command
class Pull(CheckoutCommand):
    """
    :Syntax: muddle pull [-s[top]] [-noreload] [ <checkout> ... ]

    Pull the specified checkouts from their remote repositories. Any problems
    will be (re)reported at the end.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/pulled". See "muddle help
    labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    For each checkout named, retrieve changes from the corresponding remote
    repository (as described by the build description) and apply them (to
    the checkout), but *not* if a merge would be required.

        (For a VCS such as git, this actually means "not if a user-assisted
        merge would be required" - i.e., fast-forwards will be done.)

    The value "_just_pulled" will be set to the labels of the checkouts
    whose working directories are altered by "muddle pull" or "muddle checkout"
    - i.e., those for which the "pull" or "checkout" operation did something
    tangible. One can then do "muddle rebuild _just_pulled" or "muddle
    distrebuild _just_pulled".

        (The value of _just_pulled is cleared at the start of "muddle pull"
        or "muddle checkout", and set at the end - the list of checkout labels
        is actually stored in the file .muddle/_just_pulled.)

    Normally, "muddle pull" will attempt to pull all the chosen checkouts,
    re-reporting any problems at the end. If '-s' or '-stop' is given, then
    it will instead stop at the first problem.

    How build descriptions are treated specially
    --------------------------------------------
    If the build description is in the list of checkouts that should be
    pulled, either explicitly or after expanding one of _all and friends,
    then "muddle pull" will:

        1. Remember exactly what the user asked for on the command line.
        2. Pull the build description.
        3. If the build description changed (i.e., was pulled), then reload
           it, and re-expand the labels from the command line - so, for
           instance, _all might change if the new build description has
           added or removed checkouts.
        4. Remove the build description from this (new) list of checkouts,
           and pull any that are left.

    Earlier versions of muddle (before v2.5.1) did not do this, which meant
    that one might do "muddle pull _all" and then have to do it again if the
    build description had changed. It was easy to forget to check for this,
    which could leave a build tree not as up-to-date as one might think.

    If you *do* want the older, simpler mechanism, then::

        muddle pull -noreload <arguments>

    can be used, which will just pull the labels on the command line,
    without treating the build description specially.

    What about subdomains?
    ----------------------
    If your build contains subdomains, then all of the subdomain build
    descriptions will be treated specially. Specifically, each requested build
    description is pulled in domain order, reloading the top-level build
    description and re-evaluating the command line each time.

    Other commands
    --------------
    Note that "muddle merge" and "muddle pull-upstream" do not behave in
    this manner, as it is believed that they are used in a more direct
    manner (with explicit labels).
    """

    required_tag = LabelTag.Pulled
    allowed_switches = {'-s': 'stop',
                        '-stop':'stop',
                        '-noreload':'noreload'}

    def build_these_labels(self, builder, labels):

        self.stop_on_problem = 'stop' in self.switches

        do_build_descriptions_first = 'noreload' not in self.switches

        self.problems = []
        self.not_needed  = []

        builder.db.just_pulled.clear()

        try:
            # If we have a single label, we really don't care if it's a build
            # description or not!
            if do_build_descriptions_first and len(labels) > 1:
                builder, labels = self.handle_build_descriptions_first(builder, labels)

            for co in labels:
                self.pull(builder, co)
        finally:
            # Remember to commit the 'just pulled' information, whatever happens
            builder.db.just_pulled.commit()

        just_pulled = builder.db.just_pulled.get_from_disk()
        if just_pulled:
            print '\nThe following checkouts were pulled:\n ',
            print label_list_to_string(sorted(just_pulled), join_with='\n  ')

        if self.not_needed:
            print '\nThe following pulls were not needed:'
            for e in self.not_needed:
                print
                print str(e).rstrip()

        if self.problems:
            print '\nThe following problems occurred:'
            for e in self.problems:
                print
                print str(e).rstrip()
            raise GiveUp()

    def handle_build_descriptions_first(self, builder, labels):
        """Pull our build descriptions before anything else.

        Returns:

        * the new top-level builder
        * an amended list of the checkout labels still to pull.
        """
        # This is slow because of the continual delete files, reload build
        # description, recalculate arguments cycle. On the other hand, most
        # pull commands will only have at most one build description in them,
        # so it's not *very* slow.

        # Work out our build description checkout labels, ignoring any that
        # have just been pulled (which is none so far)
        build_desc_labels = self.calc_build_descriptions(builder)

        # Which of those are in our labels-to-build?
        target_set = set(labels)
        remaining_build_descs = target_set.intersection(build_desc_labels)

        if not remaining_build_descs:               # None, move along now
            return builder, labels

        # Remember where our build tree is based, so we can reload it later on
        build_root = builder.db.root_path

        done = set()
        while remaining_build_descs:
            # Find the first of those (remember, they're in sorted domain order)
            for co in build_desc_labels:
                if co in remaining_build_descs:
                    print
                    print 'Pulling build description %s'%co
                    self.pull(builder, co)
                    # That will have added 'co' to the just_pulled set
                    # *if* it actually changed it.
                    # If it was not changed, we don't need to reload
                    if builder.db.just_pulled.is_pulled(co):
                        # Remember what that 'builder' knew was pulled
                        save_just_pulled = builder.db.just_pulled.labels.copy()
                        # Delete any .pyc files that match .py files - Python
                        # uses a very coarse granularity on its timestamps, so
                        # isn't very good at noticing that a .pyc is older than
                        # the .py. We'll assume that we can ignore any .pyc files
                        # that don't match a .py file (if some mad person has
                        # committed such)
                        self.delete_pyc_files(builder, co)
                        # And reload the *top-level* build description, so that
                        # we guarantee to get the proper version of the world
                        print 'Reloading build description'
                        builder = mechanics.load_builder(build_root, None)
                        # Don't forget what we already pulled - we need to
                        # tell this (new) builder about it
                        builder.db.just_pulled.labels.update(save_just_pulled)
                        # And we can now recalculate the labels implied by our
                        # command line (for instance, "_all" is likely to have
                        # changed its meaning...)
                        labels = self.expand_labels(builder, self.original_labels)
                    # Regardless, we've "done" this checkout
                    done.add(co)
                    # We might have gained or lost domains, too
                    if builder.db.just_pulled.is_pulled(co):
                        build_desc_labels = self.calc_build_descriptions(builder, done)
                    else:
                        build_desc_labels.remove(co)
                    # Recalculate which build descriptions are still asked for
                    # and not yet done
                    remaining_build_descs = target_set.intersection(build_desc_labels)

        # And so to whatever remains...
        target_set = set(labels)
        labels = target_set.difference(done)

        if labels:
            print
            print 'Now pulling the rest of the checkouts'
        return builder, labels

    def label_names(self, labels):
        result = []
        for label in labels:
            result.append(label.middle())
        return ', '.join(result)

    def calc_build_descriptions(self, builder, done=None):
        """Calculate all the build descriptions in this build tree.

        Remove any that have already been 'done'

        Return a list of build description checkout labels, ordered by domain.
        """
        domains = builder.all_domains()
        domains = sort_domains(domains)
        build_desc_labels = []
        for domain in domains:
            label = builder.db.get_domain_build_desc_label(domain)
            label = label.copy_with_tag(self.required_tag)
            build_desc_labels.append(label)

        if done:
            for label in done:
                # We strongly expect the label to be in our list, as the only
                # reason it would not be is if the build description has changed
                # to not include it any more, which we expect to be uncommon
                try:
                    build_desc_labels.remove(label)
                except ValueError:
                    pass

        return build_desc_labels

    def pull(self, builder, co_label):
        """Do the work of pulling checkout 'co_label'
        """
        try:
            # First clear the 'pulled' tag
            builder.db.clear_tag(co_label)
            # And then build it again
            builder.build_label(co_label)
        except Unsupported as e:
            print e
            self.not_needed.append(e)
        except GiveUp as e:
            if self.stop_on_problem:
                raise
            else:
                print e
                self.problems.append(e)

    def delete_pyc_files(self, builder, co_label):
        """Delete .pyc files in this checkout
        """
        top_dir = builder.db.get_checkout_path(co_label)
        for root, dirs, files in os.walk(top_dir):
            for file in files:
                name, ext = os.path.splitext(file)
                # Delete any .pyc file that has a corresponding .py file
                if ext == '.pyc' and name+'.py' in files:
                    print 'Found   ', os.path.join(root, name+'.py')
                    path = os.path.join(root, file)
                    print 'Deleting', path
                    os.remove(path)

@command('merge', CAT_CHECKOUT)
class Merge(CheckoutCommand):
    """
    :Syntax: muddle merge [-s[top]] [ <checkout> ... ]

    Merge the specified checkouts from their remote repositories.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/merged". See "muddle help
    labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    For each checkout named, retrieve changes from the corresponding remote
    repository (as described by the build description) and merge them (into
    the checkout). The merge process is handled in a VCS specific manner,
    as each checkout is dealt with.

    The value "_just_pulled" will be set to the labels of the checkouts
    whose working directories are altered by "muddle merge" - i.e., those
    for which the "merge" operation did something tangible. One can then do
    "muddle rebuild _just_pulled" or "muddle distrebuild _just_pulled".

        (The value of _just_pulled is cleared at the start of "muddle merge",
        and set at the end - the list of checkout labels is actually stored in
        the file .muddle/_just_pulled.)

    If '-s' or '-stop' is given, then we'll stop at the first problem,
    otherwise an attempt will be made to process all the checkouts, and any
    problems will be re-reported at the end.
    """

    required_tag = LabelTag.Merged
    allowed_switches = {'-s': 'stop', '-stop':'stop'}

    def build_these_labels(self, builder, labels):

        if 'stop' in self.switches:
            stop_on_problem = True
        else:
            stop_on_problem = False

        problems = []

        builder.db.just_pulled.clear()

        try:
            for co in labels:
                try:
                    # First clear the 'merged' tag
                    builder.db.clear_tag(co)
                    # And then build it again
                    builder.build_label(co)
                except GiveUp as e:
                    if stop_on_problem:
                        raise
                    else:
                        print e
                        problems.append(e)
        finally:
            # Remember to commit the 'just pulled' information
            builder.db.just_pulled.commit()

        just_pulled = builder.db.just_pulled.get_from_disk()
        if just_pulled:
            print '\nThe following checkouts were pulled/merged:\n ',
            print label_list_to_string(just_pulled, join_with='\n  ')

        if problems:
            print '\nThe following problems occurred:'
            for e in problems:
                print
                print str(e).rstrip()
            raise GiveUp()

@command('status', CAT_CHECKOUT)
class Status(CheckoutCommand):
    """
    :Syntax: muddle status [-v] [-j] [-quick] [ <checkout> ... ]

    Report on the status of checkouts that need attention.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/pulled". See "muddle help
    labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    If '-v' is given, report each checkout label as it is checked (allowing
    a sense of progress if there are many bazaar checkouts, for instance).

    Runs the equivalent of ``git status`` or ``bzr status`` on each repository,
    and tries to only report those which have significant status.

        Note: For subversion and bazaar, the (remote) repository is queried,
        which may be slow. For git, the HEAD of the remote may be queried.

    Be aware that "muddle status" will report on the currently checked out
    checkouts. "muddle status _all" will (attempt to) report on *all* the
    checkouts described by the build, even if they have not yet been checked
    out. This will fail on the first checkout directory it can't "cd" into
    (i.e., the first checkout that isn't there yet).

    This muddle command exits with status 0 if all checkouts appear alright,
    and with status 1 if no checkouts were specified, if an exception occurred,
    or if some checkouts need attention.

    At the end, if any checkouts need attention, their names are reported.
    With '-j', print them all on one line, separated by spaces.

    The '-quick' switch tells muddle not to make any (potentially slow) queries
    across the network, and is only supported for "git". It will only look at
    the local information it already has, which means that the information it
    can gives depends upon whatever was last fetched into the local repository.
    It can typically inform you if there are local updates to be pushed, but
    will not (cannot) warn you if there are commits to be pulled.
    """

    required_tag = LabelTag.CheckedOut
    allowed_switches = {'-v': 'verbose',
                        '-j': 'join',
                        '-quick' : 'quick'
                       }

    # This checkout command *is* allowed in a release build
    def allowed_in_release_build(self):
        return True

    def build_these_labels(self, builder, labels):

        if len(labels) == 0:
            raise GiveUp('No checkouts specified - not checking anything')
        else:
            print 'Checking %d checkout%s'%(len(labels), '' if len(labels)==1 else 's')

        verbose = ('verbose' in self.switches)
        joined = ('join' in self.switches)
        quick = ('quick' in self.switches)

        something = []
        for co in labels:
            if not builder.db.is_tag(co):
                print
                print '%s is not checked out'%co
                something.append(co)
                continue

            try:
                vcs_handler = builder.db.get_checkout_vcs(co)
            except GiveUp:
                print "Rule for label '%s' has no VCS - cannot find its status"%co
                something.append(co)
                continue

            try:
                text = vcs_handler.status(builder, co, verbose, quick=quick)
            except MuddleBug as err:
                raise MuddleBug('Giving up in %s because:\n%s'%(co,err))
            except GiveUp as err:
                print err
                something.append(co)
                continue

            if text:
                print
                print text.strip()
                something.append(co)

        if something:
            if joined:
                raise GiveUp('The following checkouts need attention:\n  '
                             '%s'%(label_list_to_string(something)))
            else:
                raise GiveUp('The following checkouts need attention:\n  '
                             '%s'%(label_list_to_string(something, join_with='\n  ')))
        else:
            print 'All checkouts seemed clean'

@command('reparent', CAT_CHECKOUT)
class Reparent(CheckoutCommand):
    """
    :Syntax: muddle reparent [-f[orce]] [ <checkout> ... ]

    Re-associate the specified checkouts with their remote repositories.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/pulled". See "muddle help
    labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

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
    """

    # XXX Is this what we want???
    required_tag = LabelTag.Pulled
    allowed_switches = {'-f':'force', '-force':'force'}

    # This checkout command *is* allowed in a release build (I think it makes sense)
    def allowed_in_release_build(self):
        return True

    def build_these_labels(self, builder, labels):

        if 'force' in self.switches:
            force = True
        else:
            force = False

        for co in labels:
            try:
                vcs_handler = builder.db.get_checkout_vcs(co)
            except GiveUp:
                print "Rule for label '%s' has no VCS - cannot reparent, ignored"%co
                continue
            vcs_handler.reparent(builder, co, force=force, verbose=True)

@command('uncheckout', CAT_CHECKOUT)
class UnCheckout(CheckoutCommand):
    """
    :Syntax: muddle uncheckout [ <checkout> ... ]

    Tell muddle that the given checkouts no longer exist in the 'src/'
    directory hierarchy, and will need to be checked out again before they
    can be used.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/checked_out". See "muddle help
    labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    For each label, unset the '/checked_out' tag for that label, and the tags
    of any labels that depend on it. Note that this will include all the tags
    for any packages that directly depend on this checkout. However, it will
    not perform any "clean" or "distclean" actions for those packages.

    Note that muddle itself does not check whether the checkout directory
    has been deleted or not. Attempting to do "muddle checkout" for a
    checkout directory that (still) exists will generally fail.
    """

    def build_these_labels(self, builder, labels):
        for c in labels:
            builder.kill_label(c)

@command('unimport', CAT_CHECKOUT)
class Unimport(CheckoutCommand):
    """
    :Syntax: muddle unimport [ <checkout> ... ]

    Assert that the given checkouts haven't been checked out and must therefore
    be checked out.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/checked_out". See "muddle help
    labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    For each label, unset the '/checked_out' tag for that label.

    This command does not do anything to labels that depend on the given
    labels - if you want that, see "muddle removed".

    Note that muddle itself does not check whether the checkout directory
    has been deleted or not. Attempting to do "muddle checkout" for a
    checkout directory that (still) exists will generally fail.
    """

    def build_these_labels(self, builder, labels):
        for c in labels:
            builder.db.clear_tag(c)

@command('import', CAT_CHECKOUT)
class Import(CheckoutCommand):
    """
    :Syntax: muddle import [ <checkout> ... ]

    Assert that the given checkouts (which may include the builds checkout)
    have been checked out.

    This is mainly used when you've just written a package you plan to commit
    to the central repository - muddle obviously can't check it out because the
    repository doesn't exist yet, but you probably want to add it to the build
    description for testing (and in fact you may want to commit it with muddle
    push). For convenience in the expected use case, it goes on to prime the
    relevant VCS module (by way of "muddle reparent") so it can be pushed once
    ready; this should be at worst harmless in all cases.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/checked_out". See "muddle help
    labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    This command is really just a wrapper to "muddle assert" and "muddle
    reparent", with the right magic label names.
    """

    def with_build_tree(self, builder, current_dir, args):
        # We need to remember our arguments
        self.current_dir = current_dir
        self.args = args
        super(Import, self).with_build_tree(builder, current_dir, args)

    def build_these_labels(self, builder, labels):
        for c in labels:
            builder.db.set_tag(c)
        # issue 143: Call reparent so the VCS is locked and loaded.
        rep = Reparent()
        rep.set_options(self.options)
        rep.set_old_env(self.old_env)
        rep.with_build_tree(builder, self.current_dir, self.args)


@command('checkout', CAT_CHECKOUT)
class Checkout(CheckoutCommand):
    """
    :Syntax: muddle checkout [ <checkout> ... ]

    Checks out the specified checkouts.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/checked_out". See "muddle help
    labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    Copies (clones/branches) the content of each checkout from its remote
    repository.

    The value "_just_pulled" will be set to the labels of the checkouts
    whose working directories are altered by "muddle pull" or "muddle checkout"
    - i.e., those for which the "pull" or "checkout" operation did something
    tangible. One can then do "muddle rebuild _just_pulled" or "muddle
    distrebuild _just_pulled".

        (The value of _just_pulled is cleared at the start of "muddle pull"
        or "muddle checkout", and set at the end - the list of checkout labels
        is actually stored in the file .muddle/_just_pulled.)
    """

    def build_these_labels(self, builder, labels):
        builder.db.just_pulled.clear()
        for co in labels:
            builder.build_label(co)

@command('sync', CAT_CHECKOUT)
class Sync(CheckoutCommand):
    """
    :Syntax: muddle sync [ <checkout> ... ]
    :or:     muddle sync [-v[erbose]] [ <checkout> ... ]
    :or:     muddle sync [-show] [ <checkout> ...]

    "Synchronise" each checkout onto the branch it should be on...

    Less succinctly, for each checkout, do the first applicable of the
    following:

    * If this is the top-level build description, then:

      - if it has "builder.follow_build_desc_branch = True", then nothing
        needs to be done, as we're already there.
      - if it does not have "builder.follow_build_desc_branch = True", but
        a branch was specified for it (i.e., via "muddle init -branch"),
        then go to that branch.
      - if it does not have "builder.follow_build_desc_branch = True", and
        no branch was specified (at "muddle init"), then go to "master".

    * If the build description specifies a revision for this checkout,
      go to that revision.
    * If the build description specifies a branch for this checkout,
      and the checkout VCS supports going to a specific branch, go to
      that branch
    * If the build description specifies that this checkout should not
      follow the build description (both Subversion and Bazaar support
      the "no_follow" option), then go to "master".
    * If the build description specifies that this checkout is shallow,
      then give up.
    * If the checkout's VCS does not support lightweight branching, then
      give up (the following choices require this).
    * If the build description has "builder.follow_build_desc_branch = True",
      then go to the same branch as the build description.
    * Otherwise, go to "master".

    With '-v' or '-verbose', report in detail on what the "sync" operation
    is doing, and why.

    With '-show', report on its decision making process, but don't actually
    do anything.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/changes_committed". See
    "muddle help labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".
    """

    # XXX Is this correct?
    required_tag = LabelTag.ChangesCommitted

    allowed_switches = {'-v': 'verbose',
                        '-verbose': 'verbose',
                        '-show': 'show'
                       }

    def build_these_labels(self, builder, labels):

        sync = 'show' not in self.switches
        if sync:
            verbose = 'verbose' in self.switches
        else:
            verbose = True

        for co in labels:
            vcs_handler = builder.db.get_checkout_vcs(co)
            vcs_handler.sync(builder, co, verbose=verbose, sync=sync)

# -----------------------------------------------------------------------------
# Checkout "upstream" commands
# -----------------------------------------------------------------------------
class UpstreamCommand(CheckoutCommand):
    """The parent class for the push/pull-upstream commands.
    """

    required_tag = LabelTag.CheckedOut
    allowed_switches = {}

    verb = 'push'
    verbing = 'Pushing'
    direction = 'to'

    def with_build_tree(self, builder, current_dir, args):
        """Our command line is somewhat differently shaped.

        So we have to handle it ourselves.
        """

        labels = []
        upstream_names = []
        had_upstream_switch = False
        for word in args:
            if word in ('-u', '-upstream'):
                if had_upstream_switch:
                    raise GiveUp('The -upstream switch should only occur once')
                else:
                    had_upstream_switch = True
            elif had_upstream_switch:
                upstream_names.append(word)
            else:
                labels.append(word)

        if labels:
            # Expand out any labels that need it
            labels = self.decode_args(builder, labels, current_dir)
        else:
            # Decide what to do based on where we are
            labels = self.default_args(builder, current_dir)

        if not upstream_names:
            raise GiveUp('"muddle %s" needs at least one upstream name'%self.cmd_name)

        # We promised a sorted list
        labels.sort()

        no_op = self.no_op()
        if no_op:
            print 'Asked to %s:\n  %s'%(self.cmd_name,
                    label_list_to_string(labels, join_with='\n  '))
            print 'for: %s'%(', '.join(upstream_names))
            # And fall through for our method to tell us more

        self.build_these_labels(builder, labels, upstream_names, no_op)

    def do_our_verb(self, builder, co_label, vcs_handler, upstream, repo):
        """Each subclass needs to implement this.
        """
        raise MuddleBug('No "do_our_verb" method provided for command "%s"'%self.cmd_name)

    def build_these_labels(self, builder, labels, upstream_names, no_op):
        get_checkout_repo = builder.db.get_checkout_repo
        get_upstream_repos = builder.db.get_upstream_repos
        for co in labels:
            orig_repo = get_checkout_repo(co)
            upstreams = get_upstream_repos(orig_repo, upstream_names)
            if upstreams:
                # Make sure we've got our checkout checked out (!)
                builder.build_label(co)

                # And then we can do the actual work
                for repo, names in upstreams:
                    if no_op:
                        print 'Would %s %s %s %s (%s)'%(self.verb,
                                co, self.direction, repo, ', '.join(names))
                        continue
                    else:
                        print
                        print '%s %s %s %s (%s)'%(self.verbing,
                                co, self.direction, repo, ', '.join(names))
                        # Arbitrarily use the first of those names as the
                        # name that the VCS (might) remember for this upstream.
                        # Note that get_upstream_repos() tells us the names
                        # will be given to us in sorted order.
                        self.handle_label(builder, co, names[0], repo)

            else:
                if not no_op:
                    print
                print 'Nowhere to %s %s %s'%(self.verb, co, self.direction)

    def handle_label(self, builder, co_label, upstream_name, repo):
        vcs_handler = version_control.vcs_handler_for(builder, co_label)
        self.do_our_verb(builder, co_label, vcs_handler, upstream_name, repo)

@command('push-upstream', CAT_CHECKOUT)
class PushUpstream(UpstreamCommand):
    """
    :Syntax: muddle push-upstream [ <checkout> ... ] -u[pstream] <name> ...

    For each checkout, push to the named upstream repositories.

    This updates the content of the remote repositories to match the local
    checkout.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/checked_out". See "muddle
    help labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    The -u or -upstream switch is required, and must be followed by at least
    one upstream repository name. If a checkout does not have an upstream of
    that name, it will be ignored.

    So, for instance::

        pushd src/checkout1
        muddle push-upstream -u upstream1 upstream2

    or::

        muddle push-upstream package:android{x86} -u upstream-android

    Note that, unlike the normal "muddle push" command, there is no -stop
    switch. Instead, we always stop at the first problem. Not finding an
    upstream with the right name does not count as a "problem" for this
    purpose.

    Use "muddle query upstream-repos [<checkout>]" to find out about the
    available upstream repositories.
    """

    required_tag = LabelTag.CheckedOut
    allowed_switches = {}

    verb = 'push'
    verbing = 'Pushing'
    direction = 'to'

    def do_our_verb(self, builder, co_label, vcs_handler, upstream, repo):
        # And we can then use that to do the push
        # (in the happy knowledge that *it* will grumble if we're not allowed to)
        vcs_handler.push(builder, co_label, upstream=upstream, repo=repo)

@command('pull-upstream', CAT_CHECKOUT)
class PullUpstream(UpstreamCommand):
    """
    :Syntax: muddle pull-upstream [ <checkout> ... ] -u[pstream] <name> ...

    For each checkout, pull from the named upstream repositories.

    Specifically, retrieve changes from the corresponding remote repository,
    and apply them (to the checkout), but *not* if a merge would be required.

        (For a VCS such as git, this actually means "not if a user-assisted
        merge would be required" - i.e., fast-forwards will be done.)

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/checked_out". See "muddle
    help labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    The -u or -upstream switch is required, and must be followed by at least
    one upstream repository name. If a checkout does not have an upstream of
    that name, it will be ignored.

    So, for instance::

        pushd src/checkout1
        muddle pull-upstream -u upstream1 upstream2

    or::

        muddle pull-upstream package:android{x86} -u upstream-android

    Note that, unlike the normal "muddle pull" command, there is no -stop
    switch. Instead, we always stop at the first problem. Not finding an
    upstream with the right name does not count as a "problem" for this
    purpose.

    Also, pull-upstream does not alter the meaning of "_just_pulled".

    Use "muddle query upstream-repos [<checkout>]" to find out about the
    available upstream repositories.
    """

    required_tag = LabelTag.CheckedOut
    allowed_switches = {}

    verb = 'pull'
    verbing = 'Pulling'
    direction = 'from'

    def do_our_verb(self, builder, co_label, vcs_handler, upstream, repo):
        # And we can then use that to do the pull
        # (in the happy knowledge that *it* will grumble if we're not allowed to)
        vcs_handler.pull(builder, co_label, upstream=upstream, repo=repo)

# -----------------------------------------------------------------------------
# AnyLabel commands
# -----------------------------------------------------------------------------
@command('buildlabel', CAT_ANYLABEL)
class BuildLabel(AnyLabelCommand):
    """
    :Syntax: muddle buildlabel <label> [ <label> ... ]

    Performs the appropriate actions to 'build' each <label>.

    Each <label> is a label fragment, in the normal manner. The <type> defaults
    to "package:", and the <tag> defaults to the normal default <tag> for that
    type. Wildcards are expanded.

    <label> may also be "_all", "_default_deployments", "_default_roles" or
    "_just_pulled".

    See "muddle help labels" for more help on label fragments and the "_xxx"
    values.

    Unlikes the checkout, package or deployment specific commands, buildlabel
    does not try to guess what to do based on which directory the command is
    given in. At least one <label> must be specified.

    This command is mainly used internally to build defaults (specifically,
    when you type a bare "muddle" command in the root directory) and the
    privileged half of instruction executions.
    """

    def build_these_labels(self, builder, labels):
        build_labels(builder, labels)

@command('assert', CAT_ANYLABEL)
class Assert(AnyLabelCommand):
    """
    :Syntax: muddle assert <label> [ <label> ... ]

    Assert the given labels.

    This sets the tags indicated by the specified label(s), and only those tags.

    This is *not* the same as if muddle had performed the equivalent "muddle
    buildlabel" command, because setting the "/installed" tag in this way will
    not also set the "/built" (or any other) tag.

    Thus this is mostly for use by experts and scripts.

    Each <label> is a label fragment, in the normal manner. The <type> defaults
    to "package:", and the <tag> defaults to the normal default <tag> for that
    type. Wildcards are expanded.

    <label> may also be "_all", "_default_deployments", "_default_roles" or
    "_just_pulled".

    See "muddle help labels" for more help on label fragments and the "_xxx"
    values.
    """

    def build_these_labels(self, builder, labels):
        for l in labels:
            builder.db.set_tag(l)

@command('retract', CAT_ANYLABEL)
class Retract(AnyLabelCommand):
    """
    :Syntax: muddle retract <label> [ <label> ... ]

    Retract the given labels and their consequents.

    This unsets the tags specified in the given labels, and also the tags for
    all labels which each label depended on. For instance, if the label
    package:fred{x86}/built was given, then package:fred{x86}/configured
    would also be retracted, as /built (normally) depends on /configured for
    the same package.

    This command is mostly for use by experts and scripts.

    Each <label> is a label fragment, in the normal manner. The <type> defaults
    to "package:", and the <tag> defaults to the normal default <tag> for that
    type. Wildcards are expanded.

    <label> may also be "_all", "_default_deployments", "_default_roles" or
    "_just_pulled".

    See "muddle help labels" for more help on label fragments and the "_xxx"
    values.
    """

    def build_these_labels(self, builder, labels):
        for l in labels:
            builder.kill_label(l)

@command('retry', CAT_ANYLABEL)
class Retry(AnyLabelCommand):
    """
    :Syntax: muddle retry <label> [ <label> ... ]

    First this unsets the tags implied by the specified label(s), and only
    those tags. Then it rebuilds the labels.

    Note that unsetting the tags *only* unsets exactly the tags named, and not
    any others.

    This is sometimes useful when you're messing about with package rebuild
    rules.

    Each <label> is a label fragment, in the normal manner. The <type> defaults
    to "package:", and the <tag> defaults to the normal default <tag> for that
    type. Wildcards are expanded.

    <label> may also be "_all", "_default_deployments", "_default_roles" or
    "_just_pulled".

    See "muddle help labels" for more help on label fragments and the "_xxx"
    values.
    """

    def build_these_labels(self, builder, labels):
        print "Clear: %s"%(label_list_to_string(labels))
        for l in labels:
            builder.db.clear_tag(l)

        print "Build: %s"%(label_list_to_string(labels))
        for l in labels:
            builder.build_label(l)

# -----------------------------------------------------------------------------
# Misc commands
# -----------------------------------------------------------------------------
@command('branch-tree', CAT_MISC)        # or perhaps CAT_CHECKOUT
class BranchTree(Command):
    """
    :Syntax: muddle branch-tree [-c[check] | -f[orce]] [-v] <branch>

    Move all checkouts in the build tree (if they support it) to branch
    <branch>.

    This works as follows:

    1. First inspect each checkout, and check if:

       a) the checkout is using a VCS which does not support this operation
          (which probably means it is not using git), or
       b) the build description explicitly specifies a particular revision, or
       c) the build description explicitly specifies a particular branch, or
       d) it is a shallow checkout, in which case there is little point
          branching it as it cannot be pushed, or
       e) the checkout already has a branch of the requested name.

       If any checkouts report problems, then the command will be aborted, and
       muddle will exit with status 1.

    2. Then, branch each checkout as requested, and change to that branch.

    3. Finally, remind the user to add "builder.follow_build_desc_branch = True"
       to the build description.

    If the user specifies "-c" or "-check", omit steps 2 and 3 (i.e., just do
    the checks).

    If the user specifies "-f" or "-force", omit step 1 (i.e., do not do the
    checks), and ignore any checkouts which do not support this operation, have
    an explicit revision specified, or are shallow. If a checkout already has a
    branch of the requested name, check it out.

    If the '-v' flag is used, report on each checkout (actually, each checkout
    directory) as it is entered.

    It is recommended that <branch> include the build name (as specified
    using ``builder.build_name = <name>`` in the build description).

    Muddle does not itself provide a means of branching only some checkouts.
    Use the appropriate VCS commands to do that (possibly in combination with
    'muddle runin').

    Normal usage
    ------------
    1. Choose a branch name that incorporates the build name and reason for
       branching. For instance, "acme_stb_alpha_v1.0_maintenance".

    2. Perform the branch::

          muddle branch-tree acme_stb_alpha_v1.0_maintenance

    3. Edit the (newly branched) build description, and add::

          builder.follow_build_desc_branch = True

       to it, so that muddle knows the build tree has been branched as
       an entity.

    4. Commit all the new branches with an appropriate message.
       At the moment, there is no convenient single line way to do this
       with muddle, but the somewhat inconvenient muddle runin command can be
       used, for instance::

           muddle runin _all_checkouts git commit -a -m 'Branch for v1.0 maintenance'

       (this, of course, relies upon the fact that muddle only supports
       tree branching with git at the moment).

    5. Possibly do a "muddle push _all" at this point, or perhaps do some
       editing, some more committing, and then push.

    Dealing with problems
    ---------------------
    If a checkout does not support lightweight branching, then the solution
    is to '-force' the tree branch, and then "branch" the offending checkout
    by hand. The branched version of the build description will then need
    to be edited to indicate (in whatever manner is appropriate) the new
    "branch" to be used.

    If the build description explicitly specifies a particular branch or
    revision for a checkout, then check the build out as normal, then branch
    the build description and remove the explicit branch or revision, and
    then use branch-tree to branch the checkout.

      (If you can promise absolutely that it will never be necessary to
      edit the offending checkout, then it would also be OK to leave the
      explicit branch or revision, but experience proves this is often a
      mistake.)

    If a checkout is marked as shallow, then the solution is to edit the
    branched build description and specify the required revision id explicitly,
    to guarantee that you keep on getting the particular shallow checkout
    that is needed (since the main build will continue to track HEAD).

    If a checkout already has a branch of the name you wanted to use, then
    either use it, or change the branch name you ask for - this can only be
    decided by yourself, because you know what the name *means*.

    Note that the check for a clashing branch name is done last. That means
    that if you change the build description so any of the previous checks
    no longer fail, you still need to re-run the "check" phase to re-check
    for clashing branch names.
    """

    allowed_switches = {'-f': 'force',
                        '-force': 'force',
                        '-c': 'check',
                        '-check': 'check',
                        '-v': 'verbose',
                       }

    def with_build_tree(self, builder, current_dir, args):

        args = self.remove_switches(args)

        if len(args) != 1:
            raise GiveUp('No branch name specified')

        branch = args[0]

        check = 'check' in self.switches
        force = 'force' in self.switches
        verbose = 'verbose' in self.switches

        if force and check:
            raise GiveUp('Cannot specify -check and -force at the same time')

        if self.no_op():
            if check:
                print 'Asked to check if branch "%s" already exists in all checkout'%branch
            else:
                print 'Asked to create branch "%s" in all checkouts'%branch
            return

        all_checkouts = builder.all_checkout_labels(LabelTag.CheckedOut)

        if not force:
            problems = self.check_checkouts(builder, all_checkouts, branch, verbose)
            if problems:
                raise GiveUp('Unable to branch-tree to %s, because:\n  %s'%(branch,
                             '\n  '.join(sorted(problems))))

            if check:
                print 'No problems expected for "branch-tree %s"'%branch

        if not check:
            branched = self.branch_checkouts(builder, all_checkouts, branch, verbose)
            if branched:
                print
                print "If you want the tree branching to be persistent, remember to edit"
                print "the branched build description,"
                print "  %s"%builder.db.build_desc_file_name()
                print "and add:"
                print
                print "  builder.follow_build_desc_branch = True"
                print
                print "to the describe_to() function, and check it in/push it."

    def check_checkouts(self, builder, checkouts, branch, verbose):
        """
        Check if we can branch our checkouts.

        Returns a list of problem reports, one per problem checkout.
        """
        problems = []
        for co in checkouts:
            co_data = builder.db.get_checkout_data(co)
            vcs_handler = co_data.vcs_handler
            repo = co_data.repo

            if not vcs_handler.vcs.supports_branching():
                problems.append('%s uses %s, which does not support'
                                ' lightweight branching'%(co, vcs_handler.vcs.short_name))

            elif repo.revision is not None:
                problems.append('%s explicitly specifies revision "%s" in'
                                ' the build description'%(co, repo.revision))

            elif repo.branch is not None:
                if co.match_without_tag(builder.build_desc_label):
                    # It's our build description that has a branch, presumably
                    # because we did "muddle init -branch". So we ignore it...
                    pass
                else:
                    problems.append('%s explicitly specifies branch "%s" in'
                                    ' the build description'%(co, repo.branch))

            # Shallow checkouts are not terribly well integrated - we do this
            # very much by hand...
            elif 'shallow_checkout' in co_data.options:
                problems.append('%s is shallow, so cannot be branched'%co)

            elif vcs_handler.branch_exists(builder, co, branch, show_pushd=verbose):
                problems.append('%s already has a branch called %s'%(co, branch))

        return problems

    def branch_checkouts(self, builder, all_checkouts, branch, verbose):
        """
        Branch our checkouts.

        If we can't, say so but continue anyway.

        If 'verbose', show each pushd into a checkout directory.

        Returns the number of branched checkouts.
        """
        created = 0
        selected = 0
        problems = []
        already_exists_in = []
        for co in all_checkouts:
            co_data = builder.db.get_checkout_data(co)
            vcs_handler = co_data.vcs_handler
            repo = co_data.repo

            if not vcs_handler.vcs.supports_branching():
                print '%s uses %s, which does not support' \
                      ' lightweight branching'%(co, vcs_handler.vcs.short_name)
                problems.append((co, "VCS %s not supported"))
                continue

            if repo.revision is not None:
                print '%s explicitly specifies revision "%s" in' \
                      ' the build description'%(co, repo.revision)
                problems.append((co, "specific revision %s"%repo.revision))
                continue

            if repo.branch is not None:
                if co.match_without_tag(builder.build_desc_label):
                    # It's our build description that has a branch, presumably
                    # because we did "muddle init -branch". So we don't believe
                    # that this is a problem, and can carry on and branch it
                    # to what was requested.
                    pass
                else:
                    print '%s explicitly specifies branch "%s" in' \
                          ' the build description'%(co, repo.branch)
                    problems.append((co, "specific branch %s"%repo.branch))
                    continue

            # Shallow checkouts are not terribly well integrated - we do this
            # very much by hand...
            if 'shallow_checkout' in co_data.options:
                print '%s is shallow, so cannot be branched'%co
                problems.append((co, "shallow checkout"))
                continue

            if vcs_handler.branch_exists(builder, co, branch, show_pushd=verbose):
                already_exists_in.append(co)
            else:
                vcs_handler.create_branch(builder, co, branch, show_pushd=False,
                                          verbose=verbose)
                created += 1

            vcs_handler.goto_branch(builder, co, branch, show_pushd=False,
                                    verbose=verbose)
            selected += 1

        print 'Successfully created  branch %s in %d out of %d checkout%s'%(branch,
                created, len(all_checkouts), '' if len(all_checkouts)==1 else 's')
        print 'Successfully selected branch %s in %d out of %d checkout%s'%(branch,
                selected, len(all_checkouts), '' if len(all_checkouts)==1 else 's')
        if already_exists_in:
            print
            print 'Branch %s already existed in:\n  %s'%(branch,
                         label_list_to_string(already_exists_in, join_with='\n  '))
        if problems:
            # Make our reporting of problems relatively terse, as we should
            # only need to report them if the user specified -force, and thus
            # may be assumed to have expected them.
            maxlen = 0
            for co, text in problems:
                length = len(str(co))
                if length > maxlen:
                    maxlen = length
            print 'Unable to branch the following:'
            for co, text in problems:
                print '  %.*s (%s)'%(maxlen, co, text)

        return selected


@command('veryclean', CAT_MISC)
class VeryClean(Command):
    """
    :Syntax: muddle veryclean

    Sets the muddle build tree back to just checked out sources.

    1. Delete the obj/, install/ and deploy/ directories.
    2. Removes all the package tags, so muddle thinks that packages have
       not had anything done to them.
    3. Removes all the deployment tags, so muddle thinks that all deployments
       have not been deployed.

    For a build tree without subdomains, this is equivalent to::

        $ rm -rf obj install deploy
        $ rm -rf .muddle/tags/package
        $ rm -rf .muddle/tags/deployment

    It's a bit more complicated if there are any subdomains. If there is a
    'domains/' directory, then this command will recurse down into it and
    perform the same operation for each subdomain it finds. This does not
    depend on whether the subdomain is defined in the build description - it
    is done purely on the basis of what directories are actually present.

    As usual, 'muddle -n veryclean' will report on what it would do, without
    actually doing it.

    Using this helps prevent unwanted built/installed software "building up"
    in the obj and install (and, to a lesser extent, deploy) infrastructure.
    Note that it does *not* remove checkouts that are no longer in use, nor
    can it do anything about any build artefacts inside checkout directories.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if args:
            print "Syntax: veryclean"
            print self.__doc__
            return

        if self.no_op():
            def delete_directory(name):
                if os.path.exists(name):
                    print 'Would delete %s'%name
                else:
                    print 'No need to delete %s as it does not exist'%name
        else:
            def onerror(fn, path, excinfo):
                type, value = excinfo[:2]
                raise GiveUp('Error in %s for %s: %s %s'%(fn.__name__,
                              path, type.__name__, value))

            def delete_directory(name):
                if os.path.exists(name):
                    print 'Deleting %s'%name
                    try:
                        shutil.rmtree(name, onerror=onerror)
                    except GiveUp as e:
                        print e
                        print '...giving up on %s'%name

        def tidy_domain(path):
            with Directory(path):
                for directory in ('obj', 'install', 'deploy'):
                    delete_directory(directory)

                for directory in ('package', 'deployment'):
                    delete_directory(os.path.join('.muddle', 'tags', directory))

                if os.path.exists('domains'):
                    subdomains = os.listdir('domains')
                    for name in subdomains:
                        tidy_domain(os.path.join(os.path.join(path, 'domains', name)))

        # And our top level is, of course, the top domain
        tidy_domain(builder.db.root_path)

@command('instruct', CAT_MISC)
class Instruct(Command):
    """
    :Syntax: muddle instruct <package>{<role>} <instruction-file>
    :or:     muddle instruct (<domain>)<package>{<role>} <instruction-file>

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

    You can list instruction files and their ordering with
    "muddle query inst-files".
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if (len(args) != 2 and len(args) != 1):
            print "Syntax: instruct [pkg{role}] <[instruction-file]>"
            print self.__doc__
            return

        arg = args[0]
        filename = None
        ifile = None

        # Validate this first
        label = self.decode_package_label(builder, arg, LabelTag.PreConfig)

        if label.role is None or label.role == '*':
            raise GiveUp("instruct takes precisely one package{role} pair "
                                "and the role must be explicit")


        if (len(args) == 2):
            filename = args[1]

            if (not os.path.exists(filename)):
                raise GiveUp("Attempt to register instructions in "
                                    "%s: file does not exist"%filename)

            # Try loading it.
            ifile = InstructionFile(filename, instr.factory)
            ifile.get()

            # If we got here, it's obviously OK

        if self.no_op():
            if filename:
                print "Register instructions for %s from %s"%(str(label), filename)
            else:
                print "Unregister instructions for %s"%label
            return

        # Last, but not least, do the instruction ..
        builder.instruct(label.name, label.role, ifile, domain=label.domain)

    def decode_package_label(self, builder, arg, tag):
        """
        Convert a 'package' or 'package{role}' or '(domain)package{role} argument to a label.

        If role or domain is not specified, use the default (which may be None).
        """
        #default_domain = builder.get_default_domain()
        label = Label.from_fragment(arg,
                                    default_type=LabelType.Package,
                                    default_role=None,
                                    #default_domain=default_domain)
                                    default_domain=None)
        if label.tag != tag:
            label = label.copy_with_tag(tag)
        if label.type != LabelType.Package:
            raise GiveUp("Label '%s', from argument '%s', is not a valid"
                    " package label"%(label, arg))
        return label

@command('runin', CAT_MISC)
class RunIn(Command):
    """
    :Syntax: muddle runin <label> <command> [ ... ]

    Run the command "<command> [ ...]" in the directory corresponding to every
    label matching <label>.

    * Checkout labels are run in the directory corresponding to their checkout.
    * Package labels are run in the directory corresponding to their object files.
    * Deployment labels are run in the directory corresponding to their deployments.

    We only ever run the command in any directory once.

    <label> may be a label fragment, or one of the _xxx arguments
    If it is a label fragment, and the label type is not given, then
    "checkout:" is assumed.
    If it is an _xxx argument, then it may not be _all, since it would not be
    clear what type of label to expand it to). See "muddle help label _all"
    for more information on these values.

    In practice, it is often simplest to use a shell script for <command>,
    rather than trying to work out the appropriate quoting rules for
    whatever command is actually wanted.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if (len(args) < 2):
            print "Syntax: runin <label> <command> [ ... ]"
            print self.__doc__
            return

        what = args[0]
        if what[0] == '_':
            labels = builder.expand_underscore_arg(what)
        else:
            labels = builder.label_from_fragment(args[0], LabelType.Checkout)
        command = " ".join(args[1:])
        dirs_done = set()

        if self.no_op():
            print 'Run "%s" for: %s'%(command, label_list_to_string(labels))
            return

        for l in labels:
            matching = builder.ruleset.rules_for_target(l)

            for m in matching:
                lbl = m.target

                dir = None
                if (lbl.name == "*"):
                    # If it's a wildcard, don't bother.
                    continue

                if (lbl.type == LabelType.Checkout):
                    dir = builder.db.get_checkout_path(lbl)
                elif (lbl.type == LabelType.Package):
                    if (lbl.role == "*"):
                        continue
                    dir = builder.package_obj_path(lbl)
                elif (lbl.type == LabelType.Deployment):
                    dir = builder.deploy_path(lbl)

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
                    builder.setup_environment(lbl, env)

                    with Directory(dir):
                        subprocess.call(command, shell=True, env=env,
                                        stdout=sys.stdout, stderr=subprocess.STDOUT)
                else:
                    print "! %s does not exist."%dir

@command('env', CAT_MISC)       # We're not *really* a normal package command
class Env(PackageCommand):
    """
    :Syntax: muddle env <language> <mode> <name> <label> [ <label> ... ]

    Produce a setenv script in the requested language listing all the
    runtime environment variables bound to <label> (or the cumulation
    of the variables for several labels).

    * <language> may be 'sh', 'c', or 'py'/'python'
    * <mode> may be 'build' (build time variables) or 'run' (run-time variables)
    * <name> is used in various ways depending upon the target language.
      It should be a legal name/symbol in the aforesaid target language (for
      instance, in C it will be uppercased and used as part of a macro name).
    * <label> should be a label fragment specifying a package, or one of _all
      and friends, as for any package command. See "muddle help labels" for
      more information.

    So, for instance::

        $ muddle env sh run 'encoder_settings' encoder > encoder_vars.sh

    might produce a file ``encoder_vars.sh`` with the following content::

        # setenv script for encoder_settings
        # 2010-10-19 16:24:05

        export BUILD_SDK=y
        export MUDDLE_TARGET_LOCATION=/opt/encoder/sdk
        export PKG_CONFIG_PATH=$MUDDLE_TARGET_LOCATION/lib/pkgconfig:$PKG_CONFIG_PATH
        export PATH=$MUDDLE_TARGET_LOCATION/bin:$PATH
        export LD_LIBRARY_PATH=$MUDDLE_TARGET_LOCATION/lib:$LD_LIBRARY_PATH

        # End file.

    """

    # We aren't *quite* like other package commands...
    def with_build_tree(self, builder, current_dir, args):
        if (len(args) < 3):
            raise GiveUp("Syntax: env [language] [build|run] [name] [label ... ]")

        self.lang = args[0]
        self.mode = args[1]
        self.name = args[2]
        args = args[3:]

        print 'args:', args

        if self.mode == "build":
            self.required_tag = LabelTag.Built
        elif self.mode == "run":
            self.required_tag = LabelTag.RuntimeEnv
        else:
            raise GiveUp("Mode '%s' is not understood - use build or run."%self.mode)

        super(Env, self).with_build_tree(builder, current_dir, args)

    def build_these_labels(self, builder, args):

        print "Environment for labels %s"%(label_list_to_string(args))

        env = env_store.Store()

        for lbl in args:
            x_env = builder.effective_environment_for(lbl)
            env.merge(x_env)

            if self.mode == "run":
                # If we have a MUDDLE_TARGET_LOCATION, use it.
                if not env.empty("MUDDLE_TARGET_LOCATION"):
                    env_store.add_install_dir_env(env, "MUDDLE_TARGET_LOCATION")

        if self.lang == "sh":
            script = env.get_setvars_script(builder, self.name, env_store.EnvLanguage.Sh)
        elif self.lang in ("py", "python"):
            script = env.get_setvars_script(builder, self.name, env_store.EnvLanguage.Python)
        elif self.lang == "c":
            script = env.get_setvars_script(builder, self.name, env_store.EnvLanguage.C)
        else:
            raise GiveUp("Language must be sh, py, python or c, not %s"%self.lang)

        print script

@command('copywithout', CAT_MISC)
class CopyWithout(Command):
    """
    :Syntax: muddle copywithout [-f[orce]] <src-dir> <dst-dir> [ <without> ... ]

    Many VCSs use '.XXX' directories to hold metadata. When installing
    files in a Makefile, it's often useful to have an operation which
    copies a hierarchy from one place to another without these dotfiles.

    This is that operation. We copy everything from the source directory,
    <src-dir>, into the target directory,  <dst-dir>, without copying anything
    which is in [ <without> ... ].  If you omit without, we just copy - this is
    a useful, working, version of 'cp -a'

    If you specify -f (or -force), then if a destination file cannot be
    overwritten because of its permissions, and attempt will be made to remove
    it, and then copy again. This is what 'cp' does for its '-f' flag.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        self.do_copy(args)

    def without_build_tree(self, muddle_binary, current_dir, args):
        self.do_copy(args)

    def do_copy(self, args):

        if args and args[0] in ('-f', '-force'):
            force = True
            args = args[1:]
        else:
            force = False

        if (len(args) < 2):
            raise GiveUp("Bad syntax for copywithout command")

        src_dir = args[0]
        dst_dir = args[1]
        without = args[2:]

        if self.no_op():
            print "Copy from: %s"%(src_dir)
            print "Copy to  : %s"%(dst_dir)
            print "Excluding: %s"%(" ".join(without))
            return

        utils.copy_without(src_dir, dst_dir, without, object_exactly=True,
                preserve=True, force=force)

@command('subst', CAT_MISC)
class Subst(Command):
    """
    :Syntax: muddle subst <src_file> [<xml_file>] <output_file>

    Reads in <src_file>, and replaces any strings of the form "${..}" with
    values from the XML file (if any) or from the environment.

    For the examples, I'm assuming we're building a release build, using
    "muddle release", and thus the MUDDLE_RELEASE_xxx environment variables
    are set.

    Without an XML file
    -------------------
    So, in the two argument form, we might run::

        $ muddle subst version.h.in version.h

    on version.h.in::

        #ifndef PROJECT99_VERSION_FILE
        #define PROJECT99_VERSION_FILE
        #define BUILD_VERSION "${MUDDLE_RELEASE_NAME}: $(MUDDLE_RELEASE_VERSION}"
        #endif

    to produce::

        #ifndef PROJECT99_VERSION_FILE
        #define PROJECT99_VERSION_FILE
        #define BUILD_VERSION "simple: v1.0"
        #endif

    With an XML file
    ----------------
    In the three argument form, values will first be looked up in the XML file,
    and then, if they're not found, in the environment. So given values.xml::

        <?xml version="1.0" ?>
        <values>
            <version>Kynesim version 99</version>
            <more>
                <value1>This is value 1</value1>
                <value2>This is value 2</value2>
            </more>
        </values>

    and values.h.in::

        #ifndef KYNESIM_VALUES
        #define KYNESIM_VALUES
        #define KYNESIM_VERSION "${/values/version}"
        #define RELEASE_VERSION "Release version ${MUDDLE_RELEASE_VERSION}"
        #endif

    then running::

        $ muddle subst values.h values.xml values.h.in

    would give us values.h::

        #ifndef KYNESIM_VALUES
        #define KYNESIM_VALUES
        #define KYNESIM_VERSION "Kynesim version 99"
        #define RELEASE_VERSION "Release version v1.0"
        #endif

    XML queries are used in the "${..}" to extract particular values from the
    XML. These look a bit like XPath queries - "/elem/elem/elem...", so for
    instance::

        ${/values/more/value2}

    would be replaced by::

        This is value 2

    You can escape a "${ .. }" by passing "$${ .. }", so::

        $${/values/more/value1}

    becomes::

        ${/values/more/value1}

    Both ${/version} and ${"/version"} give the same result.

    You can also nest evaluations. With the environment variable THING set
    to "/values/version", then::

        ${ ${THING} }

    will evaluate to::

        Kynesim version 99

    You can call functions with "${fn: .. }". Parameters can be surrounded by
    matching double quotes - these will be stripped before the parameter is
    evaluated. The available functions are:

    * "${fn:val(something)}"

      This expands to the value of 'something' as a query (either as an
      environment variable or XPath)

    * "${fn:ifeq(something,b)c}"

      If ${something} evaluates to b, then this expands to c. Both b and c
      may contain "${..}" sequences.

      Note that 'something' is expanded without you needing to specify such,
      but b and c are not.

      It is allowed to do things like::

          ${fn:ifeq(/values/version,"Kynesim version 99")
              def missing_function(a):
                  # 'Version ${/values/version} of the software does not provide
                  # this function, so we do so here
                  <implementation code>
           }

    * "${fn:ifneq(something,b)c}"

      The same, but you get c if evaluating 'something' does not give b.

    * "${fn:echo(a,b,c,...)}"

      Evaluates each parameter (a, b, c, ...) in turn. Spaces between
      parameters are ignored. So::

          ${fn:echo(a, " space ", ${/values/more/value1}}

      would give::

          a space This is value 1
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        self.do_subst(args)

    def without_build_tree(self, muddle_binary, current_dir, args):
        self.do_subst(args)

    def do_subst(self, args):
        if len(args) == 2:
            src = args[0]
            xml_file = None
            dst = args[1]
        elif len(args) == 3:
            src = args[0]
            xml_file = args[1]
            dst = args[2]
        else:
            raise GiveUp("Syntax: subst <src_file> [<xml_file>] <output_file>")


        if self.no_op():
            print 'Substitute source file %s'%src
            if xml_file:
                print '       using data from %s'%xml_file
            print '            to produce %s'%dst
            return

        if xml_file:
            f = open(xml_file, "r")
            xml_doc = xml.dom.minidom.parse(f)
            f.close()
        else:
            xml_doc = None

        try:
            subst.subst_file(src, dst, xml_doc, self.old_env)
        except GiveUp as e:
            if xml_file:
                raise GiveUp("%s\nWhilst processing %s with XML file %s"%(e, src, xml_file))
            else:
                raise GiveUp("%s\nWhilst processing %s"%(e, src))

# End file.
