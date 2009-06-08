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
    depend.depend_chain(obj, 
                        depend.Label(utils.LabelKind.Checkout, 
                                     co_name, None,
                                     utils.Tags.CheckedOut, system = True),
                        [ utils.Tags.UpToDate, 
                          utils.Tags.ChangesCommitted,
                          utils.Tags.ChangesPushed ], 
                        ruleset)

    # Last, but not least, make sure we can ever check out the package.
    # An affectation, I know .. 
    ruleset.add(depend.Rule(depend.Label(utils.LabelKind.Checkout, co_name, None,
                                         utils.Tags.CheckedOut), obj))


def package_depends_on_checkout(ruleset, pkg_name, role_name, co_name, obj):
    """
    Make the given package depend on the given checkout
    """
    new_rule = depend.Rule(depend.Label(
            utils.LabelKind.Package, 
            pkg_name, role_name, 
            utils.Tags.PreConfig, system = True), 
                           obj)

    new_rule.add(depend.Label(utils.LabelKind.Checkout, 
                              co_name, None,
                              utils.Tags.UpToDate))
    ruleset.add(new_rule)
                    

def add_package_rules(ruleset, pkg_name, role_name, obj):
    """
    Add the standard package rules to a ruleset.
    """
    
    depend.depend_chain(obj,
                        depend.Label(utils.LabelKind.Package, 
                              pkg_name, role_name, 
                              utils.Tags.PreConfig, system = True),
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
                              utils.Tags.Clean, system = True, 
                              transient = True)))
    ruleset.add(depend.depend_none
                (obj, 
                 depend.Label(utils.LabelKind.Package,
                              pkg_name, role_name, 
                              utils.Tags.DistClean, system = True, 
                              transient = True)))
    
    
    



# End file.

    
    
    
