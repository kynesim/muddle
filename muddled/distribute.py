"""
Actions and mechanisms relating to distributing build trees
"""

# XXX TODO
# Doing::
#
#   distribute_checkout_files(builder, '*', label, source_files)
#
# should arguable add those files to *all* distributions. This would make
# it easier to say "actually you always need 'src/Makefile' to be able to
# build this checkout".

# XXX TODO
# Question - what are we meant to do if a package implicitly sets
# a distribution state for a checkout, and we also explicitly set
# a different (incompatible) state for a checkout? Who wins? Or do
# we just try to satisfy both?

import os

from muddled.depend import Action, Rule, Label, required_by, label_list_to_string
from muddled.utils import GiveUp, MuddleBug, LabelTag, LabelType, \
        copy_without, normalise_dir, find_local_relative_root, package_tags, \
        copy_file, domain_subpath
from muddled.version_control import get_vcs_handler, vcs_special_files
from muddled.mechanics import build_co_and_path_from_str
from muddled.pkgs.make import MakeBuilder, deduce_makefile_name

DEBUG=False

# =============================================================================
# LICENSES
# =============================================================================

class License(object):
    """The representation of a source license.

    It seems appropriate to use a class, since I'm not yet sure what we're
    going to want to remember about a license, but I can see methods in the
    future...

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
            * 'secret' - a marker that the checkout should not be distributed
              at all.
        """
        self.name = name
        if category not in ('gpl', 'open', 'binary', 'secret'):
            raise GiveUp("Attempt to create License '%s' with unrecognised"
                         " category '%s'"%(name, category))
        self.category = category

    def __str__(self):
        return self.name

    def __repr__(self):
        return '%s(%r, %r)'%(self.__class__.__name__, self.name, self.category)

    def __eq__(self, other):
        return (self.name == other.name and self.category == other.category)

    def distribute_source(self):
        """Returns True if we should (must?) distribute source code.
        """
        return self.category in ('open', 'gpl')

    def is_open(self):
        """Returns True if this is some sort of open-source license.

        Note: this includes GPL and LGPL licenses.
        """
        return category in ('open', 'gpl')

    def is_gpl(self):
        """Returns True if this is some sort of GPL license.
        """
        return False

    def is_lgpl(self):
        """Returns True if this is some sort of LGPL license.
        """
        return False

    def is_binary(self):
        """Is this a binary-distribution-only license?
        """
        return category == 'binary'

    def is_secret(self):
        """Is this a secret-do-not-distribute license?
        """
        return category == 'secret'

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

class LicenseSecret(License):
    """A "secret" license - we do not want to distribute anything
    """

    def __init__(self, name):
        super(LicenseSecret, self).__init__(name, 'secret')

    def __repr__(self):
        return '%s(%r)'%(self.__class__.__name__, self.name)

class LicenseBinary(License):
    """A binary license - we distribute binary only, not source code
    """

    def __init__(self, name):
        super(LicenseBinary, self).__init__(name, 'binary')

    def __repr__(self):
        return '%s(%r)'%(self.__class__.__name__, self.name)

class LicenseOpen(License):
    """Some non-GPL open source license.
    """

    def __init__(self, name):
        super(LicenseOpen, self).__init__(name, 'open')

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
        super(LicenseGPL, self).__init__(name, 'gpl')
        self.with_exception = with_exception

    def __repr__(self):
        if self.with_exception:
            return '%s(%r, with_exception=True)'%(self.__class__.__name__, self.name)
        else:
            return '%s(%r)'%(self.__class__.__name__, self.name)

    def __eq__(self, other):
        # Doing the super-comparison first guarantees we're both some sort of GPL
        return (super(LicenseGPL, self).__eq__(other) and
                self.system_exception == other.system_exception)

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
        super(LicenseLGPL, self).__init__(name, with_exception)

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
        ):
    standard_licenses[mnemonic] = license

def print_standard_licenses():
    keys = standard_licenses.keys()
    for key in sorted(keys):
        print '%-10s %r'%(key, standard_licenses[key])

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

def get_unlicensed_checkouts(builder):
    """Return the set of all checkouts which do not have a license.

    (Actually, a set of checkout labels, with the label tag "/checked_out").
    """
    all_checkouts = builder.invocation.all_checkout_labels()
    result = set()
    checkout_has_license = builder.invocation.db.checkout_has_license
    normalise_checkout_label = builder.invocation.db.normalise_checkout_label
    for co_label in all_checkouts:
        if not checkout_has_license(co_label):
            result.add(normalise_checkout_label(co_label))
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

# =============================================================================
# DISTRIBUTION
# =============================================================================
def distribute_checkout(builder, name, label, copy_vcs=False):
    """Request the distribution of the specified checkout(s).

    - 'name' is the name of the distribution we're adding this checkout to
    - 'label' must be

       1. a checkout label, in which case that checkout will be distributed
       2. a package label, in which case all the checkouts directly used by
          the package will be distributed (this is identical to calling
          'distribute_checkout' on each of them in turn). Note that in this
          case the same value of 'copy_vcs' will be used for all the
          checkouts. Either the package name or package role may be
          wildcarded, in which case the checkouts directly used by each
          matching label will be distributed.

      In either case, the label tag is ignored.

    - 'copy_vcs' says whether we should copy VCS "special" files (so, for
       git this includes at least the '.git' directory, and any '.gitignore'
       or '.gitmodules' files). The default is not to do so.

    All files and directories within the specified checkout(s) will be
    distributed, except for the VCS "special" files, whose distribution
    depends on 'copy_vcs'.

    Notes:

        1. If we already described a distribution called 'name' for a given
           checkout label, then this will silently overwrite it.
    """
    if DEBUG: print '.. distribute_checkout(builder, %r, %s, %s)'%(name, label, copy_vcs)

    if label.type == LabelType.Package:
        packages = builder.invocation.expand_wildcards(label)
        for package in packages:
            checkouts = builder.invocation.checkouts_for_package(package)
            for co_label in checkouts:
                distribute_checkout(builder, name, co_label, copy_vcs)

    elif label.type == LabelType.Checkout:
        source_label = label.copy_with_tag(LabelTag.CheckedOut)
        target_label = label.copy_with_tag(LabelTag.Distributed, transient=True)

        if DEBUG: print '   target', target_label

        # Making our target label transient means that its tag will not be
        # written out to the muddle database (i.e., .muddle/tags/...) when
        # the label is built

        # Is there already a rule for distributing this label?
        if builder.invocation.target_label_exists(target_label):
            # Yes - add this distribution to it (if it's not there already)
            if DEBUG: print '   exists: add/override'
            rule = builder.invocation.ruleset.map[target_label]
            # If it was already there, we'll just override whatever it thought
            # it wanted to do before...
            rule.action.set_distribution(name, copy_vcs, just=None)
        else:
            # No - we need to create one
            if DEBUG: print '   adding anew'
            action = DistributeCheckout(name, copy_vcs)

            rule = Rule(target_label, action)       # to build target_label, run action
            rule.add(source_label)                  # after we've built source_label

            builder.invocation.ruleset.add(rule)

    else:
        raise GiveUp('distribute_checkout() takes a checkout or package label, not %s'%label)

def distribute_checkout_files(builder, name, label, source_files):
    """Request the distribution of extra files from a particular checkout.

    - 'name' is the name of the distribution we're adding this checkout to
    - 'label' must be a checkout label. The label tag is not important.
    - 'specified_files' is a sequence of file paths, relative to the checkout
      directory.

    The intent of this function is to allow adding a small number of source
    files from a checkout to a binary package distribution, typically so that
    the necessary Makefiles and other build infrastructure is distributed.
    So, for instance::

        label = Label.from_string
        distribute_package(builder, 'marmalade', label('package:binapp{x86}/*'),
                           obj=True, install=True, with_muddle_makefile=True)
        distribute_checkout(builder, 'marmalade', label('checkout:binapp-1.2/*'),
                            ['Makefile', 'src/Makefile', 'src/rules'])

    Notes:

        1. If we already described a distribution called 'name' for a given
           checkout label, then this will, if necessary, add the given source
           files to that distribution.
        2. However, if that previous distribution was distributing "all files"
           (i.e., created with 'distribute_checkout()'), then we will not alter
           the action. This means that this call may not be used to override
           the 'copy_vcs' choice by trying to specify the VCS directory as
           an extra source path...
    """
    if DEBUG: print '.. distribute_checkout_files(builder, %r, %s, %s)'%(name, label, source_files)

    source_label = label.copy_with_tag(LabelTag.CheckedOut)
    target_label = label.copy_with_tag(LabelTag.Distributed, transient=True)

    if DEBUG: print '   target', target_label

    # Making our target label transient means that its tag will not be
    # written out to the muddle database (i.e., .muddle/tags/...) when
    # the label is built

    # Is there already a rule for distributing this label?
    if builder.invocation.target_label_exists(target_label):
        # Yes - add this distribution to it (if it's not there already)
        if DEBUG: print '   exists: add/override'
        rule = builder.invocation.ruleset.map[target_label]
        action = rule.action
        if action.does_distribution(name):
            # If we're already copying all the source files, we don't need to do
            # anything. Otherwise...
            if not action.copying_all_source_files(name):
                action.add_source_files(name, source_files)
        else:
            action.set_distribution(name, False, source_files)

    else:
        # No - we need to create one
        if DEBUG: print '   adding anew'
        action = DistributeCheckout(name, False, source_files)

        rule = Rule(target_label, action)       # to build target_label, run action
        rule.add(source_label)                  # after we've built source_label

        builder.invocation.ruleset.add(rule)

def distribute_build_desc(builder, name, label, copy_vcs=False):
    """Request the distribution of the given build description checkout.

    - 'name' is the name of the distribution we're adding this build
      description to
    - 'label' must be a checkout label, but the tag is not important.
    - 'copy_vcs' says whether we should copy VCS "special" files (so, for
       git this includes at least the '.git' directory, and any '.gitignore'
       or '.gitmodules' files). The default is not to do so.

    Notes:

        1. If we already described a distribution called 'name' for 'label',
           then this will silently overwrite it.
        2. If there was already a DistributeBuildCheckout action defined for
           this build description's checkout, then we will replace it with a
           DistributeBuildDescription action. All we'll copy over from the
           older action is the distribution names.
    """
    if DEBUG: print '.. distribute_build_desc(builder, %r, %s, %s)'%(name, label, copy_vcs)
    if label.type != LabelType.Checkout:
        # This is a MuddleBug because we shouldn't be called directly by the
        # user, so it's muddle infrastructure that got it wrong
        raise MuddleBug('distribute_build_desc() takes a checkout label, not %s'%label)

    source_label = label.copy_with_tag(LabelTag.CheckedOut)
    target_label = label.copy_with_tag(LabelTag.Distributed, transient=True)

    if DEBUG: print '   target', target_label

    # Making our target label transient means that its tag will not be
    # written out to the muddle database (i.e., .muddle/tags/...) when
    # the label is built

    # Is there already a rule for distributing this label?
    if builder.invocation.target_label_exists(target_label):
        # Yes. Is it the right sort of action?
        rule = builder.invocation.ruleset.map[target_label]
        action = rule.action
        if isinstance(action, DistributeBuildDescription):
            if DEBUG: print '   exists as DistributeBuildDescrption: add/override'
            # It's the right sort of thing - just add this distribution name
            action.set_distribution(name, copy_vcs)
        elif isinstance(action, DistributeCheckout):
            if DEBUG: print '   exists as DistributeCheckout: replace'
            # Ah, it's a generic checkout action - let's replace it with
            # a build description action
            new_action = DistributeBuildDescription(name, copy_vcs)
            # And copy over any names we don't yet have
            new_action.merge_names(action)
            rule.action = new_action
        else:
            # Oh dear, it's something unexpected
            raise GiveUp('Found unexpected action %s on build description rule'%action)
    else:
        # No - we need to create one
        if DEBUG: print '   adding anew'
        action = DistributeBuildDescription(name, copy_vcs)

        rule = Rule(target_label, action)       # to build target_label, run action
        rule.add(source_label)                  # after we've built source_label

        builder.invocation.ruleset.add(rule)

def distribute_package(builder, name, label, obj=False, install=True,
                       with_muddle_makefile=True):
    """Request the distribution of the given package.

    - 'name' is the name of the distribution we're adding this package to

    - 'label' must be a package label. Either the name or the role may be
      wildcarded, in which case this function will be called on each matching
      label. The label tag is ignored.

    - If 'obj' is true, then the obj/ directory (and the associated muddle
      tags) should be copied.

    - If 'install' is true, then the install/ directory (and the associated
      muddle tags) should be copied

    - If 'with_muddle_makefile' is true, then the muddle Makefile associated
      with building this package will also be distributed.

      This is implemented by looking up the MakeBuilder action used to build
      the package, finding the checkout and Makefile name from that, and then
      calling 'distribute_checkout_files()' to add that file in that checkout
      to the distribution.

      For most distributions with obj=False, install=True, this is probably
      a useful option.

    The 'with_muddle_makefile=True' mechanism is a fair attempt at allowing the
    distributed obj/ and install/ directory contents to be built, but doesn't
    support things like calling a different makefile or including other files
    directly in the muddle Makefile.

    If you need to specify extra files, that can be done with additional calls
    to 'distribute_checkout_files()'.

    Notes:

        1. We don't forbid having any particular combinations of 'obj' and
           'install', although both False is not terribly useful.
        2. If we already described a distribution called 'name' for 'label',
           then this will silently overwrite it.
    """
    if DEBUG: print '.. distribute_package(builder, %r, %s, obj=%s, install=%s, with_muddle_makefile=%s)'%(name, label, obj, install, with_muddle_makefile)
    if label.type != LabelType.Package:
        raise GiveUp('distribute_package() takes a package label, not %s'%label)

    packages = builder.invocation.expand_wildcards(label)
    if len(packages) == 0:
        raise GiveUp('distribute_package() of %s does not distribute anything'
                     ' (no matching package labels)'%label)

    if DEBUG and len(packages) > 1:
        print '.. => %s'%(', '.join(packages))

    for pkg_label in packages:
        source_label = pkg_label.copy_with_tag(LabelTag.PostInstalled)
        target_label = pkg_label.copy_with_tag(LabelTag.Distributed, transient=True)

        if DEBUG: print '   target', target_label

        # Making our target label transient means that its tag will not be
        # written out to the muddle database (i.e., .muddle/tags/...) when
        # the label is built

        # Is there already a rule for distributing this label?
        if builder.invocation.target_label_exists(target_label):
            # Yes - add this distribution name to it (if it's not there already)
            if DEBUG: print '   exists: add/override'
            rule = builder.invocation.ruleset.map[target_label]
            rule.action.set_distribution(name, obj, install)
        else:
            # No - we need to create one
            if DEBUG: print '   adding anew'
            action = DistributePackage(name, obj, install)

            rule = Rule(target_label, action)       # to build target_label, run action
            rule.add(source_label)                  # after we've built source_label

            builder.invocation.ruleset.add(rule)

        if with_muddle_makefile:
            # Our package label gets to have one MakeBuilder action associated
            # with it, which tells us what we want to know. It in turn is
            # "attached" to the various "buildy" tags on our label.
            tmp_label = pkg_label.copy_with_tag(LabelTag.Built)
            rule = builder.invocation.ruleset.rule_for_target(tmp_label)
            # Shall we assume it is a MakeBuilder? Let's not
            action = rule.action
            if not isinstance(action, MakeBuilder):
                raise GiveUp('Tried to get MakeBuilder action for %s, got %s'%(pkg_label, action))

            makefile_name = deduce_makefile_name(action.makefile_name,
                                                 action.per_role_makefiles,
                                                 pkg_label.role)

            make_co = Label(LabelType.Checkout, action.co, domain=pkg_label.domain)

            # And that's the muddle Makefile we want to add
            distribute_checkout_files(builder, name, make_co, [makefile_name])

def _set_checkout_tags(builder, label, target_dir):
    """Copy checkout muddle tags
    """
    root_path = normalise_dir(builder.invocation.db.root_path)
    local_root = find_local_relative_root(builder, label)

    tags_dir = os.path.join('.muddle', 'tags', 'checkout', label.name)
    src_tags_dir = os.path.join(root_path, local_root, tags_dir)
    tgt_tags_dir = os.path.join(target_dir, local_root, tags_dir)
    tgt_tags_dir = os.path.normpath(tgt_tags_dir)
    if DEBUG:
        print '..copying %s'%src_tags_dir
        print '       to %s'%tgt_tags_dir
    copy_without(src_tags_dir, tgt_tags_dir, preserve=True)

def _set_package_tags(builder, label, target_dir, which_tags):
    """Copy package tags.

    However, only copy package tags (a) for the particular role, and
    (b) for the tags named in 'which_tags'
    """
    root_path = normalise_dir(builder.invocation.db.root_path)
    local_root = find_local_relative_root(builder, label)

    tags_dir = os.path.join('.muddle', 'tags', 'package', label.name)
    src_tags_dir = os.path.join(root_path, local_root, tags_dir)
    tgt_tags_dir = os.path.join(target_dir, local_root, tags_dir)
    tgt_tags_dir = os.path.normpath(tgt_tags_dir)

    if DEBUG:
        print '..copying %s'%src_tags_dir
        print '       to %s'%tgt_tags_dir

    # We only want to copy tags for this particular role,
    # and only tags up to having built our obj/ hierarchy
    if not os.path.exists(tgt_tags_dir):
        os.makedirs(tgt_tags_dir)
    for tag in which_tags:
        tag_filename = '%s-%s'%(label.role, tag)
        tag_file = os.path.join(src_tags_dir, tag_filename)
        if os.path.exists(tag_file):
            copy_file(tag_file, os.path.join(tgt_tags_dir, tag_filename),
                      preserve=True)

def _actually_distribute_some_checkout_files(builder, label, target_dir, files):
    """As it says.
    """
    # Get the actual directory of the checkout
    co_src_dir = builder.invocation.db.get_checkout_location(label)

    # So we can now copy our source directory, ignoring the VCS directory if
    # necessary. Note that this can create the target directory for us.
    co_tgt_dir = os.path.join(normalise_dir(target_dir), co_src_dir)
    co_tgt_dir = os.path.normpath(co_tgt_dir)
    if DEBUG:
        print 'Copying some files for checkout:'
        print '  from %s'%co_src_dir
        print '  to   %s'%co_tgt_dir

    for file in files:
        actual_tgt_path = os.path.join(co_tgt_dir, file)
        head, tail = os.path.split(actual_tgt_path)
        if not os.path.exists(head):
            os.makedirs(head)
        copy_file(os.path.join(co_src_dir, file), actual_tgt_path,
                  preserve=True)

    # We mustn't forget to set the appropriate tags in the target .muddle/
    # directory, since we want it to look "checked out"
    _set_checkout_tags(builder, label, target_dir)

def _actually_distribute_checkout(builder, label, target_dir, copy_vcs):
    """As it says.
    """
    # Get the actual directory of the checkout
    co_src_dir = builder.invocation.db.get_checkout_location(label)

    # If we're not doing copy_vcs, find the VCS special files for this
    # checkout, and them our "without" string
    if copy_vcs:
        without = []
    else:
        repo = builder.invocation.db.get_checkout_repo(label)
        vcs_handler = get_vcs_handler(repo.vcs)
        without = vcs_handler.get_vcs_special_files()

    # So we can now copy our source directory, ignoring the VCS files if
    # necessary. Note that this can create the target directory for us.
    co_tgt_dir = os.path.join(normalise_dir(target_dir), co_src_dir)
    co_tgt_dir = os.path.normpath(co_tgt_dir)
    if DEBUG:
        print 'Copying checkout:'
        print '  from %s'%co_src_dir
        print '  to   %s'%co_tgt_dir
        if without:
            print '  without %s'%without
    copy_without(co_src_dir, co_tgt_dir, without, preserve=True)

    # We mustn't forget to set the appropriate tags in the target .muddle/
    # directory
    _set_checkout_tags(builder, label, target_dir)

def _actually_distribute_build_desc(builder, label, target_dir, copy_vcs):
    """Very similar to what we do for any other checkout...
    """
    # Get the actual directory of the checkout
    co_src_dir = builder.invocation.db.get_checkout_location(label)

    # Now, we want to copy everything except:
    #
    #   * no .pyc files
    #   * MAYBE no VCS files, depending

    if copy_vcs:
        files_to_ignore = []
    else:
        repo = builder.invocation.db.get_checkout_repo(label)
        vcs_handler = get_vcs_handler(repo.vcs)
        files_to_ignore = vcs_handler.get_vcs_special_files()

    co_tgt_dir = os.path.join(normalise_dir(target_dir), co_src_dir)
    if DEBUG:
        print 'Copying build description:'
        print '  from %s'%co_src_dir
        print '  to   %s'%co_tgt_dir
        if files_to_ignore:
            print '  without %s'%files_to_ignore

    files_to_ignore = set(files_to_ignore)

    for dirpath, dirnames, filenames in os.walk(co_src_dir):

        for name in filenames:
            if name in files_to_ignore:           # Maybe ignore VCS files
                continue
            base, ext = os.path.splitext(name)
            if ext == '.pyc':                       # Ignore .pyc files
                continue
            src_path = os.path.join(dirpath, name)
            tgt_dir = os.path.join(target_dir, dirpath)
            tgt_path = os.path.join(tgt_dir, name)
            if not os.path.exists(tgt_dir):
                os.makedirs(tgt_dir)
            copy_file(src_path, tgt_path, preserve=True)

        # Ignore VCS directories, if we were asked to do so
        directories_to_ignore = files_to_ignore.intersection(dirnames)
        for name in directories_to_ignore:
            dirnames.remove(name)

    # Set the appropriate tags in the target .muddle/ directory
    _set_checkout_tags(builder, label, target_dir)

def _actually_distribute_instructions(builder, label, target_dir):
    """Copy over any instruction files for this label

    Instruction files are called:

        .muddle/instructions/<package-name>/_default,xml
        .muddle/instructions/<package-name>/<role>,xml
    """
    root_path = normalise_dir(builder.invocation.db.root_path)
    local_root = find_local_relative_root(builder, label)

    #    Although there is infrastructure for this (db.scan_instructions),
    #    it actually appears to be easier to do this "by hand".
    #    Assuming I'm *doing* the right thing...

    inst_subdir = os.path.join('.muddle', 'instructions', label.name)
    inst_src_dir = os.path.join(root_path, local_root, inst_subdir)
    inst_tgt_dir = os.path.join(target_dir, local_root, inst_subdir)

    def make_inst_dir():
        if not os.path.exists(inst_tgt_dir):
            os.makedirs(inst_tgt_dir)

    if label.role and label.role != '*':    # Surely we always have a role?
        src_name = '%s.xml'%label.role
        src_file = os.path.join(inst_src_dir, src_name)
        if os.path.exists(src_file):
            make_inst_dir()
            copy_file(src_file, os.path.join(inst_tgt_dir, src_name), preserve=True)

    src_file = os.path.join(inst_src_dir, '_default.xml')
    if os.path.exists(src_file):
        make_inst_dir()
        copy_file(src_file, os.path.join(inst_tgt_dir, '_default.xml'), preserve=True)

def _actually_distribute_obj(builder, label, target_dir):
    """Distribute the obj/ directory for our package.
    """
    # Get the actual directory of the package obj/ directory.
    # Luckily, we know we should always have a role (since the build mechanism
    # works on "real" labels), so for the obj/ path we will get
    # obj/<name>/<role>/
    obj_dir = builder.invocation.package_obj_path(label)

    # We can then copy it over. copy_without will create the target
    # directory for us, if necessary
    root_path = normalise_dir(builder.invocation.db.root_path)
    rel_obj_dir = os.path.relpath(normalise_dir(obj_dir), root_path)
    tgt_obj_dir = os.path.join(target_dir, rel_obj_dir)
    tgt_obj_dir = normalise_dir(tgt_obj_dir)

    if DEBUG:
        print 'Copying binaries:'
        print '    from %s'%obj_dir
        print '    to   %s'%tgt_obj_dir

    copy_without(obj_dir, tgt_obj_dir, preserve=True)

    # We mustn't forget to set the appropriate package tags
    _set_package_tags(builder, label, target_dir,
                      ('preconfig', 'configured', 'built'))

    # In order to stop muddle wanting to rebuild the sources on which this
    # package depends, we also need to set the tags for the checkouts it
    # depends on
    checkouts = builder.invocation.checkouts_for_package(label)
    for co_label in checkouts:
        _set_checkout_tags(builder, co_label, target_dir)

    # We need to distribute instruction files here (if there are any for
    # this package) because obj/ + Makefile.muddle is enough to generate
    # install/, and from that deployment (which uses the instructions files)
    _actually_distribute_instructions(builder, label, target_dir)

def _actually_distribute_install(builder, label, target_dir):
    """Distribute the install/ directory for our package.
    """
    # Work out the install/ directory path/
    # Luckily, we know we should always have a role (since the build mechanism
    # works on "real" labels), so we shall get install/<role>.
    install_dir = builder.invocation.package_install_path(label)

    root_path = normalise_dir(builder.invocation.db.root_path)
    rel_install_dir = os.path.relpath(normalise_dir(install_dir), root_path)
    tgt_install_dir = os.path.join(target_dir, rel_install_dir)
    tgt_install_dir = normalise_dir(tgt_install_dir)

    # If the target install directory already exists, we assume that some
    # previous package has already copied its content (since the content
    # is per-role, not per-package)
    if not os.path.exists(tgt_install_dir):
        if DEBUG:
            print 'and from %s'%install_dir
            print '      to %s'%tgt_install_dir
        copy_without(install_dir, tgt_install_dir, preserve=True)

    # Set the appropriate package tags
    _set_package_tags(builder, label, target_dir,
                      ('preconfig', 'configured', 'built', 'installed', 'postinstalled'))

    # In order to stop muddle wanting to rebuild the sources on which this
    # package depends, we also need to set the tags for the checkouts it
    # depends on
    checkouts = builder.invocation.checkouts_for_package(label)
    for co_label in checkouts:
        _set_checkout_tags(builder, co_label, target_dir)

    # Don't forget any instruction files (these are needed for some
    # deployments)
    _actually_distribute_instructions(builder, label, target_dir)

class DistributeAction(Action):
    """
    An action that distributes a something-or-other.

    Intended as a base class for actions that know what they're doing.

    We contain one thing: a dictionary of {name : distribution information}.
    """

    def __init__(self, name, data):
        """
        'name' is the name of a distribution that this action supports.

        'data' is the data that describes how we do the distribution - this
        will differ according to whether we are distributing a checkout or
        package.
        """
        self.distributions = {name:data}

    def __str__(self):
        return '%s: %s'%(self.__class__.__name__,
                ', '.join(sorted(self.distributions.keys())))

    def set_distribution(self, name, data):
        """Set the information for the named distribution.

        If this action already has information for that name, overwrites it.
        """
        self.distributions[name] = data

    def get_distribution(self, name):
        """Return the data for distribution 'name', or raise MuddleBug
        """
        try:
            return self.distributions[name]
        except KeyError:
            raise MuddleBug('This Action does not have data for distribution "%s"'%name)

    def does_distribution(self, name):
        """Return True if we know this distribution name, False if not.
        """
        return name in self.distributions

    def distribution_names(self):
        """Return the distribution names we know about.
        """
        return self.distributions.keys()

    def merge_names(self, other):
        """Merge in the distribution names dictionary from another action.

        Any names that the other action has that we don't will be copied over.

        Any names we already have will be ignored.
        """
        other_dict = other.distributions
        for name in other_dict.keys():
            if name not in self.distributions:
                self.distributions[name] = other_dict[name]

    def build_label(self, builder, label):
        """Override this to do the actual task of distribution.
        """
        raise MuddleBug('No build_label method defined for class'
                        ' %s'%self.__class__.__name__)

class DistributeCheckout(DistributeAction):
    """
    An action that distributes a checkout.

    By default it copies the whole of the checkout source directory, not
    including any VCS files (.git/, etc.)

    A mechanism for only copying *some* files is also included. This is
    typically used by "binary" packages that want to copy (for instance) the
    muddle Makefile for a checkout, but not all the source code.

    Each checkout distribution is associated with a data tuple of the
    form:

            (copy_vcs, specific_files)

    where specific_files is None or a set of specific files for distibution.
    """

    def __init__(self, name, copy_vcs=False, just=None):
        """
        'name' is the name of a DistributuionContext. When created, we are
        told which DistributionContext we can be distributed by. Later on,
        other names may be added...

        If 'copy_vcs' is false, then don't copy any VCS "special" files
        (['.git', '.gitignore', ...] or ['.bzr'], etc., depending on the VCS
        used for this checkout).

        If 'just' is not None, then it must be a sequence of source paths,
        relative to the checkout directory, which are the specific files
        to be distributed for this checkout.

        Note that that means we distinguish between 'just=None' and 'just=[]' -
        the former instructs us to distribute all source files, the latter
        instructs us to distribute no source files.
        """
        if just is not None:
            just = set(just)

        super(DistributeCheckout, self).__init__(name, (copy_vcs, just))

    def __str__(self):
        parts = []
        for key, (copy_vcs, just) in self.distributions.items():
            inner = []
            if copy_vcs:
                inner.append('vcs')
            if just:
                inner.append('%d'%len(just))
            else:
                inner.append('*')
            parts.append('%s[%s]'%(key, ','.join(inner)))
        return '%s: %s'%(self.__class__.__name__, ', '.join(sorted(parts)))

    def set_distribution(self, name, copy_vcs=False, just=None):
        """Set the information for the named distribution.

        If this action already has information for that name, overwrites it.
        """
        if just is not None:
            just = set(just)

        self.distributions[name] = (copy_vcs, just)

    def add_source_files(self, name, source_files):
        """Add some specific source files to distribution 'name'.

        If we're already distributing the whole checkout, then this does
        nothing, as we're already outputting all the source files.

        Don't try to use this to add the VCS directory to a distribution of all
        source files that was instantiated with copy_vcs, as the clause above
        will make that fail...
        """
        copy_vcs, just = self.get_distribution(name)

        if just is None:
            # Nothing to do, we're already copying all files
            return

        just.update(source_files)
        self.set_distribution(name, copy_vcs, just)

    def request_all_source_files(self, name):
        """Request that distribution 'name' distribute all source files.

        This is a tidy way of undoing any selection of specific files.
        """
        copy_vcs, just = self.get_distribution(name)

        if just is None:
            # Nothing to do, we're already copying all files
            return

        self.set_distribution(name, copy_vcs, None)

    def copying_all_source_files(self, name):
        """Are we distributing all the soruce files?
        """
        copy_vcs, just = self.get_distribution(name)
        return just is None

    def copying_vcs(self, name):
        """Are we distributing the VCS directory?
        """
        copy_vcs, just = self.get_distribution(name)
        return copy_vcs

    def build_label(self, builder, label):
        name, target_dir = builder.get_distribution()

        copy_vcs, just = self.distributions[name]

        if DEBUG:
            print 'DistributeCheckout %s (%s VCS) to %s'%(label,
                    'without' if copy_vcs else 'with', target_dir)

        if just is None:
            _actually_distribute_checkout(builder, label, target_dir, copy_vcs)
        else:
            _actually_distribute_some_checkout_files(builder, label, target_dir, just)

class DistributeBuildDescription(DistributeAction):
    """This is a bit like DistributeCheckoutAction, but without 'just'.
    """

    def __init__(self, name, copy_vcs=False):
        """
        'name' is the name of a DistributionContext. When created, we are
        told which DistributionContext we can be distributed by. Later on,
        other names may be added...

        If 'copy_vcs' is false, then don't copy any VCS "special" files
        (['.git', '.gitignore', ...] or ['.bzr'], etc., depending on the VCS
        used for this checkout).
        """
        super(DistributeBuildDescription, self).__init__(name, copy_vcs)

    def __str__(self):
        parts = []
        for key, copy_vcs in self.distributions.items():
            if copy_vcs:
                parts.append('%s[vcs]'%key)
            else:
                parts.append(key)
        return '%s: %s'%(self.__class__.__name__, ', '.join(sorted(parts)))

    def build_label(self, builder, label):
        name, target_dir = builder.get_distribution()

        copy_vcs = self.distributions[name]

        if DEBUG:
            print 'DistributeBuildDescription %s (%s VCS) to %s'%(label,
                    'without' if copy_vcs else 'with', target_dir)

        _actually_distribute_build_desc(builder, label, target_dir, copy_vcs)

class DistributePackage(DistributeAction):
    """
    An action that distributes a package.

    If the package is being distributed as binary, then this action copies
    the obj/ and install/ directories for the package, as well as any
    instructions (and anything else I haven't yet thought of).

    If the package is being distributed as source, then this action copies
    the source directory for each checkout that is *directly* used by the
    package.

    In either case, associated and appropriate muddle tags are also copied.

    Destination directories that do not exist are created as necessary.
    """

    def __init__(self, name, obj=True, install=True):
        """
        'name' is the name of a DistributuionContext. When created, we are
        told which DistributionContext we can be distributed by. Later on,
        other names may be added...

        If 'obj' is true, then the obj/ directory (and the associated muddle
        tags) should be copied.

        If 'install' is true, then the install/ directory (and the associated
        muddle tags) should be copied

        Notes:

            1. We don't forbid having any particular combinations of 'obj' and
               'install', although both False is not terribly useful.
        """
        super(DistributePackage, self).__init__(name, (obj, install))

    def __str__(self):
        parts = []
        for key, (obj, install) in self.distributions.items():
            inner = []
            if obj:
                inner.append('obj')
            if install:
                inner.append('install')
            if inner:
                parts.append('%s[%s]'%(key, ','.join(inner)))
            else:
                parts.append(key)
        return '%s: %s'%(self.__class__.__name__, ', '.join(sorted(parts)))

    def set_distribution(self, name, obj=True, install=True):
        """Set the information for the named distribution.

        If this action already has information for that name, overwrites it.
        """
        self.distributions[name] = (obj, install)

    def build_label(self, builder, label):
        name, target_dir = builder.get_distribution()

        obj, install = self.distributions[name]

        if DEBUG:
            print 'DistributePackage %s to %s'%(label, target_dir)

        if obj:
            _actually_distribute_obj(builder, label, target_dir)

        if install:
            _actually_distribute_install(builder, label, target_dir)

def find_all_distribution_names(builder):
    """Return a set of all the distribution names.
    """
    distribution_names = set()

    invocation = builder.invocation
    target_label_exists = invocation.target_label_exists

    # We get all the "reasonable" checkout and package labels
    all_checkouts = builder.invocation.all_checkout_labels(LabelTag.CheckedOut)
    all_packages = builder.invocation.all_package_labels()

    combined_labels = all_checkouts.union(all_packages)
    for label in combined_labels:
        target = label.copy_with_tag(LabelTag.Distributed)
        # Is there a distribution target for this label?
        if target_label_exists(target):
            # If so, what names does it know?
            rule = invocation.ruleset.map[target]
            names = rule.action.distribution_names()
            distribution_names.update(names)

    return distribution_names

def domain_from_parts(parts):
    """Construct a domain name from a list of parts.
    """
    num_parts = len(parts)
    domain = '('.join(parts) + ')'*(num_parts-1)
    return domain

def build_desc_label_in_domain(builder, domain, label_tag):
    """Return the label for the build description checkout in this domain.
    """
    # Basically, we need to figure out what checkout to use...

    if not domain:
        build_co_name, build_desc_path = builder.invocation.build_co_and_path()
    else:
        build_desc_path = os.path.join(builder.invocation.db.root_path,
                                       domain_subpath(domain),
                                       '.muddle', 'Description')
        with open(build_desc_path) as fd:
            str = fd.readline()
        build_co_name, build_desc_path = build_co_and_path_from_str(str.strip())
    return Label(LabelType.Checkout, build_co_name, tag=label_tag, domain=domain)

def add_build_descriptions(builder, name, domains, copy_vcs=False):
    """Add all the implicated build description checkouts to our distribution.
    """
    # We need a build description for each domain we had a label for
    # (and possibly also any "in between" domains that weren't mentioned
    # explicitly?)

    extra_labels = []

    cumulative_domains = set()
    for domain in sorted(domains):
        if domain is None:
            cumulative_domains.add(domain)
        else:
            parts = Label.split_domain(domain)
            for ii in range(1, 1+len(parts)):
                d = domain_from_parts(parts[:ii])
                cumulative_domains.add(d)

    if DEBUG: print 'Adding build descriptions'
    for domain in sorted(cumulative_domains):
        co_label = build_desc_label_in_domain(builder, domain, LabelTag.Distributed)
        if DEBUG: print '-- Build description', co_label
        distribute_build_desc(builder, name, co_label, copy_vcs)
        extra_labels.append(co_label)
    if DEBUG: print 'Done'

    return extra_labels

def copy_muddle_skeleton(builder, name, target_dir, domains):
    """Copy the "top files" for each necessary .muddle directory
    """

    src_root = builder.invocation.db.root_path
    tgt_root = target_dir

    for domain in sorted(domains):
        if DEBUG: print '.muddle skeleton for domain:', domain

        if not domain:
            src_dir = os.path.join(src_root, '.muddle')
            tgt_dir = os.path.join(tgt_root, '.muddle')
        else:
            inner_path = domain_subpath(domain)
            src_dir = os.path.join(src_root, inner_path, '.muddle')
            tgt_dir = os.path.join(tgt_root, inner_path, '.muddle')

        if not os.path.exists(tgt_dir):
            os.makedirs(tgt_dir)

        for name in ('RootRepository', 'Description'):
            copy_file(os.path.join(src_dir, name),
                      os.path.join(tgt_dir, name), preserve=True)

        for name in ('VersionsRepository', 'am_subdomain'):
            src_name = os.path.join(src_dir, name)
            if os.path.exists(src_name):
                copy_file(src_name, os.path.join(tgt_dir, name), preserve=True)

    if DEBUG: print 'Done'

def copy_versions_dir(builder, name, target_dir, copy_vcs=False):
    """Copy the stamp versions directory
    """

    src_root = builder.invocation.db.root_path
    src_dir = os.path.join(src_root, 'versions')
    if not os.path.exists(src_dir):
        return

    if DEBUG: print 'Copying versions/ directory'

    tgt_root = target_dir
    tgt_dir = os.path.join(tgt_root, 'versions')

    if not os.path.exists(tgt_dir):
        os.makedirs(tgt_dir)

    if copy_vcs:
        without = []
    else:
        versions_repo_url = builder.invocation.db.versions_repo.get()
        without = vcs_special_files(versions_repo_url)

    if DEBUG:
        print 'Copying versions/ directory:'
        print '  from %s'%src_dir
        print '  to   %s'%tgt_dir
        if without:
            print '  without %s'%without

    copy_without(src_dir, tgt_dir, without, preserve=True)

def distribute(builder, name, target_dir, with_versions_dir=False,
               with_vcs=False, no_muddle_makefile=False, no_op=False):
    """Distribute using distribution context 'name', to 'target_dir'.

    The DistributeContext called 'name' must exist.

    All distributions described in that DistributeContext will be made.

    'name' is the name of the distribution to, erm, distribute. The special
    names "_source_release" and "_binary_release" are always recognised.

    'target_dir' is where to put the distribution. It will be created if
    necessary.

    If 'with_versions_dir' is true, then any stamp "versions/" directory
    will also be distributed.

    If "with_vcs" is true, then the VCS directory (.git/ for git, etc.)
    will be copied for:

        - the build description(s)
        - the "versions/" directory (if it is distributed)
        - all checkouts in a "_source_release" distribution

    If 'no_muddle_makefile' is true, then the appropriate muddle Makefile (in
    the appropriate checkout) will *not* be distributed with a package.

    If 'no_op' is true, then we just report on what we would do - this
    lists the labels that would be distributed, and the action that would
    be used to do so.
    """

    print 'Writing distribution', name, 'to', target_dir

    # =========================================================================
    # PREPARE
    # =========================================================================
    distribution_labels = set()
    domains = set()

    invocation = builder.invocation
    target_label_exists = invocation.target_label_exists

    # We get all the "reasonable" checkout and package labels
    all_checkouts = builder.invocation.all_checkout_labels(LabelTag.CheckedOut)
    all_packages = builder.invocation.all_package_labels()

    # Standard names
    # ==============
    if name == '_source_release':
        # A source release is the source directories alone, but with no VCS
        for label in all_checkouts:
            distribute_checkout(builder, name, label, copy_vcs=with_vcs)
        all_packages = set()
    elif name == '_binary_release':
        # A binary release is the install directories for all packages
        for label in all_packages:
            distribute_package(builder, name, label, obj=False, install=True,
                               with_muddle_makefile=(not no_muddle_makefile))
    # ==============

    combined_labels = set(all_checkouts.union(all_packages))
    for label in sorted(combined_labels):
        target = label.copy_with_tag(LabelTag.Distributed)
        # Is there a distribution target for this label?
        if target_label_exists(target):
            # If so, is it distributable with this distribution name?
            rule = invocation.ruleset.rule_for_target(target)
            if rule.action.does_distribution(name):
                # Yes, we like this label
                distribution_labels.add(target)
                # And remember its domain
                domains.add(target.domain)

    if not distribution_labels:
        print 'Nothing to distribute for %s'%name
        return

    # Add in appropriate build descriptions
    # We need to do this after everyone else has had a chance to set rules
    # on /distribute labels, so we can override any DistributeCheckout actions
    # that were mistakenly placed on our build descriptions...
    extra_labels = add_build_descriptions(builder, name, domains, with_vcs)

    # Don't forget that means more labels for us
    distribution_labels.update(extra_labels)

    num_labels = len(distribution_labels)

    distribution_labels = sorted(distribution_labels)

    # =========================================================================
    # REPORT?
    # =========================================================================
    if no_op:
        maxlen = 0
        for label in distribution_labels:
            maxlen = max(maxlen,len(str(label)))
        for label in distribution_labels:
            rule = invocation.ruleset.map[label]
            print '%-*s %s'%(maxlen, label, rule.action)
        return

    # =========================================================================
    # DISTRIBUTE
    # =========================================================================
    # Remember to say where we're copying to...
    builder.set_distribution(name, target_dir)

    # Copy over the skeleton of the required .muddle directories
    copy_muddle_skeleton(builder, name, target_dir, domains)

    if with_versions_dir:
        # Copy over the versions directory, if any
        copy_versions_dir(builder, name, target_dir, with_vcs)

    print 'Building %d /distribute label%s'%(num_labels,
            '' if num_labels==1 else 's')
    for label in distribution_labels:
        builder.build_label(label)
