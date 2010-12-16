"""
Routines for manipulating packages and checkouts.
"""

import utils
import depend

class Action:
    """
    Represents an object you can call to build a tag.
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

class ArchSpecificAction:
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


class ArchSpecificActionGenerator:
    
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
    This class represents a checkout, which knows where it's checked out from.
    """
    def __init__(self, name, vcs):
        self.name = name
        self.vcs = vcs

    def _checkout_is_checked_out(self, builder, label):
        """
        Return True if this checkout has indeed been checked out
        """
        label = label.copy_with_tag(utils.LabelTag.CheckedOut, transient=False)
        return builder.invocation.db.is_tag(label)

    def must_fetch_before_commit(self):
        """
        Must we update in order to commit? Only the VCS handler knows .. 
        """
        return self.vcs.must_fetch_before_commit()

    def build_label(self, builder, label):
        target_tag = label.tag

        if (target_tag == utils.LabelTag.CheckedOut):
            self.vcs.checkout()
        elif (target_tag == utils.LabelTag.Fetched):
            self.vcs.fetch()
        elif (target_tag == utils.LabelTag.Merged):
            self.vcs.merge()
        elif (target_tag == utils.LabelTag.ChangesCommitted):
            if self._checkout_is_checked_out(builder, label):
                self.vcs.commit()
            else:
                print "Checkout %s has not been checked out - not commiting"%label.name
        elif (target_tag == utils.LabelTag.ChangesPushed):
            if self._checkout_is_checked_out(builder, label):
                self.vcs.push()
            else:
                print "Checkout %s has not been checked out - not pushing"%label.name
        else:
            raise utils.MuddleBug("Attempt to build unknown tag %s "%target_tag + 
                              "in checkout %s."%self.name)

        return True

# TODO: Deprecated...
# Legacy names for things.
# Since I've changed Dependable to Action (and so on), but can't guarantee that
# other code is not using this directly, I'd better provide aliases, at least
# for the moment.
Dependable = Action
SequentialDependable = SequentialAction
ArchSpecificDependable = ArchSpecificAction
ArchSpecificDependableGenerator = ArchSpecificActionGenerator
NoneDependable = NoAction

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
        
    

class Profile:
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

def add_checkout_rules(ruleset, co_label, obj):
    """
    Add the standard checkout rules to a ruleset for a checkout
    with name co_label. 'obj' should be an instance of VcsCheckoutBuilder,
    which knows how to build a checkout: label, depending on its tag.
    """

    # All of the VCS tags are transient (well, with the obvious exception
    # of "checked_out" itself). So we need to be a little bit careful.

    # Make sure we have the correct basic tag
    if co_label.tag != utils.LabelTag.CheckedOut:
        co_label = co_label.copy_with_tag(utils.LabelTag.CheckedOut)

    # And we simply use the VcsCheckoutBuilder (as we assume it to be)
    # to build us
    co_rule = depend.Rule(co_label, obj)
    ruleset.add(co_rule)

    # Fetched is a transient label.
    fetched_label = co_label.copy_with_tag(utils.LabelTag.Fetched, transient=True)
    # Since 'checked_out' is not transient, and since it seems reasonable
    # enough that "muddle fetch" should check the checkout out if it has not
    # already been done, then we can make it depend upon the checked_out label...
    # Tell its rule that it depends on the checkout being checked out (!)
    rule = depend.Rule(fetched_label, obj)
    rule.add(co_label)
    ruleset.add(rule)
    #rule = ruleset.rule_for_target(fetched_label, createIfNotPresent=True)
    #rule.add(co_label)

    # Merged is very similar, and also depends on the checkout existing
    merged_label = co_label.copy_with_tag(utils.LabelTag.Merged, transient=True)
    rule = depend.Rule(merged_label, obj)
    rule.add(co_label)
    ruleset.add(rule)
    #rule = ruleset.rule_for_target(merged_label, createIfNotPresent=True)
    #rule.add(co_label)

    ## We used to say that UpToDate depended on Pulled.
    ## Our nearest equivalent would be Merged depending on Fetched.
    ## But that's plainly not a useful dependency, so we shall ignore it.
    #depend.depend_chain(obj, 
    #                    uptodate_label, 
    #                    [ utils.LabelTag.Fetched ], ruleset)

    # We don't really want 'push' to do a 'checkout', so instead we rely on
    # the action only doing something if the corresponding checkout has
    # been checked out. Which leaves the rule with no apparent dependencies
    pushed_label = co_label.copy_with_tag(utils.LabelTag.ChangesPushed, transient=True)
    rule = depend.Rule(pushed_label, obj)
    ruleset.add(rule)

    # The same also applies to commit...
    committed_label = co_label.copy_with_tag(utils.LabelTag.ChangesCommitted, transient=True)
    rule = depend.Rule(committed_label, obj)
    ruleset.add(rule)

    # Centralised VCSs, in general, want us to do a 'fetch' (update) before
    # doing a 'commit', so we should try to honour that, if necessary
    if (obj.must_fetch_before_commit()):
        rule.add(fetched_label)

def package_depends_on_checkout(ruleset, pkg_name, role_name, co_name, obj):
    """
    Make the given package depend on the given checkout

    * ruleset   - The ruleset to use - builder.invocation.ruleset, for example.
    * pkg_name  - The package which depends.
    * role_name - The role which depends. Can be '*' for a wildcard.
    * co_name   - The checkout which this package and role depends on.
    * obj       - If non-None, specifies an Action to be invoked to get from
      the checkout to the package preconfig. You'll normally make this None
      unless you are doing something deeply weird.
    """

    checkout = depend.Label(utils.LabelType.Checkout, 
                            co_name, None,
                            utils.LabelTag.CheckedOut)

    preconfig = depend.Label(utils.LabelType.Package, 
		             pkg_name, role_name, 
			     utils.LabelTag.PreConfig)

    new_rule = depend.Rule(preconfig, obj)
    new_rule.add(checkout)
    ruleset.add(new_rule)

    # We can't distclean a package until we've checked out its checkout
    distclean = depend.Label(utils.LabelType.Package,
		             pkg_name, role_name, 
			     utils.LabelTag.DistClean, 
			     transient = True)
    ruleset.add(depend.depend_one(obj, distclean, checkout))

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

    

def add_package_rules(ruleset, pkg_name, role_name, obj):
    """
    Add the standard package rules to a ruleset.
    """
    
    depend.depend_chain(obj,
                        depend.Label(utils.LabelType.Package,
                              pkg_name, role_name, 
                              utils.LabelTag.PreConfig),
                        [ utils.LabelTag.Configured,
                          utils.LabelTag.Built,
                          utils.LabelTag.Installed,
                          utils.LabelTag.PostInstalled ],
                        ruleset)

    # "clean" dependes on "preconfig", but is transient,
    # since you don't want to remember you've done it .. 
    # 
    # (and it avoids inverse rules which would be a bit
    #  urgh)
    ruleset.add(depend.depend_one(obj, 
				   depend.Label(utils.LabelType.Package,
				                pkg_name, role_name, 
						utils.LabelTag.Clean, 
						transient = True),
				   depend.Label(utils.LabelType.Package,
					        pkg_name, role_name,
						utils.LabelTag.PreConfig,
						transient = True)))
    # "distclean" depedsn on the package's checkout(s) having
    # been checked out, so is handled in ``package_depends_on_checkout()``


def do_depend(builder, pkg_name, role_names,
              deps):
    """
    Make pkg_name in role_names depend on the contents of deps.

    deps is a list of 2-tuples (pkg_name, role_name)

    If the role name is None, we depend on the pkg name in the role we're
    currently using, so ``do_depend(a, ['b', 'c'], [ ('d', None) ])`` leads
    to ``a{b}`` depending on ``d{b}`` and ``a{c}`` depending on ``d{c}``.
    """
    
    ruleset = builder.invocation.ruleset

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
        env = builder.invocation.get_environment_for(lbl)
        env.append(name, value)
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
        env = builder.invocation.get_environment_for(lbl)
        env.set(name, value)


# End file.

    
    
    
