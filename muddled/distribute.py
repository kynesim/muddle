"""
Actions and mechanisms relating to distributing build trees
"""

# XXX TODO
# Does the -no-muddle-makefile switch to the "muddle distribute" command
# actually make any sense?
# If the user has added extra files to a distribution, then using that
# switch will suppress the muddle Makefile, but not any other specifically
# requested files, which will typically be other Makefiles. Which will lead
# to all sorts of confusion. So maybe the solution is "just don't do that",
# and we should always distribute muddle Makefiles...

# XXX TODO
# Question - what are we meant to do if a package implicitly sets
# a distribution state for a checkout, and we also explicitly set
# a different (incompatible) state for a checkout? Who wins? Or do
# we just try to satisfy both?

# XXX TODO
# There's an issue with the whole 'copy_vcs' thing about when it is specified
# and by whom.
#
# Perhaps when the user specifies it in a build file, they should be able to
# say copy_vcs=None, True or False. True means definitely copy the VCS,
# regardless of what else goes on. False means definitely don't, ditto. And
# None means go with what the actual "muddle distribute" command used suggests.
# This is probably worth doing, but maybe not in the first release...

import os
from fnmatch import fnmatchcase

from muddled.depend import Action, Rule, Label, needed_to_build, label_list_to_string
from muddled.utils import GiveUp, MuddleBug, LabelTag, LabelType, \
        copy_without, normalise_dir, find_local_relative_root, \
        copy_file, domain_subpath, sort_domains
from muddled.version_control import get_vcs_instance, vcs_special_files
from muddled.mechanics import build_co_and_path_from_str
from muddled.pkgs.make import MakeBuilder, deduce_makefile_name
from muddled.pkgs.aptget import AptGetBuilder
from muddled.licenses import get_gpl_checkouts, get_implicit_gpl_checkouts, \
        get_open_checkouts, get_binary_checkouts, get_prop_source_checkouts, \
        checkout_license_allowed, report_license_clashes, get_license, \
        report_license_clashes_in_role, ALL_LICENSE_CATEGORIES
from muddled.withdir import Directory

DEBUG=False
VERBOSE=False       # should copy_without be quiet

# Distribution names, with the license categories they distribute something
# from. Note that distributing something from 'gpl' or 'open-source' doesn't
# mean the same thing as "distributing sources", as is evidenced by
# '_binary_release'.
#
# The '_for_gpl' distribution distributes 'gpl' entities, but it may also
# distribute 'open-source' entities by license propagation. So we have to say
# that.
the_distributions = { '_source_release' : ALL_LICENSE_CATEGORIES,
                      '_binary_release' : ALL_LICENSE_CATEGORIES,
                      '_for_gpl':    ('gpl', 'open-source' ),
                      '_all_open':   ('gpl', 'open-source'),
                      '_by_license': ('gpl', 'open-source', 'prop-source', 'binary'),
                    }


def _filter(names, pattern):
    """A version of fnmatch.filter that does not do normcase.

    (The version supplied does os.path.normcase on both the pattern
    and maybe the names. We don't want either.)
    """
    result = []
    for name in names:
        if fnmatchcase(name, pattern):
            result.append(name)
    return result

def name_distribution(builder, name, categories=None):
    """Declare that a distribution called 'name' exists.

    Also specify which license categories are distributed.

    If 'categories' is None, then all license categories are distributed.

    Otherwise 'categories' must be a sequence of category names, taken
    from 'gpl', 'open-source', binary' and 'private'.

    The user may assume that the standard distributions (see "muddle help
    distribute") already exist, but otherwise must name a distribution before
    it is used.

    It is not an error to name a distribution more than once (although it won't
    have any effect), but the categories named must be identical.

        >>> name_distribution(None, '_all_open', ['gpl', 'open-source'])  # same categories
        >>> name_distribution(None, '_all_open', ['open-source']) # different categories
        Traceback (most recent call last):
        ...
        GiveUp: Attempt to name distribution "_all_open" with categories "open-source" but it already has "gpl", "open-source"

    It is an error to try to use a distribution before it has been named. This
    includes adding checkouts and packages to distributions. Wildcard
    operations will only take account of the distributions that have already
    been named.

    Distribution names that start with an underscore are reserved by muddle to
    define as it wishes, although we don't stop you naming a distribution that
    starts with an underscore (just remember muddle may take the name later
    without warning).
    """
    global the_distributions

    if name in the_distributions:   # Check we're not trying to change it
        if categories:
            new = set(categories)
        else:
            new = set(ALL_LICENSE_CATEGORIES)

        old = set(the_distributions[name])

        if new == old:
            return
        else:
            raise GiveUp('Attempt to name distribution "%s" with categories'
                         ' "%s" but it already has "%s"'%(name,
                                                          '", "'.join(sorted(new)),
                                                          '", "'.join(sorted(old))))

    # Arguably, we should remember distributions on the builder object,
    # but in fact I don't think it makes any difference whatsoever to
    # how we treat them, especially as they are not to be distinct
    # between different domains
    if not categories:
        the_distributions[name] = ALL_LICENSE_CATEGORIES
    else:
        for cat in categories:
            if cat not in ALL_LICENSE_CATEGORIES:
                raise GiveUp('Unrecognised license category "%s" in name_distribution'%cat)
        the_distributions[name] = tuple(categories)

def get_distribution_names(builder=None):
    """Return the known distribution names.

    Note that 'builder' is optional.
    """
    return the_distributions.keys()

def get_distributions_for(builder, categories):
    """Return distributions that distribute all the given 'categories'

    That is, for each distribution, look and see if the license categories
    it distributes for include all the values in 'categories', and if it does,
    add its name to the result.

    For instance, we know we should always have at least two distributions
    that work for category 'binary':

        >>> dists = get_distributions_for(None, ['binary'])
        >>> '_by_license' in dists
        True
        >>> '_binary_release' in dists
        True
        >>> '_for_gpl' in dists
        False

    'builder' is ignored at the moment, but should be the build tree "builder"
    if available.
    """
    results = []
    categories = set(categories)
    for name, does_for in the_distributions.items():
        if categories.issubset(does_for):
            results.append(name)
    return results

def get_distributions_not_for(builder, categories):
    """Return distributions that distribute none of the given 'categories'

    That is, for each distribution, look and see if the license categories
    it distributes for include any of the values in 'categories', and if it
    does not, add its name to the result.

    For instance, we know that we have at least one distribution that is not
    for 'binary' and 'secure':

        >>> dists = get_distributions_not_for(None, ['binary', 'secure'])
        >>> '_for_gpl' in dists
        True
        >>> '_source_release' in dists
        False

    Asking for distributions that don't do anything should hopefully return
    an empty list:

        >>> get_distributions_not_for(None, ALL_LICENSE_CATEGORIES)
        []

    'builder' is ignored at the moment, but should be the build tree "builder"
    if available.
    """
    results = []
    categories = set(categories)
    for name, does_for in the_distributions.items():
        if categories.isdisjoint(does_for):
            results.append(name)
    return results

def get_used_distribution_names(builder):
    """Return a set of all the distribution names that are actually in use

    "in use" is taken to mean that some rule in the dependency tree has an
    action that is defined for that particular distribution name.
    """
    distribution_names = set()

    target_label_exists = builder.target_label_exists

    # We get all the "reasonable" checkout and package labels
    all_checkouts = builder.all_checkout_labels(LabelTag.CheckedOut)
    all_packages = builder.all_package_labels()

    combined_labels = all_checkouts.union(all_packages)
    for label in combined_labels:
        target = label.copy_with_tag(LabelTag.Distributed)
        # Is there a distribution target for this label?
        if target_label_exists(target):
            # If so, what names does it know?
            rule = builder.ruleset.map[target]
            names = rule.action.distribution_names()
            distribution_names.update(names)

    return distribution_names

def get_distributions_by_category(builder):
    """Return a dictionary of distribution names according to license category.

    The dictionary returned has license category names as keys, and sets of
    distribution names as the values.
    """
    by_category = {}
    for distribution, categories in the_distributions.items():
        for category in categories:
            if category in by_category:
                by_category[category].add(distribution)
            else:
                by_category[category] = set([distribution])
    return by_category

def _assert_checkout_allowed_in_distribution(builder, co_label, name):
    """Is this checkout allowed in this distribution?

    If 'checkout_license_allowed()' returns False for this checkout label and
    the license categories of this distribution, then we raise an appropriate
    exception.
    """
    if not checkout_license_allowed(builder, co_label, the_distributions[name]):
        license = builder.db.get_checkout_license(co_label, absent_is_None=True)
        raise GiveUp('Checkout %s is not allowed in distribution "%s"\n'
                     'Checkout has license "%s",\n'
                     '  which is "%s", distribution allows "%s"'%(co_label,
                         name, license, license.category,
                         '", "'.join(the_distributions[name])))

def _distribute_checkout(builder, actual_names, label, copy_vcs=False):
    """The work of saying we should distribute a checkout.

    Depends on 'actual_names' being valid distribution names.
    """
    for name in actual_names:
        _assert_checkout_allowed_in_distribution(builder, label, name)

    source_label = label.copy_with_tag(LabelTag.CheckedOut)
    target_label = label.copy_with_tag(LabelTag.Distributed, transient=True)

    if DEBUG: print '   target', target_label

    # Making our target label transient means that its tag will not be
    # written out to the muddle database (i.e., .muddle/tags/...) when
    # the label is built

    # Is there already a rule for distributing this label?
    if builder.target_label_exists(target_label):
        # Yes, so retrieve it, and its action
        rule = builder.ruleset.map[target_label]
        action = rule.action
        if DEBUG: print '   %s exists'%action
        # but don't *do* anything to that first action yet
    else:
        # No - we need to create one
        if DEBUG: print '   adding %s anew'%actual_names[0]
        action = DistributeCheckout(actual_names[0], copy_vcs)

        rule = Rule(target_label, action)   # to build target_label, run action
        rule.add(source_label)              # after we've built source_label

        builder.ruleset.add(rule)

        # We've done with the first name
        actual_names = actual_names[1:]

    # Add the other distributions to the same action
    for name in actual_names:
        if DEBUG: print '   %s exists: add/replace %s'%(action, name)
        # NB: This call should work whether the existing Action is a
        #     DistributeCheckout or DistributeBuildDescription
        if action.does_distribution(name):
            if isinstance(action, DistributeCheckout):
                # We already know about this checkout
                # Since this is asking us to distribute the whole thing,
                # make sure we forget about any previous request for
                # specific files
                action.override(name, copy_vcs)
            else:       # Presumably a DistributeBuildDescription
                # Just override the copy_vcs request
                action.set_copy_vcs(name, copy_vcs)
        else:
            # Otherwise, it's simple to add it
            action.add_distribution(name, copy_vcs)

def distribute_checkout(builder, name, label, copy_vcs=False):
    """Request the distribution of the specified checkout(s).

    - 'name' is the name of the distribution we're adding this checkout to,
      or a "shell pattern" matching existing (already named) distributions.
      In that case::

            *       matches everything
            ?       matches any single character
            [seq]   matches any character in seq
            [!seq]  matches any char not in seq

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

    actual_names = _filter(the_distributions.keys(), name)
    if not actual_names:
        raise GiveUp('There is no distribution matching "%s"'%name)

    if label.type == LabelType.Package:
        packages = builder.expand_wildcards(label)
        for package in packages:
            checkouts = builder.checkouts_for_package(package)
            for co_label in checkouts:
                _distribute_checkout(builder, actual_names, co_label, copy_vcs)

    elif label.type == LabelType.Checkout:
        _distribute_checkout(builder, actual_names, label, copy_vcs)

    else:
        raise GiveUp('distribute_checkout() takes a checkout or package label, not %s'%label)

def distribute_checkout_files(builder, name, label, source_files):
    """Request the distribution of extra files from a particular checkout.

    - 'name' is the name of the distribution we're adding this checkout to,
      or a "shell pattern" matching existing (already named) distributions.
      In that case::

            *       matches everything
            ?       matches any single character
            [seq]   matches any character in seq
            [!seq]  matches any char not in seq

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
    if label.type != LabelType.Checkout:
        raise GiveUp('distribute_checout_files() takes a checkout label, not %s'%label)

    actual_names = _filter(the_distributions.keys(), name)
    if not actual_names:
        raise GiveUp('There is no distribution matching "%s"'%name)

    for name in actual_names:
        _assert_checkout_allowed_in_distribution(builder, label, name)

    source_label = label.copy_with_tag(LabelTag.CheckedOut)
    target_label = label.copy_with_tag(LabelTag.Distributed, transient=True)

    if DEBUG: print '   target', target_label

    # Making our target label transient means that its tag will not be
    # written out to the muddle database (i.e., .muddle/tags/...) when
    # the label is built

    # Is there already a rule for distributing this label?
    if builder.target_label_exists(target_label):
        # Yes, so retrieve it, and its action
        rule = builder.ruleset.map[target_label]
        action = rule.action
        if DEBUG: print '   %s exists'%action
        # but don't *do* anything to that first action yet
    else:
        # No - we need to create one
        if DEBUG: print '   adding %s anew'%actual_names[0]
        # We don't want to copy VCS, as we're not copying all of the
        # checkout (and VCS contains information about the other files!)
        action = DistributeCheckout(actual_names[0], False, source_files)

        rule = Rule(target_label, action)   # to build target_label, run action
        rule.add(source_label)              # after we've built source_label

        builder.ruleset.add(rule)

        # We've done with the first name
        actual_names = actual_names[1:]

    # Add the other distributions to the same action
    for name in actual_names:
        # Yes - add this distribution to it (if it's not there already)
        if DEBUG: print '   %s exists: add/replace %s'%(action, name)
        if action.does_distribution(name):
            # If we're already copying all the source files, we don't need to do
            # anything. Otherwise...
            if not action.copying_all_source_files(name):
                action.add_source_files(name, source_files)
        else:
            # We don't want to copy VCS, as we're not copying all of the
            # checkout (and VCS contains information about the other files!)
            action.add_distribution(name, False, source_files)

def distribute_build_desc(builder, name, label, copy_vcs=False):
    """Request the distribution of the given build description checkout.

    - 'name' is the name of the distribution we're adding this build
      description to.

      Note that this function is normally used by muddle itself, and it does
      not support any wildcarding of 'name'.

    - 'label' must be a checkout label, but the tag is not important.

    - 'copy_vcs' says whether we should copy VCS "special" files (so, for
       git this includes at least the '.git' directory, and any '.gitignore'
       or '.gitmodules' files). The default is not to do so.

    Notes:

        1. If there was already a DistributeBuildDescription action defined for
           this build description's checkout, then we will amend it to look as
           if we created it (but leaving any "private" file requests untouched).
        2. If there was already a DistributeBuildCheckout action defined for
           this build description's checkout, then we will replace it with a
           DistributeBuildDescription action. All we'll copy over from the
           older action is the distribution names.

    *_distribution/<name>.py files*

    If the build description checkout contains a file called
    ``_distribution/<name>.py``, where ``<name>`` is the 'name' of the
    distribution we're building, then that file will be distributed as
    the build description (using the appropriate name found from
    the ``.muddle/Description`` file), and all other files in the build
    description checkout will be ignored. Note that this also means that
    in this case any calls of ```set_private_build_files()`` will be ignored.

    Since the name of the file is specifically tied to the distribution name,
    no license checking is done in this case - if you are doing a "_for_gpl"
    distribution, and provide a ``_distribution/_for_gpl.py`` file, then it
    is assumed that this was deliberate, whatever license the main build
    description may have.

    Also, 'copy_vcs' will be ignored in this situation, and any VCS data
    will not be copied.
    """
    if DEBUG: print '.. distribute_build_desc(builder, %r, %s, %s)'%(name, label, copy_vcs)
    if label.type != LabelType.Checkout:
        # This is a MuddleBug because we shouldn't be called directly by the
        # user, so it's muddle infrastructure that got it wrong
        raise MuddleBug('distribute_build_desc() takes a checkout label, not %s'%label)

    if name not in the_distributions.keys():
        raise GiveUp('There is no distribution called "%s"'%name)

    # Check for a distribution build description
    this_dir = builder.db.get_checkout_path(label)
    dist_file = os.path.join('_distribution', '%s.py'%name)
    if os.path.exists(os.path.join(this_dir, dist_file)):
        print 'Found replacement build description for distribution "%s"'%name
        # We never copy VCS in this situation
        copy_vcs = False
        replacement_build_desc = dist_file
    else:
        replacement_build_desc = None       # use the normal build description
        # And check our licenses make sense
        try:
            _assert_checkout_allowed_in_distribution(builder, label, name)
        except GiveUp as e:
            # An undefined license is always *allowed*, so we know we don't need
            # to check for that case in getting the license for our label
            license = builder.db.get_checkout_license(label)
            if license.is_proprietary_source():
                # Normally we would not distribute proprietary source checkouts for
                # distributions that don't allow it. However, we make an exception
                # for the build description, as that's not an unreasonable way to
                # license it, but distributing it is not normally expected to be a
                # problem. However, give a warning just in case.
                print
                print 'WARNING: DISTRIBUTING BUILD DESCRIPTION DESPITE LICENSE CLASH'
                text = str(e)
                for line in text.split('\n'):
                    print ' ', line
                print 'END OF WARNING'
                print
            else:
                raise

    source_label = label.copy_with_tag(LabelTag.CheckedOut)
    target_label = label.copy_with_tag(LabelTag.Distributed, transient=True)

    if DEBUG: print '   target', target_label

    # Making our target label transient means that its tag will not be
    # written out to the muddle database (i.e., .muddle/tags/...) when
    # the label is built

    # Is there already a rule for distributing this label?
    if builder.target_label_exists(target_label):
        # Yes. Is it the right sort of action?
        rule = builder.ruleset.map[target_label]
        action = rule.action
        if isinstance(action, DistributeBuildDescription):
            if DEBUG: print '   exists as DistributeBuildDescription: add/override'
            # It's the right sort of thing
            if action.does_distribution(name):
                # If the action already know about this distribution, just
                # overwrite any value for copy_vcs and using_build_desc
                # (leave any private_files intact)
                action.set_copy_vcs(name, copy_vcs)
                action.set_replacement_build_desc(name, replacement_build_desc)
            else:
                # Otherwise, it's simple to add it
                action.add_distribution(name, copy_vcs, replacement_build_desc)
        elif isinstance(action, DistributeCheckout):
            if DEBUG: print '   exists as DistributeCheckout: replace'
            # Ah, it's a generic checkout action - let's replace it with
            # a build description action
            new_action = DistributeBuildDescription(name, copy_vcs,
                                                    replacement_build_desc=replacement_build_desc)
            # And copy over any distribution names we don't yet have
            new_action.merge_names(action)
            rule.action = new_action
        else:
            # Oh dear, it's something unexpected
            raise GiveUp('Found unexpected action %s on build description rule'%action)
    else:
        # No - we need to create one
        if DEBUG: print '   adding anew'
        action = DistributeBuildDescription(name, copy_vcs,
                                            replacement_build_desc=replacement_build_desc)

        rule = Rule(target_label, action)       # to build target_label, run action
        rule.add(source_label)                  # after we've built source_label

        builder.ruleset.add(rule)

def set_private_build_files(builder, name, private_files):
    """Set some private build files for the (current) build description.

    These are files within the build description directory that will replaced
    by dummy files when doing the distribution.

    - 'name' is the name of the distribution we're adding this checkout to,
      or a "shell pattern" matching existing (already named) distributions.
      In that case::

            *       matches everything
            ?       matches any single character
            [seq]   matches any character in seq
            [!seq]  matches any char not in seq

    - 'private_files' is the list of the files that must be distributed as dummy
      files. They are relative to the build description checkout directory.

    The "original" private files must exist and must work by providing a
    function with signature::

          def describe_private(builder, *args, **kwargs):
              ...

    The dummy files will also containg such a function, but its body will be
    ``pass``.
    """
    if DEBUG: print '.. set_private_build_files(builder, %r, %s)'%(name, private_files)

    actual_names = _filter(the_distributions.keys(), name)
    if not actual_names:
        raise GiveUp('There is no distribution matching "%s"'%name)

    # Work out the label for this build description
    label = _build_desc_label_in_domain(builder, None, LabelTag.Distributed)
    # And thus its directory
    our_dir = builder.db.get_checkout_path(label)

    # We'd better check
    for name in actual_names:
        _assert_checkout_allowed_in_distribution(builder, label, name)

    for file in private_files:
        base, ext = os.path.splitext(file)
        if ext != '.py':
            raise GiveUp('Private file "%s" does not end in ".py"'%file)
        file_path = os.path.join(our_dir, file)
        if not os.path.exists(file_path):
            raise GiveUp('Private file "%s" does not exist'%file_path)

    source_label = label.copy_with_tag(LabelTag.CheckedOut)
    target_label = label.copy_with_tag(LabelTag.Distributed, transient=True)

    if DEBUG: print '   target', target_label

    # Making our target label transient means that its tag will not be
    # written out to the muddle database (i.e., .muddle/tags/...) when
    # the label is built

    # Is there already a rule for distributing this label?
    name = actual_names[0]
    if builder.target_label_exists(target_label):
        # Yes. Is it the right sort of action?
        rule = builder.ruleset.map[target_label]
        action = rule.action
        if isinstance(action, DistributeBuildDescription):
            if DEBUG: print '   exists as DistributeBuildDescrption: add/override'
            # It's the right sort of thing - just add these private files
            if action.does_distribution(name):
                action.add_private_files(name, private_files)
            else:
                action.add_distribution(name, None, private_files)
        elif isinstance(action, DistributeCheckout):
            if DEBUG: print '   exists as DistributeCheckout: replace'
            # Ah, it's a generic checkout action - let's replace it with
            # a new build description action
            old_action = action
            action = DistributeBuildDescription(name, old_action.copying_vcs(), # XXX or None?
                                                private_files)
            # And copy over any existing names we don't yet have
            action.merge_names(old_action)
            rule.action = action
        else:
            # Oh dear, it's something unexpected
            raise GiveUp('Found unexpected action %s on build description rule'%action)
    else:
        # No - we need to create one
        if DEBUG: print '   adding anew'
        # We have to guess at 'copy_vcs', but someone later on can override us
        action = DistributeBuildDescription(name, None, private_files)

        rule = Rule(target_label, action)       # to build target_label, run action
        rule.add(source_label)                  # after we've built source_label

        builder.ruleset.add(rule)

    # Sort out the other distribution names
    for name in actual_names[1:]:
        if DEBUG: print '   %s exists: add/override %s'%(action, name)
        action.add_private_files(name, private_files)

def distribute_package(builder, name, label, obj=False, install=True,
                       with_muddle_makefile=True):
    """Request the distribution of the given package.

    - 'name' is the name of the distribution we're adding this checkout to,
      or a "shell pattern" matching existing (already named) distributions.
      In that case::

            *       matches everything
            ?       matches any single character
            [seq]   matches any character in seq
            [!seq]  matches any char not in seq

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

    actual_names = _filter(the_distributions.keys(), name)
    if not actual_names:
        raise GiveUp('There is no distribution matching "%s"'%name)

    packages = builder.expand_wildcards(label)
    if len(packages) == 0:
        raise GiveUp('distribute_package() of %s does not distribute anything'
                     ' (no matching package labels)'%label)

    if DEBUG and len(packages) > 1:
        print '.. => %s'%(', '.join(map(str, packages)))

    for pkg_label in packages:
        source_label = pkg_label.copy_with_tag(LabelTag.PostInstalled)
        target_label = pkg_label.copy_with_tag(LabelTag.Distributed, transient=True)

        if DEBUG: print '   target', target_label

        # Making our target label transient means that its tag will not be
        # written out to the muddle database (i.e., .muddle/tags/...) when
        # the label is built

        # Is there already a rule for distributing this label?
        if builder.target_label_exists(target_label):
            # Yes, so retrieve it, and its action
            rule = builder.ruleset.map[target_label]
            action = rule.action
            if DEBUG: print '   %s exists'%action
            add_index = 0
        else:
            # No - we need to create one
            if DEBUG: print '   adding %s anew'%actual_names[0]
            action = DistributePackage(actual_names[0], obj, install)

            rule = Rule(target_label, action)   # to build target_label, run action
            rule.add(source_label)              # after we've built source_label

            builder.ruleset.add(rule)

            # We've done with the first name
            add_index = 1

        # Add the other distributions to the same action
        for name in actual_names[add_index:]:
            if DEBUG: print '   %s exists: add/set %s'%(action, name)
            action.add_or_set_distribution(name, obj, install)

        if with_muddle_makefile:
            # Our package label gets to have one MakeBuilder action associated
            # with it, which tells us what we want to know. It in turn is
            # "attached" to the various "buildy" tags on our label.
            tmp_label = pkg_label.copy_with_tag(LabelTag.Built)
            rule = builder.ruleset.rule_for_target(tmp_label)
            # Shall we assume it is a MakeBuilder? Let's not
            action = rule.action

            # If this is an aptget action, then there is no Makefile.muddle,
            # and also no install/<role> directory
            if isinstance(rule.action, AptGetBuilder):
                continue

            if not isinstance(action, MakeBuilder):
                raise GiveUp('Tried to get MakeBuilder action'
                             ' for %s, got %s'%(pkg_label, action))

            makefile_name = deduce_makefile_name(action.makefile_name,
                                                 action.per_role_makefiles,
                                                 pkg_label.role)

            make_co = Label(LabelType.Checkout, action.co, domain=pkg_label.domain)

            # And that's the muddle Makefile we want to add
            for name in actual_names:
                distribute_checkout_files(builder, name, make_co, [makefile_name])

def _set_checkout_tags(builder, label, target_dir):
    """Copy checkout muddle tags
    """
    root_path = normalise_dir(builder.db.root_path)
    local_root = find_local_relative_root(builder, label)

    tags_dir = os.path.join('.muddle', 'tags', 'checkout', label.name)
    src_tags_dir = os.path.join(root_path, local_root, tags_dir)
    tgt_tags_dir = os.path.join(target_dir, local_root, tags_dir)
    tgt_tags_dir = os.path.normpath(tgt_tags_dir)
    if DEBUG:
        print '..copying %s'%src_tags_dir
        print '       to %s'%tgt_tags_dir
    copy_without(src_tags_dir, tgt_tags_dir, preserve=True, verbose=VERBOSE)

def _set_package_tags(builder, label, target_dir, which_tags):
    """Copy package tags.

    However, only copy package tags (a) for the particular role, and
    (b) for the tags named in 'which_tags'
    """
    root_path = normalise_dir(builder.db.root_path)
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
    co_src_dir = builder.db.get_checkout_path(label)

    # So we can now copy our source directory, ignoring the VCS directory if
    # necessary. Note that this can create the target directory for us.
    co_src_rel_to_root = builder.db.get_checkout_location(label)
    co_tgt_dir = os.path.join(normalise_dir(target_dir), co_src_rel_to_root)
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
    co_src_dir = builder.db.get_checkout_path(label)

    # If we're not doing copy_vcs, find the VCS special files for this
    # checkout, and them our "without" string
    if copy_vcs:
        without = []
    else:
        repo = builder.db.get_checkout_repo(label)
        vcs_instance = get_vcs_instance(repo.vcs)
        without = vcs_instance.get_vcs_special_files()

    # So we can now copy our source directory, ignoring the VCS files if
    # necessary. Note that this can create the target directory for us.
    co_src_rel_to_root = builder.db.get_checkout_location(label)
    co_tgt_dir = os.path.join(normalise_dir(target_dir), co_src_rel_to_root)
    co_tgt_dir = os.path.normpath(co_tgt_dir)
    if DEBUG:
        print 'Copying checkout:'
        print '  from %s'%co_src_dir
        print '  to   %s'%co_tgt_dir
        if without:
            print '  without %s'%without
    copy_without(co_src_dir, co_tgt_dir, without, preserve=True, verbose=VERBOSE)

    # We mustn't forget to set the appropriate tags in the target .muddle/
    # directory
    _set_checkout_tags(builder, label, target_dir)

def _actually_distribute_normal_build_desc(builder, label, target_dir,
                                           copy_vcs, private_files):
    """Copy the "normal" files for a build description
    """
    # Now, we want to copy everything except:
    #
    #   * no .pyc files
    #   * MAYBE no VCS files, depending
    #   * no private files

    # Get the actual directory of the checkout
    co_src_dir = builder.db.get_checkout_path(label)

    if copy_vcs:
        files_to_ignore = []
    else:
        repo = builder.db.get_checkout_repo(label)
        vcs_instance = get_vcs_instance(repo.vcs)
        files_to_ignore = vcs_instance.get_vcs_special_files()

    co_src_rel_to_root = builder.db.get_checkout_location(label)
    co_tgt_dir = os.path.join(normalise_dir(target_dir), co_src_rel_to_root)
    if DEBUG:
        print 'Copying build description:'
        print '  from %s'%co_src_dir
        print '  to   %s'%co_tgt_dir
        if files_to_ignore:
            print '  without %s'%files_to_ignore
        if private_files:
            print '  private files %s'%private_files

    # Make all the private files (which may be paths within our checkout)
    # be paths relative to the root of the build tree
    new_private_files = set()
    for name in private_files:
        new_private_files.add(os.path.join(co_src_rel_to_root, name))
    private_files = new_private_files

    files_to_ignore = set(files_to_ignore)

    # files_to_ignore may be specified as a filename or as a path
    # private_files, however, must be a specific path relative to our checkout,
    # and is also not a directory.

    # Remember to walk relative to the root of the build tree, so that our
    # 'dirpath' values are also relative to the root of the build tree, and
    # thus are applicable to both source and target...
    with Directory(builder.db.root_path):
        for dirpath, dirnames, filenames in os.walk(co_src_rel_to_root):

            if DEBUG: print '--', dirpath
            for name in filenames:
                if DEBUG: print '--', name
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

                if DEBUG: print '--', src_path
                if DEBUG: print '--', tgt_dir
                if DEBUG: print '--', tgt_path

                if src_path in private_files:
                    if DEBUG: print 'Replacing private file', src_path
                    with open(tgt_path, 'w') as fd:
                        fd.write("def describe_private(builder, *args, **kwargs):\n    pass\n")
                else:
                    copy_file(src_path, tgt_path, preserve=True)

            # Ignore VCS directories, if we were asked to do so
            directories_to_ignore = files_to_ignore.intersection(dirnames)
            for name in directories_to_ignore:
                dirnames.remove(name)

def _actually_distribute_replacement_build_desc(builder, label, target_dir,
                                                replacement_build_desc):
    """Copy the replacement build description for a build description
    """

    # Get the actual directory of the checkout
    co_src_dir = builder.db.get_checkout_path(label)

    src_desc_file = os.path.join(co_src_dir, replacement_build_desc)

    # Now to work out the name of the target build description file
    # Remember to use the checkout directory path relative to the root of tree
    outer_path = builder.db.get_checkout_location(label)

    inner_path = _build_desc_inner_path(builder, label)

    # So
    tgt_desc_file = os.path.join(target_dir, outer_path, inner_path)

    # And let's make sure it exists
    tgt_desc_dir = os.path.split(tgt_desc_file)[0]
    if not os.path.exists(tgt_desc_dir):
        os.makedirs(tgt_desc_dir)

    copy_file(src_desc_file, tgt_desc_file, preserve=True)


def _actually_distribute_build_desc(builder, label, target_dir, copy_vcs,
                                    private_files, replacement_build_desc):
    """Very similar to what we do for any other checkout, but with more arguments
    """
    if replacement_build_desc:
        _actually_distribute_replacement_build_desc(builder, label, target_dir,
                                                    replacement_build_desc)
    else:
        _actually_distribute_normal_build_desc(builder, label, target_dir,
                                               copy_vcs, private_files)

    # Set the appropriate tags in the target .muddle/ directory
    _set_checkout_tags(builder, label, target_dir)

def _actually_distribute_instructions(builder, label, target_dir):
    """Copy over any instruction files for this label

    Instruction files are called:

        .muddle/instructions/<package-name>/_default,xml
        .muddle/instructions/<package-name>/<role>,xml
    """
    root_path = normalise_dir(builder.db.root_path)
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
    obj_dir = builder.package_obj_path(label)

    # We can then copy it over. copy_without will create the target
    # directory for us, if necessary
    root_path = normalise_dir(builder.db.root_path)
    rel_obj_dir = os.path.relpath(normalise_dir(obj_dir), root_path)
    tgt_obj_dir = os.path.join(target_dir, rel_obj_dir)
    tgt_obj_dir = normalise_dir(tgt_obj_dir)

    if DEBUG:
        print 'Copying binaries:'
        print '    from %s'%obj_dir
        print '    to   %s'%tgt_obj_dir

    copy_without(obj_dir, tgt_obj_dir, preserve=True, verbose=VERBOSE)

    # We mustn't forget to set the appropriate package tags
    _set_package_tags(builder, label, target_dir,
                      ('preconfig', 'configured', 'built'))

    # In order to stop muddle wanting to rebuild the sources on which this
    # package depends, we also need to set the tags for the checkouts it
    # depends on
    checkouts = builder.checkouts_for_package(label)
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
    install_dir = builder.package_install_path(label)

    # For some packages, there is no installation directory.
    # The obvious example is something like::
    #
    #    aptget.medium(builder, "aptget-pkg", "aptget-role", [...], [...])
    #
    # which does not actually create the directory install/aptget-role/aptget-pkg
    if os.path.exists(install_dir):
        root_path = normalise_dir(builder.db.root_path)
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
            copy_without(install_dir, tgt_install_dir, preserve=True, verbose=VERBOSE)

    # Set the appropriate package tags
    _set_package_tags(builder, label, target_dir,
                      ('preconfig', 'configured', 'built', 'installed', 'postinstalled'))

    # In order to stop muddle wanting to rebuild the sources on which this
    # package depends, we also need to set the tags for the checkouts it
    # depends on
    checkouts = builder.checkouts_for_package(label)
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

    def add_distribution(self, name, copy_vcs=None, private_files=None):
        """Add a new named distribution.

        It is an error if there is already a distribution of this name.
        """
        if name in self.distributions:
            raise GiveUp('Distribution "%s" is already present in %s'%(name,
                self.__class__.__name__))

        self.distributions[name] = (copy_vcs, private_files)

    def get_distribution(self, name):
        """Return the data for distribution 'name', or raise MuddleBug
        """
        try:
            return self.distributions[name]
        except KeyError:
            raise MuddleBug('Action %s does not have data for distribution "%s"'%(
                self.__class__.__name__, name))

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

        If 'just' is None, then we wish to distribute all the source files
        in the checkout (apart from VCS files, for which see 'copy_vcs').

        If 'just' is not None, then it must be a sequence of source paths,
        relative to the checkout directory, which are the specific files
        to be distributed for this checkout.

        Note that we distinguish between 'just=None' and 'just=[]': the former
        instructs us to distribute all source files, the latter instructs us to
        distribute no source files.
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

    def add_distribution(self, name, copy_vcs=None, just=None):
        """Add a new named distribution.

        The arguments are interpreted as when creating an instance.

        It is an error if there is already a distribution of this name.
        """
        if name in self.distributions:
            raise GiveUp('Distribution "%s" is already present in %s'%(name,
                self.__class__.__name__))

        if just is not None:
            just = set(just)

        self.distributions[name] = (copy_vcs, just)

    def override(self, name, copy_vcs=None, just=None):
        """Override the definition of an existing named distribution.
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

        self.distributions[name] = (copy_vcs, just)

    def request_all_source_files(self, name):
        """Request that distribution 'name' distribute all source files.

        This is a tidy way of undoing any selection of specific files.
        """
        copy_vcs, just = self.get_distribution(name)

        if just is None:
            # Nothing to do, we're already copying all files
            return

        self.distributions[name] = (copy_vcs, None)

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

    def set_copy_vcs(self, name, copy_vcs):
        """Change the value of copy_vcs for distribution 'name'.
        """
        old_copy_vcs, just = self.get_distribution(name)
        self.distributions[name] = (copy_vcs, just)

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

    def __init__(self, name, copy_vcs=None, private_files=None, replacement_build_desc=None):
        """
        'name' is the name of a DistributionContext. When created, we are
        told which DistributionContext we can be distributed by. Later on,
        other names may be added...

        If 'copy_vcs' is False, then don't copy any VCS "special" files
        (['.git', '.gitignore', ...] or ['.bzr'], etc., depending on the VCS
        used for this checkout).

        If 'copy_vcs' is True, then always copy such files.

        If 'copy_vcs' is None, then do whatever "muddle distribute" indicates.

        .. note:: *Note that copy_vcs may only distinguish true and false for
                  the moment, so None may be equivalvent to False.*

        If 'private_files' is given, it is a sequence of Python files, relative
        to the build description checkout directory, that must be replaced by
        empty files when the distribution is done. It is always copied (as a
        set). If it is None, then an empty set will be used.

        If 'replacement_build_desc' is given, then it is a file (relative to
        the checkout directory) to be used instead of all the rest of the
        content of the build description checkout. It will be named using the
        appropriate name (as in ``.muddle/Description``) when it is
        distributed. If a replacement build description is named, then
        'copy_vcs' will be ignored, and no VCS will be copied. Similarly,
        'private_files' will be ignored.
        """
        if private_files is None:
            private_files = set()
        else:
            private_files = set(private_files)

        data = (copy_vcs, private_files, replacement_build_desc)

        super(DistributeBuildDescription, self).__init__(name, data)

    def __str__(self):
        parts = []
        for key, (copy_vcs, private_files, replacement_build_desc) in self.distributions.items():
            inner = []
            if copy_vcs:
                inner.append('vcs')
            if replacement_build_desc:
                inner.append('_')
            elif private_files:
                inner.append('-%d'%len(private_files))
            else:
                inner.append('*')
            parts.append('%s[%s]'%(key, ','.join(inner)))
        return '%s: %s'%(self.__class__.__name__, ', '.join(sorted(parts)))

    def add_distribution(self, name, copy_vcs=None, private_files=None, replacement_build_desc=None):
        """Add a new named distribution.

        It is an error if there is already a distribution of this name.
        """
        if name in self.distributions:
            raise GiveUp('Distribution "%s" is already present in %s'%(name,
                self.__class__.__name__))

        if private_files is None:
            private_files = set()
        else:
            private_files = set(private_files)

        self.distributions[name] = (copy_vcs, private_files, replacement_build_desc)

    def add_private_files(self, name, private_files):
        """Add some specific private files to distribution 'name'.

        Distribution 'name' must already be present on this action.

        Does nothing if the files are already added
        """
        copy_vcs, local_private_files = self.get_distribution(name)

        if private_files:
            # We know this is already a set
            local_private_files.update(private_files)

        self.distributions[name] = (copy_vcs, local_private_files)

    def copying_vcs(self, name):
        """Are we distributing the VCS directory?
        """
        copy_vcs, private_files = self.get_distribution(name)
        return copy_vcs

    def set_copy_vcs(self, name, copy_vcs):
        """Change the value of copy_vcs for distribution 'name'.
        """
        old_copy_vcs, private_files, replacement_build_desc = self.get_distribution(name)
        self.distributions[name] = (copy_vcs, private_files, replacement_build_desc)

    def set_replacement_build_desc(self, name, replacement_build_desc):
        """Change the value of replacement_build_desc for distribution 'name'.

        Note that 'None' is a perfectly sensible value.
        """
        copy_vcs, private_files, old_replacement_build_desc = self.get_distribution(name)
        self.distributions[name] = (copy_vcs, private_files, replacement_build_desc)

    def build_label(self, builder, label):
        name, target_dir = builder.get_distribution()

        copy_vcs, private_files, replacement_build_desc = self.distributions[name]

        if DEBUG:
            print 'DistributeBuildDescription %s (%s VCS) to %s'%(label,
                    'without' if copy_vcs else 'with', target_dir)

        _actually_distribute_build_desc(builder, label, target_dir, copy_vcs,
                                        private_files, replacement_build_desc)

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

    def add_distribution(self, name, obj=True, install=True):
        """Add a new named distribution.

        It is an error if there is already a distribution of this name.
        """
        if name in self.distributions:
            raise GiveUp('Distribution "%s" is already present in %s'%(name,
                self.__class__.__name__))

        self.distributions[name] = (obj, install)

    def add_or_set_distribution(self, name, obj=True, install=True):
        """Add a distribution if it's not there, or replace it if it is.
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

def _domain_from_parts(parts):
    """Construct a domain name from a list of parts.
    """
    num_parts = len(parts)
    domain = '('.join(parts) + ')'*(num_parts-1)
    return domain

def _build_desc_label_in_domain(builder, domain, label_tag):
    """Return the label for the build description checkout in this domain.
    """
    co_label = builder.db.get_domain_build_desc_label(domain)
    if co_label.tag == label_tag:
        return co_label
    else:
        return co_label.copy_with_tag(label_tag)

def _build_desc_inner_path(builder, label):
    """Given a build description checkout's label, return its inner path.

    So, if checkout:builds/* relates to directory src/builds and the build
    description within that is main/01.py, then we return main/01.py
    """
    domain = label.domain
    if domain:
        root_repo, build_desc = builder.db.get_subdomain_info(domain)
    else:
        build_desc = builder.db.Description_pathfile.get()

    co_name, inner_path = build_co_and_path_from_str(build_desc)
    return inner_path

def _add_build_descriptions(builder, name, domains, copy_vcs=False):
    """Add all the implicated build description checkouts to our distribution.
    """
    # We need a build description for each domain we had a label for
    # (and possibly also any "in between" domains that weren't mentioned
    # explicitly?)

    extra_labels = []

    cumulative_domains = set()
    for domain in sort_domains(domains):
        if domain is None or domain == '':
            cumulative_domains.add('')
        else:
            parts = Label.split_domain(domain)
            for ii in range(1, 1+len(parts)):
                d = _domain_from_parts(parts[:ii])
                cumulative_domains.add(d)

    if DEBUG: print 'Adding build descriptions'
    for domain in sort_domains(cumulative_domains):
        co_label = _build_desc_label_in_domain(builder, domain, LabelTag.Distributed)
        if DEBUG: print '-- Build description', co_label
        distribute_build_desc(builder, name, co_label, copy_vcs)
        extra_labels.append(co_label)
    if DEBUG: print 'Done'

    return extra_labels

def _maybe_add_license_file(builder, name, label, distribution_labels):
    """Check if label requires us to include a license file.

    If it does, we:

        1. Add a request to distribute the appropriate license file in the
           appropriate checkout
        2. Add the checkout to the list of labels to be distributed

    (Note that if 'label' is a package label, we look at each checkout that
    it directly requires)
    """
    if label.type == LabelType.Checkout:
        checkouts = [label]
    elif label.type == LabelType.Package:
        checkouts = builder.checkouts_for_package(label)
    else:
        raise MuddleBug('Expected a checkout or package label, not %s'%label)

    get_checkout_license_file = builder.db.get_checkout_license_file
    for co_label in checkouts:
        license_file = get_checkout_license_file(co_label, absent_is_None=True)
        if license_file:
            target = co_label.copy_with_tag(LabelTag.Distributed)
            distribute_checkout_files(builder, name, target, [license_file])
            distribution_labels.add(target)

def _copy_muddle_skeleton(builder, name, target_dir, domains):
    """Copy the "top files" for each necessary .muddle directory
    """

    src_root = builder.db.root_path
    tgt_root = target_dir

    for domain in sort_domains(domains):
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

def _copy_versions_dir(builder, name, target_dir, copy_vcs=False):
    """Copy the stamp versions directory
    """

    src_root = builder.db.root_path
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
        versions_repo_url = builder.db.VersionsRepository_pathfile.get()
        without = vcs_special_files(versions_repo_url)

    if DEBUG:
        print 'Copying versions/ directory:'
        print '  from %s'%src_dir
        print '  to   %s'%tgt_dir
        if without:
            print '  without %s'%without

    copy_without(src_dir, tgt_dir, without, preserve=True, verbose=VERBOSE)

def _find_open_deps_for_gpl(builder, label):
    """Return any open checkouts this GPL checkout depends on

    (or, rather, that its packages depend on).

    This is really rather inefficient, though...

    Returns a set of the open-source checkouts we depend on, and a list
    of warning messages (which we hope is empty)
    """
    deps = set()
    warnings = set()
    label = label.copy_with_tag(LabelTag.CheckedOut)

    # Find the package(s) that depende on this checkout
    package_labels = builder.packages_using_checkout(label)
    our_packages = set()

    # Typically we get the same package with different tags - turn them
    # all into the "final" tag for packages, to find the most dependencies
    for pkg in package_labels:
        pkg = pkg.copy_with_tag(LabelTag.PostInstalled)
        our_packages.add(pkg)

    def add_label(lbl, pkg):
        license = get_license(builder, lbl)
        if license is None or license.is_open():
            deps.add(lbl)
        else:
            warnings.add((lbl, pkg))

    # Check what each package depends on
    for pkg in our_packages:
        rules_to_build = needed_to_build(builder.ruleset, pkg)
        for rule in rules_to_build:
            lbl = rule.target
            if lbl.type == LabelType.Checkout:
                if lbl.match_without_tag(label):
                    continue
                else:
                    add_label(lbl, pkg)
            elif lbl.type == LabelType.Package:
                # Find out what checkouts that package comes from
                checkouts = builder.checkouts_for_package(label)
                for co in checkouts:
                    add_label(co, pkg)

    warning_messages = []
    if warnings:
        for lbl, pkg in warnings:
            msg = '* %s\n' \
                  '  - is used by %s\n' \
                  '  - which depends on %s\n' \
                  '  - which is "%s"'%(label, pkg, lbl, get_license(builder, lbl))
            warning_messages.append(msg)
    return deps, warning_messages


def select_all_gpl_checkouts(builder, name, with_vcs, just_from=None):
    """Select all checkouts with some sort of "gpl" license for distribution

    (or any checkout that has had "gpl"-ness propagated to it)

    (or any checkout that one of those depends on)

    'name' is the name of our distribution.

    'with_vcs' is true if we want VCS "special" files in our distributed
    checkouts.

    If 'just_from' is given, then we'll only consider the labels therein.
    """
    gpl_checkouts = get_gpl_checkouts(builder)
    imp_checkouts, because = get_implicit_gpl_checkouts(builder)

    # Don't forget any (open) checkouts the GPL checkouts depend on
    # (if they depend on any non-open checkouts, they're out of luck)
    dependencies = set()
    warning_messages = []
    for co in sorted(gpl_checkouts):
        deps, warnings = _find_open_deps_for_gpl(builder, co)
        dependencies |= deps
        warning_messages.extend(warnings)

    if warning_messages:
        print
        print 'WARNING: SOME GPL CHECKOUTS SEEM TO DEPEND ON NON-OPEN SOURCE CHECKOUTS'
        for msg in warning_messages:
            print msg
        print 'The non-open source checkouts will not be distributed.'
        print 'END OF WARNING'
        print

    all_checkouts = gpl_checkouts | imp_checkouts | dependencies
    if just_from:
        all_checkouts = all_checkouts.intersection(just_from)
    for label in all_checkouts:
        distribute_checkout(builder, name, label, copy_vcs=with_vcs)

def select_all_open_checkouts(builder, name, with_vcs, just_from=None):
    """Select all checkouts with an "open" license for distribution.

    This includes all "gpl" checkouts, and all checkouts made implicitly "gpl".

    'name' is the name of our distribution.

    'with_vcs' is true if we want VCS "special" files in our distributed
    checkouts.

    If 'just_from' is given, then we'll only consider the labels therein.
    """
    open_checkouts = get_open_checkouts(builder)
    imp_checkouts, because = get_implicit_gpl_checkouts(builder)
    all_checkouts = open_checkouts | imp_checkouts
    if just_from:
        all_checkouts = all_checkouts.intersection(just_from)
    for label in all_checkouts:
        distribute_checkout(builder, name, label, copy_vcs=with_vcs)

def select_all_prop_source_checkouts(builder, name, with_vcs, just_from=None):
    """Select all checkouts with a "prop-source" license for distribution.

    'name' is the name of our distribution.

    'with_vcs' is true if we want VCS "special" files in our distributed
    checkouts.

    If 'just_from' is given, then we'll only consider the labels therein.
    """
    prop_checkouts = get_prop_source_checkouts(builder)
    if just_from:
        prop_checkouts = prop_checkouts.intersection(just_from)
    for co_label in prop_checkouts:
        distribute_checkout(builder, name, co_label, copy_vcs=with_vcs)

def select_all_binary_nonprivate_packages(builder, name, with_muddle_makefile, just_from=None):
    """Select all packages with a "binary" license for distribution.

    'name' is the name of our distribution, for error reporting.

    If 'with_muddle_makefile' is true, then we'll make an attempt to add
    distribution information for each package's muddle Makefile (in the
    appropriate checkout)

    We do *not* want "private" packages, and as such this function checks to
    see if any "private" packages may be present in the install/ directories
    that we are proposing to distribute.

    If 'just_from' is given, then we'll only consider the (package) labels therein.
    """
    # Find all our "binary" checkouts
    binary_checkouts = get_binary_checkouts(builder)
    # Find all their packages
    binary_packages = set()
    for co_label in binary_checkouts:
        # Get the package(s) directly using this checkout
        package_labels = builder.packages_using_checkout(co_label)
        for label in package_labels:
            binary_packages.add(label.copy_with_tag('*'))
    if just_from:
        binary_packages = binary_packages.intersection(just_from)
    # Ask for them to be distributed, and also work out which roles we're using
    for pkg_label in binary_packages:
        distribute_package(builder, name, pkg_label, obj=False, install=True,
                           with_muddle_makefile=with_muddle_makefile)

def distribute(builder, name, target_dir, with_versions_dir=False,
               with_vcs=False, no_muddle_makefile=False, no_op=False,
               package_labels=None, checkout_labels=None):
    """Distribute using distribution context 'name', to 'target_dir'.

    The DistributeContext called 'name' must exist.

    All distributions described in that DistributeContext will be made.

    'name' is the name of the distribution to, erm, distribute. The special
    names:

      * _source_release (all checkout source directories)
      * _binary_release (all install directories, maybe plus extras)
      * _for_gpl (just GPL and GPL-propagated source directories)
      * _all_open (all open licensed source directories)
      * _by_license (source or install directories by license, nothing private)

    are always recognised. See the code or "muddle help distribute" for a more
    complete description of these.

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

    If 'package_labels' and/or 'checkout_labels' is not None, then the labels
    selected for distribution will be "filtered" through those sequences, and
    only labels that occur in one or the other will be added to the
    distribution. Note that this filtering is done before adding in build
    descriptions. Passing them both as empty sets is likely to give a very
    small distribution...

    NB: We assume that each package label in 'package_labels' has had the
    checkouts it directly depends upon added to 'checkout_labels' by the
    caller. Also, all labels must have their tag as '*'.
    """

    if name not in the_distributions.keys():
        raise GiveUp('There is no distribution called "%s"'%name)

    print 'Writing distribution', name, 'to', target_dir

    # =========================================================================
    # PREPARE
    # =========================================================================
    distribution_labels = set()
    domains = set()

    target_label_exists = builder.target_label_exists

    check_for_gpl_clashes = False
    check_for_binary_nonprivate_clashes = False

    if checkout_labels is None:
        # We get all the "reasonable" checkout labels
        all_checkouts = builder.all_checkout_labels(LabelTag.CheckedOut)
    else:
        all_checkouts = checkout_labels

    if package_labels is None:
        # We get all the "reasonable" package labels
        all_packages = builder.all_package_labels()
    else:
        all_packages = package_labels

    # -------------------------------------------------------------------------
    # Standard names
    # -------------------------------------------------------------------------
    # For standard distributions, we set up our own idea of which labels
    # should be distributed. This is no different than what the user might do
    # in their build description, except we do it later, and thus may override
    # things the user already did. Note that this means the user can add
    # particular files (for instance) to a checkout that would otherwise be
    # distributed (e.g., adding standard Makefiles).
    #
    # For distributions that do not distribute any package: labels, we unset
    # all_packages, but otherwise we do our job by manipulating the dependency
    # tree.
    if name == '_source_release':
        # A source release is all the source directories alone, but with no VCS
        # This ignores licenses
        for label in all_checkouts:
            distribute_checkout(builder, name, label, copy_vcs=with_vcs)
        # No packages at all
        all_packages = set()
    elif name == '_binary_release':
        # A binary release is the install directories for all packages,
        # plus muddle Makefiles and any other "selected" source files
        # This ignores licenses
        # XXX If there are things marked "private" in what we're distributing,
        # XXX should we (a) mention it, or (b) refuse to continue without '-f',
        # XXX or (c) just ignore it, as we're doing now?
        for label in all_packages:
            distribute_package(builder, name, label, obj=False, install=True,
                               with_muddle_makefile=(not no_muddle_makefile))
    elif name == '_for_gpl':
        check_for_gpl_clashes = True
        # All GPL licensed checkouts, and anything that that has propagated to
        select_all_gpl_checkouts(builder, name, with_vcs, just_from=checkout_labels)
        # No packages at all
        all_packages = set()
    elif name == '_all_open':
        check_for_gpl_clashes = True
        # All open source checkouts, including anything in _for_gpl
        select_all_open_checkouts(builder, name, with_vcs, just_from=checkout_labels)
        # No packages at all
        all_packages = set()
    elif name == '_by_license':
        check_for_gpl_clashes = True
        check_for_binary_nonprivate_clashes = True
        # All checkouts in _all_open, and any install/ directories for anything
        # with a "binary" license. Nothing at all for "private" licenses.
        select_all_open_checkouts(builder, name, with_vcs, just_from=checkout_labels)
        # All proprietary source checkouts
        select_all_prop_source_checkouts(builder, name, with_vcs, just_from=checkout_labels)
        # Note we always output muddle Makefiles with this distribution
        select_all_binary_nonprivate_packages(builder, name, with_muddle_makefile=True,
                                              just_from=package_labels)

    # -------------------------------------------------------------------------
    # Rescan
    # -------------------------------------------------------------------------
    # *All* distributions then scan through the labels looking to see what
    # needs distributing. This is a little bit inefficient for those
    # distributions which actually already KNEW all the labels they wanted
    # (e.g., _source_release), but it's still simpler to just do this in
    # all cases.

    combined_labels = set(all_checkouts.union(all_packages))
    for label in sorted(combined_labels):
        target = label.copy_with_tag(LabelTag.Distributed)
        # Is there a distribution target for this label?
        if target_label_exists(target):
            # If so, is it distributable with this distribution name?
            rule = builder.ruleset.rule_for_target(target)
            if rule.action.does_distribution(name):
                # Yes, we like this label
                distribution_labels.add(target)
                # And remember its domain, so we can find the build description
                domains.add(target.domain)

                # And are there any license files we need to tack on?
                _maybe_add_license_file(builder, name, target, distribution_labels)

    if not distribution_labels:
        print 'Nothing to distribute for %s'%name
        return

    # -------------------------------------------------------------------------
    # Filter
    # -------------------------------------------------------------------------
    if package_labels or checkout_labels:
        filter_labels = set()
        wanted_labels = set()
        for label in package_labels:
            if label.type == LabelTag.Distributed:
                filter_labels.add(label)
            else:
                filter_labels.add(label.copy_with_tag(LabelTag.Distributed))
        for label in checkout_labels:
            if label.type == LabelTag.Distributed:
                filter_labels.add(label)
            else:
                filter_labels.add(label.copy_with_tag(LabelTag.Distributed))
        for label in distribution_labels:
            if label in filter_labels:
                wanted_labels.add(label)
        distribution_labels = wanted_labels

    # -------------------------------------------------------------------------
    # Check for clashes
    # -------------------------------------------------------------------------
    if check_for_gpl_clashes:
        #print 'CHECK FOR GPL CLASHES'
        if report_license_clashes(builder, just_for=distribution_labels):
            raise GiveUp('License clashes prevent "%s" distribution'%name)

    if check_for_binary_nonprivate_clashes:
        #print 'CHECK FOR BINARY/PRIVATE CLASHES'
        roles = set()
        for label in distribution_labels:
            if label.type == LabelType.Package:
                roles.add(label.role)
        # Check if there is a binary/private clash in any of those roles
        role_clash = False
        for role in roles:
            problem = report_license_clashes_in_role(builder, role, just_report_private=True)
            if problem:
                role_clash = True
                print 'which means there will probably be private binaries in install/%s'%role
                print
        if role_clash:
            raise GiveUp('License clashes prevent "%s" distribution'%name)

    # -------------------------------------------------------------------------
    # Add in the appropriate build descriptions
    # -------------------------------------------------------------------------
    # We need to do this after everyone else has had a chance to set rules
    # on /distribute labels, so we can override any DistributeCheckout actions
    # that were mistakenly placed on our build descriptions...
    extra_labels = _add_build_descriptions(builder, name, domains, with_vcs)

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
            rule = builder.ruleset.map[label]
            print '%-*s %s'%(maxlen, label, rule.action)
        return

    # =========================================================================
    # DISTRIBUTE
    # =========================================================================
    # Remember to say where we're copying to...
    builder.set_distribution(name, target_dir)

    # Copy over the skeleton of the required .muddle directories
    _copy_muddle_skeleton(builder, name, target_dir, domains)

    if with_versions_dir:
        # Copy over the versions directory, if any
        _copy_versions_dir(builder, name, target_dir, with_vcs)

    print 'Building %d /distribute label%s'%(num_labels,
            '' if num_labels==1 else 's')
    for label in distribution_labels:
        builder.build_label(label)
