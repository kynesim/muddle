"""
Dependency sets and dependency management
"""

import os
import muddled.db
import pkg
import utils
import copy
import re

class Label(object):
    """
    A label denotes an entity in muddle's dependency heirarchy.

    A label is structured as::

            <type>:<name>{<role>}/<tag>[<flags>]

    The <type>, <name>, <role> and <tag> parts are composed of the characters
    [A-Za-z0-9-+_], or the wildcard character '*'. The role and flags are
    optional.

        .. note:: The label strings "type:name/tag" and "type:name{}/tag[]" are
           identical, although the former is the more usual form.)

           The '+' is allowed in label parts to allow for names like "g++".
    
    Names beginning with an underscore are reserved by muddle, so do not use
    them for other purposes.

    Label instances are treated as immutable by the muddle system, although the
    implementation does not currently enforce this. Please don't try to abuse
    this, as Bad Things will happen.
    """

    # Is this correct? A "word" or an asterisk...
    label_part = r"[A-Za-z0-9._+-]+|\*"
    label_part_re = re.compile(label_part)

    label_string_re = re.compile(r"""
                                 (?P<type>%s) :             # <type> and colon
                                 (?P<name>%s)               # <name>
                                 (\{
                                    (?P<role>%s)?           # optional <role>
                                  \})?                      # in optional {}
                                 / (?P<tag>%s)              # slash and <tag>
                                 (\[
                                    (?P<flags>[A-Za-z0-9]+) # 0 or more flags
                                  \])?                      # in optional []
                                 """%(label_part,label_part,label_part,label_part),
                                 re.VERBOSE)

    def __init__(self, type, name, role=None, tag='*', transient=False, system=False):
        """
        :type:      What kind of label this is. The standard muddle values are
                    "checkout", "package" and "deployment". These values are
                    defined programmatically via muddled.utils.LabelKind.
                    Thus the 'type' is conventionally used to indicate what
                    general "stage" of the build process a label belongs to.
        :name:      The name of this checkout/package/whatever. This should be
                    a useful mnemonic for the labels purpose.
        :role:      The role for this checkout/package/whatever. A role might
                    delimit the target architecture of the labels it is used
                    in (roles such as "x86", "arm", "beagleboard"), or the
                    sort of purpose ("role" in the more traditionale sense,
                    such as "boot", "firmware", "packages"), or some other
                    useful delineation of a partition in the general label
                    namespace (thinking of labels as points in an N-dimensional
                    space).
        :tag:       A tag indicating more precisely what stage the label
                    belongs to within each 'type'. There are different
                    conventional values according to the 'type' of the label
                    (for instance, "checked_out", "built", "installed", etc.).
                    These values are defined programmatically via
                    muddled.utils.Tags.
        :transient: If true, changes to this tag will not be persistent in
                    the muddle database. 'transient' is used to denote
                    something which will go away when muddle is terminated -
                    e.g. environment variables.
        :system:    If true, marks this label as a system label and not to be
                    reported (by 'muddle depend') unless asked for. System labels
                    are labels "invented" by muddle itself to satisfy implicit
                    dependencies, or to allow the build system as a whole to
                    work.

        The role may be None, indicating (for instance) that roles are not
        relevant to this particular label.

        The kind, name, role and tag may be wildcarded, by being set to '*'.
        When evaluating dependencies between labels, for instance, a wildcard
        indicates "for any value of this part of the label".

        Note that 'transient' and 'system' are not equality-preserving
        properties of a label - two labels are not made unequal just because
        they have different transiences! (indeed, no two labels should ever
        have different values for these, for obvious reasons), and the system
        flag is intended only to limit over-reporting of information.

        For instance:

            >>> Label('package', 'busybox')
            Label('package', 'busybox', role=None, tag='*')
            >>> str(_)
            'package:busybox/*'
            >>> Label('package', 'busybox', tag='installed')
            Label('package', 'busybox', role=None, tag='installed')
            >>> str(_)
            'package:busybox/installed'
            >>> Label('package', 'busybox', role='rootfs', tag='installed')
            Label('package', 'busybox', role='rootfs', tag='installed')
            >>> str(_)
            'package:busybox{rootfs}/installed'
            >>> Label('package', 'busybox', 'rootfs', 'installed')
            Label('package', 'busybox', role='rootfs', tag='installed')
            >>> str(_)
            'package:busybox{rootfs}/installed'
        """

        # Slightly icky, but it's a pain if an illegal label is allowed
        # to happen, so it's friendliest to check specifics
        self._check_value('type',type)
        self._check_value('name',name)
        if role is not None:
            self._check_value('role',role)
        self._check_value('tag',tag)

        self.type = type
        self.name = name
        self.role = role
        self.tag = tag
        self.transient = transient
        self.system = system

    def _check_value(self, what, value):
        """
        Check that a label component is allowed.

        Raises an exception if it's Bad, does nothing if it's OK.
        """
        m = self.label_part_re.match(value)
        if m is None or m.end() != len(value):
            raise utils.Failure("Label %s '%s' is not allowed"%(what,value))

    def make_transient(self, transience = True):
        """
        Set the transience status of a label.
        """
        self.transient = transience
        
    def re_tag(self, new_tag, system = None, transient = None):
        """
        Return a copy of self, with the tag changed to new_tag.
        """
        cp = self.copy()
        cp.tag = new_tag
        cp.system = system
        cp.transient = transient
        return cp

    def match(self, other):
        """
        Return an integer indicating the match specicifity - which we do
        by counting '*' s and subtracting from 0.

        Returns the match specicifity, None if there wasn't one.
        """

        nr_wildcards = 0
        if self.type != other.type:
            if self.type == "*" or other.type == "*":
                nr_wildcards += 1
            else:
                return None

        if self.name != other.name:
            if self.name == "*" or other.name == "*":
                nr_wildcards += 1
            else:
                return None

        if self.role != other.role:
            if self.role == "*" or other.role == "*":
                nr_wildcards += 1
            else:
                return None

        if self.tag != other.tag:
            if self.tag == "*" or other.tag == "*":
                nr_wildcards += 1
            else:
                return None

        return -nr_wildcards

    def match_without_tag(self, other):
        """
        Returns True if other matches self without the tag, False otherwise

        Specifically, tests whether the two Labels have identical type, name
        and role.
        """
        return (self.type == other.type and
                self.name == other.name and
                self.role == other.role)

    def copy(self):
        """
        Return a copy of this label.
        """
        return copy.copy(self)

    def __repr__(self):
        parts = [repr(self.type),
                 repr(self.name),
                 'role=%s'%repr(self.role),
                 'tag=%s'%repr(self.tag)]
                 
        if self.transient:
            parts.append('transient=True')
        if self.system:
            parts.append('system=True')
        return 'Label(%s)'%', '.join(parts)

    def __str__(self):
        if self.role:
            basename = "%s{%s}"%(self.name, self.role)
        else:
            basename = self.name

        rv =  "%s:%s/%s"%(self.type, basename, self.tag)

        if self.transient or self.system:
            extra = "[%s%s]"%( "T" if self.transient else "",
                               "S" if self.system    else "")
            rv += extra

        return rv

    def __cmp__(self, other):
        """
        Compare two Labels.
        
        Ignores the 'transient' and 'system' values (if any).
        """
        this_as_tuple = self.as_tuple()
        that_as_tuple = other.as_tuple()

        if this_as_tuple < that_as_tuple:
            return -1
        elif this_as_tuple > that_as_tuple:
            return 1
        else:
            return 0

    def as_tuple(self):
        """
        Return the Label values as a tuple, e.g., for comparison or hashing.

        Returns (type, name, role, tag). Does not return the 'transient' or
        'system' values, if any.
        """
        return (self.type, self.name, self.role, self.tag)

    def __hash__(self):
        # Is it acceptable to ignore 'transient' and 'system' when hashing?
        # I assume so.
        return hash( self.as_tuple() )

    @staticmethod
    def from_string(label_string):
        """
        Construct a Label from its string representation.

        The string should be of the correct form:

        * <type>:<name>/<tag>
        * <type>:<name>{<role>}/<tag>
        * <type>:<name>/<tag>[<flags>]
        * <type>:<name>{<role>}/<tag>[<flags>]

        See the docstring for Label itself for the meaning of the various
        parts of a label.

        <flags> is a set of individual characters indicated as flags. There are two
        pre-defined flags, 'T' for Transience and 'S' for System. Unrecognised flag
        characters will be ignored.

        If the label string is valid, a corresponding Label will be returned,
        otherwise a Failure wil be raised.

        >>> Label.from_string('package:busybox')
        Traceback (most recent call last):
        ...
        muddled.utils.Failure: Label string 'package:busybox' is not a valid Label
        >>> Label.from_string('package:busybox/installed')
        Label('package', 'busybox', role=None, tag='installed') 
        >>> Label.from_string('package:busybox{firmware}/installed[ABT]')
        Label('package', 'busybox', role='firmware', tag='installed', transient=True)
        >>> Label.from_string('*:*{*}/*')
        Label('*', '*', role='*', tag='*')
        """
        m = Label.label_string_re.match(label_string)
        if m is None or m.end() != len(label_string):
            raise utils.Failure('Label string %s is not a valid'
                                ' Label'%repr(label_string))

        type   = m.group('type')
        name   = m.group('name')
        role   = m.group('role') # conveniently, None if not present
        tag    = m.group('tag')
        flags  = m.group('flags')

        transient = False
        system = False

        if flags:
            transient = 'T' in flags
            system    = 'S' in flags

        return Label(type, name, role=role, tag=tag, transient=transient,
                      system=system)


class Rule:
    """
    A rule. Every dependency set has a target Label, an 
    object, and a set of Labels on which the target depends.

    Once you've satisfied all the depended Labels, you get to call the
    underlying object to make the target.
    """

    def __init__(self, target_dep, obj):
        self.deps = set()
        if (not isinstance(target_dep, Label)):
            raise utils.Error("Attempt to create a rule without a label"
                              " as its target")

        self.target = target_dep
        self.obj = obj
        if (self.obj is not None) and (not isinstance(obj, pkg.Dependable)):
            raise utils.Error("Attempt to create a rule with an object rule "
                              "which isn't a dependable but a %s."%(obj.__class__.__name__))


    def set_arg(self, arg):
        """ 
        arg is an optional argument used to pass extra data through to
        a dependable that is built as the result of a dependency.
        """
        self.arg = arg

    def add(self,label):
        self.deps.add(label)

    def merge(self, deps):
        """
        Merge another Deps set with this one.
        """
        for i in deps.deps:
            self.add(i)

        # This is important to ensure that empty dependencies
        # (which are rules with None as their dependable object)
        # get correctly overridden by merged rules when they're
        # registered
        if (deps.obj is not None):
            self.obj = deps.obj


    def depend_checkout(self, co_name, tag):
        dep = Label(utils.LabelKind.Checkout, co_name, None, tag)
        self.deps += dep

    def depend_pkg(self, pkg, role, tag):
        dep = Label(utils.LabelKind.Package, pkg, role, tag)
        self.deps += dep

    def depend_deploy(self, dep_name, tag):
        dep = Label(utils.LabelKind.Deployment, dep_name, None, tag)
        self.deps += dep

    def __str__(self):
        return self.to_string()

    def __cmp__(self, other):
        # XXX Is this a sensible algorithm?
        # XXX Certainly starting by sorting the target sounds good
        # XXX (I have some concern over sorting by self.obj, which doesn't
        # XXX show up in the string representation of a Rule)
        if self.target < other.target:
            return -1
        elif self.target > other.target:
            return 1
        elif self.deps > other.deps:
            return 1
        elif self.deps < other.deps:
            return -1
        elif self.obj > other.obj:
            return 1
        elif self.obj < other.obj:
            return -1
        else:
            return 0

    def __hash__(self):
        # XXX If we have __cmp__, we need __hash__ to be hashable. Does this
        # XXX implementation make sense? Would it be better to hash on our
        # XXX string representation (for instance)?
        return hash(self.target) | hash(self.obj)

    def to_string(self, showSystem = True, showUser = True):
        """
        Return a string representing this dependency set.
        """
        str_list = [ ]
        str_list.append(self.target.__str__())
        str_list.append("<- [")
        if self.deps:
            dep_list = []
            for i in self.deps:
                if ((i.system and showSystem) or ((not i.system) and showUser)):
                    dep_list.append(i.__str__())
            str_list.append(', '.join(dep_list))
        str_list.append("]\n")
        return " ".join(str_list)
        


class RuleSet:
    """
    A collection of rules that encapsulate how you can 
    get from A to B.

    Formally, this is just a mapping of labels to Rules. Duplicate
    targets are merged - it's assumed that the objects will be 
    the same.
    """
    
    def __init__(self):
        self.map = { }

    def add(self, rule):
        # Do we have the same target?
        inst = self.map.get(rule.target, None)
        if (inst is None):
            self.map[rule.target] = rule
        else:
            inst.merge(rule)


    def rules_for_target(self, label, useTags = True, useMatch = True):
        """
        Return the set of rules for any target matching tag.
    
        If useTags is true, we match against tag values. Otherwise we ignore
        tag values.

        * useTags  - True if we should match tags too, False otherwise.
        * useMatch - True if we should allow wildcards in the label.

        Returns the set of rules found, or the empty set if none were found.
        """
        rules = set()
        if (useMatch):
            for (k,v) in self.map.items():
                if (label.match(k) is not None):
                    rules.add(v)
        elif (useTags):
            rule = self.map.get(label, None)
            if (rule is not None):
                rules.add(rule)
        else:
            for (k,v) in self.map.items():
                if (k.match_without_tag(label)):
                    rules.add(v)


        return rules
            
    def targets_match(self, target, useMatch = True):
        """
        Retrieve all the targets matching target, if useMatch is True.
        If useMatch is false, just return target.

        Returns a set of suitable targets.
        """
        result_set = set()

        if (useMatch):
            for k in self.map.keys():
                if (k.match(target) is not None):
                    result_set.add(k)
        else:
            result_set.add(target)

        return result_set

                
    
    def rule_for_target(self, target, createIfNotPresent = False):
        """
        Return the rule for this target - this contains all the labels that
        need to be asserted in order to build the target.

        If there is no rule for this target, we return None
        """
        rv =  self.map.get(target, None)
        if (createIfNotPresent and (rv is None)):
            rv = Rule(target, None)
            self.map[target] = rv

        return rv
        

    def rules_which_depend_on(self, label, useTags = True, useMatch = True):
        """
        Given a label, return a set of the rules which have it as one of
        their dependencies. 
        
        If there are no rules which have this label as one of their 
        dependencies, we return the empty set.
        """
        result_set = set()

        for v in self.map.values():
            if useMatch:
                for dep in v.deps:
                    if dep.match(label) is not None:
                        result_set.add(v)
                        break
            elif useTags:
                if (label in v.deps):
                    result_set.add(v)
            else:
                for dep in v.deps:
                    if dep.match_without_tag(label):
                        result_set.add(v)
                        break
                    
                    
        return result_set

    def merge(self, other_deps):
        for i in other_deps.items():
            self.add(i)

    def to_string(self, matchLabel = None, 
                  showUser = True, showSystem = True, ignore_empty=False):
        str_list = [ ]
        str_list.append("-----\n")
        values = self.map.values()
        values.sort()
        for i in values:
            if ignore_empty and not i.deps:
                # Ignore items that don't depend on anything
                continue
            if (matchLabel is None) or (matchLabel.match(i.target) is not None):
                if ((i.target.system and showSystem) or 
                    ((not i.target.system) and showUser)):
                    str_list.append(i.to_string(showUser = showUser, showSystem = showSystem))
        str_list.append("-----\n")
        return "".join(str_list)
        

    def __str__(self):
        return self.to_string()

def label_from_string(str):
    """
    Given a string representing a label, return a corresponding Label instance.

    The string should be of the correct form:

    * <type>:<name>/<tag>
    * <type>:<name>{<role>}/<tag>
    * <type>:<name>/<tag>[<flags>]
    * <type>:<name>{<role>}/<tag>[<flags>]

    See the docstring for Label for the meaning of the various parts of a
    label.

    <flags> is a set of individual characters indicated as flags. There are two
    pre-defined flags, 'T' for Transience and 'S' for System. Unrecognised flag
    characters will be ignored.

    Returns a Label or None if the string was ill-formed.

    (This is a wrapping of Label.from_string(), but with different return
    conventions.)
    """

    try:
        return Label.from_string(str)
    except utils.Failure:
        return None
    

def depend_chain(obj, label, tags, ruleset):
    """
    Add a chain of dependencies to the given ruleset.
    """

    last = label.copy()

    # The base .. 
    r = Rule(last, obj)
    ruleset.add(r)

    for tag in tags:
        next = last.copy()
        next.tag = tag
        r = Rule(next, obj)
        r.add(last)
        ruleset.add(r)
        last = next

    

def depend_none(obj, label):
    """
    Quick rule that makes label depend on nothing.
    """
    return Rule(label, obj)

def depend_one(obj, label, dep_label):
    """
    Quick rule that makes label depend only on dep_label.
    """
    rv = Rule(label, obj)
    rv.add(dep_label)
    return rv


def depend_self(obj, label, old_tag):
    """
    Make a quick dependency set that depends just on you. Used by some of the
    standard package and checkout classes to quickly build standard dependency
    sets.
    """
    rv = Rule(label, obj)
    dep_label = label.copy()
    dep_label.tag = old_tag

    rv.add(dep_label)
    return rv
        

def depend_empty(obj, label):
    """
    Create a dependency set with no prerequisites - simply signals that a 
    tag is available to be built at any time.
    """
    rv = Rule(label, obj)
    return rv


def label_set_to_string(label_set):
    """
    Utility function to convert a label set to a string.
    """
    str_list = [ "{ " ]
    for  i in label_set:
        str_list.append(i.__str__())
        str_list.append(", ")
    str_list.append("} ")
    return "".join(str_list)

def rule_list_to_string(rule_list):
    """
    Utility function to convert a rule list to a string.
    """
    str_list = [ "[ " ]
    for i in rule_list:
        str_list.append(i.__str__())
        str_list.append(", ")
    str_list.append(" ]")
    return "".join(str_list)


def label_list_to_string(labels):
    return " ".join(map(str, labels))

def retag_label_list(labels, new_tag):
    """
    Does what it says on the tin, returning the new label list.
    """
    result = [ ]
    for l in labels:
        next_l = l.copy()
        next_l.tag = new_tag
        result.append(next_l)

    return result

def needed_to_build(ruleset, target, useTags = True, useMatch = False):
    """
    Given a rule set and a target, return a complete list of the rules needed
    to build the target.

    * useTags - If False, indicates a wildcard search - any tag will match.

    Returns a list of rules.
    """

    # rule_list stores the list of rules we're about to return.
    rule_list = [ ]
    # rule_target_set stores the set of targets resulting from rule_list
    # (i.e. if you'd obeyed rule_list, you'd have asserted all these labels)
    rule_target_set = set()

    # The set of labels we'd like to see asserted.
    targets = set()
    targets.update(ruleset.targets_match(target, useMatch = useMatch))

    done_something = True
    trace = False

    while done_something:
        done_something = False
        
        if (trace):
            print "> Loop"

        # Remove anything we've already satisfied from our list of targets.
        targets = targets - rule_target_set

        # Have we succeeded?
        if len(targets) == 0:
            # Yep!
            if (trace):
                print "To build: %s\n Needs: %s\n"%(target, map(str, rule_list))
            return rule_list
        
        # In that case, we need to go through all the dependencies of the
        # targets, adding each either to the target list or the rule_list.
        new_targets = set()

        for tgt in targets:
            rules = ruleset.rules_for_target(tgt, useTags)
            if (rules is None):
                raise utils.Error("No rule found for target %s"%tgt)

            # This is slightly icky. Technically, in the presence of wildcard
            # rules, there can be several rules which build a target.
            #
            # Since we use wildcard rules to add extra rules to targets,
            # we need to satisfy every rule that builds this target.

            # Every dependency has either already been satisfied or
            # needs to be.
            can_build_target = True

            if len(rules) == 0:
                raise utils.Error("Rule list is empty for target %s"%tgt)


            if (trace):
                print "Rules for %s = %s"%(tgt, " ".join(map(str, rules)))

            for rule in rules:            
                for dep in rule.deps:
                    if not (dep in rule_target_set):
                        # Not satisfied. We need to satisfy it, so add it
                        # to targets. The test here is purely so we can 
                        # detect circular dependencies.
                        if (not (dep in new_targets) and not (dep in targets)):
                            if (trace):
                                print "Add new target = %s"%str(dep)
                            new_targets.add(dep)
                            done_something = True

                        if (trace):
                            print "Cannot build %s because of dependency %s"%(tgt, dep)
                            # .. and we can't build this target until we have.
                        can_build_target = False
                        
            if can_build_target:
                # All dependencies are already satisfied, so we can ..
                if (trace):
                    print "Build rule = %s [ %s ] "%(str(tgt), str(rule))
                rule_list.append(rule)
                rule_target_set.add(tgt)
                done_something = True
            else:
                # Can't satisfy our dependencies. Still a target.
                new_targets.add(tgt)

        targets = new_targets

        
    # If we get here, we can never satisfy the remaining set of
    # targets because the graph is circular or incomplete.
    raise utils.Error("Dependency graph is circular or incomplete. \n" +
                      "building = %s\n"%target +
                      "targets = %s \n"%label_set_to_string(targets) + 
                      "rule_list = %s \n"%rule_list_to_string(rule_list) + 
                      "ruleset = %s\n"%ruleset)


def required_by(ruleset, label, useTags = True, useMatch = True):
    """
    Given a ruleset and a label, form the list of labels that (directly or
    indirectly) depend on label. We deliberately do not give you the 
    associated rules since you will want to call needed_to_build() individually
    to ensure that other prerequisites are satisfied.
    
    The order in which we give you the labels gives you a hint as to a
    logical order to rebuild in (i.e. one the user will vaguely understand).

    * useMatch - If True, do wildcard matches, else do an exact comparison.
    * useTags  - If False, we discount the value of a tag - this effectively
                 results in a wildcard tag search.

    Returns a set of labels to build.
    """
    
    depends = set()
    return_val = [ ]

    # Grab the initial dependency set.
    rules = ruleset.rules_for_target(label, useMatch = useMatch)
    if (len(rules) == 0):
        raise utils.Failure("No rules match label %s ."%label)

    for r in rules:
        depends.add(r.target)



    while True:
        extra = set()

        for dep in depends:
            # Merge in everything that depends on dep
            new_rules = ruleset.rules_which_depend_on(dep, useTags, useMatch = useMatch)
            
            # Each target depends on us ..
            for rule in new_rules:
                # If we're not already in the depends set, add us ..
                if (not (rule.target in depends)):
                    return_val.append(rule.target)
                    extra.add(rule.target)

        # Anything to add?
        if len(extra) > 0:
            depends = depends.union(extra)
        else:
            return depends


def rule_with_least_dependencies(rules):
    """
    Given a (Python) set of rules, find the 'best' one to use.

    This is actually impossible by any rational metric, so you 
    usually only expect to call this function with a set of
    size 1, in which case our metric really doesn't matter.

    However, in a vague attempt to be somewhat intelligent, 
    we return the element with the fewest direct dependencies.
    """
    best_r = None

    for r in rules:
        if (best_r is None) or (len(r.deps) < len(best_r.deps)):
            best_r =r

    return best_r


def rule_target_str(rule):
    """
    Take a rule and return its target as a string. Mainly used as
    an argument for map so we can print lists of rules sensibly.
    """
    return str(rule.target)

# End file.


    

