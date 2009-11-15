"""
Contains the mechanics of muddle.
"""

import os
import traceback
import sys

import db
import depend
import pkg
import utils
import version_control
import env_store
import instr

from utils import domain_subpath

class Invocation:
    """
    An invocation is the central muddle object. It holds the
    database the builder uses to perform actions on behalf
    of the user.
    """
    
    def __init__(self, root_path):
        """
        Construct a fresh invocation with a muddle db at 
        the given root_path.


        * self.db         - The metadata database for this project.
        * self.checkouts  - A map of name to checkout object.
        * self.pkgs       - Map of (package, role) -> package object.
        * self.env        - Map of label to environment
        * self.default_roles - The roles to build when you don't specify any.
        * self.default_labels - The list of labels to build.
        * self.banned_roles - An array of pairs of roles which aren't allowed
                             to share libraries.
        * self.domain_params - Maps domain names to dictionaries storing 
                              parameters that other domains can retrieve. This
                               is used to communicate values from a build to
                               its subdomains.
        """
        self.db = db.Database(root_path)
        self.ruleset = depend.RuleSet()
        self.env = { }
        self.default_roles = [ ]
        self.default_labels = [ ]
        self.banned_roles = [ ]
        self.domain_params = { }

    def roles_do_not_share_libraries(self,r1, r2):
        """
        Add (r1,r2) to the list of role pairs that do not share their libraries.
        """
        self.banned_roles.append((r1,r2));

    def role_combination_acceptable_for_lib(self, r1, r2):
        """
        True only if (r1,r2) does not appear in the list of banned roles.
        """

        # You're always allowed to depend on yourself unless you're
        # specifically banned from doing so.
        if (r1 == r2):
            for i in self.banned_roles:
                (a,b) = i
                if (a==r1 and b==r2):
                    return False
            return True

        for i in self.banned_roles:
            (a,b) = i
            #print "banned_roles = (%s,%s)"%(a,b)

            if (a == "*"):
                a = r1
            if (b== "*"):
                b = r2

            (c,d) = i
            if (c == "*"): 
                c = r2
            if (d == "*"):
                d = r1

            if ((a==r1 and b==r2) or (c==r2 and d==r1)):
                return False

        #print "role_combination_acceptable: %s, %s -> True"%(r1,r2)
        return True
     
    def get_domain_parameters(self, domain):
        if (domain not in self.domain_params):
            self.domain_params[domain] = { }

        return self.domain_params[domain]

    def get_domain_parameter(self, domain, name):
        parms = self.get_domain_parameters(domain)
        return parms.get(name)

    def set_domain_parameter(self, domain, name, value):
        parms = self.get_domain_parameters(domain)
        parms[name] = value

    def all_checkouts(self):
        """
        Return a set of the names of all the checkouts in our rule set. 
        
        Returns a set of strings.
        """
        lbl = depend.Label(utils.LabelKind.Checkout,
                           "*",
                           "*",
                           "*",
                           domain="*")
        all_labels = self.ruleset.rules_for_target(lbl)
        rv = set()
        for cur in all_labels:
            rv.add(cur.target.name)

        return rv

    def has_checkout_called(self, checkout):
        """
        Return True if this checkout exists, False if it doesn't.
        """
        lbl = depend.Label(utils.LabelKind.Checkout, 
                           checkout,
                           "*",
                           "*",
                           domain="*")
        all_labels = self.ruleset.rules_for_target(lbl)
        return (len(all_labels) > 0)
        

    def labels_for_role(self, kind,  role, tag):
        """
        Find all the target labels with the specified kind, role and tag and
        return them in a set.
        """
        rv = set()
        for tgt in self.ruleset.map.keys():
            #print "tgt = %s"%str(tgt)
            if (tgt.type == kind and
                tgt.role == role and
                tgt.tag == tag):
                rv.add(tgt)

        return rv


    def unify_environments(self, source, target):
        """
        Given a source label and a target label, find all the environments
        which might apply to source and make them also apply to target.
        
        This is (slightly) easier than one might imagine .. 
        """

        new_env = {}

        for (k,v) in self.env.items():
            m = k.match(source)
            if (m is not None):
                # Create an equivalent environment for target, and
                # add it if it isn't also the one we just matched.
                copied_label = k.copy()
                copied_label.unify_with(target)
                if (k.match(copied_label) is None):
                    # The altered version didn't match .. 
                    a_store = env_store.Store()

                    if (copied_label in self.env):
                        a_store.merge(self.env[copied_label])
                    if (copied_label in new_env):
                        a_store.merge(new_env[copied_label])

                    a_store.merge(v);
                    new_env[copied_label] = a_store;
        
        for (k,v) in new_env.items():
            self.env[k] = v
        

    def add_default_role(self, role):
        """
        Add role to the list of roles built when you don't ask
        for something different.

        Returns False if we didn't actually add the role (it was
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

        Returns a list of triples (match level, label, environment), in order.
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
        if necessary.
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
        of ``list_environments_for()``.
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
        Return a pair (build_co, build_path).
        """
        build_desc = self.db.build_desc.get()

        if (build_desc is None): 
            return None

        # Split off the first         
        
        (co,path) = utils.split_path_left(build_desc)
        return (co, path)

    def checkout_path(self, co, domain=None):
        """
        Return the path in which the given checkout resides. 
        if co is None, returns the root checkout path
        """
        return self.db.get_checkout_path(co, domain=domain)        
    
    def packages_for_checkout(self, co):
        """
        Return a set of the packages which directly use a checkout
        (this does not include dependencies)
        """
        test_label = depend.Label(utils.LabelKind.Checkout, 
                                  co, 
                                  None,
                                  "*",
                                  domain="*")   # XXX This is almost certainly wrong
        direct_deps = self.ruleset.rules_which_depend_on(test_label, useTags = False)
        pkgs = set()
        
        for rule in direct_deps:
            if (rule.target.type == utils.LabelKind.Package):
                pkgs.add(rule.target)

        return pkgs


    def package_obj_path(self, pkg, role, domain=None):
        """
        Where should package pkg in role role build its object files?
        """
        if domain:
            p = os.path.join(self.db.root_path, domain_subpath(domain), "obj")
        else:
            p = os.path.join(self.db.root_path, "obj")
        if (pkg is not None):
            p = os.path.join(p, pkg)
            if (role is not None):
                p = os.path.join(p, role)
        
        return p
    
    def package_install_path(self, pkg, role, domain=None):
        """
        Where should pkg install itself, by default?
        """
        if domain:
            p = os.path.join(self.db.root_path, domain_subpath(domain), "install")
        else:
            p = os.path.join(self.db.root_path, "install")
        if (role is not None):
            p = os.path.join(p, role)
            
        return p

    def role_install_path(self, role, domain=None):
        """
        Where should this role find its install to deploy?
        """
        if domain:
            p = os.path.join(self.db.root_path, domain_subpath(domain), "install")
        else:
            p = os.path.join(self.db.root_path, "install")
        if (role is not None):
            p = os.path.join(p, role)

        return p

    def deploy_path(self, deploy, domain=None):
        """
        Where should deployment deploy deploy to?
        
        This is slightly tricky, but it turns out that the deployment name is
        what we want.
        """
        if domain:
            p = os.path.join(self.db.root_path, domain_subpath(domain), "deploy")
        else:
            p = os.path.join(self.db.root_path, "deploy")
        if (deploy is not None):
            p = os.path.join(p, deploy)
            
        return p
        

    def commit(self):
        """
        Commit persistent invocation state to disc.
        """
        self.db.commit()
    


class Builder:
    """
    A builder performs actions on an Invocation.
    """

    def __init__(self, inv, muddle_binary, domain_params = None):
        """
        domain_params is the set of domain parameters in effect when
        this builder is loaded. It's used to communicate values down
        to sub-domains.
        
        Note that you MUST NOT set domain_params null unless you are
         the top-level domain - it MUST come from the enclosing
         domain's invocation or modifications made by the subdomain's
         buidler will be lost, and as this is the only way to
         communicate values to a parent domain, this would be
         bad. Ugh.
        """
        self.invocation = inv
        self.muddle_binary = muddle_binary
        self.muddle_dir = os.path.dirname(self.muddle_binary)
        if (domain_params is None):
            self.domain_params = { }
        else:
            self.domain_params = domain_params


    def get_subdomain_parameters(self, domain):
        return self.invocation.get_domain_parameters(domain)


    def get_parameter(self, name):
        """
        Returns the given domain parameter, or None if it 
        wasn't defined.
        """
        return self.domain_params.get(name)

    def set_parameter(self, name, value):
        """
        Set a domain parameter: Danger Will Robinson! This is a
         very odd thing to do - domain parameters are typically
         set by their enclosing domains. Setting your own is an
         odd idea and liable to get you into trouble. It is, 
         however, the only way of communicating values back from
         a domain to its parent (and you shouldn't really be doing
         that either!)
        """
        self.domain_params.set(name)
        

    def roles_do_not_share_libraries(self, a, b):
        """
        Assert that roles a and b do not share libraries: either a or b may be 
        * to mean wildcard
        """
        self.invocation.roles_do_not_share_libraries(a,b)

    def resource_file_name(self, file_name):
        return os.path.join(self.muddle_dir, "muddled", "resources", file_name)

    def resource_body(self, file_name):
        """
        Return the body of a resource as a string.
        """
        rsrc_file = self.resource_file_name(file_name)
        f = open(rsrc_file, "r")
        result = f.read()
        f.close()
        return result

    def instruct(self, pkg, role, instruction_file, domain=None):
        """
        Register the existence or non-existence of an instruction file.
        If instruction_file is None, we unregister the instruction file.

        * instruction_file - A db.InstructionFile object to save.
        """
        self.invocation.db.set_instructions(
            depend.Label(utils.LabelKind.Package, pkg, role,
                         utils.Tags.Temporary, domain=domain), 
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
        (label, filename, instructionfile).
        """
        instr_names = self.invocation.db.scan_instructions(label)
        return db.load_instructions(instr_names, instr.factory)

    def load_build_description(self):
        """
        Load the build description for this builder.

        This involves making sure we've checked out the build description and
        then loading it.

        Returns True on success, False on failure.
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

    def unify_labels(self, source, target):
        """
        Given a source and target label, unify them. Free variables (i.e. wildcards in the
        labels) are untouched - see depend for quite how this works.
        """
        self.invocation.ruleset.unify(source, target)
        self.invocation.unify_environments(source,target)

    def get_dependent_package_dirs(self, label):
        """
        Find all the dependent packages for label and return a set of
        the object directories for each. Mainly used as a helper function
        by ``set_default_variables()``.
        """
        return_set = set()
        rules = depend.needed_to_build(self.invocation.ruleset, label)
        for r in rules:
            # Exclude wildcards .. 
            if (r.target.type == utils.LabelKind.Package and
                r.target.name is not None and r.target.name != "*" and 
                ((r.target.role is None) or r.target.role != "*") and
                (self.invocation.role_combination_acceptable_for_lib(label.role, r.target.role))):

                # And don't depend on yourself.
                if (not (r.target.name == label.name and r.target.role == label.role)):
                    obj_dir = self.invocation.package_obj_path(r.target.name, 
                                                               r.target.role,
                                                               r.target.domain)
                    return_set.add(obj_dir)

        return return_set


    def set_default_variables(self, label, store):
        """
        Set some global variables used throughout muddle.
        
        ``MUDDLE_ROOT``
            Absolute path where the build tree starts.
        ``MUDDLE_LABEL``
            The label currently being built.
        ``MUDDLE_KIND``, ``MUDDLE_NAME``, ``MUDDLE_ROLE``, ``MUDDLE_TAG``, ``MUDDLE_DOMAIN``
            Broken-down bits of the label being built
        ``MUDDLE_OBJ``
            Where we should build object files for this object - the object
            directory for packages, the src directory for checkouts, and the
            deploy directory for deployments.
        ``MUDDLE_INSTALL``
            Where we should install package files to, if we're a package.
        ``MUDDLE_DEPLOY_FROM``
            Where we should deploy from (probably just ``MUDDLE_INSTALL`` with
            the last component removed)
        ``MUDDLE_DEPLOY_TO``
            Where we should deploy to, if we're a deployment.
        ``MUDDLE``
            The muddle executable itself.
        ``MUDDLE_INSTRUCT``
            A shortcut to the 'muddle instruct' command for this package, if
            this is a package build. Unset otherwise.
        ``MUDDLE_OBJ_OBJ``
            ``$(MUDDLE_OBJ)/obj``
        ``MUDDLE_OBJ_INCLUDE``
            ``$(MUDDLE_OBJ)/include``
        ``MUDDLE_OBJ_LIB``
            ``$(MUDDLE_OBJ)/lib``
        """
        store.set("MUDDLE_ROOT", self.invocation.db.root_path)
        store.set("MUDDLE_LABEL", label.__str__())
        store.set("MUDDLE_KIND", label.type)
        store.set("MUDDLE_NAME", label.name)
        store.set("MUDDLE", self.muddle_binary)
        if (label.role is None):
            store.erase("MUDDLE_ROLE")
        else:
            store.set("MUDDLE_ROLE",label.role)
        if (label.domain is None):
            store.erase("MUDDLE_DOMAIN")
        else:
            store.set("MUDDLE_DOMAIN",label.domain)

        store.set("MUDDLE_TAG", label.tag)
        if (label.type == utils.LabelKind.Checkout):
            store.set("MUDDLE_OBJ", self.invocation.checkout_path(label.name,
                                                                  label.domain))
        elif (label.type == utils.LabelKind.Package):
            obj_dir = self.invocation.package_obj_path(label.name, 
                                                       label.role,
                                                       label.domain)
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
            set_ksource_dir = None
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

                ksource_dir = os.path.join(d, "kernelsource")
                if (os.path.exists(ksource_dir) and os.path.isdir(ksource_dir)):
                    set_ksource_dir = ksource_dir
                    
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
                store.set("MUDDLE_KERNEL_DIR", 
                          set_kernel_dir)

            if set_ksource_dir is not None:
                store.set("MUDDLE_KERNEL_SOURCE_DIR", 
                          set_ksource_dir)

            store.set("MUDDLE_INSTALL", self.invocation.package_install_path(label.name,
                                                                             label.role,
                                                                             label.domain))
            # It turns out that muddle instruct and muddle uninstruct are the same thing..
            store.set("MUDDLE_INSTRUCT", "%s instruct %s{%s} "%(
                    self.muddle_binary, label.name,
                    label.role))

            store.set("MUDDLE_UNINSTRUCT", "%s instruct %s{%s} "%(
                    self.muddle_binary, label.name,
                    label.role))

        elif (label.type == utils.LabelKind.Deployment):
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
        The fundamental operation of a builder - build this label.
        
        * useDepends - Use dependencies?
        """
        
        if useDepends:
            rule_list = depend.needed_to_build(self.invocation.ruleset, label, useTags = useTags, 
                                               useMatch = True)
        else:
            rule_list = self.invocation.ruleset.rules_for_target(label, useTags = useTags, 
                                                                 useMatch = True)
    
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
    Load the build description.
    """

    def __init__(self, builder, file_name, build_co):
        self.builder = builder
        self.file_name = file_name
        self.build_co = build_co

    def build_label(self, label):
        """
        Actually load the build description into the invocation.
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


def load_builder(root_path, muddle_binary, params = None):
    """
    Load a builder from the given root path.
    """

    inv = Invocation(root_path)
    build = Builder(inv, muddle_binary, params)
    can_load = build.load_build_description()
    if (not can_load):
        return None

    inv.commit()
    return build




# =============================================================================
# Following is an initial implementation of sub-build or domain inclusion
# Treat it with caution...

def _init_without_build_tree(muddle_binary, root_path, repo_location, build_desc, 
                             domain_params):
    """
    This a more-or-less copy of the code from muddle.command.Init's
    without_build_tree() method, for purposes of my own convenience.

    I'm ignoring the "no op" case, which will need dealing with later on.

    Or at least that's how it started...

    * 'muddle_binary' is the full path to the ``muddle`` script (for use in
      environment variables)
    * 'root_path' is the directory in which the build tree is being created
      (thus, where the ``.muddle`` directory, the ``src`` directory, etc.,
      are being created). For ``muddle init`` (and thus the "main" build),
      this is the directory in which the command is being run.
    * 'repo_location' is the string defining the repository for this build.
    * 'build_desc' is then the path to the build description, within that.

    We return the new Builder instance for this build.

    For example, for a main build, if we do::

        $ which muddle
        /home/tibs/sw/muddle/muddle
        $ mkdir /home/tibs/sw/beagle
        $ cd beagle
        $ muddle init bzr+file:///home/tibs/repositories/m0.beagle/ builds/01.py

    Then we would have:

      =============    =================================================
      muddle_binary    ``/home/tibs/sw/muddle/muddle``
      root_path        ``/home/tibs/sw/beagle``
      repo_location    ``bzr+file:///home/tibs/repositories/m0.beagle/``
      build_desc       ``builds/01.py``
      =============    =================================================
    """

    database = db.Database(root_path)
    database.repo.set(repo_location)
    database.build_desc.set(build_desc)
    database.commit()

    print "Initialised build tree in %s "%root_path
    print "Repository: %s"%repo_location
    print "Build description: %s"%build_desc
    print "\n"

    print "Checking out build description .. \n"
    return load_builder(root_path, muddle_binary, domain_params)


def _new_sub_domain(root_path, muddle_binary, domain_name, domain_repo, domain_build_desc, 
                    parent_domain):
    """
    * 'muddle_binary' is the full path to the ``muddle`` script (for use in
      environment variables)
    * 'root_path' is the directory of the main build tree (the directory
      containing its ``.muddle`` directory, ``src`` directory, etc.).
    * 'domain_name' is the name of the (sub) domain
    * 'domain_repo' is the string defining the repository for the domain's
      sub-build.
    * 'domain_build_desc' is then the path to the domain's build description,
      within that.

    Really.
    """

    # Check our domain name is legitimate
    try:
        depend.Label._check_part('dummy',domain_name)
    except utils.Failure:
        raise utils.Failure('Domain name "%s" is not valid'%domain_name)

    # So, we're wanting our sub-builds to go into the 'domains/' directory
    domain_root_path = os.path.join(root_path, 'domains', domain_name)

    # Extract the domain parameters .. 
    domain_params = parent_domain.invocation.get_domain_parameters(domain_name)

    # Did we already retrieve it, earlier on?
    # muddle itself just does::
    #
    #    muddled.utils.find_root(specified_root)
    #
    # to see if it has a build present (i.e., looking up-tree). That's essentially
    # just a search for a .muddle directory. So a similarly simple algorithm to
    # decide if our sub-build is present *should* be enough
    if os.path.exists(domain_root_path) and \
       os.path.exists(os.path.join(domain_root_path,'.muddle')):
        domain_builder = load_builder(domain_root_path,
                                      muddle_binary, 
                                      domain_params)
    else:
        os.makedirs(domain_root_path)
        domain_builder = _init_without_build_tree(muddle_binary, domain_root_path,
                                                  domain_repo, domain_build_desc, 
                                                  domain_params)

    # Then we need to tell all of the labels in that build that they're
    # actually in the new domain (this is the fun part(!))
    #
    # We *should* just need to change (all of) the labels in the builds rule
    # set...
    #
    # It should help that we *know* (!) that all of the labels do not yet have
    # a domain

    # First, find all our labels.
    # Beware that we want to get labels that compare identically but are not
    # the same object, so we are willing to have an instance in our list more
    # than once.
    labels = []

    for l in domain_builder.invocation.default_labels:
        labels.append(l)

    env = domain_builder.invocation.env
    for l in env.keys():
        labels.append(l)

    ruleset = domain_builder.invocation.ruleset

    for rule in ruleset.map.values():
        labels.append(rule.target)
        for l in rule.deps:
            labels.append(l)

    # Then, mark them all as "unchanged" (because we can't guarantee we won't
    # have the same label more than once, and it's easier to do this than to
    # try to remove repeated instances)
    for l in labels:
        l._mark_unswept()

    # Then add the (new) domain name to every one (but the mark allows us to do
    # this only once if a label *does* repeat). As a side effect of that, all
    # labels in a sub-build (sub-domain) end up with a flag indicating as much,
    # which is redundant given we could just check to see if label.domain was
    # set, but might perhaps be useful somehow later on...
    for l in labels:
        l._change_domain(domain_name)

    return domain_builder

def include_domain(builder, domain_name, domain_repo, domain_desc):
    """
    Include the named domain as a sub-build of this builder.

    * 'domain_name' is the name of the domain
    * 'domain_repo' is the string defining the repository for the domain's
      build.
    * 'domain_build_desc' is then the path to the domain's build description,
      within that.

    If the domain has not yet been retrieved from 'domain_repo' (more
    specifically, if ``domains/<domain_name>/.muddle/`` doesn't yet exist),
    then it will be retrieved. This will normally happen when ``muddle init``
    is done.
    """
    domain_builder = _new_sub_domain(builder.invocation.db.root_path,
                                     builder.muddle_binary,
                                     domain_name,
                                     domain_repo,
                                     domain_desc, 
                                     parent_domain = builder)
    
    # And make sure we merge its rules into ours...
    builder.invocation.ruleset.merge(domain_builder.invocation.ruleset)

    # And its environments...
    for key, value in domain_builder.invocation.env.items():
        builder.invocation.env[key] = value


    return domain_builder


# End file.
