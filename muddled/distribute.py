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

    It copies the the obj/ and install/ directories for the package, as well
    as any instructions (and anything else I haven't yet thought of).
    """

    def __init__(self, target_dir):
        self.target_dir = target_dir

    def build_label(self, builder, label):
        print 'DistributePackage %s to %s'%(label, self.target_dir)

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

class DistributeCheckout(Action):
    """
    An action that distributes a checkout.

    It copies the checkout source directory.

    By default it does not copy any VCS subdirectory (.git/, etc.)
    """

    def __init__(self, target_dir, copy_vcs_dir=False):
        """
        If 'copy_vcs_dir' is false, then don't copy any VCS directory
        (.git/, .bzr/, etc., depending on the VCS used for this checkout).
        """
        self.target_dir = target_dir
        self.copy_vcs_dir = copy_vcs_dir

    def build_label(self, builder, label):
        print 'DistributeCheckout %s (%s VCS dir) to %s'%(label,
                'without' if self.copy_vcs_dir else 'with',
                self.target_dir)

        # 1. We know the target directory. Note it may not exist yet
        # 2. Get the actual directory of the checkout
        co_dir = builder.invocation.db.get_checkout_location(label)
        # 3. If we're not doing copy_vcs_dir, find the VCS for this
        #    checkout, and from that determine its VCS dir, and make
        #    that our "without" string
        without = []
        if not self.copy_vcs_dir:
            repo = builder.invocation.db.get_checkout_repo(label)
            vcs_handler = get_vcs_handler(repo.vcs)
            vcs_dir = vcs_handler.get_vcs_dirname()
            if vcs_dir:
                without.append(vcs_dir)
        # 4. Do a copywithout to do the actual copy, suitably ignoring
        #    the VCS directory if necessary.
        target_dir = os.path.join(normalise_dir(self.target_dir), co_dir)
        print 'Copying:'
        print '  from %s'%co_dir
        print '  to   %s'%target_dir
        if not self.copy_vcs_dir:
            print '  without %s'%vcs_dir
        copy_without(co_dir, target_dir, without, preserve=True)
        # 5. Set the appropriate tags in the target .muddle/ directory
        # 6. Set the /distributed tag on the checkout

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

def distribute_package(context, label):
    """Request the distribution of the given package.

    - 'context' is a DistributeContext instance, naming the builder and the
      target directory
    - 'label' must be a package label, but the tag is not important.
    """
    if label.type != LabelType.Package:
        raise MuddleBug('Attempt to use non-package label %s for a distribute package rule'%label)

    source_label = label.copy_with_tag(LabelTag.PostInstalled)
    target_label = label.copy_with_tag(LabelTag.Distributed)

    action = DistributePackage(context.target_dir)

    rule = Rule(target_label, action)       # to build target_label, run action
    rule.add(source_label)                  # after we've built source_label

    context.builder.invocation.ruleset.add(rule)

