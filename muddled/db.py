"""
Contains code which maintains the muddle database,
held in root/.muddle
"""

import errno
import os
import re
import xml.dom
import xml.dom.minidom
import traceback

import muddled.utils as utils
import muddled.depend as depend

from muddled.utils import GiveUp, MuddleBug
from muddled.utils import domain_subpath, split_vcs_url
from muddled.depend import normalise_checkout_label
from muddled.repository import Repository

class CheckoutData(object):
    """
    * location - The directory the checkout is in, relative to the root of the
      build tree. For instance::

        src/builds
        domains/subdomain1/src/first_co

    * dir and leaf - The same information, as it was originally specified in
      the build description. This is primarily of use in version stamping.
      The dir may be None, and the leaf defaults to the checkout labels name.

      We expect to take the repository described in 'repo' and check it out
      into:

      * src/<co_leaf> or
      * src/<co_dir>/<co_leaf>

      depending on whether <co_dir> is None.

    * repo - A Repository instance, representing where the checkout is checked
      out from. For example (eliding the actual URL)::

        Repository('git', 'http://.../main', 'builds')
        Repository('git', 'http://.../subdomain1', 'first_co')

      This the Repository as defined in the build description.

    * vcs_handler - A VCS handler, which knows how to do version control
      operations for this checkout.

    * options - Any specialised optons needed by the VCS handler. At the
      moment, the only option available is whether a git checkout is shallow or
      not. This is a dictionary.
    """

    def __init__(self, vcs_handler, repo, co_dir, co_leaf):
        self.vcs_handler = vcs_handler
        self.repo  = repo

        self.dir = co_dir
        self.leaf = co_leaf

        if co_dir:
            self.location = os.path.join('src', co_dir, co_leaf)
        else:
            self.location = os.path.join('src', co_leaf)

        self.options = {}

    def __repr__(self):
        parts = []
        parts.append(repr(self.vcs_handler))
        parts.append(repr(self.repo))
        parts.append(repr(self.dir))
        parts.append(repr(self.leaf))
        return 'CheckoutData(' + ', '.join(parts) + ')'

    def move_to_subdomain(self, other_domain_name):
        # Note that our 'dir' and 'leaf' are always with respect to the local
        # domain, so we do not need to change them

        self.location = os.path.join(utils.domain_subpath(other_domain_name), self.location)

    def set_option(self, name, value):
        """
        Add/replace the named VCS option 'name'.

        For reasons mostly to do with how stamping/unstamping works,
        we require option values to be either boolean, integer or string.

        Also, only those option names that are explicitly allowed for a
        particular VCS may be used.
        """
        vcs = self.vcs_handler.vcs

        if name not in vcs.allowed_options:
            raise GiveUp("Option '%s' is not allowed for VCS %s'"%(name, vcs.short_name))

        if not (isinstance(value, bool) or isinstance(value, int) or
                isinstance(value, str)):
            raise GiveUp("Options to VCS must be bool, int or string."
                         "'%s' option %s is %s"%(name, repr(value), type(value)))

        self.options[name] = value


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

    Various PathFile instances:

    * RootRepository_pathfile - for the '.muddle/RootRepository' file
    * Description_pathfile - for the '.muddle/Description' file
    * VersionsRepository_pathfile - for the '.muddle/VersionsRepository' file
    * DescriptionBranch_pathfile - for the '.muddle/DescriptionBranch' file

    which describe what the user requested via the original "muddle init".

    and:

    * local_labels - Transient labels which are "asserted", via
      'set_tag()', and queried via 'is_tag()'. This functionality is used
      inside the Builder's "build_label()" mechanism, and is only intended
      for use within muddle itself.

    Also, a variety of dictionaries that take (mostly) checkout labels as keys.
    Note that:

    1. All the keys are "normalised" to have an unset label tag.
    2. Thus it is assumed that the dictionaries will only be accessed via
       the methods supplied for this purpose.
    3. The existence of an entry does not necessarily imply that the
       particular checkout is actually used, as the need for it may
       have gone away during a ``builder.unify()`` operation.

    and, perhaps most importantly, the user should treat all of these as
    READ ONLY, since muddle itself maintains their content.

    The dictionaries we use are:

    * checkout_data - This maps checkout labels to the information we need
      to do checkout actions.

    * checkout_vcs - This is a cache remembering the VCS for a checkout. It
      is not intended for direct access.

    * checkout_licenses - This maps a checkout label to a License instance,
      representing the source code license under which this checkout's source
      code is being used. For instance::

        checkout:builds/*               -> License('MPL 1.1', 'open-source')
        checkout:(subdomain1)first_co/* -> License('LGPL v3', 'gpl')

      In the case of a checkout that has multiple licenses, the license that is
      being "used" should be indicated.

      Note that not all checkouts will necessarily have licenses associated
      with them.

    * checkout_license_files - Some licenses require distribution of a license
      file from within the checkout, even in binary distributions. In such
      cases, this dictionary maps the checkout label to the name of the license
      file, relative to the checkout directory.

    * license_not_affected_by is a dictionary of the form:

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

      Note that ALL labels in this dictionary and its constituent sets should
      have their tags set to '*', so it is expected that this dictionary will
      be accessed using set_license_not_affected_by() and
      get_license_not_affected_by().

    * nothing_builds_against is a set of checkout labels, each of which is
      a checkout that (presumably) has a GPL license, but against which no
      package links in a way that will cause GPL license "propagation".

    * upstream_repositories is a dictionary of the form:

        { repo : { repo, set(names) } }

      That is, the key is a Repository instance (normally expected to be
      the same as one of the values in the checkout_repos dictionary), and
      the value is a dictionary whose keys are other repositories ("upstream"
      repositories) and some names associated with them.

      The same names may be associated with more than one upstream repository.
      It is also conceivable that an upstream repository might also act as a
      key, if it in turn has upstream repositories (whether this is strictly
      necessary is unclear - XXX still to decide whether to support this).

       XXX *Note that if a checkout is branched because it is following the
       build description branch, the checkout Repository in checkot_repositories
       will get a new .branch value, at which point it will not necessarily
       compare equal to the Repository we're using as a key. This uncertainty
       MAY be a problem, and it may be better if add_upstream_repo() takes a
       copy of the Repository object before using it as a key, to force the
       issue.*

    * domain_build_desc_label is a dictionary of the form:

        { domain : build-desc-label }

      where domain is the domain from a label (so None or a suitable string),
      and build-desc-label is the (normalised) checkout label for the build
      description checkout for that domain.

      Clearly, there is always at least one entry, with key None, for the
      top-level build description.
    """

    def __init__(self, root_path):
        """
        Initialise a muddle database with the given root_path.
        """
        self.root_path = root_path
        utils.ensure_dir(os.path.join(self.root_path, ".muddle"))
        self.RootRepository_pathfile = PathFile(self.db_file_name("RootRepository"))
        self.Description_pathfile = PathFile(self.db_file_name("Description"))
        self.DescriptionBranch_pathfile = PathFile(self.db_file_name("DescriptionBranch"))
        self.VersionsRepository_pathfile = PathFile(self.db_file_name("VersionsRepository"))

        self.just_pulled = JustPulledFile(os.path.join(self.root_path,
                                          '.muddle',
                                          '_just_pulled'))

        self.checkout_data = {}

        self.checkout_licenses = {}
        self.checkout_license_files = {}
        self.license_not_affected_by = {}
        self.nothing_builds_against = set()

        # A set of "asserted" labels
        self.local_tags = set()

        # Upstream repositories
        self.upstream_repositories = {}

        # Build description checkout labels by domain
        self.domain_build_desc_label = {}

    def setup(self, repo_location, build_desc, versions_repo=None, branch=None):
        """
        Set values for the files in .muddle that describe our intial state.

        * 'repo_location' is written to .muddle/RootRepository

        * 'build_desc' is written to .muddle/Description

        * If 'versions_repo' is not None, it is written to .muddle/VersionsRepository.
          Note that "not None" means that a value of '' *will* be written to
          the file.

          If 'versions_repo' is None, and 'repo_location' is not a centralised
          VCS (i.e., subversion), then it will be written to
          .muddle/VersionsRepository instead.

        * If 'branch' is not None, then it will be written to .muddle/DescriptionBranch

        This method should only be called by muddle itself.
        """
        self.RootRepository_pathfile.set(repo_location)
        self.Description_pathfile.set(build_desc)
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
                # We go via Repository so that we get the correct handler for
                # sites like Google Code
                versions_repo = Repository(vcs, repo, "versions")
                self.VersionsRepository_pathfile.set('%s+%s'%(vcs, versions_repo.url))
        else:
            self.VersionsRepository_pathfile.set(versions_repo)
        if branch is not None:
            self.DescriptionBranch_pathfile.set(branch)
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

    def _inner_labels(self):
        """Return a list of all the labels we use.

        This is so that mechanics.py can amend them all when we're being
        included as a subdomain...

        Note that we DO NOT CARE if identical labels (those that compare the
        same with "is") are added to the list, as each label instance will
        only be updated once, regardless of how many times it occurs. But we DO
        want to make sure we have *all* non-identical labels.
        """
        labels = []
        labels.extend(self.checkout_data.keys())
        labels.extend(self.checkout_licenses.keys())
        labels.extend(self.checkout_license_files.keys())
        labels.extend(self.license_not_affected_by.keys())
        labels.extend(self.nothing_builds_against)
        # Don't forget the labels in the license_not_affected_by values
        for not_against in self.license_not_affected_by.values():
            labels.extend(not_against)
        # Or the checkout labels in the domain_build_desc_label values
        labels.extend(self.domain_build_desc_label.values())
        # And there are the labels in our just_pulled set...
        labels.extend(self.just_pulled.labels)
        return labels

    def include_domain(self, other_builder, other_domain_name):
        """
        Include data from other_builder, built in other_domain_name

        This method is the main reason why this class gets to hold so much
        information - it gives us a single place to concentrate much of the
        knowledge about including subdomains.

        Note we rely upon all the labels in the other domain already having
        been altered to reflect their subdomain-ness

        This should only be called by muddle itself.
        """
        other_db = other_builder.db

        self._merge_subdomain_labels(other_domain_name, other_db)
        self._merge_subdomain_upstreams(other_domain_name, other_db)
        self._merge_domain_information(other_domain_name, other_db)

    def _merge_subdomain_labels(self, other_domain_name, other_db):
        """Merge things from the subdomain that contain labels.
        """
        for co_obj in other_db.checkout_data.values():
            co_obj.move_to_subdomain(other_domain_name)
        self.checkout_data.update(other_db.checkout_data)

        self.checkout_licenses.update(other_db.checkout_licenses)
        self.checkout_license_files.update(other_db.checkout_license_files)

        for pkg_label, not_against in other_db.license_not_affected_by.items():
            if pkg_label in self.license_not_affected_by:
                self.license_not_affected_by[pkg_label].update(not_against)
            else:
                self.license_not_affected_by[pkg_label] = not_against

        self.nothing_builds_against.update(other_db.nothing_builds_against)

        # If the subdomain just pulled stuff (as it will have done if it
        # checked anything out, because that counts), then we need to add
        # it to *our* set of just_pulled stuff
        self.just_pulled.labels.update(other_db.just_pulled.labels)

    def _merge_subdomain_upstreams(self, other_domain_name, other_db):
        """Merge things from the subdomain that contain upstream repositories.
        """
        # We're likely to want to know what repositories we've already got
        already_got = set()
        for co_obj in self.checkout_data.values():
            already_got.add(co_obj.repo)

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
                # checkout. Which we calculated earlier.
                #
                # So we can tell if this is a repository (associated with a
                # checkout) that we already know about, or if it is a
                # repository we have no idea about (and which we therefore
                # hope is being remembered for some good reason - but ours
                # is not to reason why).
                if orig_repo in already_got:
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

    def _merge_domain_information(self, other_domain_name, other_db):
        """Merge the build description specific information from the subdomain.

        We know the checkout labels that form our values will already have
        had their domain names adjusted, so this *should* be simple enough
        """
        # Make a simple check for consistency
        build_desc_label = other_db.domain_build_desc_label[None]
        if build_desc_label.domain != other_domain_name:
            raise MuddleBug('Error merging domain_build_desc_label for subdomain "%s"\n'
                            'Build description label is %s, in domain %s'%(other_domain_name,
                                build_desc_label, build_desc_label.domain))

        # Start with the domain -> checkout label dictionary
        for label in other_db.domain_build_desc_label.values():
            domain = label.domain
            if domain in self.domain_build_desc_label:
                # Let's check it's the value we expect
                if label != self.domain_build_desc_label[label.domain]:
                    raise MuddleBug('Error merging domain_build_desc_label'
                                    ' dictionary into subdomain "%s"\n'
                                    'Given label "%s", but dictionary entry for'
                                    ' domain "%s" is already "%s"'%(other_domain_name,
                                        label, domain,
                                        self.domain_build_desc_label[domain]))
            else:
                self.domain_build_desc_label[label.domain] = label

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

        raise GiveUp('\n'.join(details))

    def set_domain_marker(self, domain_name):
        """
        Mark this as a (sub)domain

        In a (sub)domain, we have a file called ``.muddle/am_subdomain``,
        which acts as a useful flag that we *are* a (sub)domain.
        """
        utils.mark_as_domain(self.root_path, domain_name)

    def set_checkout_data(self, checkout_label, co_data):
        key = normalise_checkout_label(checkout_label)
        self.checkout_data[key] = co_data

    def get_checkout_data(self, checkout_label):
        key = normalise_checkout_label(checkout_label)
        try:
            return self.checkout_data[key]
        except KeyError:
            raise GiveUp('There is no checkout data registered for label %s'%checkout_label)

    def dump_checkout_paths(self):
        print "> Checkout paths .."
        keys = self.checkout_data.keys()
        max = 0
        for label in keys:
            length = len(str(label))
            if length > max:
                max = length
        keys.sort()
        for label in keys:
            print "%-*s -> %s"%(max, label, self.checkout_data[label].location)

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

        key = normalise_checkout_label(checkout_label)
        try:
            rel_dir = self.checkout_data[key].location
        except KeyError:
            raise GiveUp('There is no checkout data (path) registered for label %s'%checkout_label)
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

        key = normalise_checkout_label(checkout_label)
        try:
            return self.checkout_data[key].location
        except KeyError:
            raise GiveUp('There is no checkout data (location) registered for label %s'%checkout_label)

    def get_checkout_dir_and_leaf(self, checkout_label):
        key = normalise_checkout_label(checkout_label)
        try:
            co_data = self.checkout_data[key]
            return co_data.dir, co_data.leaf
        except KeyError:
            raise GiveUp('There is no checkout data (dir & leaf) registered for label %s'%checkout_label)

    def dump_checkout_repos(self, just_url=False):
        """
        Report on the repositories associated with our checkouts.

        If 'just_url' is true, then report the repository URL, otherwise
        report the full Repository definition (which shows branch and revision
        as well).
        """
        print "> Checkout repositories .."
        keys = self.checkout_data.keys()
        max = 0
        for label in keys:
            length = len(str(label))
            if length > max:
                max = length
        keys.sort()
        if just_url:
            for label in keys:
                print "%-*s -> %s"%(max, label, self.checkout_data[label].repo)
        else:
            for label in keys:
                print "%-*s -> %r"%(max, label, self.checkout_data[label].repo)

    def get_checkout_repo(self, checkout_label):
        """
        Returns the Repository instance for this checkout label
        """
        key = normalise_checkout_label(checkout_label)
        try:
            return self.checkout_data[key].repo
        except KeyError:
            raise GiveUp('There is no checkout data (repository) registered for label %s'%checkout_label)

    def dump_checkout_vcs(self):
        """
        Report on the version control systems associated with our checkouts,
        and any VCS options.
        """
        print "> Checkout version control systems .."
        keys = self.checkout_data.keys()
        max = 0
        for label in keys:
            length = len(str(label))
            if length > max:
                max = length
        keys.sort()
        for label in keys:
            options = self.checkout_data[label].options
            if options:
                print "%-*s -> %s %s"%(max, label, self.checkout_data[label].vcs_handler, options)
            else:
                print "%-*s -> %s"%(max, label, self.checkout_data[label].vcs_handler)

    def get_checkout_vcs(self, checkout_label):
        """
        'checkout_label' is a "checkout:" Label.

        Returns the VCS handler for the given checkout.

        Raises GiveUp (containing an explanatory message) if we cannot find
        that checkout label.
        """
        key = normalise_checkout_label(checkout_label)
        try:
            return self.checkout_data[key].vcs_handler
        except KeyError:
            raise GiveUp('There is no checkout data (VCS) registered for label %s'%checkout_label)

    def get_checkout_vcs_options(self, checkout_label):
        """
        'checkout_label' is a "checkout:" Label.

        Returns the options for the given checkout, as a (possibly empty) dictionary.

        Since most checkouts will not have options, and will thus have no entry
        for such, cannot return an error if there is no such checkout in the
        build.
        """
        key = normalise_checkout_label(checkout_label)
        try:
            return self.checkout_data[key].options
        except KeyError:
            raise GiveUp('There is no checkout data (VCS options) registered for label %s'%checkout_label)

    def set_checkout_vcs_option(self, checkout_label, option_name, option_value):
        """
        'checkout_label' is a "checkout:" Label.
        """
        key = normalise_checkout_label(checkout_label)
        self.checkout_data[key].set_option(option_name, option_value)

    def set_domain_build_desc_label(self, checkout_label):
        """This should only be called by muddle itself.
        """
        domain = checkout_label.domain
        if domain == '':
            domain = None
        self.domain_build_desc_label[domain] = normalise_checkout_label(checkout_label)

    def dump_domain_build_desc_labels(self):
        print "> Build descriptions for each domain .."
        keys = self.domain_build_desc_label.keys()
        max = 0
        for domain in keys:
            if domain:
                length = len(domain)
                if length > max:
                    max = length
        keys.sort()
        for domain in keys:
            print "%-*s -> %s"%(max, domain if domain is not None else '',
                                self.domain_build_desc_label[domain])

    def get_domain_build_desc_label(self, domain):
        """
        'domain' is a domain as taken from a label, so None or a string

        If it is None, then the checkout label for the top-level build
        description is returned.

        Otherwise, the checkout label for the build description for that
        domain is returned.

        In either case, the checkout label will be normalised (so its tag
        will be '*')

        Raises GiveUp with an appropriate message if 'domain' is not
        recognised.
        """
        if domain == '':
            domain = None
        try:
            return self.domain_build_desc_label[domain]
        except KeyError:
            raise utils.GiveUp('There is no build description checkout label'
                               ' registered for domain "%s"'%domain)

    def set_checkout_license(self, checkout_label, license):
        key = normalise_checkout_label(checkout_label)
        self.checkout_licenses[key] = license

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
        key = normalise_checkout_label(checkout_label)
        try:
            return self.checkout_licenses[key]
        except KeyError:
            if absent_is_None:
                return None
            else:
                raise GiveUp('There is no license registered for label %s'%checkout_label)

    def checkout_has_license(self, checkout_label):
        """
        Return True if the named checkout has a license registered
        """
        key = normalise_checkout_label(checkout_label)
        return key in self.checkout_licenses

    def set_checkout_license_file(self, checkout_label, license_file):
        """Set the license file for this checkout.
        """
        key = normalise_checkout_label(checkout_label)
        self.checkout_license_files[key] = license_file

    def get_checkout_license_file(self, checkout_label, absent_is_None=False):
        """
        Returns the License file for this checkout label

        If 'absent_is_None' is true, then if 'checkout_label' does not have
        an entry in the license files dictionary, None will be returned.
        Otherwise, an appropriate GiveUp exception will be raised.
        """
        key = normalise_checkout_label(checkout_label)
        try:
            return self.checkout_license_files[key]
        except KeyError:
            if absent_is_None:
                return None
            else:
                raise GiveUp('There is no license file registered for label %s'%checkout_label)

    def set_license_not_affected_by(self, this_label, co_label):
        """Asserts that the license for 'co_label' does not affect 'pkg_label'

        We assume that:

        1. 'this_label' is a package that depends (perhaps indirectly) on
           'co_label', or is a checkout directly required by such a package.
        2. 'co_label' is a checkout with a "propagating" license (i.e., some
           form of GPL license).
        3. Thus by default the "GPL"ness would propagate from 'co_label' to
           'this_label' (and, if it is a package, to the checkouts it is
           (directly) built from).

        However, this function asserts that, in fact, this is not true. Our
        checkout is (or our checkouts are) not built in such a way as to cause
        the license for 'co_label' to propagate.

        Or, putting it another way, for a normal GPL license, we're not linking
        with anything from 'co_label', or using its header files, or copying
        GPL'ed files from it, and so on.

        If 'co_label' is under LGPL, then that would reduce to saying we're not
        static linking against 'co_label' (or anything else not allowed by the
        LGPL).

        Note that we may be called before 'co_label' has registered its
        license, so we cannot actually check that 'co_label' has a propagating
        license (or, indeed, that it exists or is depended upon by 'pkg_label').
        """
        if this_label.type not in (utils.LabelType.Package, utils.LabelType.Checkout):
            raise GiveUp('First label in set_license_not_affected_by() is %s, which is not'
                         ' a package or checkout'%this_label)
        if co_label.type != utils.LabelType.Checkout:
            raise GiveUp('Second label in set_license_not_affected_by() is %s, which is not'
                         ' a checkout'%co_label)

        if this_label.tag == '*':
            key = this_label
        else:
            key = this_label.copy_with_tag('*')

        value = normalise_checkout_label(co_label)

        if key in self.license_not_affected_by:
            self.license_not_affected_by[key].add(value)
        else:
            self.license_not_affected_by[key] = set([value])

    def get_license_not_affected_by(self, this_label):
        """Find what is registered as not affecting this label's license

        That is, the things on which this package depends, that appear to be
        GPL and propagate, but against which we have been told we do not
        actually build, so the license is not, in fact, propagated.

        Returns a (possibly empty) set of checkout labels, each with tag '*'.
        """
        if this_label.tag == '*':
            key = this_label
        else:
            key = this_label.copy_with_tag('*')

        try:
            return self.license_not_affected_by[key]
        except KeyError:
            return set()

    def set_nothing_builds_against(self, co_label):
        """Indicate that no-one links against this checkout.

        ...or, at least, not in a way to cause GPL license "propagation".
        """
        label = normalise_checkout_label(co_label)
        self.nothing_builds_against.add(label)

    def get_nothing_builds_against(self, co_label):
        """Return True if this label is in the "not linked against" set.
        """
        label = normalise_checkout_label(co_label)
        return label in self.nothing_builds_against

    upstream_name_re = re.compile(r'[A-Za-z0-9_-]+')

    def add_upstream_repo(self, orig_repo, upstream_repo, names):
        """Add an upstream repo to 'orig_repo'.

        - 'orig_repo' is the original Repository that we are adding an
          upstream for.
        - 'upstream_repo' is the upstream Repository. It is an error if
          that repository is already an upstream of 'orig_repo'.
        - 'names' is a either a single string, or a sequence of strings, that
          can be used to select this (and possibly other) upstream
          repositories.

        Upstream repository names must be formed of A-Z, a-z, 0-9 and
        underscore or hyphen.
        """
        if not names:
            raise GiveUp('An upstream repository must have at least one name')

        if isinstance(names, basestring):
            names = [names]

        for name in names:
            m = Database.upstream_name_re.match(name)
            if m is None or m.end() != len(name):
                raise GiveUp("Upstream repository name '%s' is not allowed"%(name))

        if orig_repo in self.upstream_repositories:
            upstream_dict = self.upstream_repositories[orig_repo]
            if upstream_repo in upstream_dict:
                raise GiveUp('Repository %r is already upstream of %r'%(upstream_repo, orig_repo))
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
        for co_label, co_data in self.checkout_data.items():
            if co_data.repo == repo:
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
            print format1%(orig_repo, depend.label_list_to_string(sorted(co_labels),
                                                                  join_with=', '))
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
        return os.path.join(self.root_path, "src", self.Description_pathfile.get())

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
            raise MuddleBug("Attempt to retrieve instruction file "
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
        self.RootRepository_pathfile.commit()
        self.Description_pathfile.commit()
        self.DescriptionBranch_pathfile.commit()
        self.VersionsRepository_pathfile.commit()


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

    def get_if_it_exists(self):
        """
        Retrieve the current value of the PathFile, if it exists (on disk).

        This variant does not try to cache the value.
        """
        try:
            f = open(self.file_name, "r")
            val = f.readline()
            f.close()

            # Remove the trailing '\n' if it exists.
            if val[-1] == '\n':
                val = val[:-1]

        except IndexError as i:
            raise GiveUp("Contents of db file %s are empty - %s\n"%(self.file_name, i))
        except IOError as e:
            if e.errno == errno.ENOENT:
                return None     # but don't try to cache it
            else:
                raise GiveUp("Error retrieving value from %s\n    %s"%(self.file_name, e))

        return val

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
            raise GiveUp("Contents of db file %s are empty - %s\n"%(self.file_name, i))
        except IOError as e:
            raise GiveUp("Error retrieving value from %s\n    %s"%(self.file_name, str(e)))

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
        raise MuddleBug("Cannot convert Instruction base class to XML")

    def clone_from_xml(self, xmlNode):
        """
        Given an XML node, create a clone of yourself, initialised from that
        XML or raise an error.
        """
        raise MuddleBug("Cannot convert XML to Instruction base class")

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
                raise MuddleBug("Instruction file %s does not have <instructions> as its document element.",
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
                        raise MuddleBug("Could not manufacture an instruction "
                                        "from node %s in file %s."%(i.nodeName, self.file_name))
                    self.values.append(instr)


        except MuddleBug, e:
            raise e
        except Exception, x:
            traceback.print_exc()
            raise MuddleBug("Cannot read instruction XML from %s - %s"%(self.file_name,x))


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
            raise MuddleBug("Could not write instruction file %s - %s"%(file_name,e ))

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
            raise MuddleBug("Could not render instruction list - %s"%e)

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
            raise MuddleBug("Could not write tagfile %s"%self.file_name)


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


class JustPulledFile(object):
    """Our memory of the checkouts that have just been pulled.
    """

    def __init__(self, file_name):
        """Set the path to the _just_pulled file.
        """
        self.file_name = file_name
        self.labels = set()

    def get_from_disk(self):
        """Retrieve the contents of the _just_pulled file as a list of labels.

        First clears the local memory, then reads the labels in the _just_pulled
        file into local memory, then returns that set as a sorted list.
        """
        self.labels.clear()
        try:
            line_no = 0
            with open(self.file_name) as fd:
                for line in fd:
                    line_no += 1
                    line = line.strip()
                    if not line:    # Might as well ignore empty lines
                        continue
                    try:
                        label = depend.Label.from_string(line)
                    except GiveUp as e:
                        raise GiveUp('Error reading line %d of %s:\n%s'%(line_no,
                            self.file_name, e))
                    self.labels.add(label)

            return sorted(self.labels)
        except IOError as e:
            if e.errno == errno.ENOENT:
                # File doesn't exist - so noone has created it yet
                return []
            else:
                raise

    def clear(self):
        """Clear the contents of the _just_pulled file, and our local memory.

        If the _just_pulled files does not exist, does nothing
        """
        self.labels.clear()
        if os.path.exists(self.file_name):
            with open(self.file_name, 'w') as fd:
                pass

    def add(self, label):
        """Add the label to our local memory.

        The label is not added to the _just_pulled file until commit() is
        called.
        """
        self.labels.add(label.copy_with_tag(utils.LabelTag.CheckedOut))

    def is_pulled(self, label):
        l = label.copy_with_tag(utils.LabelTag.CheckedOut)
        return l in self.labels

    def commit(self):
        """Commit our local memory to the _just_pulled file.

        The labels are sorted before being written to the file.

        Leaves the local memory intact after writing (it does not clear it).
        """
        with open(self.file_name, 'w') as fd:
            for label in sorted(self.labels):
                ##print 'XXX %s'%label
                fd.write('%s\n'%label)

# End file


