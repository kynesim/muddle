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
import os
import posixpath
import pydoc
import subprocess
import sys
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

from muddled.db import Database, InstructionFile
from muddled.depend import Label, label_list_to_string
from muddled.utils import GiveUp, MuddleBug, Unsupported, \
        DirType, LabelTag, LabelType, find_label_dir
from muddled.version_control import split_vcs_url, checkout_from_repo
from muddled.repository import Repository
from muddled.version_stamp import VersionStamp
from muddled.licenses import print_standard_licenses, get_gpl_checkouts, \
        get_not_licensed_checkouts, get_implicit_gpl_checkouts, \
        get_license_clashes, licenses_in_role, get_license_clashes_in_role
from muddled.distribute import distribute, the_distributions, \
        get_distribution_names, get_used_distribution_names

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
    Abstract base class for muddle commands

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
        """
        raise GiveUp("Can't run %s with a build tree."%self.cmd_name)

    def without_build_tree(self, muddle_binary, root_path, args):
        """
        Run this command without a build tree.
        """
        raise GiveUp("Can't run %s without a build tree."%self.cmd_name)

class CPDCommand(Command):
    """
    A command that takes checkout, package or deployment arguments.

    This is purely an intermediate class for common code for the
    classes using it (I coult have done a mixin class instead)
    """

    # Subclasses should override the following as necessary
    required_tag = None
    required_type = LabelType.Checkout

    def with_build_tree(self, builder, current_dir, args):

        args = self.remove_switches(args)
        if args:
            # Expand out any labels that need it
            labels = self.decode_args(builder, args, current_dir)
        else:
            # Decide what to do based on where we are
            labels = self.default_args(builder, current_dir)

        # We promised a sorted list
        labels.sort()

        if self.no_op():
            print 'Asked to %s:\n  %s'%(self.cmd_name,
                    label_list_to_string(labels, join_with='\n  '))
            return
        ##elif not args:
        ##    print '%s %s'%(self.cmd_name, label_list_to_string(labels))

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
        label_from_fragment = builder.invocation.label_from_fragment
        for word in args:
            if word == '_all':
                initial_list.extend(self.interpret_all(builder))
            elif word == '_default_roles':
                for role in builder.invocation.default_roles:
                    label = Label(LabelType.Package, '*', role, LabelTag.PostInstalled)
                    labels = builder.invocation.expand_wildcards(label)
                    initial_list.extend(labels)
            elif word == '_default_deployments':
                initial_list.extend(builder.invocation.default_deployment_labels)
            else:
                labels = label_from_fragment(word, default_type=self.required_type)

                used_labels = []
                # We're only interested in any labels that are actually used
                for label in labels:
                    if builder.invocation.target_label_exists(label):
                        used_labels.append(label)

                # But it's an error if none of them were wanted
                if not used_labels:
                    raise GiveUp(self.diagnose_unused_labels(builder, labels, word))

                # Don't forget to remember those we do want!
                initial_list.extend(used_labels)

        #print 'Initial list:', label_list_to_string(initial_list)

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

    def diagnose_unused_labels(self, builder, labels, arg):
        """Concoct a useful report on why none of 'labels' is used.

        We rely on 'labels' having been generated by
        builder.invocation.label_from_fragment(),
        which means that all the labels will have the same type

        We assume quite a lot of knowledge about how that method works.
        """

        lines = []
        lines.append('Argument "%s" does not match any target labels'%arg)

        if not labels:
            # Not having any candidates generally means that wildcarding
            # didn't generate anything useful - so just do the first part
            # of what builder.invocation.label_from_fragment() does
            label = Label.from_fragment(arg, default_type=self.required_type,
                                        default_role=None, default_domain=None)
            labels = [label]
            # Because we've done this, the later stages *will* need to ignore
            # wildcards in their reporting

        lines.append('  It expands to %s'%label_list_to_string(labels))

        first = labels[0]
        if first.type == LabelType.Checkout:
            all_checkouts = builder.invocation.all_checkouts()
            names = set()
            tags = set()
            roles = set()
            for l in labels:
                if l.name != '*':
                    names.add(l.name)
                if l.tag != '*':
                    tags.add(l.tag)
                if l.role:
                    roles.add(l.role)
            names = sorted(names)
            tags = sorted(tags)
            roles = sorted(roles)
            for n in names:
                if n not in all_checkouts:
                    lines.append('  Checkout name "%s" is not defined in the build description'%n)
            if roles:
                lines.append('  Checkout labels should not have roles: {%s}'%('}, {'.join(roles)))
            for t in tags:
                if t not in (LabelTag.CheckedOut, LabelTag.Fetched, LabelTag.Merged,
                             LabelTag.ChangesCommitted, LabelTag.ChangesPushed):
                    lines.append('  Checkout tag "/%s" is unexpected'%t)
        elif first.type == LabelType.Package:
            default_roles = builder.invocation.default_roles
            all_packages = builder.invocation.all_packages()
            all_roles = builder.invocation.all_roles()
            all_domains = builder.invocation.all_domains()
            names = set()
            roles = set()
            domains = set()
            tags = set()
            for l in labels:
                if l.name != '*':
                    names.add(l.name)
                if l.role != '*':
                    roles.add(l.role)
                if l.domain != '*':
                    if l.domain == None:
                        domains.add('')
                    else:
                        domains.add(l.domain)
                if l.tag != '*':
                    tags.add(l.tag)
            names = sorted(names)
            roles = sorted(roles)
            domains = sorted(domains)
            tags = sorted(tags)
            found_problem = False
            for d in domains:
                if d not in all_domains:
                    lines.append('  Domain (%s) is not defined in the build description'%d)
                    found_problem = True
            for n in names:
                if n not in all_packages:
                    lines.append('  Package name "%s" is not defined in the build description'%n)
                    found_problem = True
            for r in roles:
                if r not in all_roles:
                    lines.append('  Role {%s} is not defined in the build description'%r)
                    found_problem = True
                elif r not in default_roles:
                    lines.append('  Role {%s} is not a default role'%r)
                    found_problem = True
            if not found_problem:
                lines.append('  There is no label matching "%s" in any of the default roles'%arg)
                actual = []
                for n in names:
                    for d in domains:
                        if d == '':
                            d = None
                        for r in builder.invocation.all_roles():
                            l = Label(LabelType.Package, n, r, self.required_tag, domain=d)
                            if builder.invocation.target_label_exists(l):
                                actual.append(l)
                if len(actual) == 1:
                    lines.append('  However, label %s is a target'%actual[0])
                elif len(actual) > 1:
                    lines.append('  However, labels\n    %s\n  are targets'%label_list_to_string(actual,
                        join_with='\n    '))
            for t in tags:
                if t not in (LabelTag.PreConfig, LabelTag.Configured, LabelTag.Built,
                             LabelTag.Installed, LabelTag.PostInstalled,
                             LabelTag.Clean, LabelTag.DistClean):
                    lines.append('  Package tag "/%s" is unexpected'%t)
        elif first.type == LabelType.Deployment:
            all_deployments = builder.invocation.all_deployments()
            names = set()
            tags = set()
            roles = set()
            for l in labels:
                if l.name != '*':
                    names.add(l.name)
                if l.tag != '*':
                    tags.add(l.tag)
                if l.role:
                    roles.add(l.role)
            names = sorted(names)
            tags = sorted(tags)
            roles = sorted(roles)
            for n in names:
                if n not in all_deployments:
                    lines.append('  Deployment name "%s" is not defined in the build description'%n)
            if roles:
                lines.append('  Deployment labels should not have roles: {%s}'%('}, {'.join(roles)))
            for t in tags:
                if t not in (LabelTag.Deployed, LabelTag.InstructionsApplied):
                    lines.append('  Deployment tag "/%s" is unexpected'%t)
        else:
            lines.append('  Unexpected label type "%s:" in label "%s"'%(first.type, first))

        return '\n'.join(lines)

    def default_args(self, builder, current_dir):
        """
        Decide on default labels, based on where we are in the build tree.
        """
        raise MuddleBug('No "default_args" method provided for command "%s"'%self.cmd_name)

    def interpret_all(self, builder):
        """Return the result of argument "_all"
        """
        raise MuddleBug('No "interpret_all" method provided for command "%s"'%self.cmd_name)

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

    def interpret_all(self, builder):
        """Return the result of argument "_all"
        """
        return builder.invocation.all_checkout_labels(LabelTag.CheckedOut)

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
                checkouts = builder.invocation.checkouts_for_package(label)
                if checkouts:
                    found = True
                    intermediate_set.update(checkouts)
            elif label.type in LabelType.Deployment:
                # All the checkouts needed for this particular deployment
                # XXX I don't think we need to specify useMatch=True, because we
                # XXX should already have expanded any wildcards
                rules = depend.needed_to_build(builder.invocation.ruleset, label)
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

    def interpret_all(self, builder):
        """Return the result of argument "_all"
        """
        return builder.invocation.all_package_labels()

    def interpret_labels(self, builder, args, initial_list):
        """
        Turn 'initial_list' into a list of labels of the required type.
        """
        potential_problems = []
        intermediate_set = set()
        default_roles = builder.invocation.default_roles
        for index, label in enumerate(initial_list):
            if label.type == LabelType.Package:
                intermediate_set.add(label)
            elif label.type == LabelType.Checkout:
                # Experience seems to show that it makes more sense to go for
                # just the *immediate* package dependencies - i.e., the packages
                # that are actually built from this checkout.
                # And the documentation says we should only use package labels
                # with the default roles
                package_labels = builder.invocation.packages_using_checkout(label)
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
                    rules = depend.needed_to_build(builder.invocation.ruleset, label)
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
                    packages = builder.invocation.packages_for_deployment(label)
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

    def interpret_all(self, builder):
        """Return all the deployment labels registered with the ruleset.
        """
        # Important not to set tag here - if there's a deployment
        # which doesn't have the right tag, we want an error,
        # not to silently ignore it.
        match_lbl = Label(LabelType.Deployment, "*", None, domain="*")
        matching = builder.invocation.ruleset.rules_for_target(match_lbl)

        return_set = set()
        for m in matching:
            label = m.target
            if label.tag == self.required_tag:
                return_set.add(label)
            else:
                return_set.add(label.copy_with_tag(self.required_tag))

        return list(return_set)
        ## Everything ..
        #return self.all_deployment_labels(builder, default_domain)

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
                required_labels = depend.required_by(builder.invocation.ruleset, label)
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
        label_from_fragment = builder.invocation.label_from_fragment
        for word in args:
            if word in ('_all', '_default_roles', '_default_deployments'):
                raise GiveUp('Command %s does not allow %s as an argument'%(self.cmd_name, word))

            labels = label_from_fragment(word, default_type=LabelType.Package)

            used_labels = []
            # We're only interested in any labels that are actually used
            for label in labels:
                if builder.invocation.target_label_exists(label):
                    used_labels.append(label)

            # But it's an error if none of them were wanted
            if not used_labels:
                if len(labels) == 1:
                    raise GiveUp("Label %s, from argument '%s', is"
                                 " not a target"%(labels[0], word))
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

    specifically:

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

    <switch> may be:

        -p[ager] <pager>    to specify a pager through which the help will be piped.
                            The default is $PAGER (if set) or else 'more'.
        -nop[ager]          don't use a pager, just print the help out.
    """

    command_line_help = """\
Usage:

  muddle [<options>] <command> [<arg> ...]

Available <options> are:

  --help, -h, -?      This help text
  --tree <dir>        Use the muddle build tree at <dir>
  --just-print, -n    Just print what muddle would have done. For commands that
                      'do something', just print out the labels for which that
                      action would be performed. For commands that "enquire"
                      (or "find out") something, this switch is ignored.
   --version          Show the version of muddle and the directory it is
                      being run from. Note that this uses git to interrogate
                      the .git/ directory in the muddle source directory.

If you don't give --tree, muddle will traverse directories up to the root to
try and find a .muddle directory, which signifies the top of the build tree.
"""

    labels_help = """\
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

"muddle" with no label arguments
--------------------------------
Muddle tries quite hard to do the sensible thing if you type it without any
arguments, depending on the current directory. Specifically, for commands
that "build" a label (whether checkout, package or deployment):

* at the very top of the build tree:

    muddle buildlabel _default_deployments _default_roles

* within a 'src/' directory, or within a non-checkout subdirectory inside
  'src'/,  "muddle rebuild" for each checkout that is below the current
  directory (i.e., rebuild all packages using the checkouts below the
  current directory).
* within a checkout directory, "muddle rebuild" for the package(s) that use
  that checkout.
* within an 'obj/' directory, no defined action
* within an 'obj/<package>' directory, "muddle rebuild" for the named
  <package> in each of the default roles.
* within an 'obj/<package>/<role>' directory (or one of its subdirectories),
  "muddle rebuild package:<package>{<role>}".
* within an 'install/' directory, no defined action.
* within an 'install/<role>' directory (or one of its subdirectories),
  "muddle build package:*{<role>}".
* within a 'deploy/' directory, no defined action.
* within a 'deploy/<deployment>' directory, "muddle redeploy <deployment>".

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

How "muddle" commands intepret labels of the "wrong" type
---------------------------------------------------------
Most muddle commands that want label arguments actually want labels of a
particular type. For instance, "muddle checkout" wants to operate on one
or more checkout: labels.

Sometimes, however, it is more convenient to specify a label of a different
type. For instance: "muddle checkout package:fred", to checkout the checkouts
needed by package "fred".

Labels of particular types are intrepreted as follows:

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

_all and friends
----------------
There are some special command line arguments that represent a set of labels.

* _all represents all target labels
* _default_roles represents package labels for all of the default roles, as
  given in the build description. Specifically, package:*{<role>}/postinstalled
  for each such <role>. You can find out what the default roles are with
  "muddle query default-roles".
* _default_deployments represents deployment labels for each of the default
  deployments, as given in the build description. You can find out what the
  default deployments are with "muddle query default-deployments".

The help for particular commands will indicate if these values can be used,
but they are generally valid for all commands that "build" checkout, package
or deployment labels.

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

    def without_build_tree(self, muddle_binary, root_path, args):
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

        if args[0] == "labels":
            return self.help_labels()

        if args[0] == "subdomains":
            return self.help_subdomains()

        if args[0] == "commands":
            return self.help_command_list()

        if args[0] == "vcs":
            return self.help_vcs(args[1:])

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

    def help_labels(self):
        """
        Return help on how to use labels
        """
        return textwrap.dedent(Help.labels_help)

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
            return "".join(str_list)

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

    Note: if you find yourself trying to "muddle init" a subdomain, don't.
    Instead, add the subdomain to the current build description (using a call
    of 'include_domain()'), and it will automatically get checked out during
    the "muddle init" of the top-level build. Or see "muddle bootstrap -subdomain".
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        raise GiveUp("Can't initialise a build tree "
                    "when one already exists (%s)"%builder.invocation.db.root_path)

    def without_build_tree(self, muddle_binary, root_path, args):
        """
        Initialise a build tree.
        """
        if len(args) != 2:
            raise GiveUp(self.__doc__)

        repo = args[0]
        build = args[1]

        print "Initialising build tree in %s "%root_path
        print "Repository: %s"%repo
        print "Build description: %s"%build

        if self.no_op():
            return

        db = Database(root_path)
        db.setup(repo, build)

        print
        print "Checking out build description .. \n"
        mechanics.load_builder(root_path, muddle_binary)

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

    def with_build_tree(self, builder, current_dir, args):
        if args[0] != '-subdomain':
            raise GiveUp("Can't bootstrap a build tree when one already"
                               " exists (%s)\nTry using '-bootstrap' if you"
                               " want to bootstrap a subdomain"%builder.invocation.db.root_path)
        args = args[1:]

        if os.path.exists('.muddle'):
            raise GiveUp("Even with '-subdomain', can't bootstrap a build"
                               " tree in the same directory as an existing"
                               " tree (found .muddle)")

        self.bootstrap(current_dir, args)

    def without_build_tree(self, muddle_binary, root_path, args):
        """
        Bootstrap a build tree.
        """

        if args and args[0] == '-subdomain':
            print 'You are not currently within a build tree. "-subdomain" ignored'
            args = args[1:]

        self.bootstrap(root_path, args)

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
                             '''.format(name=build_name)
        with utils.NewDirectory(build_dir):
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
        db.set_tag(Label.from_string('checkout:builds/checked_out'))

        print 'Setting up versions directory'
        with utils.NewDirectory("versions"):
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

        return builder.invocation.apply_unifications(label)

    def get_label(self, builder, args):
        if len(args) != 1:
            raise GiveUp("Command '%s' needs a (single) label"%(self.cmd_name))

        try:
            label = Label.from_string(args[0])
        except GiveUp as exc:
            raise GiveUp("%s\nIt should contain at least <type>:<name>/<tag>"%exc)

        return builder.invocation.apply_unifications(label)

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
        print builder.invocation.ruleset.to_string(matchLabel = label,
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

    def without_build_tree(self, muddle_binary, root_path, args):
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

    def without_build_tree(self, muddle_binary, root_path, args):
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

        cos = builder.invocation.all_checkout_labels(LabelTag.CheckedOut)
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
        builder.invocation.db.dump_checkout_paths()

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

            orig_repo = builder.invocation.db.get_checkout_repo(co_label)
            builder.invocation.db.print_upstream_repo_info(orig_repo, [co_label], just_url)
        else:
            # Report on all the upstream repositories
            builder.invocation.db.dump_upstream_repos(just_url=just_url)

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
        builder.invocation.db.dump_checkout_repos(just_url=just_url)

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

    See also "muddle query role-licenses" for licenses applying to (packages
    in) each role.
    """

    def with_build_tree(self, builder, current_dir, args):

        builder.invocation.db.dump_checkout_licenses(just_name=False)

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

        maxlen = calc_maxlen(builder.invocation.db.checkout_licenses.keys())

        gpl_licensed = get_gpl_checkouts(builder)
        get_co_license = builder.invocation.db.get_checkout_license
        if gpl_licensed:
            print
            print 'The following checkouts have some sort of GPL license:'
            print
            for label in sorted(gpl_licensed):
                print '* %-*s %r'%(maxlen, label, get_co_license(label))

        if builder.invocation.db.not_built_against or \
           builder.invocation.db.nothing_builds_against:
            print
            print 'Exceptions to "implicit" GPL licensing are:'
            print
            for co_label in sorted(builder.invocation.db.nothing_builds_against):
                print '* nothing builds against %s'%co_label
            for key, value in sorted(builder.invocation.db.not_built_against.items()):
                print '* %s is not built against %s'%(key,
                                    label_list_to_string(value, join_with=', '))

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

        roles = builder.invocation.all_roles()

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

    def without_build_tree(self, muddle_binary, root_path, args):
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

        domains = builder.invocation.all_domains()
        a_list = list(domains)
        a_list.sort()
        if a_list[0] == '':
            a_list = a_list[1:]
        if joined:
            print '%s'%" ".join(a_list)
        else:
            print '%s'%"\n".join(a_list)

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

        packages = builder.invocation.all_packages()
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

        packages = builder.invocation.all_packages_with_roles()
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

        roles = builder.invocation.all_deployments()
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

        default_deployments = builder.invocation.default_deployment_labels
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

        roles = builder.invocation.all_roles()
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
    description (as defined using 'builder.invocation.add_default_role()').

    These are the roles that will be assumed for 'package:' label fragments.

    With '-j', print them all on one line, separated by spaces.
    """

    allowed_switches = {'-j':'join'}

    def with_build_tree(self, builder, current_dir, args):
        args = self.remove_switches(args, allowed_more=False)

        joined = ('join' in self.switches)

        default_roles = list(builder.invocation.default_roles) # use a copy!
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
        print builder.invocation.db.root_path

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
        to_build = depend.needed_to_build(builder.invocation.ruleset, label, useMatch = True)
        if to_build:
            print "Build order for %s .. "%label
            for rule in to_build:
                print rule.target
        else:
            print "Nothing else needs building to build %s"%label

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
        for lbl, path in builder.invocation.db.scan_instructions(wild):
            print lbl, path
        wild = wild.copy_with_role('*')     # Once with {*}/*
        print 'Instructions for', wild
        for lbl, path in builder.invocation.db.scan_instructions(wild):
            print lbl, path
        # =====================================================================
        inst_subdir = os.path.join('instructions', label.name)
        inst_src_dir = os.path.join(builder.invocation.db.root_path, '.muddle', inst_subdir)

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
        the_env = builder.invocation.effective_environment_for(label)
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
        a_list = builder.invocation.list_environments_for(label)

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
        result = builder.invocation.db.scan_instructions(label)
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
        all_rules = builder.invocation.ruleset.rules_for_target(wildcard_label)
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
        rule_set = builder.invocation.ruleset.rules_for_target(label,
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
            co_path = builder.invocation.checkout_path(tmp)
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
        print builder.invocation.package_obj_path(label)

@subcommand('query', 'precise-env', CAT_QUERY) # It used to be 'preciseenv'
class QueryPreciseEnv(QueryCommand):
    """
    :Syntax: muddle query precise-env <label>

    Print the environment pertaining to exactly this label (no fuzzy matches)
    """

    def with_build_tree(self, builder, current_dir, args):
        label = self.get_label_from_fragment(builder, args)
        the_env = builder.invocation.get_environment_for(label)

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
        result = depend.required_by(builder.invocation.ruleset, label)
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
        local_rule = builder.invocation.ruleset.rule_for_target(label)
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
        local_rules = builder.invocation.ruleset.targets_match(label, useMatch = True)
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
            all_rules = builder.invocation.ruleset.rules_for_target(search_label)
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
            targets = set(builder.invocation.default_deployment_labels)

        targets = list(targets)
        targets.sort()
        for label in targets:
            print '    %s'%label

        all_needed_labels = set()
        for label in targets:
            print '>>> Processing %s'%label
            needed = depend.needed_to_build(builder.invocation.ruleset, label)
            for r in needed:
                all_needed_labels.add(r.target)

        print 'Number of "needed" labels is %d.'%len(all_needed_labels)

        search_label = Label("*", "*", "*", "*", domain="*")
        all_rules = builder.invocation.ruleset.rules_for_target(search_label)
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
        fetched     = set()
        merged     = set()
        missing    = set()
        num_transient = 0
        for l in all_not_needed:
            if l.transient:
                num_transient += 1
            elif not l.is_definite():
                wildcarded.add(l)
            elif l.tag == LabelTag.Fetched:
                fetched.add(l)
            elif l.tag == LabelTag.Merged:
                merged.add(l)
            else:
                missing.add(l)

        print '    Transient  %d'%num_transient
        print '    Wildcarded %d'%len(wildcarded)
        print '    /fetched   %d'%len(fetched)
        print '    /merged    %d'%len(merged)
        print '    Missing    %d'%len(missing)
        print 'Transient labels are (internally) generated by muddle, and can be ignored.'
        print 'We ignore wildcarded labels - this should be OK.'
        print 'We ignore /fetched and /merged checkout labels.'

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
        kernel_root = builder.invocation.package_obj_path(kernel_pkg)
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
                                  'Current directory %s'%(builder.invocation.db.root_path,
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

    def without_build_tree(self, muddle_binary, root_path, args):
        detail = self.want_detail(args)
        if detail:
            print 'None None None'
        else:
            print "You are here. Here is not in a muddle build tree."

@command('doc', CAT_QUERY)
class Doc(Command):
    """
    :Syntax: muddle doc [-d] <name>

    Looks up the documentation string for ``muddled.<name>`` and presents
    it, using the pydoc Python help mechanisms. Doesn't put "muddled." on
    the start of <name> if it is already there.

    For instance:

        muddle doc depend.Label

    With -d, just presents the symbols in <name>, omitting anything that starts
    with an underscore.

    NB: "muddle doc" uses the pydoc module, which will automatically page
    its output. This does not apply for "doc -d".
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        self.doc_for(args)

    def without_build_tree(self, muddle_binary, root_path, args):
        self.doc_for(args)

    def doc_for(self, args):
        just_dir = False
        if len(args) == 1:
            what = args[0]
        elif len(args) == 2 and args[0] == '-d':
            what = args[1]
            just_dir = True
        else:
            print 'Syntax: doc [-d] <name>'
            return
        environment = {}

        # Allow 'muddle doc muddled' explicitly
        if what != 'muddled' and not what.startswith('muddled.'):
            what = 'muddled.%s'%what

        # We need a bit of trickery to cope with the fact that,
        # for instance, we cannot "import muddled" and then access
        # "muddled.deployments.cpio", but we can "import
        # muddled.deployments.cpio" directly.
        words = what.split('.')
        count = len(words)
        for idx in range(0, count):
            a = words[:idx+1]
            try:
                exec 'import %s; thing=%s'%('.'.join(a), what) in environment
                if just_dir:
                    d = dir(environment['thing'])
                    for item in d:
                        if item[0] != '_':
                            print '  %s'%item
                else:
                    pydoc.doc(environment['thing'])
                return
            except AttributeError:
                pass
            except ImportError as e:
                print 'ImportError: %s'%e
                break

        # Arguably, we should also try looking in muddled.XXX.<what>,
        # where XXX is one of ('checkouts', 'deployments', 'pkgs', 'vcs')
        # If we're going to do that sort of thing, then perhaps we should
        # precalculate all the things we're going to try, and then run
        # through them...
        # Pragmatically, also, if <what> starts with (for instance) "make.",
        # then we might assume that it should actually start with
        # "muddled.pkgs.make." - there must be other common examples of this...

        print 'Cannot find %s'%what

# -----------------------------------------------------------------------------
# Stamp commands
# -----------------------------------------------------------------------------
@subcommand('stamp', 'save', CAT_EXPORT)
class StampSave(Command):
    """
    :Syntax: muddle stamp save [-f[orce]|-h[ead]|-v[ersion] <version>] [<filename>]

    Go through each checkout, and save its remote repository and current
    revision id/number to a file.

    This is intended to be enough information to allow reconstruction of the
    entire build tree, as-is.

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

    By default, a version 2 stamp file will be created. This is equivalent
    to specifying '-version 2'. If '-version 1' is specified, then a version
    1 stamp file will be created instead. This is the version of stamp file
    understood by muddle before it was able to create version 2 stamp files
    (see 'muddle help stamp save' to see if this is the case for a particular
    version of muddle or not). Note that the version 1 stamp file created
    by muddle 2.3 and above is not absolutely guaranteed to be correct.

    See 'unstamp' for restoring from stamp files.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        force = False
        just_use_head = False
        filename = None
        version = 2

        while args:
            word = args[0]
            args = args[1:]
            if word in ('-f', '-force'):
                force = True
                just_use_head = False
            elif word in ('-h', '-head'):
                just_use_head = True
                force = False
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

        stamp, problems = VersionStamp.from_builder(builder, force, just_use_head)

        working_filename = 'working.stamp'
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

    See 'unstamp' for restoring from stamp files.
    """

    def requires_build_tree(self):
        return True

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

        version_dir = os.path.join(builder.invocation.db.root_path, 'versions')
        if not os.path.exists(version_dir):
            print 'Creating directory %s'%version_dir
            os.mkdir(version_dir)

        working_filename = os.path.join(version_dir, '_temporary.stamp')
        print 'Writing to',working_filename
        hash = stamp.write_to_file(working_filename, version=version)
        print 'Wrote revision data to %s'%working_filename
        print 'File has SHA1 hash %s'%hash

        version_filename = "%s.stamp"%builder.build_name
        final_name = os.path.join(version_dir, version_filename)
        print 'Renaming %s to %s'%(working_filename, final_name)
        os.rename(working_filename, final_name)

        db = builder.invocation.db
        versions_url = db.versions_repo.from_disc()
        if versions_url:
            with utils.Directory(version_dir):
                vcs_name, just_url = version_control.split_vcs_url(versions_url)
                if vcs_name:
                    print 'Adding version stamp file to VCS'
                    version_control.vcs_init_directory(vcs_name, [version_filename])

@subcommand('stamp', 'diff', CAT_EXPORT)
class StampDiff(Command):
    """
    :Syntax: muddle stamp diff [-u[nified]|-c[ontext]|-n|-h[tml]|-x] <file1> <file2> [<output_file>]

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

    If '-x' is specified, then both stamp files are read in as VersionStamp
    entities, and the checkouts therein are compared (just the checkouts).
    This option only writes to stdout, not to <output_file>
    """

    def requires_build_tree(self):
        return False

    def print_syntax(self):
        print ':Syntax: muddle stamp diff [-u[nified]|-n|-h[tml]] <file1> <file2> [<output_file>]'

    def without_build_tree(self, muddle_binary, root_path, args):
        if not args:
            raise GiveUp("'stamp diff' needs two stamp files to compare")
        self.compare_stamp_files(args)

    def with_build_tree(self, builder, current_dir, args):
        if not args:
            raise GiveUp("'stamp diff' needs two stamp files to compare")
        self.compare_stamp_files(args)

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
            elif word == '-x':
                diff_style = 'local'
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

        if self.no_op():
            print 'Comparing stamp files %s and %s'%(file1, file2)
            return

        if diff_style == 'local':
            if output_file:
                raise GiveUp('"muddle stamp diff -x" does not support an output file')
            self.diff_local(file1, file2)
        else:
            self.diff(file1, file2, diff_style, output_file)

    def diff_local(self, file1, file2):
        """
        Output comparison using VersionStamp instances.
        """
        stamp1 = VersionStamp.from_file(file1)
        stamp2 = VersionStamp.from_file(file2)
        print
        deleted, new, changed, problems = stamp1.compare_checkouts(stamp2)
        if deleted or new or changed or problems:
            print
        if deleted:
            print 'The following were deleted in the second stamp file:'
            for co_label, co_dir, co_leaf, repo in deleted:
                print '  %s'%co_label
        if new:
            print 'The following were new in the second stamp file:'
            for co_label, co_dir, co_leaf, repo in new:
                print '  %s'%co_label
        if changed:
            print 'The following were changed:'
            for co_label, rev1, rev2 in changed:
                print '  %s went from revision %s to %s'%(co_label, rev1, rev2)
        if problems:
            print 'The following problems were found:'
            for co_label, problem in problems:
                print '  %s'%(problem)
        if not (deleted or new or changed or problems):
            print "The checkouts in the stamp files appear to be the same"

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

    'stamp push' does not (re)create a stamp file in the "versions/`"
    directory - use 'stamp version' to do that separately.

    See 'unstamp' for restoring from stamp files.
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if len(args) > 1:
            raise GiveUp("Unexpected argument '%s' for 'stamp push'"%' '.join(args))

        db = builder.invocation.db

        if args:
            versions_url = args[0]
        else:
            # Make sure we always look at the *actual* value in the
            # '.muddle/VersionsRepository file, in case someone has edited it
            versions_url = db.versions_repo.from_disc()

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

        with utils.Directory('versions'):
            version_control.vcs_push_directory(versions_url)

        if args:
            print 'Remembering versions repository %s'%versions_url
            db.versions_repo.set(versions_url)
            db.versions_repo.commit()

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

    def with_build_tree(self, builder, current_dir, args):
        if len(args) > 1:
            raise GiveUp("Unexpected argument '%s' for 'stamp pull'"%' '.join(args))

        db = builder.invocation.db

        if args:
            versions_url = args[0]
        else:
            # Make sure we always look at the *actual* value in the
            # '.muddle/VersionsRepository file, in case someone has edited it
            versions_url = db.versions_repo.from_disc()

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
            with utils.Directory(versions_dir):
                version_control.vcs_fetch_directory(versions_url)
        else:
            print "'versions/' directory does not exist - cloning instead"
            with utils.Directory(db.root_path):
                # Make sure we always clone to a directory of the right name...
                version_control.vcs_get_directory(versions_url, "versions")

        if args:
            print 'Remembering versions repository %s'%versions_url
            db.versions_repo.set(versions_url)
            db.versions_repo.commit()

@command('unstamp', CAT_EXPORT)
class UnStamp(Command):
    """
    :Syntax: muddle unstamp <file>
    :or:     muddle unstamp <url>
    :or:     muddle unstamp <vcs>+<url>
    :or:     muddle unstamp <vcs>+<repo_url> <version_desc>

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

    def print_syntax(self):
        print """
    :Syntax: muddle unstamp <file>
    :or:     muddle unstamp <url>
    :or:     muddle unstamp <vcs>+<url>
    :or:     muddle unstamp <vcs>+<repo_url> <version_desc>

Try "muddle help unstamp" for more information."""

    def requires_build_tree(self):
        return False

    def without_build_tree(self, muddle_binary, root_path, args):
        # Strongly assume the user wants us to work in the current directory
        current_dir = os.getcwd()

        # In an ideal world, we'd only be called if there really was no muddle
        # build tree. However, in practice, the top-level script may call us
        # because it can't find an *intact* build tree. So it's up to us to
        # know that we want to be a bit more careful...
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

        if self.no_op():
            return

        stamp = VersionStamp.from_file(filename)

        builder = mechanics.minimal_build_tree(muddle_binary, current_dir,
                                               stamp.repository,
                                               stamp.description)

        self.restore_stamp(builder, root_path, stamp.domains, stamp.checkouts)

        # Once we've checked everything out, we should ideally check
        # if the build description matches what we've checked out...
        return self.check_build(current_dir, stamp.checkouts, builder,
                                muddle_binary)

    def unstamp_from_repo(self, muddle_binary, root_path, current_dir, repo,
                          version_path):
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

        builder = mechanics.minimal_build_tree(muddle_binary, current_dir,
                                               stamp.repository,
                                               stamp.description,
                                               versions_repo=actual_url)

        self.restore_stamp(builder, root_path, stamp.domains, stamp.checkouts)

        # Once we've checked everything out, we should ideally check
        # if the build description matches what we've checked out...
        return self.check_build(current_dir, stamp.checkouts, builder,
                                muddle_binary)

    def _domain_path(self, root_path, domain_name):
        """Turn a domain name into its path.

        Perhaps should be in utils.py...
        """
        domain_parts = Label.split_domain(domain_name)
        path_parts = [root_path]
        for d in domain_parts:
            path_parts.append('domains')
            path_parts.append(d)
        return os.path.join(*path_parts)

    def restore_stamp(self, builder, root_path, domains, checkouts):
        """
        Given the information from our stamp file, restore things.
        """
        domain_names = domains.keys()
        domain_names.sort()
        for domain_name in domain_names:
            domain_repo, domain_desc = domains[domain_name]

            print "Adding domain %s"%domain_name

            # Take care to allow for multiple parts
            # Thus domain 'fred(jim)' maps to <root>/domains/fred/domains/jim
            domain_root_path = self._domain_path(root_path, domain_name)

            os.makedirs(domain_root_path)

            domain_builder = mechanics.minimal_build_tree(builder.muddle_binary,
                                                          domain_root_path,
                                                          domain_repo, domain_desc)

            # Tell the domain's builder that it *is* a domain
            domain_builder.invocation.mark_domain(domain_name)

        co_labels = checkouts.keys()
        co_labels.sort()
        for label in co_labels:
            co_dir, co_leaf, repo = checkouts[label]
            if label.domain:
                domain_root_path = self._domain_path(root_path, label.domain)
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

    def check_build(self, current_dir, checkouts, builder, muddle_binary):
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
        b_checkouts = b.invocation.all_checkout_labels(LabelTag.CheckedOut)
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
class Distribute(Command):
    """
    :Syntax: muddle distribute [<switches>|-no-muddle-makefile] <name> <target_directory>

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
    licenses in the current build, and any clashes that may exist.

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

        name = None
        target_dir = None

        args = self.remove_switches(args)

        with_versions_dir = ('with-versions' in self.switches)
        with_vcs = ('with-vcs' in self.switches)
        no_muddle_makefile = ('no-muddle-makefile' in self.switches)

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
                raise GiveUp("Unexpected argument '%s' for 'distribute'"%word)

        if name is None or target_dir is None:
            raise GiveUp("Syntax: muddle distribute [<switches>] <name> <target_directory>")

        distribute(builder, name, target_dir,
                   with_versions_dir=with_versions_dir,
                   with_vcs=with_vcs,
                   no_muddle_makefile=no_muddle_makefile,
                   no_op=self.no_op())

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

    reuired_tag = LabelTag.Clean

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
                builder.invocation.db.clear_tag(co)
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
    :Syntax: muddle pull [-s[top]] [ <checkout> ... ]

    Pull the specified checkouts from their remote repositories. Any problems
    will be (re)reported at the end.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/fetched". See "muddle help
    labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    For each checkout named, retrieve changes from the corresponding remote
    repository (as described by the build description) and apply them (to
    the checkout), but *not* if a merge would be required.

        (For a VCS such as git, this actually means "not if a user-assisted
        merge would be required" - i.e., fast-forwards will be done.)

    Normally, "muddle pull" will attempt to pull all the chosen checkouts,
    re-reporting any problems at the end. If '-s' or '-stop' is given, then
    it will instead stop at the first problem.
    """

    required_tag = LabelTag.Fetched
    allowed_switches = {'-s': 'stop', '-stop':'stop'}

    def build_these_labels(self, builder, labels):

        if 'stop' in self.switches:
            stop_on_problem = True
        else:
            stop_on_problem = False

        problems = []
        not_needed  = []

        for co in labels:
            try:
                # First clear the 'fetched' tag
                builder.invocation.db.clear_tag(co)
                # And then build it again
                builder.build_label(co)
            except Unsupported as e:
                print e
                not_needed.append(e)
            except GiveUp as e:
                if stop_on_problem:
                    raise
                else:
                    print e
                    problems.append(e)

        if not_needed:
            print '\nThe following pulls were not needed:\n'
            for e in not_needed:
                print str(e).rstrip()
                print

        if problems:
            print '\nThe following problems occurred:\n'
            for e in problems:
                print str(e).rstrip()
                print
            raise GiveUp()

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

        for co in labels:
            try:
                # First clear the 'merged' tag
                builder.invocation.db.clear_tag(co)
                # And then build it again
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

@command('status', CAT_CHECKOUT)
class Status(CheckoutCommand):
    """
    :Syntax: muddle status [-v] [ <checkout> ... ]

    Report on the status of checkouts that need attention.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/fetched". See "muddle help
    labels" for more information.

    If no checkouts are named, what we do depends on where we are in the
    build tree. See "muddle help labels".

    If '-v' is given, report each checkout label as it is checked (allowing
    a sense of progress if there are many bazaar checkouts, for instance).

    Runs the equivalent of ``git status`` or ``bzr status`` on each repository,
    and tries to only report those which have significant status.

        Note: For subversion, the (remote) repository is queried,
        which may be slow.

    Be aware that "muddle status" will report on the currently checked out
    checkouts. "muddle status _all" will (attempt to) report on *all* the
    checkouts described by the build, even if they have not yet been checked
    out. This will fail on the first checkout directory it can't "cd" into
    (i.e., the first checkout that isn't there yet).
    """

    # XXX Is this what we want???
    required_tag = LabelTag.Fetched
    allowed_switches = {'-v': 'verbose'}

    def build_these_labels(self, builder, labels):

        if len(labels) == 0:
            raise GiveUp('No checkouts specified - not checking anything')
        else:
            print 'Checking %d checkout%s'%(len(labels), '' if len(labels)==1 else 's')

        if 'verbose' in self.switches:
            verbose = True
        else:
            verbose = False

        something_needs_doing = False
        for co in labels:
            rule = builder.invocation.ruleset.rule_for_target(co)
            try:
                vcs = rule.action.vcs
            except AttributeError:
                print "Rule for label '%s' has no VCS - cannot find its status"%co
                continue
            text = vcs.status(verbose)
            if text:
                print text
                something_needs_doing = True
        if not something_needs_doing:
            print 'All checkouts seemed clean'

@command('reparent', CAT_CHECKOUT)
class Reparent(CheckoutCommand):
    """
    :Syntax: muddle reparent [-f[orce]] [ <checkout> ... ]

    Re-associate the specified checkouts with their remote repositories.

    <checkout> should be a label fragment specifying a checkout, or one of
    _all and friends, as for any checkout command. The <type> defaults to
    "checkout", and the checkout <tag> will be "/fetched". See "muddle help
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
    required_tag = LabelTag.Fetched
    allowed_switches = {'-f':'force', '-force':'force'}

    def build_these_labels(self, builder, labels):

        if 'force' in self.switches:
            force = True
        else:
            force = False

        for co in labels:
            rule = builder.invocation.ruleset.rule_for_target(co)
            try:
                vcs = rule.action.vcs
            except AttributeError:
                print "Rule for label '%s' has no VCS - cannot reparent, ignored"%co
                continue
            vcs.reparent(force=force, verbose=True)

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
            builder.invocation.db.clear_tag(c)

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
            builder.invocation.db.set_tag(c)
        # issue 143: Call reparent so the VCS is locked and loaded.
        rep = g_command_dict['reparent']() # should be Reparent but go via the dict just in case
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
    """

    def build_these_labels(self, builder, labels):
        for co in labels:
            builder.build_label(co)

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

    def build_these_labels(self, builder, labels, upstream_names, no_op):
        get_checkout_repo = builder.invocation.db.get_checkout_repo
        get_upstream_repos = builder.invocation.db.get_upstream_repos
        get_checkout_location = builder.invocation.db.get_checkout_location
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
                        co_locn = get_checkout_location(co)
                        self.handle_label(builder, co, repo, co_locn)

            else:
                if not no_op:
                    print
                print 'Nowhere to %s %s %s'%(self.verb, co, self.direction)

    def handle_label(self, builder, co_label, repo, co_locn):
        src_dir, rest = utils.split_path_left(co_locn)
        if src_dir != 'src':
            raise MuddleBug('Splitting location for %s, but %s does not'
                            ' start "src"'%(co_label, co_locn))
        co_dir, co_leaf = os.path.split(rest)

        # And from *that*, we can build the handler we actually want
        vcs_handler = version_control.vcs_handler_for(builder, co_label,
                                                      co_leaf, repo, co_dir)

        # And do whatever we need to do
        self.do_our_verb(vcs_handler)

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

    Use "muddle upstream-repos [<checkout>]" to find out about the available
    upstream repositories.
    """

    required_tag = LabelTag.CheckedOut
    allowed_switches = {}

    verb = 'push'
    verbing = 'Pushing'
    direction = 'to'

    def do_our_verb(self, vcs_handler):
        # And we can then use that to do the push
        # (in the happy knowledge that *it* will grumble if we're not allowed to)
        vcs_handler.push()

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

    Use "muddle upstream-repos [<checkout>]" to find out about the available
    upstream repositories.
    """

    required_tag = LabelTag.CheckedOut
    allowed_switches = {}

    verb = 'pull'
    verbing = 'Pulling'
    direction = 'from'

    def do_our_verb(self, vcs_handler):
        # And we can then use that to do the pull
        # (in the happy knowledge that *it* will grumble if we're not allowed to)
        vcs_handler.fetch()

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

    <label> may also be "_all", "_default_deployments" or "_default_roles".

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

    <label> may also be "_all", "_default_deployments" or "_default_roles".

    See "muddle help labels" for more help on label fragments and the "_xxx"
    values.
    """

    def build_these_labels(self, builder, labels):
        for l in labels:
            builder.invocation.db.set_tag(l)

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

    <label> may also be "_all", "_default_deployments" or "_default_roles".

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

    <label> may also be "_all", "_default_deployments" or "_default_roles".

    See "muddle help labels" for more help on label fragments and the "_xxx"
    values.
    """

    def build_these_labels(self, builder, labels):
        print "Clear: %s"%(label_list_to_string(labels))
        for l in labels:
            builder.invocation.db.clear_tag(l)

        print "Build: %s"%(label_list_to_string(labels))
        for l in labels:
            builder.build_label(l)

# -----------------------------------------------------------------------------
# Misc commands
# -----------------------------------------------------------------------------
# It's arguable what category this should go in, but I've not put it in
# CAT_PACKAGE because its argument list is not the same as all the other
# package commands
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
    """

    def requires_build_tree(self):
        return True

    def with_build_tree(self, builder, current_dir, args):
        if (len(args) < 2):
            print "Syntax: runin <label> <command> [ ... ]"
            print self.__doc__
            return

        labels = self.decode_labels(builder, args[0:1] )
        command = " ".join(args[1:])
        dirs_done = set()

        if self.no_op():
            print 'Run "%s" for: %s'%(command, label_list_to_string(labels))
            return

        for l in labels:
            matching = builder.invocation.ruleset.rules_for_target(l)

            for m in matching:
                lbl = m.target

                dir = None
                if (lbl.name == "*"):
                    # If it's a wildcard, don't bother.
                    continue

                if (lbl.type == LabelType.Checkout):
                    dir = builder.invocation.checkout_path(lbl)
                elif (lbl.type == LabelType.Package):
                    if (lbl.role == "*"):
                        continue
                    dir = builder.invocation.package_obj_path(lbl)
                elif (lbl.type == LabelType.Deployment):
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

                    with utils.Directory(dir):
                        subprocess.call(command, shell=True, env=env,
                                        stdout=sys.stdout, stderr=subprocess.STDOUT)
                else:
                    print "! %s does not exist."%dir

    def decode_labels(self, builder, in_args):
        """
        Each argument is a label - convert each to a proper label
        object and then return the resulting list
        """
        rv = [ ]
        for arg in in_args:
            # XXX Label fragments would be better?
            lbl = Label.from_string(arg)
            rv.append(lbl)

        return rv

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
            x_env = builder.invocation.effective_environment_for(lbl)
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

    def without_build_tree(self, muddle_binary, root_path, args):
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
    :Syntax: muddle subst <src_file> <xml_file> <dst_file>

    Substitute (with "${.. }") <src file> into <dst file> using data from
    the environment or from the given xml file.

    XML queries look a bit like XPath queries - "/elem/elem/elem..."
    An implicit "::text()" is appended so you get all the text in the specified
    element.

    You can escape a "${ .. }" by passing "$${ .. }"

    You can insert literals with "${" .. " }"

    Or call functions with "${fn: .. }". Available functions include:

    * "${val:(something)}" - Value of something as a query (env var or XPath)
    * "${ifeq:(a,b,c)}" - If eval(a)==eval(b), expand to eval(c)
    * "${ifneq:(a,b,c)}" - If eval(a)!=eval(b), expand to eval(c)
    * "${echo:(..)}" -  Evaluate all your parameters in turn.
    """

    def requires_build_tree(self):
        return False

    def with_build_tree(self, builder, current_dir, args):
        self.do_subst(args)

    def without_build_tree(self, muddle_binary, root_path, args):
        self.do_subst(args)

    def do_subst(self, args):
        if len(args) != 3:
            raise GiveUp("Syntax: subst [src] [xml] [dst]")

        src = args[0]
        xml_file = args[1]
        dst = args[2]

        if self.no_op():
            print 'Substitute source file %s'%src
            print '       using data from %s'%xml_file
            print '            to produce %s'%dst
            return

        f = open(xml_file, "r")
        xml_doc = xml.dom.minidom.parse(f)
        f.close()

        subst.subst_file(src, dst, xml_doc, self.old_env)
        return 0

# End file.
