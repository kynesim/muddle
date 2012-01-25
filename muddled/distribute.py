"""
Actions and mechanisms relating to distributing build trees
"""

from muddled.depend import Action, Rule
from muddled.utils import MuddleBug, LabelTag

class DistributePackage(Action):
    """
    An action that distributes a package.

    It copies the the obj/ and install/ directories for the package, as well
    as any instructions (and anything else I haven't yet thought of).
    """

    def build_label(self, builder, label):
        print 'DistributePackage %s'%label

class DistributeCheckout(Action):
    """
    An action that distributes a checkout.

    It copies the checkout source directory.

    By default it does not copy any VCS subdirectory (.git/, etc.)
    """

    def __init__(self, copy_vcs_dir=False):
        self.copy_vcs_dir = copy_vcs_dir

    def build_label(self, builder, label):
        print 'DistributeCheckout %s (%s VCS)'%(label,
                'without' if self.copy_vcs_dir else 'with')

def distribute_checkout(builder, label, copy_vcs_dir=False):
    """Request the distribution of the given checkout.

    'label' must be a checkout label, but the tag is not important.

    By default, don't copy any VCS directory.
    """
    if label.type != LabelType.Checkout:
        raise MuddleBug('Attempt to use non-checkout label %s for a distribute checkout rule'%label)

    source_label = label.copy_with_tag(LabelTag.CheckedOut)
    target_label = label.copy_with_tag(LabelTag.Distributed)

    action = DistributeCheckout(copy_vcs_dir)
    rule = Rule(target_label, action)       # to build target_label, run action
    rule.add(source_label)                  # after we've built source_label

def distribute_package(builder, label):
    """Request the distribution of the given package.

    'label' must be a package label, but the tag is not important.
    """
    if label.type != LabelType.Package:
        raise MuddleBug('Attempt to use non-package label %s for a distribute package rule'%label)

    source_label = label.copy_with_tag(LabelTag.PostInstalled)
    target_label = label.copy_with_tag(LabelTag.Distributed)

    action = DistributePackage()
    rule = Rule(target_label, action)       # to build target_label, run action
    rule.add(source_label)                  # after we've built source_label

