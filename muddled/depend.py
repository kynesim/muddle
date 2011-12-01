"""
Dependency sets and dependency management
"""

import re
import copy

import muddled.utils as utils

class Label(object):
    """
    A label denotes an entity in muddle's dependency hierarchy.

    A label is structured as::

            <type>:<name>{<role>}/<tag>[<flags>]

    or::

            <type>:(<domain>)<name>{<role>}/<tag>[<flags>]

    The <type>, <name>, <role> and <tag> parts are composed of the characters
    [A-Za-z0-9-+_], or the wildcard character '*'.

    The <domain> name is composed of the same plus '(' and ')'.

    The domain, role and flags are all optional.

        .. note:: The label strings "type:name/tag" and "type:name{}/tag[]" are
           identical, although the former is the more usual form.)

           The '+' is allowed in label parts to allow for names like "g++".

           Domains are used when relating sub-builds to each other, and are
           not necessary when relating labels within the same build. It is
           not allowed to specify the empty domain as "()" - just omit the
           parentheses.

           If necessary "sub-domains" are specified using nested domains -- for
           instance::

                (outer)
                (outer(inner))
                (outer(inner(even.innerer)))

           This is intended to be unambiguous rather than pretty.

           Note that wildcarding of a domain name currently only supports one
           level (i.e., the top "(*)"), and not wildcarding of nested domains.

           If you do find yourself using multi-level domains, we would strongly
           suggest reconsidering your overall build design.

    The "core" part of a label is the ``<name>{<role>}`` or
    ``(<domain>)<name>{<role>}``. The <type> and <tag> can (typically) be
    thought of as tracking the progress of the "core" entity through its
    lifecycle (build sequence, etc.).

    Names beginning with an underscore are reserved by muddle, so do not use
    them for other purposes.

        (Why is the 'domain' argument at the end of the argument list? Because
        it was added after the other arguments were already well-established,
        and some uses of Label use positional arguments.)

    Label instances are treated as immutable by the muddle system, although the
    implementation does not currently enforce this. Please don't try to abuse
    this, as Bad Things will happen.

    .. note:: The *flags* on a label are not immutable, and are regarded as
              transient annotations.

    .. note:: When a domain is included as a subdomain, all of its labels are
              "adjusted" to have the new, appropriate domain name. This is
              clearly a special meaning of the word "immutable". However, it
              should only be the muddle system itself doing this.

              Because of this (potential change in content of a label), the
              domain name does not contribute to a label's hash value. Thus
              a label that whose domain name is changed will continue to
              work as the same key in a dictionary (for instance).
    """

    # Let's make a record of what conventional flag characters are
    FLAG_SYSTEM       = 'S'
    FLAG_TRANSIENT    = 'T'
    FLAG_DOMAIN_SWEEP = 'D'

    # Is this correct? A "word" or an asterisk...
    label_part = r"[A-Za-z0-9._+-]+|\*"
    label_part_re = re.compile(label_part)

    domain_part = r"[()A-Za-z0-9._+-]+|\*"
    domain_part_re = re.compile(domain_part)

    label_string_re = re.compile(r"""
                                 (?P<type>%s) :             # <type> and colon
                                 (\(
                                     (?P<domain>%s)         # <domain>
                                 \))?                       # in optional ()
                                 (?P<name>%s)               # <name>
                                 (\{
                                    (?P<role>%s)?           # optional <role>
                                  \})?                      # in optional {}
                                 / (?P<tag>%s)              # slash and <tag>
                                 (\[
                                    (?P<flags>[A-Za-z0-9]+) # 0 or more flags
                                  \])?                      # in optional []
                                 """%(label_part,domain_part,label_part,
                                      label_part,label_part),
                                 re.VERBOSE)

    # In fragments, we allow want to allow ()<name> to mean "in the toplevel
    # domain", so that we can override the default domain (which is presumably
    # implied by location in the build tree)
    fragment_re = re.compile(r"""
                             ((?P<type>%s) :)?          # optional <type> and colon
                             (\(
                                 (?P<domain>%s)         # <domain>
                             \))?                       # in optional ()
                             (?P<name>%s)               # <name>
                             (\{
                                (?P<role>%s)?           # optional <role>
                              \})?                      # in optional {}
                              (/ (?P<tag>%s))?          # optional slash and <tag>
                              $                         # and nothing more
                              """%(label_part, domain_part, label_part,
                                   label_part, label_part),
                             re.VERBOSE)

    def __init__(self, type, name, role=None, tag='*', transient=False,
                 system=False, domain=None):
        """
        :type:      What kind of label this is. The standard muddle values are
                    "checkout", "package" and "deployment". These values are
                    defined programmatically via muddled.utils.LabelType.
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
                    muddled.utils.LabelTag.
        :transient: If true, changes to this tag will not be persistent in
                    the muddle database. 'transient' is used to denote
                    something which will go away when muddle is terminated -
                    e.g. environment variables.
        :system:    If true, marks this label as a system label and not to be
                    reported (by 'muddle depend') unless asked for. System labels
                    are labels "invented" by muddle itself to satisfy implicit
                    dependencies, or to allow the build system as a whole to
                    work.
        :domain:    The domain is used to specify which build or sub-build this
                    label corresponds to. Nested "tail recursive" parenthesised
                    components may be used to specify sub-domains (but this is
                    not recommended). The domain defaults to the current build.

        The role may be None, indicating (for instance) that roles are not
        relevant to this particular label.

        The domain may be None, indicating that the label belongs to the
        current build. Do not specify domains unless you need to.

        The kind, name, role and tag may be wildcarded, by being set to '*'.
        When evaluating dependencies between labels, for instance, a wildcard
        indicates "for any value of this part of the label".

        Domains can be wildcarded, and that probably means the obvious (that
        the label applies across all domains), but this may not yet be
        implemented. Wildcarding of sub-domains may never be supported.

        Note that label flags (including specifically 'transient' and 'system')
        are not equality-preserving properties of a label - two labels are not
        made unequal just because they have different flags.

        (In fact, no two labels should ever have different values for
        transience, for obvious reasons, and the system flag is intended only
        to limit over-reporting of information.)

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
            >>> Label('package', 'busybox', role='rootfs', tag='installed', domain="arm.helloworld")
            Label('package', 'busybox', role='rootfs', tag='installed', domain='arm.helloworld')
            >>> str(_)
            'package:(arm.helloworld)busybox{rootfs}/installed'
            >>> Label('package', 'busybox', role='rootfs', tag='installed', domain="arm(helloworld)")
            Label('package', 'busybox', role='rootfs', tag='installed', domain='arm(helloworld)')
            >>> str(_)
            'package:(arm(helloworld))busybox{rootfs}/installed'

        """

        # Slightly icky, but it's a pain if an illegal label is allowed
        # to happen, so it's friendliest to check specifics
        _check_part = Label._check_part
        _check_part('type',type)
        _check_part('name',name)
        if role is not None:
            _check_part('role',role)
        _check_part('tag',tag)
        if domain is not None:
            Label._check_domain(domain)

        self._type = type
        self._domain = domain
        self._name = name
        self._role = role
        self._tag = tag

        # Flags are *not* immutable
        self.transient = transient
        self.system = system
        # The "unswept" flag is regarded as internal
        self._unswept = False

    @property
    def type(self):
        return self._type

    @property
    def domain(self):
        return self._domain

    @property
    def name(self):
        return self._name

    @property
    def role(self):
        return self._role

    @property
    def tag(self):
        return self._tag

    def copy_and_unify_with(self, target):
        """
        Return a copy of ourserlves, unified with the target.

        All the non-wildcard parts of 'target' are copied, to overwrite
        the equivalent parts of the new label.
        """
        new = self.copy()

        #print "unify src = %s"%self
        if (target._type != "*"):
            new._type = target._type

        if (target._domain != "*"):
            new._domain = target._domain

        if (target._name != "*"):
            new._name = target._name

        if (target._role != "*"):
            new._role = target._role

        if (target._tag != "*"):
            new._tag = target._tag

        new.system = target.system
        new.transient = target.transient
        return new

    def copy_with_tag(self, new_tag, system = None, transient = None):
        """
        Return a copy of self, with the tag changed to new_tag.
        """
        Label._check_part('tag', new_tag)
        cp = self.copy()
        cp._tag = new_tag
        cp.system = system
        cp.transient = transient
        return cp

    def copy_with_role(self, new_role):
        """
        Return a copy of self, with the role changed to new_role.
        """
        Label._check_part('role', new_role)
        cp = self.copy()
        cp._role = new_role
        return cp

    def copy_with_domain(self, new_domain):
        """
        Return a copy of self, with the domain changed to new_domain.
        """
        Label._check_domain(new_domain)
        cp = self.copy()
        cp._domain = new_domain
        return cp

    def is_definite(self):
        """
        Return True iff this label contains no wildcards
        """
        if (self._type == "*" or
            self._domain == "*" or
            self._name == "*" or
            self._role == "*" or
            self._tag == "*"):
            return False

        return True

    def is_wildcard(self):
        """
        Return True iff this label contains at least one wildcard.

        This is the dual of is_definite(), but is provided so whichever seems
        more appropriate to the task at hand can be chosen.
        """
        return not self.is_definite()

    def unifies(self, other):
        """
        Returns True if and only if every field in self is either equal to a
        field in other , or if other is a wildcard. Wildcards in self do not match
        anything but a wildcard in other.
        """

        if (self._type != other._type and other._type != "*"):
            return False

        if (self._domain != other._domain and other._domain != "*"):
            return False

        if (self._name != other._name and other._name != "*"):
            return False

        if (self._role != other._role and other._role != "*"):
            return False

        if (self._tag != other._tag and other._tag != "*"):
            return False

        # We match all the way down.
        #print "Unifies(%s,%s)"%(self,other)
        return True


    def match(self, other):
        """
        Return an integer indicating the match specicifity - which we do
        by counting '*' s and subtracting from 0.

        Returns the match specicifity, None if there wasn't one.
        """

        nr_wildcards = 0
        if self._type != other._type:
            if self._type == "*" or other._type == "*":
                nr_wildcards += 1
            else:
                return None

        if self._domain != other._domain:
            if self._domain == "*" or other._domain == "*":
                nr_wildcards += 1
            else:
                return None

        if self._name != other._name:
            if self._name == "*" or other._name == "*":
                nr_wildcards += 1
            else:
                return None

        if self._role != other._role:
            if self._role == "*" or other._role == "*":
                nr_wildcards += 1
            else:
                return None

        if self._tag != other._tag:
            if self._tag == "*" or other._tag == "*":
                nr_wildcards += 1
            else:
                return None

        return -nr_wildcards

    def just_match(self, other):
        """
        Return True if the labels match, False if they do not
        """

        # There are a relatively predictable number of dependencies
        # between labels of the same name, which we assume will normally
        # be due to going from checkout -> package -> deployment,
        # changing tag as we go.
        # On the other hand, there are lots of dependencies between
        # labels with *different* names
        if self._name != other._name:
            if self._name == "*" or other._name == "*":
                pass
            else:
                return False

        # Within a type, dependencies between tags are common.
        # So maybe this goes here.
        if self._tag != other._tag:
            if self._tag == "*" or other._tag == "*":
                pass
            else:
                return False

        # We don't have many different sorts of type, and I think
        # *most* dependencies are going to be between the same type
        # (actually, mostly between packages)
        if self._type != other._type:
            if self._type == "*" or other._type == "*":
                pass
            else:
                return False

        # Traditionally, one has a single role, or not many more, and
        # there aren't many dependencies between them. So do this near
        # the end.
        if self._role != other._role:
            if self._role == "*" or other._role == "*":
                pass
            else:
                return False

        # Check domains last - we relatively rarely expect to have
        # dependencies across domain boundaries. So try this last.
        if self._domain != other._domain:
            if self._domain == "*" or other._domain == "*":
                pass
            else:
                return False

        return True

    def match_without_tag(self, other):
        """
        Returns True if other matches self without the tag, False otherwise

        Specifically, tests whether the two Labels have identical type, domain,
        name and role.
        """
        return (self._type   == other._type and
                self._domain == other._domain and
                self._name == other._name and
                self._role == other._role)

    def copy(self):
        """
        Return a copy of this label.
        """
        return copy.copy(self)

    def __repr__(self):
        parts = [repr(self._type),
                 repr(self._name),
                 'role=%s'%repr(self._role),
                 'tag=%s'%repr(self._tag)]

        if self.transient:
            parts.append('transient=True')
        if self.system:
            parts.append('system=True')
        if self.domain:
            parts.append('domain=%s'%repr(self._domain))
        return 'Label(%s)'%', '.join(parts)

    def __str__(self):
        if self._role:
            basename = "%s{%s}"%(self._name, self._role)
        else:
            basename = self._name

        if self._domain:
            domain = "(%s)"%self._domain
        else:
            domain = ""

        rv =  "%s:%s%s/%s"%(self._type, domain, basename, self._tag)

        extra = []
        if self.transient:
            extra.append(self.FLAG_TRANSIENT)
        if self.system:
            extra.append(self.FLAG_SYSTEM)
        if self._unswept:
            extra.append(self.FLAG_DOMAIN_SWEEP)
        if extra:
            rv += '[%s]'%''.join(extra)

        return rv

    def __cmp__(self, other):
        """
        Compare two Labels.

        Ignores the 'transient' and 'system' values (if any).

        *Does* take the domains (if any) into account.
        """
        this_as_tuple = (self._type, self._domain, self._name, self._role, self._tag)
        that_as_tuple = (other._type, other._domain, other._name, other._role, other._tag)

        if this_as_tuple < that_as_tuple:
            return -1
        elif this_as_tuple > that_as_tuple:
            return 1
        else:
            return 0

    def __hash__(self):
        """
        Calculate the hash for a label.

        Ignores the domain name (since that may be changed) and the
        transient and system flags (since they are defined to be, well,
        transient).
        """
        return hash( (self._type, self._name, self._role, self._tag) )

    def _mark_unswept(self):
        """
        Mark this label as "not swept" for our mark-and-sweep processing.

        Setting the domain name for labels is done using a "mark and sweep"
        approach.

        Do not call this otherwise - it is purely for use by muddle itself in
        this process.

        And it works like:

            >>> l = Label.from_string('a:b{c}/d')
            >>> l._mark_unswept()
            >>> print l
            a:b{c}/d[D]

        """
        self._unswept = True

    def _change_domain(self, domain, verbose=False):
        """Change our domain name (by adding the new 'domain' to it).

        Labels are generally regarded as immutable. This is a Good Thing
        (especially as they are hashable).

        However, in the case of importing sub-builds, it becomes necessary
        to tell a Label (in the dependency tree for said sub-build) that it is
        now in a (new) domain. And this is the call to do that thing.

        Which is why it has a leading underscore in its name - i.e., if you
        call this, you'd better be muddle, or otherwise Very Sure of yourself.

        Used as part of a mark-and-sweep approach, so only amends the label if
        it has not already been amended.

        Note that we do not check that the domain name is valid - this is
        assumed to have been done by the caller before they change the domain
        name of a lot of labels, so we're assuming it's best done once by them.
        So there.

        And it should work like:

            >>> l = Label.from_string('a:b{c}/d')
            >>> print l
            a:b{c}/d
            >>> l._change_domain('e')   # label not marked unswept
            >>> print l
            a:b{c}/d
            >>> l._mark_unswept()
            >>> print l
            a:b{c}/d[D]
            >>> l._change_domain('e')
            >>> print l
            a:(e)b{c}/d
            >>> l._change_domain('f')   # label not marked unswept
            >>> print l
            a:(e)b{c}/d
            >>> l._mark_unswept()
            >>> l._change_domain('f')
            >>> print l
            a:(f(e))b{c}/d

        """
        if self._unswept:
            if verbose: print 'sweep: %s -> '%str(self),
            if self._domain:
                self._domain = '%s(%s)'%(domain, self._domain)
            else:
                self._domain = domain
            self._unswept = False
            if verbose: print str(self)

        elif verbose:
            print 'sweep: %s ignored'%str(self)

    @staticmethod
    def _check_part(what_part, value):
        """
        Check that a label component is valid.

        Raises a utils.GiveUp exception if it's Bad, does nothing if it's OK.
        """
        m = Label.label_part_re.match(value)
        if m is None or m.end() != len(value):
            raise utils.GiveUp("Label %s '%s' is not allowed"%(what_part,value))

    @staticmethod
    def _check_domain(value):
        """
        Check that a label domain component is valid.

        Raises a utils.GiveUp exception if it's Bad, does nothing if it's OK.

        For instance:

            >>> Label._check_domain('fred')
            >>> Label._check_domain('fred(jim)')
            >>> Label._check_domain('fred(jim(bob))')
            >>> Label._check_domain('')
            Traceback (most recent call last):
            ...
            GiveUp: Label domain '()' is not allowed
            >>> Label._check_domain('()')
            Traceback (most recent call last):
            ...
            GiveUp: Label domain '(())' starts with zero length domain, '(()', i.e. '(('
            >>> Label._check_domain('(')
            Traceback (most recent call last):
            ...
            GiveUp: Label domain part '(()' has unbalanced parentheses, '('
            >>> Label._check_domain(')')
            Traceback (most recent call last):
            ...
            GiveUp: Label domain '())' has unbalanced parentheses, ')'
            >>> Label._check_domain('fred(jim')
            Traceback (most recent call last):
            ...
            GiveUp: Label domain part '(fred(jim)' has unbalanced parentheses, 'fred(jim'
            >>> Label._check_domain('fred((jim(bob)))')
            Traceback (most recent call last):
            ...
            GiveUp: Label domain '(fred((jim(bob))))' starts with zero length domain, '((jim(bob))', i.e. '(('

        """
        m = Label.domain_part_re.match(value)
        if m is None or m.end() != len(value):
            raise utils.GiveUp("Label domain '(%s)' is not allowed"%(value))
        dom = value
        while dom:
            pos = dom.find('(')
            if pos == -1:
                if dom[-1] == ')':
                    raise utils.GiveUp("Label domain '(%s)' has unbalanced"
                                        " parentheses, '%s'"%(value, dom))
                break
            else:
                if dom[-1] != ')':
                    raise utils.GiveUp("Label domain part '(%s)' has unbalanced"
                                        " parentheses, '%s'"%(value, dom))
                part = dom[:pos]
                if len(part) == 0:
                    raise utils.GiveUp("Label domain '(%s)' starts with zero"
                                        " length domain, '(%s', i.e. '(('"%(value, dom))
                dom = dom[pos+1:-1]

    @staticmethod
    def from_string(label_string):
        """
        Construct a Label from its string representation.

        The string should be of the correct form:

        * <type>:<name>/<tag>
        * <type>:<name>{<role>}/<tag>
        * <type>:<name>/<tag>[<flags>]
        * <type>:<name>{<role>}/<tag>[<flags>]
        * <type>:(<domain>)<name>/<tag>
        * <type>:(<domain>)<name>{<role>}/<tag>
        * <type>:(<domain>)<name>/<tag>[<flags>]
        * <type>:(<domain>)<name>{<role>}/<tag>[<flags>]

        See the docstring for Label itself for the meaning of the various
        parts of a label.

        <flags> is a set of individual characters indicated as flags. There are two
        flags that will be recognised and used, 'T' for Transience and 'S' for
        System. Any other flag characters will be ignored.

        If the label string is valid, a corresponding Label will be returned,
        otherwise a utils.GiveUp exception will be raised.

            >>> Label.from_string('package:busybox/installed')
            Label('package', 'busybox', role=None, tag='installed')
            >>> Label.from_string('package:busybox{firmware}/installed[ABT]')
            Label('package', 'busybox', role='firmware', tag='installed', transient=True)
            >>> Label.from_string('package:(arm.hello)busybox{firmware}/installed[ABT]')
            Label('package', 'busybox', role='firmware', tag='installed', transient=True, domain='arm.hello')
            >>> Label.from_string('*:(*)*{*}/*')
            Label('*', '*', role='*', tag='*', domain='*')
            >>> Label.from_string('*:*{*}/*')
            Label('*', '*', role='*', tag='*')
            >>> Label.from_string('foo:bar{baz}/wombat[T]')
            Label('foo', 'bar', role='baz', tag='wombat', transient=True)
            >>> Label.from_string('foo:(ick)bar{baz}/wombat[T]')
            Label('foo', 'bar', role='baz', tag='wombat', transient=True, domain='ick')
            >>> Label.from_string('foo:(ick(ack))bar{baz}/wombat[T]')
            Label('foo', 'bar', role='baz', tag='wombat', transient=True, domain='ick(ack)')

        A tag must be supplied:

            >>> Label.from_string('package:busybox')
            Traceback (most recent call last):
            ...
            GiveUp: Label string 'package:busybox' is not a valid Label

        If you specify a domain, it may not be "empty":

            >>> Label.from_string('package:()busybox/*')
            Traceback (most recent call last):
            ...
            GiveUp: Label string 'package:()busybox/*' is not a valid Label

        """
        m = Label.label_string_re.match(label_string)
        if m is None or m.end() != len(label_string):
            raise utils.GiveUp('Label string %s is not a valid'
                                ' Label'%repr(label_string))

        type   = m.group('type')
        domain = m.group('domain') # conveniently, None if not present
        name   = m.group('name')
        role   = m.group('role')   # conveniently, None if not present
        tag    = m.group('tag')
        flags  = m.group('flags')

        transient = False
        system = False

        if flags:
            transient = Label.FLAG_TRANSIENT in flags
            system    = Label.FLAG_SYSTEM in flags

        return Label(type, name, role=role, tag=tag, transient=transient,
                     system=system, domain=domain)
    @staticmethod
    def from_fragment(fragment, default_type, default_role, default_domain):
        """
        Given a string containing a label fragment, return a Label.

        The caller indicates the default type, role and domain.

        The fragment must contain a <name>, but otherwise *may* contain
        any of:

            * <type>: - if this is not given, the default is used
            * (<domain>) - if this is not given, the default is used.
            * {<role>} - if this is not given, the default is used.
            * /<tag> - if this is not given, a tag appropriate to the
              <type> is chosen (checked_out, postinstalled or deployed)

        Any of the default_xx values may be None.
        """
        m = Label.fragment_re.match(fragment)
        if m is None or m.end() != len(fragment):
            raise utils.GiveUp("Label fragment '%s' is not allowed"%fragment)

        type = m.group("type")
        if type is None:
            type = default_type
        elif type == '*':
            raise utils.GiveUp("Label type '*' is not allowed,"
                               " in label fragment '%s'"%fragment)
        name = m.group("name")
        role = m.group("role")
        if role is None:
            role = default_role         # which may be None as well
        tag = m.group("tag")
        if tag is None:
            try:
                tag = utils.package_type_to_tag[type]
            except KeyError:
                raise utils.GiveUp("Cannot guess tag for label fragment '%s'"
                        " (using label type '%s')"%(fragment, type))
        domain = m.group("domain")
        if domain is None:
            domain = default_domain

        return Label(type, name, role, tag, domain=domain)

    def split_domains(self):
        """
        Returns a list of the domains for this Label, in order.

        If there are no subdomains, then a zero length list is returned.

        Raises a utils.GiveUp exception if the parentheses do not match up
        (the check is only fairly crude), or if there are two adjacent opening
        parentheses.
        """
        dom = self._domain
        rv = []
        while dom:
            pos = dom.find('(')
            if pos == -1:
                if dom[-1] == ')':
                    raise utils.GiveUp("Label %s domain part '%s' has unbalanced"
                                        " parentheses"%(self, dom))
                rv.append(dom)
                break
            else:
                if dom[-1] != ')':
                    raise utils.GiveUp("Label %s domain part '%s' has unbalanced"
                                        " parentheses"%(self, dom))
                part = dom[:pos]
                if len(part) == 0:
                    raise utils.GiveUp("Label %s domain part '%s' starts with zero"
                                        " length domain - i.e., '(('"%(self, dom))
                rv.append(part)
                dom = dom[pos+1:-1]
        return rv

def label_from_string(str):
    """Do not use this!!! Can you say "deprecated"?

    This function was originally removed, since it is replaced by
    Label.from_string. However, too many old builds still attempt to
    import it, which can cause problems at the "muddle init" stage, and
    also with "muddle unstamp".

    Please do not use this function in new builds.
    """
    return Label.from_string(str)

class Action:
    """
    Represents an object you can call to "build" a tag.
    """

    def build_label(self, builder, label):
        """
        Build the given label. Your dependencies have been satisfied.

        * in_deps -  Is the set whose dependencies have been satisified.

        Returns True on success, False or throw otherwise.
        """
        pass

    # It may be necessary to declare the following methods, to enable
    # sub-domains to work properly:
    #
    # _mark_unswept()
    # _change_domain(new_domain)
    #
    #    which are used together to change domains within the Action,
    #    that are not contained within Labels.
    #
    # _inner_labels()
    #
    #    which returns a list of those Labels contained "inside" the Action,
    #    which might not otherwise be moved to the new domain.


class SequentialAction:
    """
    Invoke two actions in turn
    """

    def __init__(self, a, b) :
        self.a = a
        self.b = b

    def build_label(self, builder, label):
        self.a.build_label(builder, label)
        self.b.build_label(builder, label)

class Rule:
    """
    A rule or "dependency set".

    Every Rule has:

    * a target Label (its desired result),
    * an optional Action object (to do the work to produce that result),
    * and a set of Labels on which the target depends (which must have been
      satisfied before this Rule can be triggered).

    In other words, once all the dependency Labels are satisfied, the object
    can be called to 'build' the target Label.

        (And if there is no object, the target is automatically satisfied.)

    Note that the "set of Labels" is indeed a set, so adding the same Label
    more than once will not have any effect (caveat: adding a label with
    different flags from a previous label may have an effect, but it's not
    something that should be relied on).

    .. note:: The actual "satisfying" of labels is done in muddled.mechanics.
       For instance, Builder.build_label() "builds" a label in the context
       of the rest of its environment, and uses 'action' to "build" the label.
    """

    def __init__(self, target_dep, action):
        """
        * `target_dep` is the Label this Rule intends to "make".
        * `action` is None or an Action, which will be used to "make" the
          `target_dep`.
        """
        self.deps = set()
        if (not isinstance(target_dep, Label)):
            raise utils.MuddleBug("Attempt to create a rule without a label"
                              " as its target")

        self.target = target_dep
        self.action = action
        if (self.action is not None) and (not isinstance(action, Action)):
            raise utils.MuddleBug("Attempt to create a rule with an object rule "
                              "which isn't an action but a %s."%(action.__class__.__name__))

    def replace_target(self, new_t):
        self.target = new_t

    def unify_dependencies(self, source, target):
        """
        Whenever source appears in our dependencies, replace it with source.unify(target)
        """
        new_deps = set()

        for d in self.deps:
            if (d.unifies(source)):
                copied_d = d.copy_and_unify_with(target)
                new_deps.add(copied_d)
            else:
                new_deps.add(d)

        self.deps = new_deps


    def catenate_and_merge(self, other_rule, complainOnDuplicate = False,
                           replaceOnDuplicate = True):
        """
        Merge ourselves with the given rule.

        If replaceOnDuplicate is true, other_rule get priority - this is the
        target for a unify() and makes the source build instructions go away.
        """
        if (self.action is None):
            self.action = other_rule.action
        elif (other_rule.action is None):
            pass
        else:
            if complainOnDuplicate:
                raise utils.MuddleBug(
                    ("Duplicate action objects for %s and %s - have you "%(self.target, other_rule.target)) +
                    "remembered to remove a package from one of your domain builds?")
            else:
                if replaceOnDuplicate:
                    self.action = other_rule.action
                else:
                    self.action = SequentialAction(self.action, other_rule.action)

        #print "catenate and merge for target = %s"%(self.target)
        self.deps.union(other_rule.deps)

    def add(self,label):
        """
        Add a dependency on the given Label.
        """
        self.deps.add(label)

    def merge(self, deps):
        """
        Merge another Rule with this one.

        Adds all the dependency labels from `deps` to this Rule.

        If `deps.action` is not None, replaces our `action` with the one from `deps`.
        """
        for i in deps.deps:
            self.add(i)

        # This is important to ensure that empty dependencies
        # (which are rules with None as their action object)
        # get correctly overridden by merged rules when they're
        # registered
        if (deps.action is not None):
            self.action = deps.action


    def depend_checkout(self, co_name, tag):
        """
        Add a dependency on label "checkout:<co_name>/<tag>".
        """
        dep = Label(utils.LabelType.Checkout, co_name, None, tag)
        self.add(dep)

    def depend_pkg(self, pkg, role, tag):
        """
        Add a dependency on label "package:<pkg>{<role>}/tag".
        """
        dep = Label(utils.LabelType.Package, pkg, role, tag)
        self.add(dep)

    def depend_deploy(self, dep_name, tag):
        """
        Add a dependency on label "deployment:<dep_name>/tag".
        """
        dep = Label(utils.LabelType.Deployment, dep_name, None, tag)
        self.add(dep)

    def __str__(self):
        return self.to_string()

    def __cmp__(self, other):
        # XXX Is this a sensible algorithm?
        # XXX Certainly starting by sorting the target sounds good
        # XXX (I have some concern over sorting by self.action, which doesn't
        # XXX show up in the string representation of a Rule)
        if self.target < other.target:
            return -1
        elif self.target > other.target:
            return 1
        elif self.deps > other.deps:
            return 1
        elif self.deps < other.deps:
            return -1
        elif self.action > other.action:
            return 1
        elif self.action < other.action:
            return -1
        else:
            return 0

    def __hash__(self):
        # XXX If we have __cmp__, we need __hash__ to be hashable. Does this
        # XXX implementation make sense? Would it be better to hash on our
        # XXX string representation (for instance)?
        return hash(self.target) | hash(self.action)

    def to_string(self, showSystem = True, showUser = True):
        """
        Return a string representing this dependency set.

        If `showSystem` is true, include dependency labels with the System tag
        (i.e., dependencies inserted by the muddle system itself), otherwise
        ignore such.

        If `showUser` is true, include dependency labels without the System tag
        (i.e., "normal" dependencies, explicitly added by the user), otherwise
        ignore such.

        The default is to show all of the dependencies.

        For instance (not a very realistic example):

            >>> tgt = Label.from_string('package:fred{jim}/*')
            >>> r = Rule(tgt,None)
            >>> r.to_string()
            'package:fred{jim}/* <- [ ]'
            >>> r.add(Label.from_string('package:bob{bob}/built'))
            >>> r.depend_checkout('fred','jim')
            >>> r.depend_pkg('albert','jim','built')
            >>> r.depend_deploy('hall','deployed')
            >>> r.to_string()
            'package:fred{jim}/* <- [ checkout:fred/jim, deployment:hall/deployed, package:albert{jim}/built, package:bob{bob}/built ]'

        The "<-" is to be read "depends on".

        Note that the order of the dependencies in the output is sorted by label.
        """
        output = [ str(self.target) ]

        if self.action:
            output.append('<-%s--'%self.action.__class__.__name__)
        else:
            output.append('<-')

        output.append('[')
        if self.deps:
            deps = []
            for label in self.deps:
                if (label.system and showSystem) or ((not label.system) and showUser):
                    deps.append(label)
            deps.sort()
            deps_output = []
            for label in deps:
                deps_output.append(str(label))
            output.append(", ".join(deps_output))
        output.append(']')
        return " ".join(output)


class RuleSet:
    """
    A collection of rules that encapsulate how you can get from A to B.

    Formally, this is just a mapping of labels to Rules. Duplicate
    targets are merged - it's assumed that the objects will be
    the same.

    CAVEAT: Be aware that new rules (when added) can be merged into existing
    rules.  Since we don't *copy* rules when we add them, this could be a cause
    of unexpected side effects...
    """

    def __init__(self):
        self.map = { }

    def add(self, rule):
        """
        Add the Rule 'rule'.

        Specifically, if we already have a rule for this rule's target label,
        merge the new rule into the old (see Rule.merge).

        If this rule is for a new target, just remember it.
        """
        # Do we have the same target?
        inst = self.map.get(rule.target, None)
        if (inst is None):
            self.map[rule.target] = rule
        else:
            inst.merge(rule)


    def rules_for_target(self, label, useTags = True, useMatch = True):
        """
        Return the set of rules for any target(s) matching the given label.

        * If useTags is true, then we should take account of tags when
          matching, otherwise we should ignore them. If useMatch is true,
          then useTags is ignored.
        * If useMatch is true, then we allow wildcards in 'label', otherwise
          we do not.

        Returns the set of Rules found, or an empty set if none were found.
        """
        rules = set()
        if (useMatch):
            for (k,v) in self.map.items():
                #if (label.match(k) is not None):
                if label.just_match(k):
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

    def wrap_actions(self, generator, label):
        for r in self.map.values():
            if (r.target.match(label)):
                r.action = generator.generate(r.action)

    def targets_match(self, target, useMatch = True):
        """
        Return the set of targets matching the given 'target' label.

        If useMatch is true, allow wildcards in 'target' (in which case
        more than one result may be obtained). If useMatch is false,
        then at most one match can be found ('target' itself).

        Returns a set of suitable targets, or an empty set if there are none.
        """
        result_set = set()

        if (useMatch):
            for k in self.map.keys():
                if (k.match(target) is not None):
                    result_set.add(k)
        elif target in self.map.keys():
            result_set.add(target)

        return result_set

    def rule_for_target(self, target, createIfNotPresent = False):
        """
        Return the rule for this target - this contains all the labels that
        need to be asserted in order to build the target.

        If createIfNotPresent is true, and there is no rule for this target,
        then we will create (and add to our internal map) an empty Rule for
        this target.

        Otherwise, if there is no rule for this target, we return None
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

        * If useTags is true, then we should take account of tags when
          matching, otherwise we should ignore them. If useMatch is true,
          then useTags is ignored.
        * If useMatch is true, then we allow wildcards in 'label', otherwise
          we do not.
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
        """
        Merge another RuleSet into this one.

        Simply adds each rule from the other RuleSet to this one (see the
        'RuleSet.add' method)
        """
        for i in other_deps.map.values():
            self.add(i)

    def unify(self, source, target):
        """
        Merge source into target.

        This is a pain, and depends heavily on CatenatedObject
        """

        new_map = { }


        # First, collect anything that might be rewritten.
        for (k,v) in self.map.items():
            new_k = None
            new_v = v

            if (k.unifies(source)):
                copied_source = k.copy_and_unify_with(target)
                new_v.replace_target(copied_source)
                new_k = copied_source
                if False:
                    print "Ruleset: rewrite src = %s\n" \
                          "                   k = %s\n" \
                          "                    to %s"%(source,k,copied_source)
            else:
                new_k = k

            if (new_k in new_map):
                old_v = new_map[new_k]
                old_v.catenate_and_merge(new_v)
            else:
                new_map[new_k] = new_v

        # Now, rename everything in the dependencies and copy
        # back ..
        for (k,v) in new_map.items():
            v.unify_dependencies(source, target)

        # .. and new_map is the new map.
        self.map = new_map


    def to_string(self, matchLabel = None,
                  showUser = True, showSystem = True, ignore_empty=False):
        """
        Return a string representing this rule set.

        If `showSystem` is true, include dependency labels with the System tag
        (i.e., dependencies inserted by the muddle system itself), otherwise
        ignore such.

        If `showUser` is true, include dependency labels without the System tag
        (i.e., "normal" dependencies, explicitly added by the user), otherwise
        ignore such.

        The default is to show all of the dependencies.

        For instance (not a very realistic example):

            >>> l = Label.from_string('package:fred{bob}/initial')
            >>> r = RuleSet()
            >>> depend_chain(None, l, ['built', 'bamboozled'], r)
            >>> print str(r)
            -----
            package:fred{bob}/bamboozled <- [ package:fred{bob}/built ]
            package:fred{bob}/built <- [ package:fred{bob}/initial ]
            package:fred{bob}/initial <- [ ]
            -----
            <BLANKLINE>

        The "<-" is to be read "depends on".

        Note that the order of the rules in the output is sorted by target
        label, and is thus reproducible.
        """
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
                    str_list.append('\n')
        str_list.append("-----\n")
        return "".join(str_list)


    def __str__(self):
        return self.to_string()

def depend_chain(action, label, tags, ruleset):
    """
    Add a chain of dependencies to the given ruleset.

    This is perhaps best explained with an example:

        >>> l = Label.from_string('package:fred{bob}/initial')
        >>> r = RuleSet()
        >>> depend_chain(None, l, ['built', 'bamboozled'], r)
        >>> print str(r)
        -----
        package:fred{bob}/bamboozled <- [ package:fred{bob}/built ]
        package:fred{bob}/built <- [ package:fred{bob}/initial ]
        package:fred{bob}/initial <- [ ]
        -----
        <BLANKLINE>

    """

    last = label.copy()

    # The base ..
    r = Rule(last, action)
    ruleset.add(r)

    for tag in tags:
        next = last.copy_with_tag(tag)
        r = Rule(next, action)
        r.add(last)
        ruleset.add(r)
        last = next



def depend_none(action, label):
    """
    Quick rule that makes label depend on nothing.
    """
    return Rule(label, action)

def depend_one(action, label, dep_label):
    """
    Quick rule that makes label depend only on dep_label.
    """
    rv = Rule(label, action)
    rv.add(dep_label)
    return rv


def depend_self(action, label, old_tag):
    """
    Make a quick dependency set that depends just on you. Used by some of the
    standard package and checkout classes to quickly build standard dependency
    sets.
    """
    rv = Rule(label, action)
    dep_label = label.copy_with_tag(old_tag)

    rv.add(dep_label)
    return rv


def depend_empty(action, label):
    """
    Create a dependency set with no prerequisites - simply signals that a
    tag is available to be built at any time.
    """
    rv = Rule(label, action)
    return rv


def label_set_to_string(label_set, start_with="[", end_with="]", join_with=", " ):
    """
    Utility function to convert a label set to a string.
    """
    str_list = []
    for  i in label_set:
        str_list.append(i.__str__())
    return "%s%s%s"%(start_with, join_with.join(str_list), end_with)

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


def label_list_to_string(labels, join_with=' '):
    return join_with.join(map(str, labels))

def retag_label_list(labels, new_tag):
    """
    Does what it says on the tin, returning the new label list.

    That is, returns a list formed by copying each Label in 'labels' and
    setting its tag to the given 'new_tag'.
    """
    result = [ ]
    for l in labels:
        next_l = l.copy_with_tag(new_tag)
        result.append(next_l)

    return result

def needed_to_build(ruleset, target, useTags = True, useMatch = False):
    """
    Given a rule set and a target, return a complete list of the rules needed
    to build the target.

        * If useTags is true, then we should take account of tags when
          looking for the rules for this 'target', otherwise we should ignore
          them.

        * If useMatch is true, then we allow wildcards in 'target', otherwise
          we do not.

    Returns a list of rules.
    """

    # rule_list stores the list of rules we're about to return.
    rule_list = [ ]
    # rule_target_set stores the set of targets resulting from rule_list
    # (i.e. if you'd obeyed rule_list, you'd have asserted all these labels)
    rule_target_set = set()

    # The set of labels we'd like to see asserted.
    targets = set()
    targets.update(ruleset.targets_match(target, useMatch=useMatch))

    done_something = True
    trace = False

    while done_something:
        done_something = False

        if trace:
            print "\n> Loop"

        # Remove anything we've already satisfied from our list of targets.
        targets = targets - rule_target_set

        # Have we succeeded?
        if len(targets) == 0:
            # Yep!
            if trace:
                print
                print "To build %s we need:"%target
                for r in rule_list:
                    print '    %s'%r
                print
            return rule_list

        # In that case, we need to go through all the dependencies of the
        # targets, adding each either to the target list or the rule_list.
        new_targets = set()

        for tgt in targets:
            if trace:
                print "\nLooking at target %s"%tgt
            rules = ruleset.rules_for_target(tgt, useTags)
            if rules is None:
                raise utils.MuddleBug("No rule found for target %s"%tgt)

            # This is slightly icky. Technically, in the presence of wildcard
            # rules, there can be several rules which build a target.
            #
            # Since we use wildcard rules to add extra rules to targets,
            # we need to satisfy every rule that builds this target.

            # Every dependency has either already been satisfied or
            # needs to be.
            can_build_target = True

            if len(rules) == 0:
                raise utils.MuddleBug("Rule list is empty for target %s"%tgt)

            if trace:
                print "Rules for %s:"%tgt
                for r in rules:
                    print '    %s'%r

            rule = None
            for rule in rules:
                if trace:
                    print "Looking at rule %s"%rule
                for dep in rule.deps:
                    if dep not in rule_target_set:
                        if trace:
                            print "  Cannot build %s because it needs %s"%(tgt, dep)
                            # .. and we can't build this target until we have.

                        # We need to satisfy this dependency, so add it
                        # to targets. The test here is purely so we can
                        # detect circular dependencies.
                        if dep not in new_targets and dep not in targets:
                            if trace:
                                print "  Add new target %s"%str(dep)
                            new_targets.add(dep)
                            done_something = True
                        elif trace:
                            if dep in targets: print "  ..already in targets"
                            if dep in new_targets: print "  ..already in new_targets"

                        can_build_target = False

            if can_build_target:
                # All dependencies are already satisfied, so we can ..
                if trace:
                    print "Add build rule: target %s"%tgt
                    for rule in rules:
                        print "                rule %s"%rule
                for rule in rules:
                    rule_list.append(rule)
                rule_target_set.add(tgt)
                done_something = True
            else:
                # Can't satisfy our dependencies. Still a target.
                new_targets.add(tgt)

        targets = new_targets

    # If we get here, we can never satisfy the remaining set of
    # targets because the graph is circular or incomplete.
    targets = list(targets)
    targets.sort()
    raise utils.GiveUp("Dependency graph is circular or incomplete. \n" +
                      "building = %s\n"%target +
                      "targets = %s \n"%label_set_to_string(targets,
                                                            start_with='[\n    ',
                                                            end_with='\n]',
                                                            join_with='\n    '))


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
        # If this was a wildcarded label, who cares?
        if (label.is_definite()):
            raise utils.GiveUp("No rules match label %s ."%label)

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




