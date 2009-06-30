"""
Contains the mechanics of muddle
"""

import os
import db
import depend
import pkg
import utils
import version_control
import env_store
import instr
import traceback
import sys

class Invocation:
    """
    An invocation is the central muddle object. It holds the
    database the builder uses to perform actions on behalf
    of the user
    """
    
    def __init__(self, root_path):
        """
        Construct a fresh invocation with a muddle db at 
        the given root_path


        self.db         The metadata database for this project.
        self.checkouts  A map of name to checkout object.
        self.pkgs       Map of (package, role) -> package object.
        self.env        Map of label to environment
        self.default_roles The roles to build when you don't specify any.
        self.default_labels The list of labels to build.
        """
        self.db = db.Database(root_path)
        self.ruleset = depend.RuleSet()
        self.env = { }
        self.default_roles = [ ]
        self.default_labels = [ ]
        
    def all_checkouts(self):
        """
        Return a set of the names of all the checkouts in our rule set. 
        
        @return A set of strings.
        """
        lbl = depend.Label(utils.LabelKind.Checkout,
                           "*",
                           "*",
                           "*")
        all_labels = self.ruleset.rules_for_target(lbl)
        rv = set()
        for cur in all_labels:
            rv.add(cur.target.name)

        return rv
        

    def labels_for_role(self, kind,  role, tag):
        """
        Find all the target labels with the specified kind, role and tag and
        return them in a set.
        """
        rv = set()
        for tgt in self.ruleset.map.keys():
            #print "tgt = %s"%str(tgt)
            if (tgt.tag_kind == kind and
                tgt.role == role and
                tgt.tag == tag):
                rv.add(tgt)

        return rv


    def add_default_role(self, role):
        """
        Add role to the list of roles built when you don't ask
        for something different

        @return False if we didn't actually add the role (it was
        already there), True if we did.
        """

        for i in self.default_roles:
            if i == role:
                return False
            
        self.default_roles.append(role)
        return True

    def add_default_label(self, label):
        """
        Set the label that's built when you call muddle from the root
        directory
        """
        self.default_labels.append(label)
      

    def list_environments_for(self, label):
        """
        Return a list of environments that contribute to the environment for
        the given label.

        @return A list of triples (match level, label, environment), in order.

        """
        to_apply = [ ]
        
        for (k,v) in self.env.items():
            m = k.match(label)
            if (m is not None):
                # We matched!
                to_apply.append((m, k, v))
        
        if len(to_apply) == 0:
            # Nothing to do.
            return [ ]

        # Now sort in order of first component
        def bespoke_cmp(a,b):
            (p,q,r) = a
            (x,y,z) = b

            if (p<x):
                return -1
            elif (p>x):
                return 1
            else:
                return 0
            
        to_apply.sort(bespoke_cmp)
        return to_apply
        

    def get_environment_for(self, label):
        """
        Return the environment store for the given label, inventing one
        if necessary
        """
        if (label in self.env):
            return self.env[label]
        else:
            store = env_store.Store()
            self.env[label] = store
            return store
      
    
    def effective_environment_for(self, label):
        """
        Return an environment which embodies the settings that should be
        used for the given label. It's the in-order merge of the output
        of list_environments_for()
        """
        to_apply = self.list_environments_for(label)

        a_store = env_store.Store()

        for (lvl, label, env) in to_apply:
            a_store.merge(env)

        return a_store
        

    def setup_environment(self, label, src_env):
        """
        Modify src_env to reflect the environments which apply to label, 
        in match order.
        """
        # Form a list of pairs (prio, env) ..
        to_apply = self.list_environments_for(label)

        for (lvl, label, env) in to_apply:
            env.apply(src_env)

        # Done.
        

    def build_co_and_path(self):
        """
        Return a pair (build_co, build_path) 
        """
        build_desc = self.db.build_desc.get()

        if (build_desc is None): 
            return None

        # Split off the first         
        
        (co,path) = utils.split_path_left(build_desc)
        return (co, path)

    def checkout_path(self, co):
        """
        Return the path in which the given checkout resides. 
        if co is None, returns the root checkout path
        """
        return self.db.get_checkout_path(co)        
    
    def packages_for_checkout(self, co):
        """
        Return a set of the packages which directly use a checkout
        (this does not include dependencies)
        """
        test_label = depend.Label(utils.LabelKind.Checkout, 
                                  co, 
                                  None,
                                  "*")
        direct_deps = self.ruleset.rules_which_depend_on(test_label, useTags = False)
        pkgs = set()
        
        for rule in direct_deps:
            if (rule.target.tag_kind == utils.LabelKind.Package):
                pkgs.add(rule.target)

        return pkgs


    def package_obj_path(self, pkg, role):
        """
        Where should package pkg in role role build its object files?
        """
        p = os.path.join(self.db.root_path, "obj")
        if (pkg is not None):
            p = os.path.join(p, pkg)
            if (role is not None):
                p = os.path.join(p, role)
        
        return p
    
    def package_install_path(self, pkg, role):
        """
        Where should pkg install itself, by default?
        """
        p = os.path.join(self.db.root_path, "install")
        if (role is not None):
            p = os.path.join(p, role)
            
        return p

    def role_install_path(self, role):
        """
        Where should this role find its install to deploy?
        """
        p = os.path.join(self.db.root_path, "install")
        if (role is not None):
            p = os.path.join(p, role)

        return p

    def deploy_path(self, deploy):
        """
        Where should deployment deploy deploy to?
        
        This is slightly tricky, but it turns out that the deployment name is
        what we want.
        """
        p = os.path.join(self.db.root_path, "deploy")
        if (deploy is not None):
            p = os.path.join(p, deploy)
            
        return p
        

    def commit(self):
        """
        Commit persistent invocation state to disc
        """
        self.db.commit()
    


class Builder:
    """
    A builder performs actions on an Invocation
    """

    def __init__(self, inv, muddle_binary):
        self.invocation = inv
        self.muddle_binary = muddle_binary
        self.muddle_dir = os.path.dirname(self.muddle_binary)

    def resource_file_name(self, file_name):
        return os.path.join(self.muddle_dir, "muddled", "resources", file_name)

    def resource_body(self, file_name):
        """
        Return the body of a resource as a string
        """
        rsrc_file = self.resource_file_name(file_name)
        f = open(rsrc_file, "r")
        result = f.read()
        f.close()
        return result

    def instruct(self, pkg, role, instruction_file):
        """
        Register the existence or non-existence of an instruction file.
        If instruction_file is None, we unregister the instruction file

        @param instruction_file A db.InstructionFile object to save.
        """
        self.invocation.db.set_instructions(
            depend.Label(utils.LabelKind.Package, pkg, role, utils.Tags.Temporary), 
            instruction_file)

    def uninstruct_all(self):
        self.invocation.db.clear_all_instructions()
        
    def by_default_deploy(self, deployment):
        """
        Set your invocation's default label to be to build the 
        given deployment
        """
        label = depend.Label(utils.LabelKind.Deployment,
                             deployment,
                             None, 
                             utils.Tags.Deployed)
        self.invocation.add_default_label(label)

    def by_default_deploy_list(self, deployments):
        """
        Now we've got a list of default labels, we can just add them .. 
        """

        for d in deployments:
            dep_label = depend.Label(utils.LabelKind.Deployment,
                                     d, 
                                     None,
                                     utils.Tags.Deployed)
            self.invocation.add_default_label(dep_label)
            

    def load_instructions(self, label):
        """
        Load the instructions which apply to the given label (usually a wildcard
        on a role, from a deployment) and return a list of triples
        (label, filename, instructionfile)
        """
        instr_names = self.invocation.db.scan_instructions(label)
        return db.load_instructions(instr_names, instr.factory)

    def load_build_description(self):
        """
        Load the build description for this builder.

        This involves making sure we've checked out the build description and
        then loading it.

        @return True on success, False on failure.
        """

        
        co_path = self.invocation.build_co_and_path()
        if (co_path is None):
            return False

        (desc_co, desc_path) = co_path

        # Essentially, we register the build as a perfectly normal checkout
        # but add a dependency of loaded on checked_out and then build it .. 
        
        vcs_handler = version_control.vcs_handler_for(self.invocation,
                                                      desc_co, 
                                                      self.invocation.db.repo.get(), 
                                                      "HEAD",
                                                      desc_co)
        
        # This is a perfectly normal build .. 
        vcs = pkg.VcsCheckoutBuilder(desc_co, vcs_handler)
        pkg.add_checkout_rules(self.invocation.ruleset, desc_co, vcs)


        # But we want to load it once we've checked it out...
        checked_out = depend.Label(utils.LabelKind.Checkout, 
                                   desc_co, None, 
                                   utils.Tags.CheckedOut, 
                                   system = True)

        loaded = checked_out.re_tag(utils.Tags.Loaded, system = True, transient = True)

        loader = BuildDescriptionDependable(self, 
                                            self.invocation.db.build_desc_file_name(), 
                                            desc_co)
        self.invocation.ruleset.add(depend.depend_one(loader, 
                                                      loaded, checked_out))

        # .. and load the build description.
        self.build_label(loaded, silent = True)

        return True

    def get_dependent_package_dirs(self, label):
        """
        Find all the dependent packages for label and return a set of
        the object directories for each. Mainly used as a helper function
        by set_default_variables()
        """
        return_set = set()
        rules = depend.needed_to_build(self.invocation.ruleset, label)
        for r in rules:
            # Exclude wildcards .. 
            if (r.target.tag_kind == utils.LabelKind.Package and
                r.target.name is not None and r.target.name != "*" and 
                ((r.target.role is None) or r.target.role != "*")):

                # And don't depend on yourself.
                if (not (r.target.name == label.name and r.target.role == label.role)):
                    obj_dir = self.invocation.package_obj_path(r.target.name, 
                                                               r.target.role)                
                    return_set.add(obj_dir)

        return return_set


    def set_default_variables(self, label, store):
        """
        Set some global variables used throughout muddle
        
        MUDDLE_ROOT          Absolute path where the build tree starts.
        MUDDLE_LABEL         The label currently being built.
        MUDDLE_KIND
        MUDDLE_NAME
        MUDDLE_ROLE
        MUDDLE_TAG           Broken-down bits of the label being built
        MUDDLE_OBJ           Where we should build object files for this object -
                                the object directory for packages, the src 
                                directory for checkouts, and the deploy directory
                                for deployments.
        MUDDLE_INSTALL       Where we should install package files to, if we're 
                                a package.
        MUDDLE_DEPLOY_FROM   Where we should deploy from (probably just MUDDLE_INSTALL with
                                the last component removed)
        MUDDLE_DEPLOY_TO        Where we should deploy to, if we're a deployment.
        MUDDLE               The muddle executable itself.

        
        MUDDLE_INSTRUCT      A shortcut to the 'muddle instruct' command for this
                               package, if this is a package build. Unset otherwise.
        MUDDLE_OBJ_OBJ       $(MUDDLE_OBJ)/obj
        MUDDLE_OBJ_INCLUDE   $(MUDDLE_OBJ)/include
        MUDDLE_OBJ_LIB       $(MUDDLE_OBJ)/lib
        """
        store.set("MUDDLE_ROOT", self.invocation.db.root_path)
        store.set("MUDDLE_LABEL", label.__str__())
        store.set("MUDDLE_KIND", label.tag_kind)
        store.set("MUDDLE_NAME", label.name)
        store.set("MUDDLE", self.muddle_binary)
        if (label.role is None):
            store.erase("MUDDLE_ROLE")
        else:
            store.set("MUDDLE_ROLE",label.role)

        store.set("MUDDLE_TAG", label.tag)
        if (label.tag_kind == utils.LabelKind.Checkout):
            store.set("MUDDLE_OBJ", self.invocation.checkout_path(label.name))
        elif (label.tag_kind == utils.LabelKind.Package):
            obj_dir = self.invocation.package_obj_path(label.name, 
                                                       label.role)
            store.set("MUDDLE_OBJ", obj_dir)
            store.set("MUDDLE_OBJ_LIB", os.path.join(obj_dir, "lib"))
            store.set("MUDDLE_OBJ_INCLUDE", os.path.join(obj_dir, "include"))
            store.set("MUDDLE_OBJ_OBJ", os.path.join(obj_dir, "obj"))

            # include and library dirs are slightly interesting .. 
            dep_dirs = self.get_dependent_package_dirs(label)
            inc_dirs = [ ]
            lib_dirs = [ ]
            pkg_dirs = [ ]
            set_kernel_dir = None
            for d in dep_dirs:
                inc_dir = os.path.join(d, "include")
                if (os.path.exists(inc_dir) and os.path.isdir(inc_dir)):
                    inc_dirs.append(inc_dir)

                lib_dir = os.path.join(d, "lib")
                if (os.path.exists(lib_dir) and os.path.isdir(lib_dir)):
                    lib_dirs.append(lib_dir)

                pkg_dir = os.path.join(d, "lib/pkgconfig")
                if (os.path.exists(pkg_dir) and os.path.isdir(pkg_dir)):
                    pkg_dirs.append(pkg_dir)

                kernel_dir = os.path.join(d, "kerneldir")
                if (os.path.exists(kernel_dir) and os.path.isdir(kernel_dir)):
                    set_kernel_dir = kernel_dir
                    
            store.set("MUDDLE_INCLUDE_DIRS", 
                      " ".join(map(lambda x:utils.maybe_shell_quote(x, True), 
                                   inc_dirs)))
            store.set("MUDDLE_LIB_DIRS", 
                      " ".join(map(lambda x:utils.maybe_shell_quote(x, True), 
                                   lib_dirs)))
            store.set("MUDDLE_PKGCONFIG_DIRS", 
                      " ".join(map(lambda x:utils.maybe_shell_quote(x, True), 
                                   pkg_dirs)))

            if set_kernel_dir is not None:
                store.set("MUDDLE_KERNELDIR", 
                          set_kernel_dir)

            store.set("MUDDLE_INSTALL", self.invocation.package_install_path(label.name,
                                                                             label.role))
            # It turns out that muddle instruct and muddle uninstruct are the same thing..
            store.set("MUDDLE_INSTRUCT", "%s instruct %s{%s} "%(
                    self.muddle_binary, label.name,
                    label.role))

            store.set("MUDDLE_UNINSTRUCT", "%s instruct %s{%s} "%(
                    self.muddle_binary, label.name,
                    label.role))

        elif (label.tag_kind == utils.LabelKind.Deployment):
            store.set("MUDDLE_DEPLOY_FROM", self.invocation.role_install_path(label.role))
            store.set("MUDDLE_DEPLOY_TO", self.invocation.deploy_path(label.name))
        

    def kill_label(self, label, useTags = True, useMatch = True):
        """
        Kill everything that matches the given label and all its consequents.
        """
        
        # First, find all the labels that match this one.
        all_rules = self.invocation.ruleset.rules_for_target(label, useTags = useTags, 
                                                             useMatch = True)

        for r in all_rules:
            # Find all our depends.
            all_required = depend.required_by(self.invocation.ruleset, r.target, 
                                              useMatch = False)
            
            print "Clearing tags: %s %s"%(str(r.target), " ".join(map(str, all_required)))

            # Kill r.targt
            self.invocation.db.clear_tag(r.target)
            
            for r in all_required:
                self.invocation.db.clear_tag(r)



    def build_label(self, label, useDepends = True, useTags = True, silent = False):
        """
        The fundamental operation of a builder - build this label
        
        @param[in] useDepends   Use dependencies?
        """
        
        if useDepends:
            rule_list = depend.needed_to_build(self.invocation.ruleset, label, useTags = useTags)
        else:
            rule_list = self.invocation.ruleset.rules_for_target(label, useTags = useTags)
    
        for r in rule_list:
            # Build it.
            if (not self.invocation.db.is_tag(r.target)):
                # Don't build stuff that's already built .. 
                if (not silent):
                    print "> Building %s"%(r.target)

                # Set up the environment for building this label
                old_env = os.environ

                local_store = env_store.Store()

                # Add the default environment variables for building this label
                self.set_default_variables(r.target, local_store)
                local_store.apply(os.environ)
                
                # Add anything the rest of the system has put in.
                self.invocation.setup_environment(r.target, os.environ)
                    
                if (r.obj is not None):
                    r.obj.build_label(r.target)

                # .. and restore
                os.environ = old_env

                self.invocation.db.set_tag(r.target)
            


class BuildDescriptionDependable(pkg.Dependable):
    """
    Load the build description
    """

    def __init__(self, builder, file_name, build_co):
        self.builder = builder
        self.file_name = file_name
        self.build_co = build_co

    def build_label(self, label):
        """
        Actually load the build description into the invocation
        """
        desc = self.builder.invocation.db.build_desc_file_name()

        setup = None # To make sure it's defined.
        try:
            old_path = sys.path
            sys.path.insert(0, self.builder.invocation.checkout_path(self.build_co))
            setup = utils.dynamic_load(desc)
            setup.describe_to(self.builder)
            sys.path = old_path
        except AttributeError, a:
            if setup is None:
                traceback.print_exc()
                print "Cannot load %s - %s"%(desc, a)
            else:
                traceback.print_exc()
                print "No describe_to() attribute in module %s"%setup
                print "Available attributes: %s"%(dir(setup))
                print "Error was %s"%str(a)
                raise utils.Error("Cannot load build description %s"%setup)


def load_builder(root_path, muddle_binary):
    """
    Load a builder from the given root path
    """

    inv = Invocation(root_path)
    build = Builder(inv, muddle_binary)
    can_load = build.load_build_description()
    if (not can_load):
        return None

    inv.commit()
    return build







# End file.
        
        
        




