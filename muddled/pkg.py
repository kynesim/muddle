"""
Routines for manipulating packages and checkouts.
"""

import muddled.utils as utils
import muddled.depend as depend
from muddled.depend import Action

class ArchSpecificAction(object):
    """
    Allow an action to be invoked if and only if you're on the
    right architecture
    """

    def __init__(self, underlying, arch):
        self.underlying = underlying
        self.arch = arch

    def build_label(self, builder, label):
        if (utils.arch_name() == self.arch):
            return self.underlying.build_label(builder, label)
        else:
            raise utils.MuddleBug("Label %s cannot be built on this architecture (%s) - requires %s"%(label, utils.arch_name(), self.arch))


class ArchSpecificActionGenerator(object):

    def __init__(self, arch):
        self.arch = arch

    def generate(self, underlying):
        return ArchSpecificAction(underlying, self.arch)

class NoAction(Action):
    """
    An action which does nothing - used largely for testing.
    """

    def __init__(self):
        pass

    def build_label(self, builder, label):
        pass

class VcsCheckoutBuilder(Action):
    """
    This class represents the actions available on a checkout.

    'self.vcs' is the VCS handler which knows how to do version control
    operations on a checkout.
    """
    def __init__(self, vcs):
        self.vcs = vcs

    def _checkout_is_checked_out(self, builder, co_label):
        """
        Return True if this checkout has indeed been checked out
        """
        co_label = co_label.copy_with_tag(utils.LabelTag.CheckedOut, transient=False)
        return builder.db.is_tag(co_label)

    def must_pull_before_commit(self, builder, co_label):
        """
        Must we update in order to commit? Only the VCS handler knows ..
        """
        return self.vcs.must_pull_before_commit(builder, co_label)

    def build_label(self, builder, co_label):

        # Note that we don't in fact check that self.name matches (part of)
        # the checkout label we're building.

        target_tag = co_label.tag

        if (target_tag == utils.LabelTag.CheckedOut):
            self.vcs.checkout(builder, co_label)
            # For all intents and purposes, cloning is equivalent to pulling
            builder.db.just_pulled.add(co_label)
        elif (target_tag == utils.LabelTag.Pulled):
            if self.vcs.pull(builder, co_label):
                builder.db.just_pulled.add(co_label)
        elif (target_tag == utils.LabelTag.Merged):
            if self.vcs.merge(builder, co_label):
                builder.db.just_pulled.add(co_label)
        elif (target_tag == utils.LabelTag.ChangesCommitted):
            if self._checkout_is_checked_out(builder, co_label):
                self.vcs.commit(builder, co_label)
            else:
                print "Checkout %s has not been checked out - not commiting"%co_label
        elif (target_tag == utils.LabelTag.ChangesPushed):
            if self._checkout_is_checked_out(builder, co_label):
                self.vcs.push(builder, co_label)
            else:
                print "Checkout %s has not been checked out - not pushing"%co_label.name
        else:
            raise utils.MuddleBug("Attempt to build unknown tag %s "%target_tag +
                                  "in checkout %s."%co_label)

        return True

class PackageBuilder(Action):
    """
    Describes a package.
    """

    def __init__(self, name, role):
        """
        Construct a package.

        self.name
          The name of this package

        self.deps
          The dependency set for this package. The dependency set contains
          mappings from role to ( package, role ). A role of '*' indicates
          a wildcard.
        """

        self.name = name
        self.role = role
        self.deps = None

    def build_label(self, builder, label):
        raise utils.MuddleBug("Attempt to build unknown label %s"%label)

class Deployment(Action):
    """
    Represents a deployment. Deployments (typically) package code into
    release packages
    """

    def build_label(self, builder, tag):
        """
        Whatever's needed to build the relevant tag for this deployment.
        """
        pass

class NullPackageBuilder(PackageBuilder):
    """
    A package that does nothing.

    This can be useful when a build wants to force some checkouts to be
    present (and checked out), but there is nothing to build in them.
    Examples include documentation and meta-information that is just
    being kept in the build tree so that it doesn't get lost.

    Use the 'null_package' function to construct a useful instance.
    """
    def build_label(self, builder, label):
        pass

def null_package(builder, name, role):
    """
    Create a Null package, a package that does nothing.

    Uses NullPackageBuilder to construct our package, and then calls
    add_package_rules() to add the standard rules for a package.

    Returns the new package instance.

    Use like this::

        # We have documentation in this checkout
        checkouts.simple.relative(builder, co_name='docs')

        # And we'd like it always to be checked out
        # For this, we use a Null package that doesn't build itself
        null_pkg = null_package(builder, name='docs', role='meta')
        pkg.package_depends_on_checkout(builder.ruleset,
                                        pkg_name='docs', role_name='meta',
                                        co_name='docs')

        # And add that to our default roles
        builder.add_default_role('meta')

    """
    this_pkg = NullPackageBuilder(name='meta', role='meta')
    # Add the standard rules for a package
    add_package_rules(builder.ruleset, name, role, this_pkg)
    return this_pkg

class Profile(object):
    """
    A profile ties together a role, a deployment and an installation
    directory. Profiles aren't actions - they modify the builder.

    There are two things you can do to a profile: you can ``assume()`` it,
    in which case you build that profile, or you can ``use()`` it, in
    which case that profile's build results (if any) become available
    to you.
    """

    def __init__(self, name, role):
        self.name = name
        self.role = role

    def assume(self, builder):
        pass

    def use(self, builder):
        pass

def add_checkout_rules(builder, co_label, action):
    """
    Add the standard checkout rules to a ruleset for a checkout
    with name co_label. 'action' should be an instance of VcsCheckoutBuilder,
    which knows how to build a checkout: label, depending on its tag.
    """

    ruleset = builder.ruleset

    # All of the VCS tags are transient (well, with the obvious exception
    # of "checked_out" itself). So we need to be a little bit careful.

    # Make sure we have the correct basic tag
    if co_label.tag != utils.LabelTag.CheckedOut:
        co_label = co_label.copy_with_tag(utils.LabelTag.CheckedOut)

    # And we simply use the VcsCheckoutBuilder (as we assume it to be)
    # to build us
    co_rule = depend.Rule(co_label, action)
    ruleset.add(co_rule)

    # Pulled is a transient label.
    pulled_label = co_label.copy_with_tag(utils.LabelTag.Pulled, transient=True)
    # Since 'checked_out' is not transient, and since it seems reasonable
    # enough that "muddle pull" should check the checkout out if it has not
    # already been done, then we can make it depend upon the checked_out label...
    # Tell its rule that it depends on the checkout being checked out (!)
    rule = depend.Rule(pulled_label, action)
    rule.add(co_label)
    ruleset.add(rule)

    # Merged is very similar, and also depends on the checkout existing
    merged_label = co_label.copy_with_tag(utils.LabelTag.Merged, transient=True)
    rule = depend.Rule(merged_label, action)
    rule.add(co_label)
    ruleset.add(rule)

    ## We used to say that UpToDate depended on Pulled.
    ## Our nearest equivalent would be Merged depending on Pulled.
    ## But that's plainly not a useful dependency, so we shall ignore it.
    #depend.depend_chain(action,
    #                    uptodate_label,
    #                    [ utils.LabelTag.Pulled ], ruleset)

    # We don't really want 'push' to do a 'checkout', so instead we rely on
    # the action only doing something if the corresponding checkout has
    # been checked out. Which leaves the rule with no apparent dependencies
    pushed_label = co_label.copy_with_tag(utils.LabelTag.ChangesPushed, transient=True)
    rule = depend.Rule(pushed_label, action)
    ruleset.add(rule)

    # The same also applies to commit...
    committed_label = co_label.copy_with_tag(utils.LabelTag.ChangesCommitted, transient=True)
    rule = depend.Rule(committed_label, action)
    ruleset.add(rule)

    # Centralised VCSs, in general, want us to do a 'pull' (update) before
    # doing a 'commit', so we should try to honour that, if necessary
    if (action.must_pull_before_commit(builder, co_label)):
        rule.add(pulled_label)

def package_depends_on_checkout(ruleset, pkg_name, role_name, co_name, action=None):
    """
    Make the given package depend on the given checkout

    * ruleset   - The ruleset to use - builder.ruleset, for example.
    * pkg_name  - The package which depends.
    * role_name - The role which depends. Can be '*' for a wildcard.
    * co_name   - The checkout which this package and role depends on.
    * action    - If non-None, specifies an Action to be invoked to get from
      the checkout to the package preconfig. If you are a normal (outside
      muddle itself) caller, then you will normally leave this None unless you
      are doing something deeply weird.
    """

    checkout = depend.Label(utils.LabelType.Checkout,
                            co_name, None,
                            utils.LabelTag.CheckedOut)

    preconfig = depend.Label(utils.LabelType.Package,
                             pkg_name, role_name,
                             utils.LabelTag.PreConfig)

    new_rule = depend.Rule(preconfig, action)
    new_rule.add(checkout)
    ruleset.add(new_rule)

    # We can't clean or distclean a package until we've checked out its checkout
    # Both are transient, as we don't need to remember we've done them, and
    # indeed they should be doable more than once
    clean = depend.Label(utils.LabelType.Package,
                         pkg_name, role_name,
                         utils.LabelTag.Clean,
                         transient = True)
    ruleset.add(depend.depend_one(action, clean, checkout))

    distclean = depend.Label(utils.LabelType.Package,
                             pkg_name, role_name,
                             utils.LabelTag.DistClean,
                             transient = True)
    ruleset.add(depend.depend_one(action, distclean, checkout))

def package_depends_on_packages(ruleset, pkg_name, role, tag_name, deps):
    """
    Make pkg_name depend on the list in deps.

    pkg_name's tag_name tag ends up depending on the deps having been installed -
    this can be PreConfig or Built, depending on whether you need that dependency
    to configure yourself or not.
    """
    target_label = depend.Label(utils.LabelType.Package,
                                pkg_name, role, tag_name)

    r = ruleset.rule_for_target(target_label, createIfNotPresent = True)

    for d in deps:
        dep_label = depend.Label(utils.LabelType.Package,
                                 d,
                                 role,
                                 utils.LabelTag.PostInstalled)
        r.add(dep_label)



def add_package_rules(ruleset, pkg_name, role_name, action):
    """
    Add the standard package rules to a ruleset.
    """

    depend.depend_chain(action,
                        depend.Label(utils.LabelType.Package,
                              pkg_name, role_name,
                              utils.LabelTag.PreConfig),
                        [ utils.LabelTag.Configured,
                          utils.LabelTag.Built,
                          utils.LabelTag.Installed,
                          utils.LabelTag.PostInstalled ],
                        ruleset)

    # "clean" is transient, since we don't want/need to remember that it
    # has been done (doing "clean" more than once is rather requires to
    # be harmless)
    #
    # "clean" used to depend on "preconfig", but this sometimes had strange
    # results - for instance, if "preconfig" on A depended on "checked_out"
    # of B.
    #
    # Instead, we will make "clean" depend on "checked_out", and as such this
    # is done in package_depends_on_checkout, just as "distclean" always has
    # been
    if False:
        ruleset.add(depend.depend_one(action,
                                       depend.Label(utils.LabelType.Package,
                                                    pkg_name, role_name,
                                                    utils.LabelTag.Clean,
                                                    transient = True),
                                       depend.Label(utils.LabelType.Package,
                                                    pkg_name, role_name,
                                                    utils.LabelTag.CheckedOut,
                                                    transient = True)))
    # "distclean" depends on the package's checkout(s) having
    # been checked out, so is handled in ``package_depends_on_checkout()``


def do_depend_label(builder, pkg_name, role_names, 
                    label):
    """ 
    Make pkg_name in role_names depend on the given label
    
    If role_names is a string, we will implicitly convert it into the 
    singleton list [ role_names ].
    """
    ruleset = builder.ruleset
    if isinstance(role_names, basestring):
        r = role_names
        role_names = [ r ]

    for role_name in role_names:
        ruleset.add(depend.depend_one(None,
                                      depend.Label(utils.LabelType.Package,
                                                   pkg_name, role_name,
                                                   utils.LabelTag.PreConfig),
                                      label))


def do_depend(builder, pkg_name, role_names,
              deps):
    """
    Make pkg_name in role_names depend on the contents of deps.

    deps is a list of 2-tuples (pkg_name, role_name)

    If the role name is None, we depend on the pkg name in the role we're
    currently using, so ``do_depend(a, ['b', 'c'], [ ('d', None) ])`` leads
    to ``a{b}`` depending on ``d{b}`` and ``a{c}`` depending on ``d{c}``.
    
    If role_names is a string, we will implicitly convert it into the 
    singleton list [ role_names ].
    """

    ruleset = builder.ruleset
    if isinstance(role_names, basestring):
        r = role_names
        role_names = [ r ]

    for role_name in role_names:
        for (pkg, role) in deps:
            if (role is None):
                role = role_name

            ruleset.add(depend.depend_one(None,
                                          depend.Label(utils.LabelType.Package,
                                                       pkg_name, role_name,
                                                       utils.LabelTag.PreConfig),
                                          depend.Label(utils.LabelType.Package,
                                                       pkg, role,
                                                       utils.LabelTag.PostInstalled)))


def depend_across_roles(ruleset, pkg_name, role_names,
                        depends_on_pkgs, depends_on_role):
    """
    Register that pkg_name{role_name}'s preconfig depends on
    depends_on_pkg{depends_on_role} having been postinstalled.
    """
    for pkg in depends_on_pkgs:
        for role_name in role_names:
            ruleset.add(depend.depend_one(None,
                                          depend.Label(utils.LabelType.Package,
                                                       pkg_name, role_name,
                                                       utils.LabelTag.PreConfig),
                                          depend.Label(utils.LabelType.Package,
                                                       pkg,
                                                       depends_on_role,
                                                       utils.LabelTag.PostInstalled)))

def append_env_for_package(builder, pkg_name, pkg_roles,
                           name, value,
                           domain = None,
                           type = None):
    """
    Set the environment variable name to value in the given
    package built in the given roles. Useful for customising
    package behaviour in particular roles in the build
    description.
    """

    for r in pkg_roles:
        lbl = depend.Label(utils.LabelType.Package,
                           pkg_name,
                           r,
                           "*",
                           domain = domain)
        env = builder.get_environment_for(lbl)
        env.append(name, value)
        if (type is not None):
            env.set_type(name, type)


def prepend_env_for_package(builder, pkg_name, pkg_roles,
                           name, value,
                           domain = None,
                           type = None):
    """
    Set the environment variable name to value in the given
    package built in the given roles. Useful for customising
    package behaviour in particular roles in the build
    description.
    """

    for r in pkg_roles:
        lbl = depend.Label(utils.LabelType.Package,
                           pkg_name,
                           r,
                           "*",
                           domain = domain)
        env = builder.get_environment_for(lbl)
        env.prepend(name, value)
        if (type is not None):
            env.set_type(name, type)

def set_env_for_package(builder, pkg_name, pkg_roles,
                        name, value,
                        domain = None):
    """
    Set the environment variable name to value in the given
    package built in the given roles. Useful for customising
    package behaviour in particular roles in the build
    description.
    """

    for r in pkg_roles:
        lbl = depend.Label(utils.LabelType.Package,
                           pkg_name,
                           r,
                           "*",
                           domain = domain)
        env = builder.get_environment_for(lbl)
        env.set(name, value)

def set_checkout_vcs_option(builder, co_label, **kwargs):
    """
    Sets extra VCS options for a checkout (identified by its label).

    For reasons mostly to do with how stamping/unstamping works, we require
    option values to be either boolean, integer or string.

    For example::

      pkg.set_checkout_vcs_option(builder, depend.checkout('kernel-source'),
                                  shallow_checkout=True, something_else=99)

    This is a wrapper around::

      builder.db.set_checkout_vcs_option(depend.checkout('kernel-source'),
                                         'shallow', True)
      builder.db.set_checkout_vcs_option(depend.checkout('kernel-source'),
                                         'something_else', 99)

    "muddle help vcs <name>" should document the available options for the
    version control system <name> (see "muddle help vcs" for the supported
    version control systems).
    """
    for key, value in kwargs.items():
        builder.db.set_checkout_vcs_option(co_label, key, value)

# End file.
