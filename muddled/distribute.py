"""
Actions and mechanisms relating to distributing build trees
"""

import os

from muddled.depend import Action, Rule
from muddled.utils import MuddleBug, LabelTag, LabelType, copy_without, normalise_dir
from muddled.version_control import get_vcs_handler

class DistributeContext(object):
    """Information we need to do a "distribute" action.

    The main thing we need is where to distribute to - a directory.
    """

    def __init__(self, builder, target_dir):
        """Create our distribution context

        - 'builder' is our muddle builder
        - 'target_dir' is the directory to distribute to. It need not exist.
        """
        self.builder = builder
        self.target_dir = target_dir

    def __repr__(self):
        return "DistributeContext(builder, '%s')"%self.target_dir

class DistributePackage(Action):
    """
    An action that distributes a package.

    If the package is being distributed as binary, then this action copies
    the obj/ and install/ directories for the package, as well as any
    instructions (and anything else I haven't yet thought of).

    If the package is being distributed as source, then this action copies
    the source directory for each checkout that is *directly* used by the
    package.
    """

    def __init__(self, target_dir, binary=True, source=False, copy_vcs_dir=False):
        """
        'target_dir' is where to copy our distributed files. It should either
        not exist (in which case we will create it when necessary), or should
        be empty. Distribution will create .muddle/, obj/, install/ and src/
        directories within it, as necessary.

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
        self.target_dir = target_dir
        self.binary = binary
        self.source = source
        self.copy_vcs_dir = copy_vcs_dir

    def _distribute_binary(self, builder, label):
        """Do a binary distribution of our package.
        """
        # 1. We know the target directory. Note it may not exist yet
        # 2. Get the actual directory of the package obj/ and install/
        #    directories
        obj_dir = builder.invocation.package_obj_path(label)
        install_dir = builder.invocation.package_install_path(label)
        # 3. Use copywithout to copy the obj/ and install/ directories over
        root_path = normalise_dir(builder.invocation.db.root_path)
        rel_obj_dir = os.path.relpath(normalise_dir(obj_dir), root_path)
        rel_install_dir = os.path.relpath(normalise_dir(install_dir), root_path)

        target_obj_dir = os.path.join(self.target_dir, rel_obj_dir)
        target_install_dir = os.path.join(self.target_dir, rel_install_dir)

        target_obj_dir = normalise_dir(target_obj_dir)
        target_install_dir = normalise_dir(target_install_dir)

        print 'Copying:'
        print '  from %s'%obj_dir
        print '  and  %s'%install_dir
        print '  to   %s'%target_obj_dir
        print '  and  %s'%target_install_dir

        copy_without(obj_dir, target_obj_dir, preserve=True)
        copy_without(install_dir, target_install_dir, preserve=True)
        # 4. Set the appropriate tags in the target .muddle/ directory
        # 5. Set the /distributed tag on the package

    def build_label(self, builder, label):
        print 'DistributePackage %s to %s'%(label, self.target_dir)

        if self.binary:
            self._distribute_binary(builder, label)

        if self.source:
            checkouts = builder.invocation.checkouts_for_package(label)
            for co_label in checkouts:
                _actually_distribute_checkout(builder, co_label,
                                              self.target_dir, self.copy_vcs_dir)

def _actually_distribute_checkout(builder, label, target_dir, copy_vcs_dir):
    """As it says.
    """
    # 1. We know the target directory. Note it may not exist yet
    # 2. Get the actual directory of the checkout
    co_dir = builder.invocation.db.get_checkout_location(label)
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
    target_dir = os.path.join(normalise_dir(target_dir), co_dir)
    print 'Copying:'
    print '  from %s'%co_dir
    print '  to   %s'%target_dir
    if not copy_vcs_dir:
        print '  without %s'%vcs_dir
    copy_without(co_dir, target_dir, without, preserve=True)
    # 5. Set the appropriate tags in the target .muddle/ directory
    # 6. Set the /distributed tag on the checkout

class DistributeCheckout(Action):
    """
    An action that distributes a checkout.

    It copies the checkout source directory.

    By default it does not copy any VCS subdirectory (.git/, etc.)
    """

    def __init__(self, target_dir, copy_vcs_dir=False):
        """
        'target_dir' is where to copy our distributed files. It should either
        not exist (in which case we will create it when necessary), or should
        be empty. Distribution will create .muddle/ and src/ directories within
        it, as necessary.

        If 'copy_vcs_dir' is false, then don't copy any VCS directory
        (.git/, .bzr/, etc., depending on the VCS used for this checkout).
        """
        self.target_dir = target_dir
        self.copy_vcs_dir = copy_vcs_dir

    def build_label(self, builder, label):
        print 'DistributeCheckout %s (%s VCS dir) to %s'%(label,
                'without' if self.copy_vcs_dir else 'with',
                self.target_dir)
        _actually_distribute_checkout(builder, label, self.target_dir,
                                      self.copy_vcs_dir)


class DistributeBuildDescription(DistributeCheckout):
    """
    An action that distributes a build description's checkout.

    It copies the checkout source directory.

    By default it does not copy any VCS subdirectory (.git/, etc.)

    For the moment, it is identical to DistributeCheckout, but that will
    not be so when it is finished
    """
    pass

def distribute_checkout(context, label, copy_vcs_dir=False):
    """Request the distribution of the given checkout.

    - 'context' is a DistributeContext instance, naming the builder and the
      target directory
    - 'label' must be a checkout label, but the tag is not important.

    By default, don't copy any VCS directory.
    """
    if label.type != LabelType.Checkout:
        raise MuddleBug('Attempt to use non-checkout label %s for a distribute checkout rule'%label)

    source_label = label.copy_with_tag(LabelTag.CheckedOut)
    target_label = label.copy_with_tag(LabelTag.Distributed)

    action = DistributeCheckout(context.target_dir, copy_vcs_dir)

    rule = Rule(target_label, action)       # to build target_label, run action
    rule.add(source_label)                  # after we've built source_label

    context.builder.invocation.ruleset.add(rule)

def distribute_build_description(context, label, copy_vcs_dir=False):
    """Request the distribution of the build description checkout.

    - 'context' is a DistributeContext instance, naming the builder and the
      target directory
    - 'label' must be a checkout label, but the tag is not important.

    By default, don't copy any VCS directory.
    """
    # For the moment, just like any other checkout
    distribute_checkout(context, label, copy_vcs_dir)

def distribute_package(context, label, binary=True, source=False, copy_vcs_dir=False):
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
    """
    if label.type != LabelType.Package:
        raise MuddleBug('Attempt to use non-package label %s for a distribute package rule'%label)

    source_label = label.copy_with_tag(LabelTag.PostInstalled)
    target_label = label.copy_with_tag(LabelTag.Distributed)

    action = DistributePackage(context.target_dir)

    rule = Rule(target_label, action)       # to build target_label, run action
    rule.add(source_label)                  # after we've built source_label

    context.builder.invocation.ruleset.add(rule)

