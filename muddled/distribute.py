"""
Actions and mechanisms relating to distributing build trees
"""

import os

from muddled.depend import Action, Rule, Label
from muddled.utils import GiveUp, MuddleBug, LabelTag, LabelType, \
        copy_without, normalise_dir, find_local_relative_root, package_tags, \
        copy_file, domain_subpath
from muddled.version_control import get_vcs_handler
from muddled.mechanics import build_co_and_path_from_str

def distribute_checkout(builder, name, label, copy_vcs_dir=False):
    """Request the distribution of the given checkout.

    - 'name' is the name of this distribution
    - 'label' must be a checkout label, but the tag is not important.

    By default, we don't copy any VCS directory.

    Notes:

        1. If we already described a distribution called 'name' for 'label',
           then this will silently overwrite it.
    """
    if label.type != LabelType.Checkout:
        raise MuddleBug('Attempt to use non-checkout label %s for a distribute checkout rule'%label)

    source_label = label.copy_with_tag(LabelTag.CheckedOut)
    target_label = label.copy_with_tag(LabelTag.Distributed, transient=True)

    # Making our target label transient means that its tag will not be
    # written out to the muddle database (i.e., .muddle/tags/...) when
    # the label is built

    # Is there already a rule for distributing this label?
    if builder.invocation.target_label_exists(target_label):
        # Yes - add this distribution to it (if it's not there already)
        action = builder.invocation.ruleset.map[target_label]
        action.add_distribution(name, copy_vcs_dir)
    else:
        # No - we need to create one
        action = DistributeCheckout(name, copy_vcs_dir)

        rule = Rule(target_label, action)       # to build target_label, run action
        rule.add(source_label)                  # after we've built source_label

        builder.invocation.ruleset.add(rule)

def distribute_build_desc(builder, name, label, copy_vcs_dir=False):
    """Request the distribution of the given build description checkout.

    - 'name' is the name of this distribution
    - 'label' must be a checkout label, but the tag is not important.

    By default, we don't copy any VCS directory.

    Notes:

        1. If we already described a distribution called 'name' for 'label',
           then this will silently overwrite it.
    """
    if label.type != LabelType.Checkout:
        raise MuddleBug('Attempt to use non-checkout label %s for a distribute checkout rule'%label)

    source_label = label.copy_with_tag(LabelTag.CheckedOut)
    target_label = label.copy_with_tag(LabelTag.Distributed, transient=True)

    # Making our target label transient means that its tag will not be
    # written out to the muddle database (i.e., .muddle/tags/...) when
    # the label is built

    # Is there already a rule for distributing this label?
    if builder.invocation.target_label_exists(target_label):
        # Yes - add this distribution to it (if it's not there already)
        action = builder.invocation.ruleset.map[target_label]
        action.add_distribution(name, copy_vcs_dir)
    else:
        # No - we need to create one
        action = DistributeBuildDescription(name, copy_vcs_dir)

        rule = Rule(target_label, action)       # to build target_label, run action
        rule.add(source_label)                  # after we've built source_label

        builder.invocation.ruleset.add(rule)

def distribute_package(builder, name, label, binary=True, source=False, copy_vcs_dir=False):
    """Request the distribution of the given package.

    - 'context' is a DistributeContext instance, naming the builder and the
      target directory
    - 'label' must be a package label, but the tag is not important.

    - If 'binary' is true, then a binary distribution will be performed.
      This means that obj/ and install/ directories (and the associated
      muddle tags) will be copied.

    - If 'source' is true, then a source distribution will be performed.
      This means that the source directories (within src/) for the checkouts
      directly used by the package will be copied, along with the
      associated muddle tags. If 'source' is true and 'copy_vcs_dir' is
      true, then the VCS directories for those source checkouts will also
      be copied, otherwise they will not.

    Notes:

        1. We don't forbid having both 'binary' and 'source' true,
           but this may change in the future.
        2. If the package directly uses more than one checkout, then
           'copy_vcs_dir' applies to all of them. It is not possible
           to give different values for different checkouts.
        3. You can determine which checkouts 'source' distribution will
           use with "muddle -n import <package_label>" (or "muddle -n"
           with the package label for any "checkout" command).
        4. If we already described a distribution called 'name' for 'label',
           then this will silently overwrite it.
    """
    if label.type != LabelType.Package:
        raise MuddleBug('Attempt to use non-package label %s for a distribute package rule'%label)

    source_label = label.copy_with_tag(LabelTag.PostInstalled)
    target_label = label.copy_with_tag(LabelTag.Distributed, transient=True)

    # Making our target label transient means that its tag will not be
    # written out to the muddle database (i.e., .muddle/tags/...) when
    # the label is built

    # Is there already a rule for distributing this label?
    if builder.invocation.target_label_exists(target_label):
        # Yes - add this distribution name to it (if it's not there already)
        action = builder.invocation.ruleset.map[target_label]
        action.add_context_name(name)
    else:
        # No - we need to create one
        action = DistributePackage(name)

        rule = Rule(target_label, action)       # to build target_label, run action
        rule.add(source_label)                  # after we've built source_label

        builder.invocation.ruleset.add(rule)

def _set_checkout_tags(builder, label, target_dir):
    """Copy checkout muddle tags
    """
    root_path = normalise_dir(builder.invocation.db.root_path)
    tags_dir = os.path.join('.muddle', 'tags', 'checkout', label.name)
    local_root = find_local_relative_root(builder, label)
    src_tags_dir = os.path.join(root_path, local_root, tags_dir)
    tgt_tags_dir = os.path.join(target_dir, local_root, tags_dir)
    print '..copying %s'%src_tags_dir
    print '       to %s'%tgt_tags_dir
    copy_without(src_tags_dir, tgt_tags_dir, preserve=True)

def _actually_distribute_checkout(builder, label, target_dir, copy_vcs_dir):
    """As it says.
    """
    # 1. We know the target directory. Note it may not exist yet
    # 2. Get the actual directory of the checkout
    co_src_dir = builder.invocation.db.get_checkout_location(label)
    # 3. If we're not doing copy_vcs_dir, find the VCS for this
    #    checkout, and from that determine its VCS dir, and make
    #    that our "without" string
    without = []
    if not copy_vcs_dir:
        repo = builder.invocation.db.get_checkout_repo(label)
        vcs_handler = get_vcs_handler(repo.vcs)
        vcs_dir = vcs_handler.get_vcs_dirname()
        if vcs_dir:
            without.append(vcs_dir)
    # 4. Do a copywithout to do the actual copy, suitably ignoring
    #    the VCS directory if necessary.
    co_tgt_dir = os.path.join(normalise_dir(target_dir), co_src_dir)
    print 'Copying:'
    print '  from %s'%co_src_dir
    print '  to   %s'%co_tgt_dir
    if not copy_vcs_dir:
        print '  without %s'%vcs_dir
    copy_without(co_src_dir, co_tgt_dir, without, preserve=True)
    # 5. Set the appropriate tags in the target .muddle/ directory
    _set_checkout_tags(builder, label, target_dir)

def _actually_distribute_build_desc(builder, label, target_dir, copy_vcs_dir):
    """Very similar to what we do for any other checkout...
    """
    # Get the actual directory of the checkout
    co_src_dir = builder.invocation.db.get_checkout_location(label)

    # Now, we want to copy everything except:
    #
    #   * no .pyc files
    #   * MAYBE no VCS file, depending

    vcs_dir = None
    if not copy_vcs_dir:
        repo = builder.invocation.db.get_checkout_repo(label)
        vcs_handler = get_vcs_handler(repo.vcs)
        vcs_dir = vcs_handler.get_vcs_dirname()

    co_tgt_dir = os.path.join(normalise_dir(target_dir), co_src_dir)
    print 'Copying:'
    print '  from %s'%co_src_dir
    print '  to   %s'%co_tgt_dir
    if vcs_dir:
        print '  without %s'%vcs_dir

    for dirpath, dirnames, filenames in os.walk(co_src_dir):

        # Where are we inside the checkout?
        # Beware, inner_path may be something like './01.py'
        inner_path = os.path.relpath(co_src_dir, dirpath)
        inner_path = os.path.normpath(inner_path)   # there, better

        for name in filenames:
            base, ext = os.path.splitext(name)
            if ext == '.pyc':                       # Ignore .pyc files
                continue
            src_path = os.path.join(dirpath, name)
            tgt_dir = os.path.join(co_tgt_dir, inner_path)
            tgt_path = os.path.join(tgt_dir, name)
            if not os.path.exists(tgt_dir):
                os.makedirs(tgt_dir)
            copy_file(src_path, tgt_path, preserve=True)

        # Ignore VCS directories, if we were asked to do so
        if vcs_dir and vcs_dir in dirnames:
            dirnames.remove(vcs_dir)

    # Set the appropriate tags in the target .muddle/ directory
    _set_checkout_tags(builder, label, target_dir)

def _actually_distribute_binary(builder, label, target_dir):
    """Do a binary distribution of our package.
    """
    # 1. We know the target directory. Note it may not exist yet
    # 2. Get the actual directory of the package obj/ and install/
    #    directories. Luckily, we know we should always have a role
    #    (since the build mechanism works on "real" labels), so
    #    for the obj/ path we will get obj/<name>/<role>/
    #
    obj_dir = builder.invocation.package_obj_path(label)
    #
    #    and for the install/ path, we shall get install/<role>.
    #    This last means that multiple packages will copy to the
    #    same directory, so it's worth checking that we don't do
    #    that.
    #
    install_dir = builder.invocation.package_install_path(label)
    #
    # 3. Use copywithout to copy the obj/ and install/ directories over

    root_path = normalise_dir(builder.invocation.db.root_path)
    rel_obj_dir = os.path.relpath(normalise_dir(obj_dir), root_path)
    rel_install_dir = os.path.relpath(normalise_dir(install_dir), root_path)

    tgt_obj_dir = os.path.join(target_dir, rel_obj_dir)
    tgt_install_dir = os.path.join(target_dir, rel_install_dir)

    tgt_obj_dir = normalise_dir(tgt_obj_dir)
    tgt_install_dir = normalise_dir(tgt_install_dir)

    print 'Copying:'
    print '    from %s'%obj_dir
    print '    to   %s'%tgt_obj_dir

    copy_without(obj_dir, tgt_obj_dir, preserve=True)

    if not os.path.exists(tgt_install_dir):
        print 'and from %s'%install_dir
        print '      to %s'%tgt_install_dir
        copy_without(install_dir, tgt_install_dir, preserve=True)

    # 4. Set the appropriate tags in the target .muddle/ directory
    tags_dir = os.path.join('.muddle', 'tags', 'package', label.name)
    local_root = find_local_relative_root(builder, label)
    src_tags_dir = os.path.join(root_path, local_root, tags_dir)
    tgt_tags_dir = os.path.join(target_dir, local_root, tags_dir)
    print '..copying %s'%src_tags_dir
    print '       to %s'%tgt_tags_dir

    #    We only want to copy tags for this particular role...
    if not os.path.exists(tgt_tags_dir):
        os.makedirs(tgt_tags_dir)
    for tag in package_tags.values():
        tag_filename = '%s-%s'%(label.role, tag)
        tag_file = os.path.join(src_tags_dir, tag_filename)
        if os.path.exists(tag_file):
            copy_file(tag_file, os.path.join(tgt_tags_dir, tag_filename),
                      preserve=True)

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

    def add_distribution(self, name, data):
        """Add another distribution to this action.
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

    def build_label(self, builder, label):
        """Override this to do the actual task of distribution.
        """
        raise MuddleBug('No build_label method defined for class'
                        ' %s'%self.__class__.__name__)

class DistributeCheckout(DistributeAction):
    """
    An action that distributes a checkout.

    It copies the checkout source directory.

    By default it does not copy any VCS subdirectory (.git/, etc.)
    """

    def __init__(self, name, copy_vcs_dir=False):
        """
        'name' is the name of a DistributuionContext. When created, we are
        told which DistributionContext we can be distributed by. Later on,
        other names may be added...

        If 'copy_vcs_dir' is false, then don't copy any VCS directory
        (.git/, .bzr/, etc., depending on the VCS used for this checkout).
        """
        super(DistributeCheckout, self).__init__(name, copy_vcs_dir)

    def build_label(self, builder, label):
        name, target_dir = builder.get_distribution()

        copy_vcs_dir = self.distributions[name]

        print 'DistributeCheckout %s (%s VCS dir) to %s'%(label,
                'without' if copy_vcs_dir else 'with', target_dir)

        _actually_distribute_checkout(builder, label, target_dir, copy_vcs_dir)

class DistributeBuildDescription(DistributeCheckout):
    """This is similar to DistributeCheckout, but differs in detail.
    """

    def build_label(self, builder, label):
        name, target_dir = builder.get_distribution()

        copy_vcs_dir = self.distributions[name]

        print 'DistributeBuildDescription %s (%s VCS dir) to %s'%(label,
                'without' if copy_vcs_dir else 'with', target_dir)

        _actually_distribute_build_desc(builder, label, target_dir, copy_vcs_dir)

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

    def __init__(self, name, binary=True, source=False, copy_vcs_dir=False):
        """
        'name' is the name of a DistributuionContext. When created, we are
        told which DistributionContext we can be distributed by. Later on,
        other names may be added...

        If 'binary' is true, then a binary distribution will be performed.
        This means that obj/ and install/ directories (and the associated
        muddle tags) will be copied.

        If 'source' is true, then a source distribution will be performed.
        This means that the source directories (within src/) for the checkouts
        directly used by the package will be copied, along with the
        associated muddle tags. If 'source' is true and 'copy_vcs_dir' is
        true, then the VCS directories for those source checkouts will also
        be copied, otherwise they will not.

        Notes:

            1. We don't forbid having both 'binary' and 'source' true,
               but this may change in the future.
            2. If the package directly uses more than one checkout, then
               'copy_vcs_dir' applies to all of them. It is not possible
               to give different values for different checkouts.
            3. You can determine which checkouts 'source' distribution will
               use with "muddle -n import <package_label>" (or "muddle -n"
               with the package label for any "checkout" command).
        """
        super(DistributePackage, self).__init__(name, (binary, source, copy_vcs_dir))

    def build_label(self, builder, label):
        name, target_dir = builder.get_distribution()

        binary, source, copy_vcs_dir = self.distributions[name]

        print 'DistributePackage %s to %s'%(label, target_dir)

        if binary:
            _actually_distribute_binary(builder, label, target_dir)

        if source:
            checkouts = builder.invocation.checkouts_for_package(label)
            for co_label in checkouts:
                _actually_distribute_checkout(builder, co_label,
                                              target_dir, copy_vcs_dir)

def find_all_distribution_names(builder):
    """Return a set of all the distribution names.
    """
    distribution_names = set()

    invocation = builder.invocation
    target_label_exists = invocation.target_label_exists

    # We get all the "reasonable" checkout and package labels
    all_checkouts = builder.invocation.all_checkout_labels()
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

    print 'Domain:', domain
    if not domain:
        build_co_name, build_desc_path = builder.invocation.build_co_and_path()
    else:
        build_desc_path = os.path.join(builder.invocation.db.root_path,
                                       domain_subpath(domain),
                                       '.muddle', 'Description')
        with open(build_desc_path) as fd:
            str = fd.readline()
        build_co_name, build_desc_path = build_co_and_path_from_str(str.strip())
    print '  co_name', build_co_name
    return Label(LabelType.Checkout, build_co_name, tag=label_tag, domain=domain)

def add_build_descriptions(builder, name, domains):
    """Add all the implicated build description checkouts to our distribution.
    """
    # We need a build description for each domain we had a label for
    # (and possibly also any "in between" domains that weren't mentioned
    # explicitly?)

    extra_labels = []

    cumulative_domains = set()
    for domain in sorted(domains):
        print 'Domain %r'%domain
        if domain is None:
            print '  Add domain %r'%domain
            cumulative_domains.add(domain)
        else:
            parts = Label.split_domain(domain)
            for ii in range(1, 1+len(parts)):
                d = domain_from_parts(parts[:ii])
                print '  Add domain %r'%d
                cumulative_domains.add(d)
    print 'Found all domains'

    # XXX TODO XXX
    # Do we want VCS dir for our build descriptions?
    copy_vcs_dir = False

    print 'Adding build descriptions'
    for domain in sorted(cumulative_domains):
        co_label = build_desc_label_in_domain(builder, domain, LabelTag.Distributed)
        print '  Label', co_label
        distribute_build_desc(builder, name, co_label, copy_vcs_dir)
        extra_labels.append(co_label)
    print 'Done'

    return extra_labels

def distribute(builder, target_dir, name, unset_tags=False):
    """Distribute using distribution context 'name', to 'target_dir'.

    The DistributeContext called 'name' must exist.

    All distributions described in that DistributeContext will be made.

    'target_dir' need not exist - it will be created if necessary.

    If 'unset_tags' is true, then we unset the /distribute tags for our
    labels before doing the distribution.
    """

    # XXX TODO
    # XXX TODO 1. We should copy the "top level" of each .muddle directory
    # XXX TODO 2. We should distribute the build description checkouts
    # XXX TODO    (how do we know whether to copy VCS or not?)
    # XXX TODO 3. If we have subdomains, we should do both (1) and (2) for
    # XXX TODO    them as well, BUT:
    # XXX TODO
    # XXX TODO      Should we only do so if there are any labels *with* that
    # XXX TODO      subdomain actually being distributed? Or do we always
    # XXX TODO      distribute the whole "skeleton" of a build tree?
    # XXX TODO
    # XXX TODO      ...Maybe we should have a switch to tell us which to do
    # XXX TODO

    # XXX TODO Add support for "generic" distributions, including at least:
    # XXX TODO
    # XXX TODO  - all checkouts, without VCS (useful for packaging up releases)
    # XXX TODO  - all checkouts, with VCS (useful as a "clean copy" command)
    # XXX TODO  - all packages as binary only
    # XXX TODO
    # XXX TODO Of course, naming them is the hard part - for instance,
    # XXX TODO _all_sources, or _all_binaries, or _all_checkouts, ...

    distribution_labels = set()
    domains = set()

    invocation = builder.invocation
    target_label_exists = invocation.target_label_exists

    # We get all the "reasonable" checkout and package labels
    all_checkouts = builder.invocation.all_checkout_labels()
    all_packages = builder.invocation.all_package_labels()

    combined_labels = all_checkouts.union(all_packages)
    for label in combined_labels:
        target = label.copy_with_tag(LabelTag.Distributed)
        # Is there a distribution target for this label?
        if target_label_exists(target):
            # If so, is it distributable with this distribution name?
            rule = invocation.ruleset.map[target]
            if rule.action.does_distribution(name):
                # Yes, we like this label
                distribution_labels.add(target)
                # And remember its domain
                domains.add(target.domain)

    if not distribution_labels:
        print 'Nothing to distribute for %s'%name
        return

    # Add in appropriate build descriptions
    extra_labels = add_build_descriptions(builder, name, domains)

    # Don't forget that means more labels for us
    distribution_labels.update(extra_labels)

    num_labels = len(distribution_labels)

    distribution_labels = sorted(distribution_labels)

    # If '/distributed' is now transient, do we need to do this?
    if unset_tags:
        print 'Killing %d /distribute label%s'%(num_labels,
                '' if num_labels==1 else 's')
        for label in distribution_labels:
            builder.kill_label(label)

    # Remember to say where we're copying to...
    builder.set_distribution(name, target_dir)

    print 'Building %d /distribute label%s'%(num_labels,
            '' if num_labels==1 else 's')
    for label in distribution_labels:
        builder.build_label(label)

    # XXX TODO
    # Question - what are we meant to do if a package implicitly sets
    # a distribution state for a checkout, and we also explicitly set
    # a different (incompatible) state for a checkout? Who wins? Or do
    # we just try to satisfy both?
