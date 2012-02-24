"""
Contains the mechanics of muddle.
"""

import os
import re
import sys
import traceback

import muddled.db as db
import muddled.depend as depend
import muddled.pkg as pkg
import muddled.utils as utils
import muddled.env_store as env_store
import muddled.instr as instr

from muddled.depend import Label, Action
from muddled.utils import domain_subpath, GiveUp, MuddleBug, LabelType, LabelTag
from muddled.repository import Repository
from muddled.version_control import split_vcs_url, checkout_from_repo

build_name_re = re.compile(r"[A-Za-z0-9_-]+")

def check_build_name(name):
    """Check a build name for legality.

    Raises a GiveUp exception if the name is not allowed.
    """
    m = build_name_re.match(name)
    if m is None or m.end() != len(name):
        raise GiveUp("Build name '%s' is not allowed (it may only contain"
                     " 'A'-'Z', 'a'-'z', '0'-'9', '_' or '-')"%name)

class Invocation(object):
    """
    An invocation is the central muddle object. It holds the
    database the builder uses to perform actions on behalf
    of the user.
    """

    def __init__(self, root_path):
        """
        Construct a fresh invocation with a .muddle directory at the given
        root_path.

        * self.db         - The metadata database for this project.
        * self.ruleset    - The rules describing this build
        * self.env        - A dictionary of label to environment
        * self.default_roles - The roles to build when you don't specify any.
        * self.default_deployment_labels - The deployments to deploy ditto
        * self.banned_roles - An array of pairs of the form (role, domain)
          which aren't allowed to share libraries.
        * self.domain_params - Maps domain names to dictionaries storing
          parameters that other domains can retrieve. This is used to
          communicate values from a build to its subdomains.
        * self.unifications - This is a list of tuples of the form
          (source-label, target-label), where one "replaces" the other in the
          build tree.
        """
        self.db = db.Database(root_path)
        self.ruleset = depend.RuleSet()
        self.env = {}
        self.default_roles = []
        self.default_deployment_labels = []
        self.banned_roles = []
        self.domain_params = {}
        self.unifications = []

    def note_unification(self, source, target):
        self.unifications.append( (source, target) )

    def map_unifications(self, source_list):
        result = [ ]
        for s in source_list:
            result.append(self.apply_unifications(s))

        return result

    def apply_unifications(self, source):
        for i in self.unifications:
            (s,t) = i
            #print "(s,t) = (%s,%s)"%(s,t)
            if (source.unifies(s)):
                copied = source.copy_and_unify_with(t)
                return copied

        return source

    def mark_domain(self, domain_name):
        """
        Write a file that marks this directory as a domain so we don't
        mistake it for the root.
        """
        self.db.set_domain_marker(domain_name)

    def include_domain(self, domain_builder, domain_name):
        """
        Import the builder domain_builder into the current invocation, giving it
        domain_name.

        We first import the db, then we rename None to domain_name in
        banned_roles, then we sort out the not_built_against dictionary
        """
        self.db.include_domain(domain_builder, domain_name)
        for r in domain_builder.invocation.banned_roles:
            (a,d1,b,d2) = r
            if (d1 == None):
                d1 = domain_name

            # This is a bit of a hack - it ensures that just because r1 in d1
            # doesn't share with r2 in d1, it also doesn't share with r2 in d2 -
            # preventing accidental sharing leakage. Ugh.
            #
            # - rrw 2009-11-24
            if (d2 == None):
                d2 = "*"

            self.banned_roles.append((a,d1,b,d2))

    def roles_do_not_share_libraries(self,r1, r2, domain1 = None, domain2 = None):
        """
        Add (r1,r2) to the list of role pairs that do not share their libraries.
        """
        self.banned_roles.append((r1,domain1, r2,domain2))

    def print_banned_roles(self):
        print "[ "
        for j in self.banned_roles:
            (a,b,c,d) = j
            print " - ( %s, %s, %s, %s ) "%(a,b,c,d)
        print "]"

    def role_combination_acceptable_for_lib(self, r1, r2, domain1 = None, domain2 = None):
        """
        True only if (r1,r2) does not appear in the list of banned roles.
        """

        #self.print_banned_roles()
        # You're always allowed to depend on yourself unless you're
        # specifically banned from doing so.
        if (r1 == r2):
            for i in self.banned_roles:
                (a,d1,b,d2) = i
                if (a==r1 and b==r2 and d1 == domain1 and d2 == domain2):
                    return False
            return True

        for i in self.banned_roles:
            (a,d1,b,d2) = i
            #print "banned_roles = (%s,%s)"%(a,b)

            if (a == "*"):
                a = r1
            if (b== "*"):
                b = r2

            if (d1 == "*"):
                d1 = domain1
            if (d2 == "*"):
                d2 = domain2

            (c,d3,d,d4) = i
            if (c == "*"):
                c = r2
            if (d == "*"):
                d = r1

            if (d3 == "*"):
                d3 = domain1

            if (d4 == "*"):
                d4 = domain2

            if ((a==r1 and b==r2 and d1 == domain1 and d2 == domain2) or
                (c==r2 and d==r1 and d3 == domain1 and d4 == domain2)):
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

        This is not domain aware. Consider using all_checkout_labels(),
        which is.
        """
        lbl = Label(LabelType.Checkout, "*", domain="*")
        all_rules = self.ruleset.rules_for_target(lbl)
        rv = set()
        for cur in all_rules:
            rv.add(cur.target.name)
        return rv

    def all_checkout_labels(self, tag=None):
        """
        Return a set of the labels of all the checkouts in our rule set.

        Note that if 'tag' is None then all the labels will be of the form:

            checkout:<co_name>/*

        otherwise 'tag' will be used as the checkout label tag:

            checkout:<co_name>/<tag>
        """
        lbl = Label(LabelType.Checkout, "*", domain="*")
        all_rules = self.ruleset.rules_for_target(lbl)
        all_labels = set()
        if tag is None:
            required_tag = '*'
        else:
            required_tag = tag
        for cur in all_rules:
            lbl = cur.target
            #vanilla = lbl.copy_with_tag(LabelTag.CheckedOut)
            vanilla = lbl.copy_with_tag(required_tag)
            all_labels.add(vanilla)
        return all_labels

    def all_domains(self):
        """
        Return a set of the names of all the domains in our rule set.

        Returns a set of strings. The 'None' domain (the unnamed, top-level
        domain) is returned as the empty string, "".
        """
        lbl = Label(LabelType.Package, "*", "*", "*", domain="*")
        all_labels = self.ruleset.rules_for_target(lbl)
        rv = set()
        for cur in all_labels:
            domain = cur.target.domain
            if domain:
                rv.add(domain)
            else:
                rv.add('')
        return rv

    def all_packages(self):
        """
        Return a set of the names of all the packages in our rule set.

        Returns a set of strings.

        Note that if '*' is one of the package "names" in the ruleset,
        then it will be included in the names returned.
        """
        lbl = Label(LabelType.Package, "*", "*", "*", domain="*")
        all_labels = self.ruleset.rules_for_target(lbl)
        rv = set()
        for cur in all_labels:
            rv.add(cur.target.name)
        return rv

    def all_package_labels(self):
        """
        Return a set of the labels of all the packages in our rule set.
        """
        lbl = Label(LabelType.Package, "*", "*", "*", domain="*")
        all_rules = self.ruleset.rules_for_target(lbl)
        rv = set()
        for rule in all_rules:
            rv.add(rule.target)
        return rv

    def all_deployments(self):
        """
        Return a set of the names of all the deployments in our rule set.

        Returns a set of strings.
        """
        lbl = Label(LabelType.Deployment, "*", None, "*", domain="*")
        all_labels = self.ruleset.rules_for_target(lbl)
        rv = set()
        for cur in all_labels:
            rv.add(cur.target.name)
        return rv

    def all_deployment_labels(self):
        """
        Return a set of all the deployment labels in our rule set.
        """
        lbl = Label(LabelType.Deployment, "*", None, "*", domain="*")
        all_labels = self.ruleset.rules_for_target(lbl)
        rv = set()
        for cur in all_labels:
            rv.add(cur.target)
        return rv

    def all_packages_with_roles(self):
        """
        Return a set of the names of all the packages/roles in our rule set.

        Returns a set of strings.

        Note that if '*' is one of the package "names" in the ruleset,
        then it will be included in the names returned.

        However, any labels with role '*' will be ignored.
        """
        rv = set()
        for role in self.all_roles():
            if role == '*':
                continue
            lbl = Label(LabelType.Package, "*", role, "*", domain="*")
            all_rules = self.ruleset.rules_for_target(lbl)
            for cur in all_rules:
                lbl = cur.target
                if lbl.domain:
                    rv.add('(%s)%s{%s}'%(lbl.domain, lbl.name, role))
                else:
                    rv.add('%s{%s}'%(lbl.name,role))
        return rv

    def all_roles(self):
        """
        Return a set of the names of all the roles in our rule set.

        Returns a set of strings.
        """
        lbl = Label(LabelType.Package, "*", "*", "*", domain="*")
        all_labels = self.ruleset.rules_for_target(lbl)
        rv = set()
        for cur in all_labels:
            rv.add(cur.target.role)
        return rv

    def all_checkout_rules(self):
        """
        Returns a set of the labels of all the checkouts in our rule set.

        Specifically, all the rules for labels of the form::

            checkout:*{*}/checked_out
            checkout:(*)*{*}/checked_out

        Returns a set of labels, thus allowing one to know the domain of
        each checkout as well as its name.
        """
        lbl = Label(LabelType.Checkout, "*", None,
                    LabelTag.CheckedOut, domain="*")
        all_rules = self.ruleset.rules_for_target(lbl)
        rv = set()
        rv.update(all_rules)
        return rv

    def target_label_exists(self, label):
        """
        Return True if this label is a target.

        If it is not, then we are not going to be able to build it.

        Note that this method does not understand wildcards, so the match
        must be exact.
        """
        return label in self.ruleset.map.keys()

    def checkout_label_exists(self, label):
        """
        Return True if this checkout label is in any rules (i.e., is used).

        Note that this method does not understand wildcards, so the match
        must be exact.
        """
        all_labels = self.ruleset.rules_for_target(label)
        return len(all_labels) > 0

    def labels_for_role(self, kind,  role, tag, domain=None):
        """
        Find all the target labels with the specified kind, role and tag and
        return them in a set.

        If 'domain' is specified, also require the domain to match.
        """
        rv = set()
        for tgt in self.ruleset.map.keys():
            #print "tgt = %s"%str(tgt)
            if tgt.type == kind and tgt.role == role and tgt.tag == tag:
                if domain and tgt.domain != domain:
                    continue
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
            if (k.unifies(source)):
                # Create an equivalent environment for target, and
                # add it if it isn't also the one we just matched.
                copied_label = k.copy_and_unify_with(target)
                if (k.match(copied_label) is None):
                    # The altered version didn't match ..
                    a_store = env_store.Store()

                    if (copied_label in self.env):
                        a_store.merge(self.env[copied_label])
                    if (copied_label in new_env):
                        a_store.merge(new_env[copied_label])

                    a_store.merge(v)
                    new_env[copied_label] = a_store

        for (k,v) in new_env.items():
            self.env[k] = v


    def add_default_role(self, role):
        """
        Add role to the list of roles built when you don't ask
        for something different.

        Returns False if we didn't actually add the role (it was
        already there), True if we did.
        """

        if role in self.default_roles:
            return False

        self.default_roles.append(role)
        return True

    def add_default_deployment_label(self, label):
        """
        Set the label that's built when you call muddle from the root
        directory
        """
        if label.type != LabelType.Deployment:
            raise MuddleBug('Attempt to add label %s to default deployments'%label)

        self.default_deployment_labels.append(label)

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

        return build_co_and_path_from_str(build_desc)

    def dump_checkout_paths(self):
        return self.db.dump_checkout_paths()

    def checkout_path(self, label):
        """
        Return the path in which the given checkout resides.
        If 'label' is None, returns the root checkout path

        TODO: No-one uses (I hope) the "None" variant of this call.
        Deprecate it, extirpate it, please...
        """
        if label:
            assert label.type == LabelType.Checkout
            return self.db.get_checkout_path(label)
        else:
            return self.db.get_checkout_path(None)

    def packages_using_checkout(self, co_label):
        """
        Return a set of the packages which directly use a checkout
        (this does not include dependencies)
        """
        direct_deps = self.ruleset.rules_which_depend_on(co_label, useTags = False)
        pkgs = set()

        for rule in direct_deps:
            if (rule.target.type == LabelType.Package):
                pkgs.add(rule.target)

        return pkgs

    def checkouts_for_package(self, pkg_label):
        """
        Return a set of the checkouts that the given package depends upon

        This only looks at *direct* dependencies (so if a package depends
        on something that in turn depends on a checkout that it does not
        directly depend on, then that indirect checkout will not be returned).

        It does, however, expand wildcards.
        """
        # A normal package/checkout dependency has the package's PreConfig
        # tagged label depend upon the checkouts CheckedOut tagged label.
        # So that would be the obvious thing to look for. However, for safety,
        # (if not speed) we shall look for ANY checkouts this package depends
        # on, by ignoring the labels tag.

        rules = self.ruleset.rules_for_target(pkg_label,
                                              useTags=False,    # ignore the tag
                                              useMatch=False)   # we don't need wildcarding

        checkouts = set()
        for rule in rules:
            for lbl in rule.deps:
                if lbl.type == LabelType.Checkout:
                    if lbl.is_wildcard():
                        checkouts.update(self.expand_wildcards(lbl))
                    else:
                        checkouts.add(lbl)

        return checkouts

    def packages_for_deployment(self, dep_label):
        """
        Return a set of the packages that the given deployment depends upon

        This only looks at *direct* dependencies (so if a deployment depends
        on something that in turn depends on a package that it does not
        directly depend on, then that indirect package will not be returned).

        It does, however, expand wildcards.
        """
        rules = self.ruleset.rules_for_target(dep_label,
                                              useTags=False,    # ignore the tag
                                              useMatch=False)   # we don't need wildcarding

        packages = set()
        for rule in rules:
            for lbl in rule.deps:
                if lbl.type == LabelType.Package:
                    if lbl.is_wildcard():
                        packages.update(self.expand_wildcards(lbl))
                    else:
                        packages.add(lbl)

        return packages

    def package_obj_path(self, label):
        """
        Where should the package with this label build its object files?
        """
        assert label.type == LabelType.Package
        if label.domain:
            p = os.path.join(self.db.root_path, domain_subpath(label.domain), "obj")
        else:
            p = os.path.join(self.db.root_path, "obj")
        if label.name:
            p = os.path.join(p, label.name)
            if label.role:
                p = os.path.join(p, label.role)
        return p

    def package_install_path(self, label):
        """
        Where should pkg install itself, by default?
        """
        assert label.type == LabelType.Package
        # Actually, which package it is doesn't matter
        if label.role == '*':
            return self.role_install_path(None, label.domain)
        else:
            return self.role_install_path(label.role, label.domain)

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

    def label_from_fragment(self, fragment, default_type):
        """A variant of Label.from_fragment that understands types and wildcards

        In particular, it knows that:

        1. packages have roles, but checkouts and deployments do not.
        2. wildcards expand to their appropriate values

        Returns a list of labels. This method does not check that all of the
        labels returned actually exist as targets in the dependency tree.
        """
        label = Label.from_fragment(fragment,
                                    default_type=default_type,
                                    default_role=None,
                                    default_domain=None)
        labels = []
        if label.type == LabelType.Package and label.role is None and self.default_roles:
            for role in self.default_roles:
                label = label.copy_with_role(role)
                labels.append(label)
        else:
            labels.append(label)

        return_list = []
        for label in labels:
            if label.is_wildcard():
                return_list.extend(self.expand_wildcards(label))
            else:
                return_list.append(label)
        return return_list

    def expand_wildcards(self, label, default_to_obvious_tag=True):
        """
        Given a label which may contain wildcards, return a set of labels that match.

        As per the normal definition of labels, the <type>, <name>, <role> and
        <tag> parts of the label may be wildcarded.

        If default_to_obvious_tag is true, then if label has a tag of '*', it
        will be replaced by the "obvious" (final) tag for this label type,
        before any searching (so for a checkout: label, /checked_out would
        be used).
        """

        if label.is_definite():
            # There are no wildcards - it matches itself
            # (should we check if it exists?)
            return set([label])

        if default_to_obvious_tag and label.tag == '*':
            tag = utils.package_type_to_tag[label.type]
            label = label.copy_with_tag(tag)

        return self.ruleset.targets_match(label)

class Builder(object):
    """
    A builder performs actions on an Invocation.
    """

    def __init__(self, inv, muddle_binary, domain_params = None,
                 default_domain = None):
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

        default_domain is the default domain value to add to anything
        in local_pkgs , etc - it's used to make sure that if you're
        cd'd into a domain subdirectory, we build the right labels.

        """
        self.invocation = inv
        # The 'muddle_binary' is what will be run when the user does
        # $(MUDDLE) inside a makefile. Obviously our caller has to
        # decide this.
        self.muddle_binary = muddle_binary
        # The 'muddled_dir' is the directory of our package itself
        # (which we need to find the resources inside this package,
        # for instance). This is most easily taken from the location
        # of *this* module, as we're running it.
        self.muddled_dir = os.path.split(os.path.abspath(__file__))[0]

        # XXX Check the utility of this
        self.default_domain = default_domain

        if (domain_params is None):
            self.domain_params = { }
        else:
            self.domain_params = domain_params

        # Guess a default build name
        # Whilst the build description filename should be a legal Python
        # module name (and thus only include alphanumerics and underscores),
        # and thus also be a legal build name, we shall be cautious and
        # assign it directly to self._build_name (thus not checking), rather
        # than assigning to the property self.build_name (which would check).
        build_desc = inv.db.build_desc.get()
        build_fname = os.path.split(build_desc)[1]
        self._build_name = os.path.splitext(build_fname)[0]

        # It's useful to know our build description's Repository
        # Should this be kept in our Invocation?
        self.build_desc_repo = None

        # The current distribution name and target directory, as a tuple,
        # or actually None, since we've not set it yet
        # directory with each...
        self.distribution = None

    def get_subdomain_parameters(self, domain):
        return self.invocation.get_domain_parameters(domain)


    def get_default_domain(self):
        return self.default_domain

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
        self.domain_params[name] = value

    def set_distribution(self, name, target_dir):
        """Set the current distribution name and target directory.
        """
        self.distribution = (name, target_dir)

    def get_distribution(self):
        """Retrieve the current distribution name and target directory.

        Raises GiveUp if there is no current distribution set.
        """
        if self.distribution:
            return self.distribution
        else:
            raise GiveUp('No distribution name or target directory set')

    def roles_do_not_share_libraries(self, a, b):
        """
        Assert that roles a and b do not share libraries: either a or b may be
        * to mean wildcard
        """
        self.invocation.roles_do_not_share_libraries(a,b)

    def resource_file_name(self, file_name):
        return os.path.join(self.muddled_dir, "resources", file_name)

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
            Label(LabelType.Package, pkg, role,
                  LabelTag.Temporary, domain=domain),
            instruction_file)

    def uninstruct_all(self):
        self.invocation.db.clear_all_instructions()

    def by_default_deploy(self, deployment):
        """
        Set your invocation's default label to be to build the
        given deployment
        """
        label = Label(LabelType.Deployment, deployment, None, LabelTag.Deployed)
        self.invocation.add_default_deployment_label(label)

    def by_default_deploy_list(self, deployments):
        """
        Now we've got a list of default labels, we can just add them ..
        """

        for d in deployments:
            dep_label = Label(LabelType.Deployment, d, None, LabelTag.Deployed)
            self.invocation.add_default_deployment_label(dep_label)

    def add_default_roles(self, roles):
        """
        Add the given roles to the list of default roles for this build.
        """
        for r in roles:
            self.invocation.add_default_role(r)

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

        # The build description is a bit odd, but we still set it up as a
        # normal checkout (albeit we check it out ourselves)

        co_path = self.invocation.build_co_and_path()
        if (co_path is None):
            return False

        # That gives us the checkout name (assumed the first element of the
        # path we were given in the .muddled/Description file), and where we
        # keep our build description therein (which we aren't interested in)
        (build_co_name, build_desc_path) = co_path

        # And we're going to want its Repository later on, to use as the basis
        # for other (relative) checkouts
        build_repo = self.invocation.db.repo.get()
        vcs, base_url = split_vcs_url(build_repo)

        if not vcs:
            raise GiveUp('Build description URL must be of the form <vcs>+<url>, not'
                         '\n  "%s"'%build_repo)

        # For the moment (and always as default) we just use the simplest
        # possible interpretation of that as a repository - i.e., build
        # descriptions have to be simple top-level repositories at the
        # base_url location, named by their checkout name.
        repo = Repository(vcs, base_url, build_co_name)
        # Remember this specifically as the "default" repository
        self.build_desc_repo = repo

        co_label = Label(LabelType.Checkout, build_co_name, None,
                         LabelTag.CheckedOut, domain=self.default_domain)

        # But is it also a perfectly normal build ..
        checkout_from_repo(self, co_label, repo)

        # Although we want to load it once we've checked it out...
        checked_out = Label(LabelType.Checkout, build_co_name, None,
                            LabelTag.CheckedOut, domain=self.default_domain,
                            system=True)

        loaded = checked_out.copy_with_tag(LabelTag.Loaded, system=True, transient=True)
        loader = BuildDescriptionAction(self.invocation.db.build_desc_file_name(),
                                        build_co_name)
        self.invocation.ruleset.add(depend.depend_one(loader, loaded, checked_out))

        # .. and load the build description.
        try:
            self.build_label(loaded, silent=True)
        except Exception:
            raise GiveUp('Error in build description\n%s'%traceback.format_exc())

        return True

    def unify_labels(self, source, target):
        """
        Unify the 'source' label with/into the 'target' label.

        Given a dependency tree containing rules to build both 'source' and
        'target', this edits the tree such that the any occurrences of 'source'
        are replaced by 'target', and dependencies are merged as appropriate.

        Free variables (i.e. wildcards in the labels) are untouched - if you
        need to understand that, see depend.py for quite how this works.

        Why is it called "unify" rather than "replace"? Mainly because it
        does more than replacement, as it has to merge the rules/dependencies
        together. In retrospect, though, some variation on "merge" might have
        been easier to remember (if also still inaccurate).
        """
        if not self.invocation.target_label_exists(source):
            raise GiveUp('Cannot unify source label %s which does not exist'%source)
        if not self.invocation.target_label_exists(target):
            raise GiveUp('Cannot unify target label %s which does not exist'%target)

        self.invocation.ruleset.unify(source, target)
        self.invocation.unify_environments(source,target)
        self.invocation.note_unification(source, target)


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
            if (r.target.type == LabelType.Package and
                r.target.name is not None and r.target.name != "*" and
                ((r.target.role is None) or r.target.role != "*") and
                (self.invocation.role_combination_acceptable_for_lib(label.role, r.target.role,
                                                                     label.domain, r.target.domain))):

                # And don't depend on yourself.
                if (not (r.target.name == label.name and r.target.role == label.role)):
                    obj_dir = self.invocation.package_obj_path(r.target)
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
        ``MUDDLE_PKGCONFIG_DIRS``
            Sets pkg-config to look only at packages we are declared to be
            dependent on, or none if there are not declared dependencies.
        ``MUDDLE_PKGCONFIG_DIRS_AS_PATH``
            The same values as in ``MODULE_PKGCONFIG_DIRS``, but with items
            separated by colons.
        ``MUDDLE_LD_LIBRARY_PATH``
            The same values as in ``MUDDLE_LIB_DIRS``, but with items separated
            by colons. This is useful for passing (as LD_LIBRARY_PATH) to
            configure scripts that try to look for libraries when linking test
            programs.
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
        if (label.type == LabelType.Checkout):
            store.set("MUDDLE_OBJ", self.invocation.checkout_path(label))
        elif (label.type == LabelType.Package):
            obj_dir = self.invocation.package_obj_path(label)
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

                # Yes, I know, but some debian packages do ..
                pkg_dir = os.path.join(d, "share/pkgconfig")
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
            store.set("MUDDLE_LD_LIBRARY_PATH",
                      ":".join(lib_dirs))
            # pkg-config takes ':' separated paths and wraps single quotes around
            # each element thereof. Therefore we must not quote the individual path
            # elements (or the quoted string will be wrapped in single quotes, and
            # all will go wrong when pkg-config tries to open something like
            # '"/somewhere/lib"'). Of course, this will cause difficulty if any of
            # the directories contain a colon in their name...
            store.set("MUDDLE_PKGCONFIG_DIRS",
                      ":".join(pkg_dirs))
            store.set("MUDDLE_PKGCONFIG_DIRS_AS_PATH",
                      ":".join(pkg_dirs))

            #print "> pkg_dirs = %s"%(" ".join(pkg_dirs))

            if set_kernel_dir is not None:
                store.set("MUDDLE_KERNEL_DIR",
                          set_kernel_dir)

            if set_ksource_dir is not None:
                store.set("MUDDLE_KERNEL_SOURCE_DIR",
                          set_ksource_dir)

            store.set("MUDDLE_INSTALL", self.invocation.package_install_path(label))
            # It turns out that muddle instruct and muddle uninstruct are the same thing..
            store.set("MUDDLE_INSTRUCT", "%s instruct %s{%s} "%(
                    self.muddle_binary, label.name,
                    label.role))

            store.set("MUDDLE_UNINSTRUCT", "%s instruct %s{%s} "%(
                    self.muddle_binary, label.name,
                    label.role))

        elif (label.type == LabelType.Deployment):
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
            all_required = list(all_required)
            all_required.sort()

            print "Clearing tags for %s"%(str(r.target))
            for l in all_required:
                print '  %s'%l

            # Kill r.targt
            self.invocation.db.clear_tag(r.target)

            for r in all_required:
                self.invocation.db.clear_tag(r)


    def _build_label_env(self, label, env_store):
        """
        Amend the environment, ready for building a label.

        'r' is the rule for how to build the label.

        'env_store' is the environment store holding (most of) the environment
        we want to use.

        It is the caller's responsibility to put the environment BACK when
        finished with it...
        """
        local_store = env_store.Store()

        # Add the default environment variables for building this label
        self.set_default_variables(label, local_store)
        local_store.apply(os.environ)

        # Add anything the rest of the system has put in.
        self.invocation.setup_environment(label, os.environ)

    def build_label(self, label, silent=False):
        """
        The fundamental operation of a builder - build this label.
        """

        # In actual use, this was never called as anything other than
        # 'build_label(label)', so I've made it do *just* that, for
        # simplicity of understanding...
        #
        # build_label_with_options() is retained as the original code
        rule_list = depend.needed_to_build(self.invocation.ruleset, label,
                                           useTags=True, useMatch=True)

        if not rule_list:
            print "There is no rule to build label %s"%label
            return

        for r in rule_list:
            if self.invocation.db.is_tag(r.target):
                # Don't build stuff that's already built ..
                pass
            else:
                if not silent:
                    print "> Building %s"%(r.target)

                # Set up the environment for building this label
                old_env = os.environ.copy()
                try:
                    self._build_label_env(r.target, env_store)

                    if r.action is not None:
                        r.action.build_label(self, r.target)
                finally:
                    os.environ = old_env

                self.invocation.db.set_tag(r.target)

    def build_label_with_options(self, label, useDepends = True, useTags = True, silent = False):
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

        if not rule_list:
            print "There is no rule to build label %s"%label
            return

        for r in rule_list:
            # Build it.
            if (not self.invocation.db.is_tag(r.target)):
                # Don't build stuff that's already built ..
                if (not silent):
                    print "> Building %s"%(r.target)

                # Set up the environment for building this label
                old_env = os.environ.copy()
                try:
                    self._build_label_env(r.target, env_store)

                    if (r.action is not None):
                        r.action.build_label(self, r.target)
                finally:
                    os.environ = old_env

                self.invocation.db.set_tag(r.target)

    @property
    def build_name(self):
        """
        The build name is meant to be a short description of the purpose of a
        build. It might thus be something like "ProjectBlue_intel_STB" or
        "XWing-minimal".

        The name may only contain alphanumerics, underlines and hyphens - this
        is to facilitate its use in version stamp filenames. Also, it is a
        superset of the allowed characters in a Python module name, which means
        that the build description filename (excluding its ".py") will be a
        legal build name (so we can use that as a default).
        """
        return self._build_name

    @build_name.setter
    def build_name(self, name):
        check_build_name(name)
        self._build_name = name


    def get_all_checkout_labels_below(self, dir):
        """
        Get the labels of all the checkouts in or below directory 'dir'

        NOTE that this will not work if you are in a subdirectory of a
        checkout. It's not meant to. Consider using find_location_in_tree()
        to determine that, before calling this method.
        """
        rv = [ ]
        all_cos = self.invocation.all_checkout_labels(LabelTag.CheckedOut)

        for co in all_cos:
            co_dir = self.invocation.checkout_path(co)
            # Is it below dir? If it isn't, os.path.relpath() will
            # start with .. ..
            rp = os.path.relpath(co_dir, dir)
            if (rp[0:2] != ".."):
                # It's relative
                rv.append(co)

        return rv

    def find_local_package_labels(self, dir, tag):
        """
        This is slightly horrible because if you're in a source checkout
        (as you normally will be), there could be several packages.

        Returns a list of the package labels involved. Uses the given tag
        for the labels.
        """

        inv = self.invocation

        # We want to know if we're in a domain. The simplest way to that is:
        root_dir, current_domain = utils.find_root_and_domain(dir)

        # We then try to figure out where we are in the build tree
        # - this must be duplicating some of what we just did above,
        # but that can be optimised another day...
        tloc = self.find_location_in_tree(dir)
        if tloc is None:
            return []

        what, label, domain = tloc

        if what == utils.DirType.Checkout:
            packages = set()
            if label:
                co_labels = [label]
            else:
                co_labels = self.get_all_checkout_labels_below(dir)

            for co in co_labels:
                for p in inv.packages_using_checkout(co):
                    packages.add(p.copy_with_tag(tag))
            return list(packages)
        elif what == utils.DirType.Object:
            if label is None:
                label = Label(LabelType.Package, '*', '*', tag=tag,
                              domain=domain)
            return [label]
        elif what == utils.DirType.Install:
            if label is None:
                label = Label(LabelType.Package, '*', '*', tag=tag,
                              domain=domain)
            return [label]
        else:
            return []



    def find_location_in_tree(self, dir):
        """
        Find the directory type and name of subdirectory in a repository.
        This is used by the find_local_package_labels method to work out
        which packages to rebuild

        * dir - The directory to analyse

        If nothing sensible can be determined, we return None.
        Otherwise we return a tuple of the form:

          (DirType, label, domain_name)

        where:

        * 'DirType' is a utils.DirType value,
        * 'label' is None or a label describing our location,
        * 'domain_name' None or the subdomain we are in and

        If 'label' and 'domain_name' are both given, they will name the same
        domain.
        """

        invocation = self.invocation
        root_dir = invocation.db.root_path

        # Are these necessary? normcase doesn't do anything on Posix,
        # and anyway we should surely have done such earlier on if needed?
        dir = os.path.normcase(os.path.normpath(dir))
        root_dir = os.path.normcase(os.path.normpath(root_dir))

        if not dir.startswith(root_dir):
            raise GiveUp("Directory '%s' is not within muddle build tree '%s'"%(
                dir, root_dir))

        if dir == root_dir:
            return (utils.DirType.Root, None, None)

        # Are we in a subdomain?
        domain_name, domain_dir = utils.find_domain(root_dir, dir)

        if dir == domain_dir:
            return (utils.DirType.DomainRoot, None, domain_name)

        # If we're in a subdomain, then we're working with respect to that,
        # otherwise we're working with respect to the build root
        if domain_name:
            our_root = domain_dir
        else:
            our_root = root_dir

        # Dir is (hopefully) a bit like
        # root / X , so we walk up it  ...
        rest = []
        while dir != our_root:
            base, cur = os.path.split(dir)
            rest.insert(0, cur)
            dir = base

        result = None

        if rest[0] == "src":
            checkout_locations = invocation.db.checkout_locations
            if len(rest) > 1:
                lookfor = os.path.join(utils.domain_subpath(domain_name),
                                       'src', *rest[1:])
                for label, locn in checkout_locations.items():
                    if lookfor.startswith(locn) and domain_name == label.domain:
                        # but just in case we have (for instance) checkouts
                        # 'fred' and 'freddy'...
                        relpath = os.path.relpath(lookfor, locn)
                        if relpath.startswith('..'):
                            # It's not actually the same
                            continue
                        else:
                            result = (utils.DirType.Checkout, label, domain_name)
                            break
            if result is None:
                # Part way down a from src/ towards a checkout
                result = (utils.DirType.Checkout, None, domain_name)

        elif rest[0] == "obj":
            # We know it goes obj/<package>/<role>
            if len(rest) > 2:
                label = Label(LabelType.Package, name=rest[1],
                              role=rest[2], domain=domain_name)
            elif len(rest) == 2:
                label = Label(LabelType.Package, name=rest[1],
                              role='*', domain=domain_name)
            else:
                label = None
            result = (utils.DirType.Object, label, domain_name)

        elif rest[0] == "install":
            # We know it goes install/<role>
            if len(rest) > 1:
                label = Label(LabelType.Package, name='*',
                              role=rest[1], domain=domain_name)
            else:
                label = None
            result = (utils.DirType.Install, label, domain_name)

        elif rest[0] == "deploy":
            # We know it goes deploy/<deployment>
            if len(rest) > 1:
                label = Label(LabelType.Deployment, name=rest[1],
                              domain=domain_name)
            else:
                label = None
            result = (utils.DirType.Deployed, label, domain_name)

        elif rest[0] == "domains":
            # We're inside the current domain - this is actually a root
            result = (utils.DirType.DomainRoot, None, domain_name)

        elif rest[0] == '.muddle':
            result = (utils.DirType.MuddleDir, None, domain_name)

        elif rest[0] == 'versions':
            result = (utils.DirType.Versions, None, domain_name)

        else:
            result = (utils.DirType.Unexpected, None, domain_name)

        return result


class BuildDescriptionAction(Action):
    """
    Load the build description.
    """

    def __init__(self, file_name, build_co):
        self.file_name = file_name
        self.build_co = build_co

    def build_label(self, builder, label):
        """
        Actually load the build description into the invocation.
        """
        # TODO: where is 'label' used?
        desc = builder.invocation.db.build_desc_file_name()

        setup = None # To make sure it's defined.
        try:
            old_path = sys.path
            # TODO: should we use a domain?
            tmp = Label(LabelType.Checkout, self.build_co)
            sys.path.insert(0, builder.invocation.checkout_path(tmp))
            setup = utils.dynamic_load(desc)
            setup.describe_to(builder)
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
                raise MuddleBug("Cannot load build description %s"%setup)

def load_builder(root_path, muddle_binary, params = None,
                 default_domain = None):
    """
    Load a builder from the given root path.
    """

    inv = Invocation(root_path)
    build = Builder(inv, muddle_binary, params, default_domain = default_domain)
    can_load = build.load_build_description()
    if (not can_load):
        return None

    # We shouldn't have changed the RootRepository, Description or
    # VersionsRepository file, so there's no particular reason to
    # write them back out - and if we do, I believe it (occasionally)
    # goes wrong and leaves a file blank
    ##inv.commit()  # XXX
    return build


def minimal_build_tree(muddle_binary, root_path, repo_location, build_desc, versions_repo=None):
    """
    Setup the very minimum of a build tree.

    This should give a .muddle directory with its main files, but will not
    actually try to retrieve any checkouts.
    """
    # The following sets up a .muddle directory, with its Description and
    # RootRepository files, and optionally a VersionsRepository file
    database = db.Database(root_path)
    database.setup(repo_location, build_desc, versions_repo)

    # We need a minimalistic builder
    inv = Invocation(root_path)
    builder = Builder(inv, muddle_binary, None, None)
    # ... remember *not* to retrieve the build description from its
    # repository, since we want to do that with the specific revision
    # given in the [CHECKOUT builds] configuration
    inv.commit()
    return builder



# =============================================================================
# Following is an initial implementation of sub-build or domain inclusion
# Treat it with caution...

def _init_without_build_tree(muddle_binary, root_path, repo_location, build_desc,
                             domain_params):
    """
    This a more-or-less copy of the code from muddle.command.Init's
    without_build_tree() method, for purposes of my own convenience.

    It also looks suspiciously like 'minimal_build_tree', but it *does*
    actually set up the content of the tree...

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
    database.setup(repo_location, build_desc)

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
        Label._check_part('dummy',domain_name)
    except GiveUp:
        raise GiveUp('Domain name "%s" is not valid'%domain_name)

    # So, we're wanting our sub-builds to go into the 'domains/' directory
    domain_root_path = os.path.join(root_path, 'domains', domain_name)

    # Extract the domain parameters ..
    domain_params = parent_domain.invocation.get_domain_parameters(domain_name)

    # Did we already retrieve it, earlier on?
    # muddle itself just does::
    #
    #    muddled.utils.find_root_and_domain(specified_root)
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

    for l in domain_builder.invocation.default_deployment_labels:
        labels.append(l)

    env = domain_builder.invocation.env
    for l in env.keys():
        labels.append(l)

    ruleset = domain_builder.invocation.ruleset

    rules = ruleset.map.values()

    # TODO: This is terribly clumsy, as any change elsewhere in muddle
    #       requires us to remember to update this.

    # Unfortunately, as it turns out, the seemingly sensible decision that
    # each VCS handler object should know its builder causes us a problem,
    # since we're going to need to change each of their minds, one at a time...
    vcs_handlers = []

    for rule in rules:
        labels.append(rule.target)
        for l in rule.deps:
            labels.append(l)
        if rule.action is not None:
            if hasattr(rule.action, '_inner_labels'):
                labels.extend(rule.action._inner_labels())
            if hasattr(rule.action, 'vcs'):
                # This relies WAY too much on knowledge of the inside of a
                # version control handler - TODO is to fix it!!!
                labels.append(rule.action.vcs.checkout_label)
                vcs_handlers.append(rule.action.vcs)

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

    # Also, check if any of our Rules need their "action" changing
    # (we'll assume that they do if they appear to have the appropriate magic
    # method names)
    for rule in rules:
        if rule.action is not None and hasattr(rule.action, '_mark_unswept'):
            rule.action._mark_unswept()

    for rule in rules:
        if rule.action is not None and hasattr(rule.action, '_change_domain'):
            rule.action._change_domain(domain_name)

    # Now mark the builder as a domain.
    domain_builder.invocation.mark_domain(domain_name)

    return domain_builder, vcs_handlers

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

    Note that, as a short-hand convenience, sub-domains are marked as such by
    having a ``.muddle/am_subdomain`` file. This will be created by
    ``include_domain()`` if necessary.
    """

    domain_builder, vcs_handlers = _new_sub_domain(builder.invocation.db.root_path,
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

    # And sort out which builder its VCS handlers think they belong to
    for vcs in vcs_handlers:
        vcs.builder = builder

    builder.invocation.include_domain(domain_builder, domain_name)

    return domain_builder

def build_co_and_path_from_str(str):
    """Turn a BuildDescription text into checkout name and inner path.

    That is, we assume the string we're given (which was presumably
    read from a BuildDescription) is of the form:

        <checkout-name>/<path-to-build-desc>

    For instance::

        >>> build_co_and_path_from_str('builds/01.py')
        ('builds', '01.py')
        >>> build_co_and_path_from_str('strawberry/jam/toast.py')
        ('strawberry', 'jam/toast.py')
    """
    co_name, inner_path = utils.split_path_left(str)
    return co_name, inner_path

# End file.
