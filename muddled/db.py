"""
Contains code which maintains the muddle database,
held in root/.muddle
"""

import os
import xml.dom
import xml.dom.minidom
import traceback

import muddled.utils as utils
import muddled.depend as depend

from muddled.utils import domain_subpath
from muddled.version_control import split_vcs_url

class Database(object):
    """
    Represents the muddle database

    Historically, this class represented the muddle database as stored
    in the .muddle directory (on disk). Since we expect the user (and code) to
    edit these files frequently, we deliberately do not cache their values
    (other than, well, as themselves in the .muddle directory).

    Since then however, we have also gained some dictionaries linking
    checkout labels to particular quantities.

    It's useful to have a single place for most such dictionaries because
    when we do subdomain manipulation (i.e., taking a build description and
    including its build tree into another as a subdomain) we need to change
    all the labels in the new subdomain to reflect that fact. The fewer places
    we have to worry about that, the better.

    So, we remember:

    * root_path - The path to the root of the build tree.
    * repo - the PathFile for the '.muddle/RootRepository' file
    * build_desc - the PathFile for the '.muddle/Description' file
    * versions_repo - the PathFile for the '.muddle/VersionsRepository' file

    * local_labels - Transient labels which are "asserted", via
      'set_tag()', and queried via 'is_tag()'. This functionality is used
      inside the Builder's "build_label()" mechanism, and is only intended
      for use within muddle itself.

    And a variety of dictionaries that take (mostly) checkout labels as keys.
    Note that:

    1. All the keys are "normalised" to have an unset label tag.
    2. Thus it is assumed that the dictionaries will only be accessed via
       the methods supplied for this purpose.
    3. The existence of an entry in does not necessarily imply that the
       particular checkout still exists/is used. It may, for instance, have
       gone away during a ``builder.unify()`` operation.

    The dictionaries we use are:

    * checkout_locations - This maps a checkout label to the directory the
      checkout is in, relative to the root of the build tree. So examples
      might be::

        checkout:builds/*               -> src/builds
        checkout:(subdomain1)first_co/* -> domains/subdomain1/src/first_co

    * checkout_repositories - This maps a checkout_label to a Repository
      instance, representing where it is checked out from. So examples might
      be (eliding the actual URL)::

        checkout:builds/*               -> Repository('git', 'http://.../main', 'builds')
        checkout:(subdomain1)first_co/* -> Repository('git', 'http://.../subdomain1', 'first_co')

    * checkout_licenses - This maps a checkout label to a License instances,
      representing the source code license under which this checkout's source
      code is being used. For instance::

        checkout:builds/*               -> License('MPL 1.1', 'open')
        checkout:(subdomain1)first_co/* -> License('LGPL v3', 'gpl')

      In the case of a checkout that has multiple licenses, the license that is
      being "used" should be indicated.

      Note that not all checkouts will necessarily have licenses associated
      with them.

    * self.not_built_against is a dictionary of the form:

        { package_label : set( gpl_checkout_labels ) }

      Each gpl_checkout_label is a label whose license (typically GPL) might be
      expected to "propagate" to any package built against that checkout. This
      dictionary is used to tell the system that, whilst 'package_label' may
      depend upon any of the 'gpl_checkout_labels', it doesn't build against
      them in a way that actually causes that propagation.

      So, for instance, if we have LGPL checkout label which our package links
      to as a dynamic library, we'd want to tell muddle that the package
      *depends* on the checkout, but doesn't get affected by the GPL nature of
      its license.

      This sort of thing is necessary because muddle itself has no way of
      telling.

    * self.upstream_repositories is a dictionary of the form:

        { repo : { repo, set(names) } }

      That is, the key is a Repository instance (normally expected to be
      the same as one of the values in the checkout_repos dictionary), and
      the value is a dictionary whose keys are other repositories ("upstream"
      repositories) and some names associated with them.

      The same names may be associated with more than one upstream repository.
      It is also conceivable that an upstream repository might also act as a
      key, if it in turn has upstream repositories (whether this is strictly
      necessary is unclear - XXX still to decide whether to support this).

    Note that ALL labels in this dictionary and its constituent sets should
    have their tags set to '*', so it is expected that this dictionary will
    be accessed using set_not_built_against() and get_not_built_against().
    """

    def __init__(self, root_path):
        """
        Initialise a muddle database with the given root_path.
        """
        self.root_path = root_path
        utils.ensure_dir(os.path.join(self.root_path, ".muddle"))
        self.repo = PathFile(self.db_file_name("RootRepository"))
        self.build_desc = PathFile(self.db_file_name("Description"))
        self.versions_repo = PathFile(self.db_file_name("VersionsRepository"))
        self.role_env = {}      # DEPRECATED - never used - XXX REMOVE XXX

        self.checkout_locations = {}
        self.checkout_repositories = {}
        self.checkout_licenses = {}
        self.not_built_against = {}

        # A set of "asserted" labels
        self.local_tags = set()

        # Upstream repositories
        self.upstream_repositories = {}

    def setup(self, repo_location, build_desc, versions_repo=None):
        """
        Set the 'repo' and 'build_desc' on the current database.

        If 'versions_repo' is not None, it will set the versions_repo
        to this value. Note that "not None" means that a value of ''
        *will* set the value to the empty string.

        If 'versions_repo' is None, and 'repo_location' is not a
        centralised VCS (i.e., subversion), then it will set the
        versions_repo to repo_location.
        """
        self.repo.set(repo_location)
        self.build_desc.set(build_desc)
        if versions_repo is None:
            vcs, repo = split_vcs_url(repo_location)
            ##print 'vcs',vcs
            ##print 'repo',repo
            # Rather hackily, assume that it is only the given VCS names
            # that will stop us storing our 'versions' repository in the
            # same "place" as the src/ checkouts (because they store
            # everything in one monolithic entity)
            if vcs not in ('svn', ):
                ##print 'setting versions repository'
                self.versions_repo.set(os.path.join(repo_location,"versions"))
        else:
            self.versions_repo.set(versions_repo)
        self.commit()

    def get_subdomain_info(self, domain_name):
        """Return the root repository and build description for a subdomain.

        Reads the RootRepository and Description files in the (sub)domain's
        ".muddle" directory.
        """
        domain_dir = os.path.join(self.root_path,
                                  utils.domain_subpath(domain_name),
                                  ".muddle")
        repo_file = PathFile(os.path.join(domain_dir, "RootRepository"))
        desc_file = PathFile(os.path.join(domain_dir, "Description"))

        return (repo_file.get(), desc_file.get())

    def include_domain(self, other_builder, other_domain_name):
        """
        Include data from other_builder, built in other_domain_name

        This method is the main reason why this class gets to hold so much
        information - it gives us a single place to concentrate much of the
        knowledge about including subdomains.
        """

        other_db = other_builder.invocation.db

        self._merge_subdomain_labels(other_domain_name, other_db)
        self._merge_subdomain_upstreams(other_domain_name, other_db)

    def _merge_subdomain_labels(self, other_domain_name, other_db):
        """Merge things from the subdomain that contain labels.
        """
        keys = set()
        keys.update(other_db.checkout_locations.keys())
        keys.update(other_db.checkout_repositories.keys())
        keys.update(other_db.checkout_licenses.keys())
        keys.update(other_db.not_built_against.keys())
        # Don't forget the labels in the not_built_against values
        for not_against in other_db.not_built_against.values():
            keys.update(not_against)

        # We really only want to transform the labels once
        new_labels = {}
        for label in keys:
            new_label = label.copy()
            new_label._mark_unswept()
            new_label._change_domain(other_domain_name)
            new_labels[label] = new_label

        for co_label, co_dir in other_db.checkout_locations.items():
            #print "Including %s -> %s -- %s"%(co_label,co_dir, other_domain_name)
            new_label = new_labels[co_label]
            new_dir = os.path.join(utils.domain_subpath(other_domain_name), co_dir)
            self.checkout_locations[new_label] = new_dir

        for co_label, repo in other_db.checkout_repositories.items():
            new_label = new_labels[co_label]
            self.checkout_repositories[new_label] = repo

        for co_label, repo in other_db.checkout_licenses.items():
            new_label = new_labels[co_label]
            self.checkout_licenses[new_label] = repo

        for pkg_label, not_against in other_db.not_built_against.items():
            new_set = set()
            for lbl in not_against:
                new_set.add(new_labels[lbl])

            # And rememember to *update* the destination dictionary...
            new_label = new_labels[pkg_label]
            if new_label in self.not_built_against:
                self.not_built_against[new_label].update(new_set)
            else:
                self.not_built_against[new_label] = new_set

    def _merge_subdomain_upstreams(self, other_domain_name, other_db):
        """Merge things from the subdomain that contain upstream repositories.
        """
        for orig_repo, that_upstream_dict in other_db.upstream_repositories.items():
            ##print 'Looking at %r'%orig_repo
            if orig_repo in self.upstream_repositories:
                ##print '  already known'
                # Oh dear, we already think we know about this repository
                # and its upstreams...
                this_upstream_dict = self.upstream_repositories[orig_repo]

                for upstream_repo, that_names in that_upstream_dict.items():
                    ##print '  upstream %r'%upstream_repo
                    if upstream_repo in this_upstream_dict:
                        ##print '    already known'
                        # And this is one of the upstreams we already recognise
                        this_names = this_upstream_dict[upstream_repo]
                        if that_names != this_names:
                            ##print '      adding extra names'
                            # If there are *extra* names, we'll just add them
                            this_names.update(that_names)
                            this_upstream_dict[upstream_repo] = this_names
                    else:
                        ##print '    never heard of it'
                        # So we already had some upstreams on this repository,
                        # and this subdomain is wanting to add more. Deal with
                        # it appropriately.
                        self._subdomain_new_upstream(other_domain_name, orig_repo, other_db)
            else:
                ##print '  new to us'
                # This repository is not in our dictionary of "repositories
                # that have upstreams". However, we don't keep repositories
                # that *don't* have upstreams in there, so we need to check
                # for that.
                #
                # The obvious case is a repository that is being used by a
                # checkout, and we *do* have a dictionary for that.
                #
                # So we can tell if this is a repository (associated with a
                # checkout) that we already know about, or if it is a
                # repository we have no idea about (and which we therefore
                # hope is being remembered for some good reason - but ours
                # is not to reason why).
                if orig_repo in self.checkout_repositories.values():
                    # So, we've got a checkout using it, *without* upstreams,
                    # and this is therefore the same as the case where we
                    # were adding (new) upstreams to a repository that already
                    # had them. So we do the same thing...
                    ##print '    but we already have a checkout using it!'
                    self._subdomain_new_upstream(other_domain_name, orig_repo, other_db)
                else:
                    # We have no record of this repository, with or without
                    # upstreams, so let's record it...
                    self.upstream_repositories[orig_repo] = that_upstream_dict

    def _subdomain_new_upstream(self, other_domain_name, orig_repo, other_db):
        """A subdomain introduces a new upstream on a repo we already know

        It's not entirely clear whether a subdomain should be able to add a new
        upstream that the main domain had not explicitly asked for. We could:

        1. just add this new upstream, or
        2. cause an error and force the user to amend the build descriptions to
           avoid it, or
        3. ignore the new upstream

        I think (2) is perhaps acceptable. The user may not be able to change
        the subdomain build description (it may have come from elsewhere, and
        subdomain builds are valid top-level builds as well). But they could
        arguably alter the top-level build to have the same remotes as the
        subdomain. Of course, if the subdomain *is* from elsewhere, it may
        change, and then the top-level build would be forever changing to keep
        up.  But perhaps that is another argument...

        I think (3) is just unacceptable - there was some reason for including
        the upstream. We shouldn't throw the information away.

        If we follow (1), then we potentially risk pushing to an upstream that
        we didn't expect to (since the new upstream may share names with an
        existing one).  So I think perhaps we should not allow this option,
        tempting as it is.

        Which leaves us with (2) as the least worst choice.
        """
        this_upstream = self.upstream_repositories[orig_repo]
        that_upstream = other_db.upstream_repositories[orig_repo]
        details = ['Subdomain %s adds a new upstream to\n'
                   '  %r'%(other_domain_name, orig_repo)]

        co_labels = self._find_checkouts_for_repo(orig_repo)
        if co_labels:
            details.append('  (used by %s)'%(depend.label_list_to_string(co_labels,
                                                                         join_with=', ')))

        details.append('  Original upstreams:')
        for upstream_repo in sorted(this_upstream.keys()):
            details.append('    %r  %s'%(upstream_repo,
                           ', '.join(sorted(this_upstream[upstream_repo]))))

        details.append('  Subdomain %s has:'%other_domain_name)
        for upstream_repo in sorted(that_upstream.keys()):
            details.append('    %r  %s'%(upstream_repo,
                           ', '.join(sorted(that_upstream[upstream_repo]))))

        raise utils.GiveUp('\n'.join(details))

    def set_domain_marker(self, domain_name):
        """
        Mark this as a (sub)domain

        In a (sub)domain, we have a file called ``.muddle/am_subdomain``,
        which acts as a useful flag that we *are* a (sub)domain.
        """
        utils.mark_as_domain(self.root_path, domain_name)

    def normalise_checkout_label(self, label):
        """
        Given a checkout label with random "other" fields, normalise it.

        Returns a normalised checkout label, with the role unset and the
        tag set to '*'.

        Raise a MuddleBug exception if the label is not a checkout label.

        Note that:

        1. this *always* copies the label, and
        2. any label stored by a method in this class is created by this
           methor, and thus
        3. when _merge_subdomain_labels is called, we know that all the
           labels it manipulates are unique to this class, so can't have
           had their domains (already) altered by code anywhere else.

        The downside, of course, is that we always take a copy...

        (so ideally, all stored labels would be held by us, and then we
        could reliably be in charge of their domains, and then we'd only
        need to return a new label if it wasn't exactly what we want).
        """
        if label.type != utils.LabelType.Checkout:
            # The user probably needs an exception to spot why this is
            # happening
            raise MuddleBug('Cannot "normalise" a non-checkout label: %s'%label)

        return depend.Label(label.type, label.name,
                           role=None,
                           tag='*',
                           domain=label.domain)

    def set_checkout_path(self, checkout_label, dir):
        key = self.normalise_checkout_label(checkout_label)

	#print '### set_checkout_path for %s'%checkout_label
	#print '... dir',dir

        self.checkout_locations[key] = os.path.join('src', dir)

    def dump_checkout_paths(self):
        print "> Checkout paths .."
        keys = self.checkout_locations.keys()
        max = 0
        for label in keys:
            length = len(str(label))
            if length > max:
                max = length
        keys.sort()
        for label in keys:
            print "%-*s -> %s"%(max, label, self.checkout_locations[label])

    def get_checkout_path(self, checkout_label):
        """
        'checkout_label' is a "checkout:" Label, or None

        If it is None, then "<root path>/src" is returned.

        Otherwise, the path to the checkout directory for this label is
        calculated and returned.

        If you want the path *relative* to the root of the build tree
        (i.e., a path starting "src/"), then use get_checkout_location().
        """
        if checkout_label is None:
            return os.path.join(self.root_path, "src")

        root = self.root_path

        key = self.normalise_checkout_label(checkout_label)
        try:
            rel_dir = self.checkout_locations[key]
        except KeyError:
            raise utils.GiveUp('There is no checkout path registered for label %s'%checkout_label)

        return os.path.join(root, rel_dir)

    def get_checkout_location(self, checkout_label):
        """
        'checkout_label' is a "checkout:" Label, or None

        If it is None, then "src" is returned.

        Otherwise, the path to the checkout directory for this label, relative
        to the root of the build tree, is calculated and returned.

        If you want the full path to the checkout directory, then use
        get_checkout_path().
        """
        if checkout_label is None:
            return 'src'

        key = self.normalise_checkout_label(checkout_label)
        try:
            return self.checkout_locations[key]
        except KeyError:
            raise utils.GiveUp('There is no checkout path registered for label %s'%checkout_label)

    def set_checkout_repo(self, checkout_label, repo):
        key = self.normalise_checkout_label(checkout_label)
        self.checkout_repositories[key] = repo

    def dump_checkout_repos(self, just_url=False):
        """
        Report on the repositories associated with our checkouts.

        If 'just_url' is true, then report the repository URL, otherwise
        report the full Repository definition (which shows branch and revision
        as well).
        """
        print "> Checkout repositories .."
        keys = self.checkout_repositories.keys()
        max = 0
        for label in keys:
            length = len(str(label))
            if length > max:
                max = length
        keys.sort()
        if just_url:
            for label in keys:
                print "%-*s -> %s"%(max, label, self.checkout_repositories[label])
        else:
            for label in keys:
                print "%-*s -> %r"%(max, label, self.checkout_repositories[label])

    def get_checkout_repo(self, checkout_label):
        """
        Returns the Repository instance for this checkout label
        """
        key = self.normalise_checkout_label(checkout_label)
        try:
            return self.checkout_repositories[key]
        except KeyError:
            raise utils.GiveUp('There is no repository registered for label %s'%checkout_label)

    def set_checkout_license(self, checkout_label, lic):
        key = self.normalise_checkout_label(checkout_label)
        self.checkout_licenses[key] = lic

    def dump_checkout_licenses(self, just_name=False):
        """
        Report on the licenses associated with our checkouts.

        If 'just_name' is true, then report the licenses name, otherwise
        report the full License definition.
        """
        print "Checkout licenses are:"
        print
        keys = self.checkout_licenses.keys()
        max = 0
        for label in keys:
            length = len(str(label))
            if length > max:
                max = length
        keys.sort()
        if just_name:
            for label in keys:
                print "* %-*s %s"%(max, label, self.checkout_licenses[label])
        else:
            for label in keys:
                print "* %-*s %r"%(max, label, self.checkout_licenses[label])

    def get_checkout_license(self, checkout_label, absent_is_None=False):
        """
        Returns the License instance for this checkout label

        If 'absent_is_None' is true, then if 'checkout_label' does not have
        an entry in the licenses dictionary, None will be returned. Otherwise,
        an appropriate GiveUp exception will be raised.
        """
        key = self.normalise_checkout_label(checkout_label)
        try:
            return self.checkout_licenses[key]
        except KeyError:
            if absent_is_None:
                return None
            else:
                raise utils.GiveUp('There is no license registered for label %s'%checkout_label)

    def checkout_has_license(self, checkout_label):
        """
        Return True if the named checkout has a license registered
        """
        key = self.normalise_checkout_label(checkout_label)
        return key in self.checkout_licenses

    def set_not_built_against(self, pkg_label, co_label):
        """Asserts that this package is not "built against" that checkout.

        We assume that:

        1. 'pkg_label' is a package that depends (perhaps indirectly) on 'co_label'
        2. 'co_label' is a checkout with a "propagating" license (i.e., some for of
           GPL license).
        3. Thus by default the "GPL"ness would propagate from 'co_label' to this
           package, and thus to the checkouts we are (directly) built from.

        However, this function asserts that, in fact, our checkout is (or our
        checkouts are) not built in such a way as to cause the license for
        'co_label' to propagate.

        Or, putting it another way, for a normal GPL license, we're not linking
        with anything from 'co_label', or using its header files, or copying GPL'ed
        files from it, and so on.

        If 'co_label' is under LGPL, then that would reduce to saying we're not
        static linking against 'co_label' (or anything else not allowed by the
        LGPL).

        Note that we may be called before 'co_label' has registered its license, so
        we cannot actually check that 'co_label' has a propagating license (or,
        indeed, that it exists or is depended upon by 'pkg_label').
        """
        if pkg_label.type != utils.LabelType.Package:
            raise utils.GiveUp('First label in not_build_against() is %s, which is not'
                               ' a package'%pkg_label)
        if co_label.type != utils.LabelType.Checkout:
            raise utils.GiveUp('Second label in not_build_against() is %s, which is not'
                               ' a checkout'%co_label)

        if pkg_label.tag == '*':
            key = pkg_label
        else:
            key = pkg_label.copy_with_tag('*')

        value = self.normalise_checkout_label(co_label)

        if key in self.not_built_against:
            self.not_built_against[key].add(value)
        else:
            self.not_built_against[key] = set([value])

    def get_not_built_against(self, pkg_label):
        """Find those things against which this package is *not* built.

        That is, the things on which this package depends, that appear to be
        GPL and propagate, but against which we have been told we do not
        actually build, so the license is not, in fact, propagated.

        Returns a (possibly empty) set of checkout labels, each with tag '*'.
        """
        if pkg_label.tag == '*':
            key = pkg_label
        else:
            key = pkg_label.copy_with_tag('*')

        try:
            return self.not_built_against[key]
        except KeyError:
            return set()

    def add_upstream_repo(self, orig_repo, upstream_repo, names=None):
        """Add an upstream repo to 'orig_repo'.

        - 'orig_repo' is the original Repository that we are adding an
          upstream for.
        - 'upstream_repo' is the upstream Repository. It is an error if
          that repository is already an upstream of 'orig_repo'.
        - 'names' is a sequence of strings that can be used to select
          this (and possibly other) upstream repositories.
        """
        if orig_repo in self.upstream_repositories:
            upstream_dict = self.upstream_repositories[orig_repo]
            if upstream_repo in upstream_dict:
                raise utils.GiveUp('Repository %r is already upstream'
                                   ' of %r'%(upstream_repo, orig_repo))
        else:
            upstream_dict = {}

        upstream_dict[upstream_repo] = set(names)

        self.upstream_repositories[orig_repo] = upstream_dict

    def get_upstream_repos(self, orig_repo, names=None):
        """Retrieve the upstream repositories for 'orig_repo'

        If 'names' is given, it must be a sequence of strings, in which
        case only those upstream repositories annotated with any of the
        names will be returned.

        Returns a list of tuples of the form:

            (upstream repositories, matching names)

        This will be empty if there are no upstream repositories for
        'orig_repo', or none with any of the names in 'names' (if given).

        In the case of 'names' being empty, 'matching names' will contain
        the names registered for that upstream repository.

        NB: 'matching names' is a tuple with the names sorted, and the list
        returned is also sorted.
        """
        results = []
        try:
            upstream_dict = self.upstream_repositories[orig_repo]
        except KeyError:
            return results

        if names:
            for upstream_repo, upstream_names in sorted(upstream_dict.items()):
                found_names = upstream_names.intersection(names)
                if found_names:
                    results.append((upstream_repo,
                                   tuple(sorted(found_names))))
        else:
            for upstream_repo, upstream_names in sorted(upstream_dict.items()):
                results.append((upstream_repo,
                                tuple(sorted(upstream_names))))
        return results

    def _find_checkouts_for_repo(self, repo):
        """Find the checkout(s) that use a repository.

        Do we really believe we're going to have the same repository used by
        more than one checkout? We certainly can't rule it out (it is
        particularly likely if we have similar checkouts in different domains,
        and they've not been unified).

        On the other hand, checking for *everything* every time slows us down a
        lot, so if this happens often we might want to consider a cache...

        Returns a (possibly empty) set of checkout labels.
        """
        results = set()
        if repo in self.checkout_repositories.values():
            for co_label, co_repo in self.checkout_repositories.items():
                if co_repo == repo:
                    results.add(co_label)
        return results

    def dump_upstream_repos(self, just_url=False):
        """
        Report on the upstream repositories associated "default" repositories

        If 'just_url' is true, then report the repository URL, otherwise
        report the full Repository definition (which shows branch and revision
        as well).
        """
        print "> Upstream repositories .."
        keys = self.upstream_repositories.keys()
        keys.sort()

        for orig_repo in keys:
            # Calling find_checkout_for to do a linear search through the
            # checkout_repositories dictionary for every repository is
            # likely to be, well, a bit slow. So let's hope we don't do this
            # too often...
            co_labels = self._find_checkouts_for_repo(orig_repo)
            self.print_upstream_repo_info(orig_repo, co_labels, just_url)

    def print_upstream_repo_info(self, orig_repo, co_labels, just_url):
        """Print upstream repository information.

        'orig_repo' is the "main" repository, the one that is not upstream

        'co_labels' is a sequence of 0 or more checkout labels, which are
        associated with that repository.

        If 'just_url' is true, then report the repository URL, otherwise
        report the full Repository definition (which shows branch and revision
        as well).
        """
        if just_url:
            format1 = "%s used by %s"
            format2 = "%s"
            format3 = "    %s  %s"
        else:
            format1 = "%r used by %s"
            format2 = "%r"
            format3 = "    %r  %s"

        if co_labels:
            print format1%(orig_repo, depend.label_list_to_string(co_labels, join_with=', '))
        else:
            print format2%orig_repo
        try:
            upstream_dict = self.upstream_repositories[orig_repo]
            for upstream_repo in sorted(upstream_dict.keys()):
                print format3%(upstream_repo,
                               ', '.join(sorted(upstream_dict[upstream_repo])))
        except KeyError:
            print '  Has no upstream repositories'

    def build_desc_file_name(self):
        """
        Return the filename of the build description.
        """
        return os.path.join(self.root_path, "src", self.build_desc.get())

    def db_file_name(self, rel):
        """
        The full path name of the given relative filename in the
        current build tree.
        """
        return os.path.join(self.root_path, ".muddle", rel)

    def set_instructions(self, label, instr_file):
        """
        Set the name of a file containing instructions for the deployment
        mechanism.

        * label -
        * instr_file - The InstructionFile object to set.

        If instr_file is None, we unset the instructions.

        """
        file_name = self.instruction_file_name(label)

        if instr_file is None:
            if os.path.exists(file_name):
                os.remove(file_name)
        else:
            instr_file.save_as(file_name)

    def clear_all_instructions(self, domain=None):
        """
        Clear all instructions - essentially only ever called from
        the command line.
        """
        os.removedirs(self.instruction_file_dir(domain))

    def scan_instructions(self, lbl):
        """
        Returns a list of pairs (label, filename) indicating the
        list of instruction files matching lbl. It's up to you to
        load and sort them (but load_instructions() will help
        with that).
        """
        the_instruction_files = os.walk(self.instruction_file_dir(lbl.domain))

        return_list = [ ]

        for (path, dirname, files) in the_instruction_files:
            for f in files:
                if (f.endswith(".xml")):
                    # Yep
                    # This was of the form 'file/name/role.xml' or _default.xml
                    # if there was no role, so ..
                    role = f[:-4]

                    # dirname is only filled in for directories (?!). We actually want
                    # the last element of path ..
                    pkg_name = os.path.basename(path)


                    #print "Check instructions role = %s name = %s f = %s p = %s"%(role, pkg_name, f, path)
                    if (role == "_default"):
                        role = None

                    test_lbl = depend.Label(utils.LabelType.Package, pkg_name, role,
                                            utils.LabelTag.Temporary,
                                            domain = lbl.domain)
                    #print "Match %s -> %s = %s"%(lbl, test_lbl, lbl.match(test_lbl))
                    if (lbl.match(test_lbl) is not None):
                        # We match!
                        return_list.append((test_lbl, os.path.join(path, f)))

        return return_list


    def instruction_file_dir(self, domain=None):
        """
        Return the name of the directory in which we keep the instruction files
        """
        if domain:
            root = os.path.join(self.root_path, domain_subpath(domain))
        else:
            root = self.root_path
        return os.path.join(root, ".muddle", "instructions")

    def instruction_file_name(self, label):
        """
        If this label were to be associated with a database file containing
        the (absolute) filename of an instruction file to use for this
        package and role, what would it be?
        """
        if (label.type != utils.LabelType.Package):
            raise utils.MuddleBug("Attempt to retrieve instruction file "
                              "name for non-package tag %s"%(str(label)))

        # Otherwise ..
        if label.role is None:
            leaf = "_default.xml"
        else:
            leaf = "%s.xml"%label.role

        dir = os.path.join(self.instruction_file_dir(domain=label.domain),
                           label.name)
        utils.ensure_dir(dir)
        return os.path.join(dir, leaf)


    def tag_file_name(self, label):
        """
        If this file exists, the given label is asserted.

        To make life a bit easier, we group labels.
        """

        if label.domain:
            root = os.path.join(self.root_path, domain_subpath(label.domain))
        else:
            root = self.root_path

        if (label.role is None):
            leaf = label.tag
        else:
            leaf = "%s-%s"%(label.role, label.tag)

        return os.path.join(root,
                            ".muddle",
                            "tags",
                            label.type,
                            label.name, leaf)

    def is_tag(self, label):
        """
        Is this label asserted?
        """
        if (label.transient):
            return (label in self.local_tags)
        else:
            return (os.path.exists(self.tag_file_name(label)))

    def set_tag(self, label):
        """
        Assert this label.
        """


        #print "Assert tag %s transient? %s"%(label, label.transient)

        if (label.transient):
            self.local_tags.add(label)
        else:
            file_name = self.tag_file_name(label)
            (dir,name) = os.path.split(file_name)
            utils.ensure_dir(dir)
            f = open(file_name, "w+")
            f.write(utils.iso_time())
            f.write("\n")
            f.close()

    def clear_tag(self, label):
        if (label.transient):
            self.local_tags.discard(label)
        else:
            try:
                os.remove(self.tag_file_name(label))
            except:
                pass

    def commit(self):
        """
        Commit changes to the db back to disc.

        Remember to call this function when anything of note happens -
        don't assume you aren't about to hit an exception.
        """
        self.repo.commit()
        self.build_desc.commit()
        self.versions_repo.commit()


class PathFile(object):
    """
    Manipulates a file containing a single path name.
    """

    def __init__(self, file_name):
        """
        Create a PathFile object with the given filename.
        """
        self.file_name = file_name
        self.value = None
        self.value_valid = False

    def get(self):
        """
        Retrieve the current value of the PathFile, or None if
        there isn't one.

        Uses the cached value if that is believed valid.
        """
        if self.value_valid:
            return self.value
        else:
            return self.from_disc()

    def set(self, val):
        """
        Set the value of the PathFile (possibly to None).
        """
        self.value_valid = True
        self.value = val

    def from_disc(self):
        """
        Retrieve the current value of the PathFile, directly from disc.

        Returns None if there is a problem reading the PathFile.

        Caches the value if there was one.
        """
        try:
            f = open(self.file_name, "r")
            val = f.readline()
            f.close()

            # Remove the trailing '\n' if it exists.
            if val[-1] == '\n':
                val = val[:-1]

        except IndexError as i:
            raise utils.GiveUp("Contents of db file %s are empty - %s\n"%(self.file_name, i))
        except IOError as e:
            raise utils.GiveUp("Error retrieving value from %s\n"
                                "    %s"%(self.file_name, str(e)))

        self.value = val
        self.value_valid = True
        return val

    def commit(self):
        """
        Write the value of the PathFile to disc.
        """

        if not self.value_valid:
            return

        if (self.value is None):
            if (os.path.exists(self.file_name)):
                try:
                    os.remove(self.file_name)
                except Exception:
                    pass
        else:
            f = open(self.file_name, "w")
            f.write(self.value)
            f.write("\n")
            f.close()


class Instruction(object):
    """
    Something stored in an InstructionFile.

    Subtypes of this type are mainly defined in the instr.py module.
    """

    def to_xml(self, doc):
        """
        Given an XML document, return a node which represents this instruction
        """
        raise utils.MuddleBug("Cannot convert Instruction base class to XML")

    def clone_from_xml(self, xmlNode):
        """
        Given an XML node, create a clone of yourself, initialised from that
        XML or raise an error.
        """
        raise utils.MuddleBug("Cannot convert XML to Instruction base class")

    def outer_elem_name(self):
        """
        What's the outer element name for this instructiont type?
        """
        return "instruction"

    def equal(self, other):
        """
        Return True iff self and other represent the same instruction.

        Not __eq__() because we want the python identity to be object identity
        as always.
        """
        if (self.__class__ == other.__class__):
            return True
        else:
            return False



class InstructionFactory(object):
    """
    An instruction factory.
    """

    def from_xml(self, xmlNode):
        """
        Given an xmlNode, manufacture an Instruction from it or return
        None if none could be built
        """
        return None



class InstructionFile(object):
    """
    An XML file containing a sequence of instructions for deployments.
    Each instruction is a subtype of Instruction.
    """

    def __init__(self, file_name, factory):
        """
        file_name       Where this file is stored
        values          A list of instructions. Note that instructions are ordered.
        """
        self.file_name = file_name
        self.values = None
        self.factory = factory


    def __iter__(self):
        """
        We can safely delegate iteration to our values collection.
        """
        if (self.values is None):
            self.read()

        return self.values.__iter__()

    def save_as(self, file_name):
        self.commit(file_name)

    def get(self):
        """
        Retrieve the value of this instruction file.
        """
        if (self.values is None):
            self.read()

        return self.values

    def add(self, instr):
        """
        Add an instruction.
        """
        if (self.values is None):
            self.read()

        self.values.append(instr)

    def clear(self):
        self.values = [ ]

    def read(self):
        """
        Read our instructions from disc. The XML file in question looks like::

            <?xml version="1.0"?>
            <instructions priority=100>
             <instr-name>
               <stuff .. />
             </instr-name>
            </instructions>

        The priority is used by deployments when deciding in what order to
        apply instructions. Higher priorities get applied last (which is the
        logical way around, if you think about it).
        """
        self.values = [ ]

        if (not os.path.exists(self.file_name)):
            return

        try:
            top = xml.dom.minidom.parse(self.file_name)
            doc = top.documentElement

            if (doc.nodeName != "instructions"):
                raise utils.MuddleBug("Instruction file %s does not have <instructions> as its document element.",
                                  self.file_name)

            # See if we have a priority attribute.
            prio = doc.getAttribute("priority")
            if (len(prio) > 0):
                self.priority = int(prio)
            else:
                self.priority = 0


            for i in doc.childNodes:
                if (i.nodeType == i.ELEMENT_NODE):
                    # Try to build an instruction from it ..
                    instr = self.factory.from_xml(i)
                    if (instr is None):
                        raise utils.MuddleBug("Could not manufacture an instruction "
                                          "from node %s in file %s."%(i.nodeName, self.file_name))
                    self.values.append(instr)


        except utils.MuddleBug, e:
            raise e
        except Exception, x:
            traceback.print_exc()
            raise utils.MuddleBug("Cannot read instruction XML from %s - %s"%(self.file_name,x))


    def commit(self, file_name):
        """
        Commit an instruction list file back to disc.
        """

        if (self.values is None):
            # Attempt to read it.
            self.read()

        try:
            f = open(file_name, "w")
            f.write(self.get_xml())
            f.close()
        except Exception, e:
            raise utils.MuddleBug("Could not write instruction file %s - %s"%(file_name,e ))

    def get_xml(self):
        """
        Return an XML representation of this set of instructions as a string.
        """
        try:
            impl = xml.dom.minidom.getDOMImplementation()
            new_doc = impl.createDocument(None, "instructions", None)
            top = new_doc.documentElement

            for i in self.values:
                elem = i.to_xml(new_doc)
                top.appendChild(new_doc.createTextNode("\n"))
                top.appendChild(elem)

            top.appendChild(new_doc.createTextNode("\n"))

            return top.toxml()
        except Exception,e:
            traceback.print_exc()
            raise utils.MuddleBug("Could not render instruction list - %s"%e)

    def __str__(self):
        """
        Convert to a string. Our preferred string representation is XML.
        """
        return self.get_xml()


    def equal(self, other):
        """
        Return True iff self and other represent the same set of instructions.
        False if they don't.
        """
        if (self.values is None):
            self.read()
        if (other.values is None):
            other.read()

        if (len(self.values) != len(other.values)):
            return False

        for i in range(0, len(self.values)):
            if not self.values[i].equal(other.values[i]):
                return False

        return True





class TagFile(object):
    """
    An XML file containing a set of tags (statements).
    """

    def __init__(self, file_name):
        self.file_name = file_name
        self.value = None


    def get(self):
        """
        Retrieve the value of this tagfile.
        """
        if (self.value is None):
            self.read()

        return self.value

    def set(self, tag_value):
        """
        Set the relevant tag value.
        """
        if (self.value is None):
            self.read()

        self.value += tag_value

    def clear(self, tag_value):
        """
        Clear the relevant tag value.
        """
        if (self.value is None):
            self.read()

        self.value -= tag_value

    def erase(self):
        """
        Erase this tag file.
        """
        self.value = set()

    def read(self):
        """
        Read data in from the disc.

        The XML file in question looks a bit like::

            <?xml version="1.0"?>
            <tags>
              <X />
              <Y />
            </tags>
        """

        new_value = set()

        try:
            top = xml.dom.minidom.parse(self.file_name)

            # Get the root element
            doc = top.documentElement()

            for i in doc.childNodes:
                if (i.nodeType == i.ELEMENT_NODE):
                    new_value += i.tagName
        except:
            pass

        return new_value

    def commit(self):
        """
        Commit an XML tagfile back to a file.
        """

        if (self.value is None):
            return


        try:
            impl = xml.dom.minidom.getDOMImplementation()
            new_doc = impl.createDocument(None, "tags", None)
            top = new_doc.documentElement

            for i in self.value:
                this_elem = new_doc.createElement(i)
                top.appendChild(this_elem)

            f = open(self.file_name, "w")
            f.write(top.toxml())
            f.close()
        except:
            raise utils.MuddleBug("Could not write tagfile %s"%self.file_name)


def load_instruction_helper(x,y):
    """
    Given two triples (l,f,i), compare i.prio followed by f.
    """

    (l1, f1, i1) = x
    (l2, f2, i2) = y

    rv = cmp(l1,l2)
    if rv == 0:
        return cmp(f1, f2)
    else:
        return rv


def load_instructions(in_instructions, a_factory):
    """
    Given a list of pairs (label, filename) and a factory, load each instruction
    file, sort the result by priority and filename (the filename just to ensure
    that the sort is stable across fs operations), and return a list of triples
    (label,  filename, instructionfile).

    * in_instructions -
    * a_factory - An instruction factory - typically instr.factory.

    Returns a list of triples (label, filename, instructionfile object)
    """

    # First off, just load everything ..
    loaded = [ ]

    for (lbl, filename) in in_instructions:
        the_if = InstructionFile(filename, a_factory)
        the_if.read()
        loaded.append( ( lbl, filename, the_if ) )


    # OK. Now sort by priority and filename ..
    loaded.sort(load_instruction_helper)

    return loaded


# End file


