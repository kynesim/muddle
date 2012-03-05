"""
Matters relating to attributing licenses to checkouts
"""

import os
import fnmatch

from muddled.depend import Label, required_by, label_list_to_string
from muddled.utils import GiveUp, LabelType, wrap

DEBUG=False

ALL_LICENSE_CATEGORIES = ('gpl', 'open', 'binary', 'private')

class License(object):
    """The representation of a source license.

    License instances should be:

        1. Singular
        2. Immutable

    but I don't particularly propose to work hard to enforce those...

    Use the subclasses to create your actual License instance, so that you
    can use any appropriate extra methods...
    """

    def __init__(self, name, category):
        """Initialise a new License.

        The 'name' is the name of this license, as it is normally recognised.

        'category' is meant to be a broad categorisation of the type of the
        license. Currently that is one of:

            * 'gpl' - some sort of GPL license, which propagate the need to
              distribute source code to other "adjacent" entities
            * 'open' - an open source license, anything that is not 'gpl'.
              Source code may, but need not be, distributed.
            * 'binary' - a binary license, indicating that the source code is
              not to be distributed, but binary (the contents of the "install"
              directory) may be.
            * 'private' - a marker that the checkout should not be distributed
              at all.
        """
        self.name = name
        if category not in ALL_LICENSE_CATEGORIES:
            raise GiveUp("Attempt to create License '%s' with unrecognised"
                         " category '%s'"%(name, category))
        self.category = category

    def __str__(self):
        return self.name

    def __repr__(self):
        return '%s(%r, %r)'%(self.__class__.__name__, self.name, self.category)

    def __eq__(self, other):
        return (self.name == other.name and self.category == other.category)

    def __hash__(self):
        return hash((self.name, self.category))

    def distribute_source(self):
        """Returns True if we should (must?) distribute source code.

        XXX Should this only be True for 'gpl'???
        """
        return self.category in ('open', 'gpl')

    def is_open(self):
        """Returns True if this is some sort of open-source license.

        Note: this includes GPL and LGPL licenses.
        """
        return self.category in ('open', 'gpl')

    def is_open_not_gpl(self):
        """Returns True if this license is 'open' but not 'gpl'.
        """
        return self.category == 'open'

    def is_gpl(self):
        """Returns True if this is some sort of GPL license.
        """
        return self.category == 'gpl'

    def is_lgpl(self):
        """Returns True if this is some sort of LGPL license.

        This *only* works for the LicenseLGpl class (and any subclasses of it,
        of course).
        """
        return False

    def is_binary(self):
        """Is this a binary-distribution-only license?
        """
        return self.category == 'binary'

    def is_private(self):
        """Is this a private-do-not-distribute license?
        """
        return self.category == 'private'

    def propagates(self):
        """Does this license "propagate" to other checkouts?

        In other words, if checkout A has this license, and checkout B depends
        on checkout A, does the license have an effect on what you can do with
        checkout B?

        For non-GPL licenses, the answer is assumed "no", and we thus return
        False.

        For GPL licenses with a linking exception (e.g., the GCC runtime
        library, or some Java libraries with CLASSPATH exceptions), the answer
        is also "no", and we return False.

        However, for most GPL licenses (and this includes LGPL), the answer
        if "yes", there is some form of propagation (remember, LGPL allows
        dynamic linking, and use of header files, but not static linking),
        and we return True.

        If we return True, it is then up to the user to decide if this means
        anything in this particular case - muddle doesn't know *why* one
        checkout depends on another.
        """
        return False

class LicensePrivate(License):
    """A "private" license - we do not want to distribute anything
    """

    def __init__(self, name):
        super(LicensePrivate, self).__init__(name=name, category='private')

    def __repr__(self):
        return '%s(%r)'%(self.__class__.__name__, self.name)

class LicenseBinary(License):
    """A binary license - we distribute binary only, not source code
    """

    def __init__(self, name):
        super(LicenseBinary, self).__init__(name=name, category='binary')

    def __repr__(self):
        return '%s(%r)'%(self.__class__.__name__, self.name)

class LicenseOpen(License):
    """Some non-GPL open source license.
    """

    def __init__(self, name):
        super(LicenseOpen, self).__init__(name=name, category='open')

    def __repr__(self):
        return '%s(%r)'%(self.__class__.__name__, self.name)

class LicenseGPL(License):
    """Some sort of GPL license.

    (Why LicenseGPL rather than GPLLicense? Because I find the later more
    confusing with the adjacent 'L's, and I want to keep GPL uppercase...)
    """

    def __init__(self, name, with_exception=False):
        """Initialise a new GPL License.

        The 'name' is the name of this license, as it is normally recognised.

        Some GNU libraries provide a `linking exception`_, which allows
        software to "link" (depending on the exception) to the library, without
        needing to be GPL-compatible themselves. One example of this (more or
        less) is the LGPL, for which we have a separate class. Another example
        is the GCC Runtime Library.

        .. _`linking exception`: http://en.wikipedia.org/wiki/GPL_linking_exception
        """
        super(LicenseGPL, self).__init__(name=name, category='gpl')
        self.with_exception = with_exception

    def __repr__(self):
        if self.with_exception:
            return '%s(%r, with_exception=True)'%(self.__class__.__name__, self.name)
        else:
            return '%s(%r)'%(self.__class__.__name__, self.name)

    def __eq__(self, other):
        # Doing the super-comparison first guarantees we're both some sort of GPL
        return (super(LicenseGPL, self).__eq__(other) and
                self.with_exception == other.with_exception)

    def __hash__(self):
        return hash((self.name, self.category, self.with_exception))

    def is_gpl(self):
        """Returns True if this is some sort of GPL license.
        """
        return True

    def propagates(self):
        return not self.with_exception

    # I don't want to type all that documentation again...
    propagates.__doc__ = License.propagates.__doc__

class LicenseLGPL(LicenseGPL):
    """Some sort of Lesser GPL (LGPL) license.

    The lesser GPL implies that it is OK to link to this checkout as a shared
    library, or to include its header files, but not link statically. We don't
    treat that as a "with_exception" case specifically, since it is up to the
    user to decide if an individual checkout that depends on a checkout with
    this license is affected by our GPL-ness.
    """

    def __init__(self, name, with_exception=False):
        """Initialise a new LGPL License.

        The 'name' is the name of this license, as it is normally recognised.
        """
        super(LicenseLGPL, self).__init__(name=name, with_exception=with_exception)

    def is_lgpl(self):
        """Returns True if this is some sort of LGPL license.
        """
        return True

# Let's define some standard licenses:
standard_licenses = {}
for mnemonic, license in (
        ('apache',  LicenseOpen('Apache')),
        ('apache2', LicenseOpen('Apache 2.0')),
        ('bsd-new',     LicenseOpen('BSD 3-clause')),
        ('bsd-original', LicenseOpen('BSD 4-clause')), # "with advertising"
        ('bsd-simplified',     LicenseOpen('BSD 2-clause')), # as used by FreeBSD
        ('common',          LicenseOpen('Common Public License')), # Some JAVA stuff
        ('eclipse',         LicenseOpen('Eclipse Public License 1.0')),
        ('gpl2',            LicenseGPL('GPL v2')),
        ('gpl2-except',     LicenseGPL('GPL v2', with_exception=True)),
        ('gpl2plus',        LicenseGPL('GPL v2 and above')),
        ('gpl2plus-except', LicenseGPL('GPL v2 and above', with_exception=True)),
        ('gpl3',            LicenseGPL('GPL v3')), # Implicit "and above"?
        ('gpl3-except',     LicenseGPL('GPL v3', with_exception=True)),
        ('lgpl',            LicenseLGPL('LGPL')),
        ('lgpl-except',     LicenseLGPL('LGPL', with_exception=True)),
        ('mpl',             LicenseOpen('MPL 1.1')),
        ('mpl1_1',          LicenseOpen('MPL 1.1')),
        ('ukogl',           LicenseOpen('UK Open Government License')),
        ('zlib',            LicenseOpen('zlib')), # ZLIB has its own license
        ('code-nightmare-green', LicensePrivate('Code Nightmare Green')),
        ):
    standard_licenses[mnemonic] = license

def print_standard_licenses():
    keys = standard_licenses.keys()
    maxlen = len(max(keys, key=len))

    gpl_keys = []
    open_keys = []
    binary_keys = []
    private_keys = []
    other_keys = []

    for key in keys:
        license = standard_licenses[key]
        if license.is_gpl():
            gpl_keys.append((key, license))
        elif license.is_open():
            open_keys.append((key, license))
        elif license.is_binary():
            binary_keys.append((key, license))
        elif license.is_private():
            private_keys.append((key, license))
        else:
            other_keys.append((key, license))

    print 'Standard licenses are:'

    for thing in (gpl_keys, open_keys, binary_keys, private_keys, other_keys):
        if thing:
            print
            for key, license in sorted(thing):
                print '%-*s %r'%(maxlen, key, license)
    print

def set_license(builder, co_label, license):
    """Set the license for a checkout.

    'license' must either be a License instance, or the mnemonic for one
    of the standard licenses.
    """
    if isinstance(license, License):
        builder.invocation.db.set_checkout_license(co_label, license)
    else:
        builder.invocation.db.set_checkout_license(co_label,
                                                   standard_licenses[license])

def set_license_for_names(builder, co_names, license):
    """A convenience function to set one license for several checkout names.

    Since this uses checkout names rather than labels, it is not domain aware.

    It calls 'set_license()' for each checkout name, passing it a checkout
    label constructed from the checkout name, with no domain.
    """
    # Try to stop the obvious mistake...
    if isinstance(co_names, basestring):
        raise GiveUp('Second argument to set_license_for_names() must be a sequence, not a string')

    for name in co_names:
        co_label = Label(LabelType.Checkout, name)
        set_license(builder, co_label, license)

def get_license(builder, co_label, absent_is_None=True):
    """Get the license for a checkout.

    If 'absent_is_None' is true, then if 'co_label' does not have an entry in
    the licenses dictionary, None will be returned. Otherwise, an appropriate
    GiveUp exception will be raised.

    This is a simple wrapper around builder.invocation.db.get_checkout_license.
    """
    return builder.invocation.db.get_checkout_license(co_label, absent_is_None)

def set_not_built_against(builder, pkg_label, co_label):
    """Asserts that this package is not "built against" that checkout.

    We assume that:

    1. 'pkg_label' is a package that depends (perhaps indirectly) on 'co_label'
    2. 'co_label' is a checkout with a "propagating" license (i.e., some for of
       GPL license).
    3. Thus by default the "GPL"ness would propagate from 'co_label' to this
       package, and thus to the checkouts we are (directly) built from.

    However, this function asserts that, in fact, our checkout is (or our
    checkouts are) not built in such a way as to cause the license for
    'co_label' to propagate.

    Or, putting it another way, for a normal GPL license, we're not linking
    with anything from 'co_label', or using its header files, or copying GPL'ed
    files from it, and so on.

    If 'co_label' is under LGPL, then that would reduce to saying we're not
    static linking against 'co_label' (or anything else not allowed by the
    LGPL).

    Note that we may be called before 'co_label' has registered its license, so
    we cannot actually check that 'co_label' has a propagating license (or,
    indeed, that it exists or is depended upon by 'pkg_label').

    This is a simple wrapper around builder.invocation.db.set_not_built_against.
    """
    builder.invocation.db.set_not_built_against(pkg_label, co_label)

def _normalise_checkout_label(co_label):
    """Normalise a checkout label.

    Only takes a copy if it needs to.
    """
    if co_label.tag == '*' and co_label.role is None and \
       not co_label.system and not co_label.transient:
       return co_label
    else:
       return Label(LabelType.Checkout, co_label.name,
                    role=None, tag='*', domain=co_label.domain)

def get_not_licensed_checkouts(builder):
    """Return the set of all checkouts which do not have a license.

    (Actually, a set of checkout labels, with the label tag "/checked_out").
    """
    all_checkouts = builder.invocation.all_checkout_labels()
    result = set()
    checkout_has_license = builder.invocation.db.checkout_has_license
    for co_label in all_checkouts:
        if not checkout_has_license(co_label):
            result.add(_normalise_checkout_label(co_label))
    return result

def get_gpl_checkouts(builder):
    """Return a set of all the GPL licensed checkouts.

    That's checkouts with any sort of GPL license.
    """
    all_checkouts = builder.invocation.all_checkout_labels()
    get_checkout_license = builder.invocation.db.get_checkout_license
    gpl_licensed = set()
    for co_label in all_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license and license.is_gpl():
            gpl_licensed.add(co_label)
    return gpl_licensed

def get_open_checkouts(builder):
    """Return a set of all the open licensed checkouts.

    That's checkouts with any sort of GPL or open license.
    """
    all_checkouts = builder.invocation.all_checkout_labels()
    get_checkout_license = builder.invocation.db.get_checkout_license
    gpl_licensed = set()
    for co_label in all_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license and license.is_open():
            gpl_licensed.add(co_label)
    return gpl_licensed

def get_open_not_gpl_checkouts(builder):
    """Return a set of all the open licensed checkouts that are not GPL.

    Note sure why anyone would want this, but it's easy to provide.
    """
    all_checkouts = builder.invocation.all_checkout_labels()
    get_checkout_license = builder.invocation.db.get_checkout_license
    gpl_licensed = set()
    for co_label in all_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license and license.category == 'open':
            gpl_licensed.add(co_label)
    return gpl_licensed

def get_implicit_gpl_checkouts(builder):
    """Find all the checkouts to which GPL-ness propagates.

    Returns a tuple, (result, because), where:

    * 'result' is a set of the checkout labels that are implicitly made "GPL"
      by propagation, and
    * 'because' is a dictionary linking each such label to a set of strings
       explaining the reason for the labels inclusion
    """

    # There are clearly two ways we can do this:
    #
    # 1. For each checkout, follow its dependencies until we find something
    #    that is non-system GPL, or we don't (obviously, finding one such
    #    is enough).
    #
    # 2. For each non-system GPL checkout, find everything that depends upon
    #    it and mark it as propagated-to
    #
    # In either case, it is definitely worth checking to see if there are
    # *any* non-system GPL checkouts.
    #
    # If we do (1) then we may need to traverse the entire dependency tree
    # for each and every checkout in it (e.g., if there are no non-system
    # GPL licensed checkouts).
    #
    # If we do (2), then we do nothing if there are no non-system GPL
    # checkouts. For each that there is, we do need to traverse the entire
    # dependency tree, but we can hope that this is for significantly fewer
    # cases than in (1).
    #
    # Also, it is possible that we may have "blockers" inserted into the tree,
    # which truncate such a traversal (I'm not 100% sure about this yet).
    #
    # Regardless, approach (2) seems the more sensible.

    all_gpl_checkouts = get_gpl_checkouts(builder)

    # Localise for our loop
    get_checkout_license = builder.invocation.db.get_checkout_license
    get_not_built_against = builder.invocation.db.get_not_built_against
    ruleset = builder.invocation.ruleset

    DEBUG = False

    def add_if_not_us(our_co, this_co, result, because, reason):
        """Add 'this_co' to 'result' if it is not 'our_co'.

        In which case, also add 'this_co':'reason' to 'because'

        Relies on 'our_co' having a wildcarded label tag.
        """
        if our_co.just_match(this_co):
            # OK, that's just some variant on ourselves
            if DEBUG: print 'WHICH is our_co'%this_co
        else:
            lbl = this_co.copy_with_tag('*')
            result.add(lbl)
            if lbl in because:
                because[lbl].add(reason)
            else:
                because[lbl] = set([reason])
            if DEBUG: print 'ADD %s'%lbl

    result = set()              # Checkouts implicitly affected
    because = {}                # checkout -> what it depended on that did so
    if DEBUG:
        print
        print 'Finding implicit GPL checkouts'
    for co_label in all_gpl_checkouts:
        if DEBUG: print '.. %s'%co_label
        license = get_checkout_license(co_label)
        if not license.propagates():
            if DEBUG: print '     has a link-exception of some sort - ignoring it'
            continue
        depend_on_this = required_by(ruleset, co_label)
        for this_label in depend_on_this:
            # We should have a bunch of package labels (possibly the same
            # package present with different tags), plus quite likely some
            # variants on our own checkout label, and sometimes other stuff
            if DEBUG: print '     %s'%this_label,
            if this_label.type == LabelType.Package:

                not_against = get_not_built_against(this_label)
                if co_label in not_against:
                    if DEBUG: print 'NOT against %s'%co_label
                    continue

                # OK, what checkouts does that imply?
                pkg_checkouts = builder.invocation.checkouts_for_package(this_label)
                if DEBUG: print 'EXPANDS to %s'%(label_list_to_string(pkg_checkouts))

                for this_co in pkg_checkouts:
                    if DEBUG: print '         %s'%this_label,
                    # We know that our original 'co_label' has type '/*`
                    add_if_not_us(co_label, this_co, result, because,
                                  '%s depends on %s'%(this_label.copy_with_tag('*'), co_label))
            elif this_label.type == LabelType.Checkout:
                # We know that our original 'co_label' has type '/*`
                add_if_not_us(co_label, this_label, result, because,
                              '%s depends on %s'%(this_label.copy_with_tag('*'), co_label))
            else:
                # Deployments don't build stuff, so we can ignore them
                if DEBUG: print 'IGNORE'
                continue
    return result, because

def get_binary_checkouts(builder):
    """Return a set of all the "binary" licensed checkouts.
    """
    all_checkouts = builder.invocation.all_checkout_labels()
    get_checkout_license = builder.invocation.db.get_checkout_license
    binary_licensed = set()
    for co_label in all_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license and license.is_binary():
            binary_licensed.add(co_label)
    return binary_licensed

def get_private_checkouts(builder):
    """Return a set of all the "private" licensed checkouts.
    """
    all_checkouts = builder.invocation.all_checkout_labels()
    get_checkout_license = builder.invocation.db.get_checkout_license
    private_licensed = set()
    for co_label in all_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license and license.is_private():
            private_licensed.add(co_label)
    return private_licensed

def checkout_license_allowed(builder, co_label, categories):
    """Does this checkout have a license in the given categories?

    Returns True if the checkout has a license that is in any of the
    given categories, or if it does not have a license.

    Returns False if it is licensed, but its license is not in any of
    the given categories.
    """
    license = builder.invocation.db.get_checkout_license(co_label, absent_is_None=True)
    if license is None or license.category in categories:
        return True
    else:
        return False

def get_license_clashes(builder, implicit_gpl_checkouts):
    """Return clashes between actual license and "implicit GPL" licensing.

    ``get_implicit_gpl_checkouts()`` returns those checkouts that are
    implicitly "made" GPL by propagation. However, if the checkouts concerned
    were already licensed with either "binary" or "private" licenses, then it
    is likely that the caller would like to know about it, as it is probably
    a mistake (or at best an infelicity).

    This function returns two sets, (bad_binary, bad_private), of checkouts
    named in ``implicit_gpl_checkouts`` that have an explicit "binary" or
    "private" license.
    """
    bad_binary = set()
    bad_private = set()

    get_checkout_license = builder.invocation.db.get_checkout_license
    for co_label in implicit_gpl_checkouts:
        license = get_checkout_license(co_label, absent_is_None=True)
        if license is None:
            continue
        elif license.is_binary():
            bad_binary.add(co_label)
        elif license.is_private():
            bad_private.add(co_label)

    return bad_binary, bad_private

def report_license_clashes(builder, report_binary=True, report_private=True):
    """Report any license clashes.

    This wraps get_implicit_gpl_checkouts() and check_for_license_clashes(),
    plus some appropriate text reporting any problems.

    It returns True if there were any clashes, False if there were not.

    It reports clashes with "binary" licenses if 'report_binary' is True.

    It reports clashes with "private" licenses if 'report_private' is True.

    If both are False, it is silent.
    """
    implicit_gpl, because = get_implicit_gpl_checkouts(builder)

    if not implicit_gpl:
        return False

    bad_binary, bad_private = get_license_clashes(builder, implicit_gpl)

    if not bad_binary and not bad_private:
        return False

    def report(co_label):
        license = get_checkout_license(co_label)
        reasons = because[co_label]
        header = '* %-*s is %r, but is implicitly GPL because:'%(maxlen, co_label, license)
        print wrap(header, subsequent_indent='  ')
        print
        for reason in sorted(reasons):
            print '  - %s'%reason
        print

    if report_binary or report_private:
        print
        print 'The following GPL license clashes occur:'
        print

        maxlen = 0
        if report_binary:
            for label in bad_binary:
                length = len(str(label))
                if length > maxlen:
                    maxlen = length
        if report_private:
            for label in bad_private:
                length = len(str(label))
                if length > maxlen:
                    maxlen = length

        get_checkout_license = builder.invocation.db.get_checkout_license

        if report_binary:
            for co_label in sorted(bad_binary):
                report(co_label)

        if report_private:
            for co_label in sorted(bad_private):
                report(co_label)

    return True

def licenses_in_role(builder, role):
    """Given a role, what licenses are used by the packages (checkouts) therein?

    Returns a set of License instances. May also include None in the values in
    the set, if some of the checkouts are not licensed.
    """
    licenses = set()
    get_checkout_license = builder.invocation.db.get_checkout_license

    lbl = Label(LabelType.Package, "*", role, "*", domain="*")
    all_rules = builder.invocation.ruleset.rules_for_target(lbl)

    for rule in all_rules:
        pkg_label = rule.target
        checkouts = builder.invocation.checkouts_for_package(pkg_label)
        for co_label in checkouts:
            license = get_checkout_license(co_label, absent_is_None=True)
            licenses.add(license)

    return licenses

def get_license_clashes_in_role(builder, role):
    """Find license clashes in the install/ directory of 'role'.

    Returns two dictionaries (binary_items, private_items)

    'binary_items' is a dictionary of {checkout_label : binary_license}

    'private_items' is a dictionary of {checkout_label : private_license}

    If private_items has content, then there is a licensing clash in the given
    role, as one cannot do a binary distribution of both "binary" and "private"
    licensed content in the same "install" directory.
    """
    binary_items = {}
    private_items = {}

    get_checkout_license = builder.invocation.db.get_checkout_license

    lbl = Label(LabelType.Package, "*", role, "*", domain="*")
    all_rules = builder.invocation.ruleset.rules_for_target(lbl)

    for rule in all_rules:
        pkg_label = rule.target
        checkouts = builder.invocation.checkouts_for_package(pkg_label)
        for co_label in checkouts:
            license = get_checkout_license(co_label, absent_is_None=True)
            if license:
                if license.is_binary():
                    binary_items[_normalise_checkout_label(co_label)] = license
                elif license.is_private():
                    private_items[_normalise_checkout_label(co_label)] = license

    return binary_items, private_items

def report_license_clashes_in_role(builder, role, just_report_private=True):
    """Report license clashes in the install/ directory of 'role'.

    Basically, this function allows us to be unhappy if there are a mixture of
    "binary" and "private" things being put into the same "install/" directory.

    If 'just_report_private' is true, then we will only talk about the
    private entities, otherwise we'll report the "binary" licensed packages
    that end up there as well.

    If there was a clash reported, we return True, and otherwise we return
    False.
    """
    binary_items, private_items = get_license_clashes_in_role(builder, role)

    if not (binary_items and private_items):
        return False

    binary_keys = binary_items.keys()
    private_keys = private_items.keys()

    maxlen = 0
    for label in private_keys:
        length = len(str(label))
        if length > maxlen:
            maxlen = length

    if just_report_private:
        print 'There are both binary and private licenses in role %s:'%(role)
        for key in sorted(private_keys):
            print '* %-*s is %r'%(maxlen, key, private_items[key])
    else:
        for label in binary_keys:
            length = len(str(label))
            if length > maxlen:
                maxlen = length
        print 'There are both binary and private licenses in role %s:'%(role)
        for key in sorted(binary_keys):
            print '* %-*s is %r'%(maxlen, key, binary_items[key])
        for key in sorted(private_keys):
            print '* %-*s is %r'%(maxlen, key, private_items[key])

    return True
