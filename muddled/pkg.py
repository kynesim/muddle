"""
Routines for manipulating packages and checkouts
"""

import utils
import depend

class Dependable:
    """
    Represents an object you can call to build a tag
    """

    def build_label(self, label):
        """
        Build the given label. Your dependencies have been
        satisfied

        @param[in] in_deps  Is the set whose dependencies have been
          satisified.
        @return True on success, False or throw otherwise.
        """
        pass

        

class NoneDependable(Dependable):
    """
    A dependable which does nothing - used largely for testing
    """
    
    def __init__(self):
        pass

    def build_label(self, label):
        pass



class Checkout(Dependable):
    """
    Represents a checkout object. Don't use this class - at the very least use
    VcsCheckout, which has some idea about whether it's in vcs or not
    """

    def __init__(self, name, vcs):
        self.name = name
        self.vcs = vcs


    def build_label(self, tag):
        """
        Do whatever's needed to ensure that you can assert the given tag. Your
        dependencies have been met.
        """
        pass



class VcsCheckoutBuilder(Checkout):
    def __init__(self, name, vcs):
        Checkout.__init__(self, name, vcs)
        
    def must_update_to_commit(self):
        """
        Must we update in order to commit? Only the VCS handler
        knows .. 
        """
        return self.vcs.must_update_to_commit()

    def build_label(self, label):
        target_tag = label.tag

        if (target_tag == utils.Tags.CheckedOut):
            self.vcs.check_out()
        elif (target_tag == utils.Tags.Pulled):
            self.vcs.pull()
        elif (target_tag == utils.Tags.UpToDate):
            self.vcs.update()
        elif (target_tag == utils.Tags.ChangesCommitted):
            self.vcs.commit()
        elif (target_tag == utils.Tags.ChangesPushed):
            self.vcs.push()
        else:
            raise utils.Error("Attempt to build unknown tag %s "%target_tag + 
                              "in checkout %s."%self.name)

        return True

    


class PackageBuilder(Dependable):
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

    def build_label(self, label):
        raise utils.Error("Attempt to build unknown label %s"%self.label)

class Deployment(Dependable):
    """
    Represents a deployment. Deployments (typically) package code into
    release packages
    """

    def build_label(self, tag):
        """
        Whatever's needed to build the relevant tag for this 
        deployment
        """

        
    

class Profile:
    """
    A profile ties together a role, a deployment and an installation 
    directory. Profiles aren't dependable - they modify the builder.

    There are two things you can do to a profile: you can assume() it,
    in which case you build that profile, or you can use() it, in
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
    

                          
def add_checkout_rules(ruleset, co_name, obj):
    """
    Add the standard checkout rules to a ruleset for a checkout
    with name co_name
    """

    # This needs to be slightly clever, since uptodate, changescommitted
    # and changespushed must be transient.
    co_label = depend.Label(utils.LabelKind.Checkout, 
                            co_name, None, 
                            utils.Tags.CheckedOut)
    co_rule = depend.Rule(co_label, obj)
    ruleset.add(co_rule)
    
    uptodate_label = co_label.re_tag(utils.Tags.UpToDate, transient = True)
    rule = ruleset.rule_for_target(uptodate_label, createIfNotPresent = True)
    rule.add(co_label)

    # We actually need to ask the object whether this is a centralised 
    # or a decentralised VCS .. 
    if (obj.must_update_to_commit()):
        depend.depend_chain(obj, 
                            uptodate_label,
                            [ utils.Tags.ChangesCommitted,
                              utils.Tags.ChangesPushed ], 
                            ruleset)

    else:
        # We don't need to update to commit.
        commit_label = co_label.re_tag(utils.Tags.ChangesCommitted, 
                                       transient = True)
        depend.depend_chain(obj, 
                            commit_label,
                            [ utils.Tags.ChangesPushed ], 
                            ruleset)
        commit_rule = ruleset.rule_for_target(commit_label)
        commit_rule.add(co_label)
        update_rule = depend.Rule(uptodate_label,
                                  obj)
        update_rule.add(co_label)
        ruleset.add(update_rule)


def package_depends_on_checkout(ruleset, pkg_name, role_name, co_name, obj):
    """
    Make the given package depend on the given checkout
    """
    new_rule = depend.Rule(depend.Label(
            utils.LabelKind.Package, 
            pkg_name, role_name, 
            utils.Tags.PreConfig), 
                           obj)

    new_rule.add(depend.Label(utils.LabelKind.Checkout, 
                              co_name, None,
                              utils.Tags.CheckedOut))
    ruleset.add(new_rule)
                    

def package_depends_on_packages(ruleset, pkg_name, role, tag_name, deps):
    """
    Make pkg_name depend on the list in deps.

    pkg_name's tag_name tag ends up depending on the deps having been installed -
    this can be PreConfig or Built, depending on whether you need that dependency
    to configure yourself or not.
    """
    target_label = depend.Label(utils.LabelKind.Package,
                                pkg_name, role, tag_name)

    r = ruleset.rule_for_target(target_label, createIfNotPresent = True)

    for d in deps:
        dep_label = depend.Label(utils.LabelKind.Package,
                                 d,
                                 role, 
                                 utils.Tags.PostInstalled)
        r.add(dep_label)

    

def add_package_rules(ruleset, pkg_name, role_name, obj):
    """
    Add the standard package rules to a ruleset.
    """
    
    depend.depend_chain(obj,
                        depend.Label(utils.LabelKind.Package, 
                              pkg_name, role_name, 
                              utils.Tags.PreConfig),
                        [ utils.Tags.Configured, 
                          utils.Tags.Built,
                          utils.Tags.Installed,
                          utils.Tags.PostInstalled ], 
                        ruleset)
                             
    # Now the clean and distclean rules. These are transient,
    #  since you don't want to remember you've done it .. 
    # 
    # (and it avoids inverse rules which would be a bit
    #  urgh)
    ruleset.add(depend.depend_none
                (obj, 
                 depend.Label(utils.LabelKind.Package,
                              pkg_name, role_name, 
                              utils.Tags.Clean, 
                              transient = True)))
    ruleset.add(depend.depend_none
                (obj, 
                 depend.Label(utils.LabelKind.Package,
                              pkg_name, role_name, 
                              utils.Tags.DistClean, 
                              transient = True)))
    
    
def depend_across_roles(ruleset, pkg_name, role_name, 
                        depends_on_pkgs, depends_on_role):
    """
    Register that pkg_name{role_name}'s preconfig depends on 
    depends_on_pkg{depends_on_role} having been postinstalled
    """
    for pkg in depends_on_pkgs:
        ruleset.add(depend.depend_one(None,
                                      depend.Label(utils.LabelKind.Package,
                                                   pkg_name, role_name, 
                                                   utils.Tags.PreConfig),
                                      depend.Label(utils.LabelKind.Package,
                                                   pkg,
                                                   depends_on_role,
                                                   utils.Tags.PostInstalled)))


def set_env_for_package(builder, pkg_name, pkg_roles,
                        name, value):
    """
    Set the environment variable name to value in the given
    package built in the given roles. Useful for customising
    package behaviour in particular roles in the build
    description
    """
    
    for r in pkg_roles:
        lbl = depend.Label(utils.LabelKind.Package,
                           pkg_name, 
                           r, 
                           "*")
        env = builder.invocation.get_environment_for(lbl)
        env.set(name, value)


# End file.

    
    
    
