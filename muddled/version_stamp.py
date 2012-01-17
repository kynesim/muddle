"""VersionStamp and stamp file support.

.. TODO .. Insert accurate documentation for version 2 stamp files ..

.. TODO .. Insert approximate (historical) documentation for version 1 stamp files ..
"""

import sys

from collections import namedtuple, Mapping
from ConfigParser import RawConfigParser

from muddled.repository import Repository
from muddled.utils import MuddleSortedDict, HashFile, GiveUp

DomainTuple = namedtuple('DomainTuple', 'name repository description')
CheckoutTupleV1 = namedtuple('CheckoutTupleV1', 'name repo rev rel dir domain co_leaf branch')

def set_option(config, section, name, value):
    """Set an option in a section.
    """
    config.set(section, name, value)

def maybe_set_option(config, section, name, value):
    """Set an option in a section, if its value is not None.
    """
    if value is not None:
        config.set(section, name, value)

def get_option(config, section, name):
    """Get an option from a section, as a string.
    """
    return config.get(section, name)

def maybe_get_option(config, section, name):
    """Get an option from a section, as a string, or as None.

    If the option is present, return it, otherwise return None.
    """
    if config.has_option(section, name):
        return config.get(section, name)
    else:
        return None

class VersionStamp(Mapping):
    """A representation of the revision state of a build tree's checkouts.

    Our internal data is:

        * 'repository' is a string giving the default repository (as stored
          in ``.muddle/RootRepository``)

        * ``description`` is a string naming the build description (as stored
          in ``.muddle/Description``)

        * 'domains' is a (possibly empty) set of tuples (specifically,
          DomainTuple), each containing:

            * name - the name of the domain
            * repository - the default repository for the domain
            * descripton - the build description for the domain

        * 'checkouts' is a list of named tuples (specifically, CheckoutTupleV1)
          describing the checkouts, each tuple containing:

            * name - the name of the checkout
            * repo - the actual repository of the checkout
            * rev - the revision of the checkout
            * rel - the relative directory of the checkout
              (the 'prefix' from the Repository instance)
            * dir - the directory in ``src`` where the checkout goes
            * domain - which domain the checkout is in, or None. This
              is the domain as given within '(' and ')' in a label, so
              it may contain commas - for instance "fred" or "fred,jim,bob".
            * co_leaf - The leaf directory in which this checkout resides -
              this is just the name for one and two-level checkouts, but will
              be different for multilevel checkouts
            * branch - the branch for this checkout, if it is not the default
              (e.g., "master" in git).

          These are essentially the exact arguments that would have been given
          to the old VCS initialisation mechanism, and should be enough to
          enable us to recreate a checkout exactly.

        * 'problems' is a list of problems in determining the stamp
          information. This will be of zero length if the stamp if accurate,
          but will otherwise contain a string for each checkout whose revision
          could not be accurately determined.

          Note that when problems descriptions are written to a stamp file,
          they are truncated.

    A VersionStamp instance also acts as if it were a dictionary from checkout
    name to the checkout tuple.

    So, for instance:

        >>> v = VersionStamp('Somewhere', 'src/builds/01.py', [],
        ...                  [('fred', 'vcs+Somewhere', 3, None, 'fred', None, None, None),
        ...                   ('jim',  'vcs+Elsewhere', 7, None, 'jim', None, 'sheila', None)],
        ...                  ['Oops, a problem'])
        >>> print v
        [ROOT]
        repository = Somewhere
        description = src/builds/01.py
        <BLANKLINE>
        [CHECKOUT fred]
        directory = fred
        name = fred
        repository = vcs+Somewhere
        revision = 3
        <BLANKLINE>
        [CHECKOUT jim]
        co_leaf = sheila
        directory = jim
        name = jim
        repository = vcs+Elsewhere
        revision = 7
        <BLANKLINE>
        [PROBLEMS]
        problem1 = Oops, a problem
        >>> v['jim']
        CheckoutTupleV1(name='jim', repo='vcs+Elsewhere', rev=7, rel=None, dir='jim', domain=None, co_leaf='sheila', branch=None)

    Note that this is *not* intended to be a mutable class, so please do not
    change any of its internals directly. In particular, if you *did* change
    the checkouts sequence, you would definitely need to remember to update
    the checkouts dictionary, and vice versa. And you would need to remember
    that the checkouts list is composed of CheckoutTupleV1s, and the domains
    list of DomainTuples, or otherwise stuff would go wrong.
    """

    MAX_PROBLEM_LEN = 100               # At what length to truncate problems

    def __init__(self):
        self.repository = ''
        self.description = ''
        self.domains = {}       # domain_name -> (domain_repo, domain_desc)
        self.checkouts = {}     # label -> (co_dir, co_leaf, repo)
        self.problems = []

    def _update_checkout_dict(self):
        """Always call this after updating self.checkouts. Sorry.
        """
        if self.checkouts:
            self._checkout_dict = dict([ (x.name, x) for x in self.checkouts ])
        else:
            self._checkout_dict = {}

    def __str__(self):
        """Make 'print' do something useful.
        """
        s = StringIO()
        self.write_to_file_object(s)
        rv = s.getvalue()
        s.close()
        return rv.rstrip()

    # ==========================================================
    # Mapping infrastructure
    def __getitem__(self, key):
        return self._checkout_dict[key]

    def __len__(self):
        return len(self._checkout_dict)

    def __contains__(self, key):
        return key in self._checkout_dict

    def __iter__(self):
        return iter(self._checkout_dict)
    # ==========================================================

    def write_to_file(self, filename, version=2):
        """Write our data out to a file.

        By default, writes out a version 2 stamp file, as opposed to the older
        version 1 format.

        Returns the SHA1 hash for the file.
        """
        with HashFile(filename, 'w') as fd:
            self.write_to_file_object(fd, version)
            return fd.hash()

    def write_to_file_object(self, fd, version=2):
        """Write our data out to a file-like object (one with a 'write' method).

        By default, writes out a version 2 stamp file, as opposed to the older
        version 1 format.

        Returns the SHA1 hash for the file.
        """

        if version not in (1, 2):
            raise GiveUp('Attempt to write version %d stamp file;'
                         ' we only support 1 or 2'%version)

        # Note we take care to write out the sections by hand, so that they
        # come out in the order we want, other than in some random order (as
        # we're effectively writing out a dictionary)
        config = RawConfigParser()

        if version > 1:
            config.add_section("STAMP")
            config.set("STAMP", "version", version)
            config.write(fd)

        config.add_section("ROOT")
        config.set("ROOT", "repository", self.repository)
        config.set("ROOT", "description", self.description)
        config.write(fd)

        if self.domains:
            config = RawConfigParser(None, dict_type=MuddleSortedDict)
            domain_names = self.domains.keys()
            #domain_names.sort()
            for domain_name in domain_names:
                domain_repo, domain_desc = self.domains[domain_name]
                section = "DOMAIN %s"%domain_name
                config.add_section(section)
                config.set(section, "name", domain_name)
                config.set(section, "repository", domain_repo)
                config.set(section, "description", domain_desc)
            config.write(fd)

        config = RawConfigParser(None, dict_type=MuddleSortedDict)
        if version == 1:
            co_labels = self.checkouts.keys()
            #co_labels.sort()
            for co_label in co_labels:
                co_dir, co_leaf, repo = self.checkouts[co_label]
                if co_label.domain:
                    section = 'CHECKOUT (%s)%s'%(co_label.domain,
                                                 co_label.name)
                else:
                    section = 'CHECKOUT %s'%co_label.name
                config.add_section(section)
                # =============================================================
                # Attempt to approximate version 1
                if co_label.domain:
                    config.set(section, "domain", co_label.domain)
                config.set(section, "name", co_label.name)
                config.set(section, "repository", '%s+%s'%(repo.vcs, repo.base_url))
                config.set(section, "revision", repo.revision)
                if co_leaf:
                    config.set(section, "co_leaf", co_leaf)
                if repo.prefix:
                    relative = os.path.join(repo.prefix, repo.repo_name)
                else:
                    relative = repo.repo_name
                if rel:
                    config.set(section, "relative", relative)
                if dir:
                    config.set(section, "directory", co_dir)
                if branch:
                    config.set(section, "branch", branch)
                # =============================================================

        else:
            co_labels = self.checkouts.keys()
            #co_labels.sort()
            for co_label in co_labels:
                co_dir, co_leaf, repo = self.checkouts[co_label]
                if co_label.domain:
                    section = 'CHECKOUT (%s)%s'%(co_label.domain,
                                                 co_label.name)
                else:
                    section = 'CHECKOUT %s'%co_label.name
                config.add_section(section)
                config.set(section, "co_label", co_label)
                if vcs.checkout_dir:
                    config.set(section, "co_dir", co_dir)
                if vcs.checkout_leaf:
                    config.set(section, "co_leaf", co_leaf)

                config.set(section, "repo_vcs", repo.vcs)
                # If we got our repository URL as a string, directly, then
                # there is no point in outputting the parts that Repository
                # deduced from it - we just need the original URL
                config.set(section, "repo_from_url_string", repo.from_url_string)
                if not repo.from_url_string:
                    # We need to specify all the parts
                    config.set(section, "repo_base_url", repo.base_url)
                    config.set(section, "repo_name", repo.repo_name)
                    maybe_set_option(config, section, "repo_prefix", repo.prefix)
                    maybe_set_option(config, section, "repo_prefix_as_is", repo.prefix_as_is)
                    maybe_set_option(config, section, "repo_suffix", repo.suffix)
                    maybe_set_option(config, section, "repo_inner_path", repo.inner_path)
                    maybe_set_option(config, section, "repo_revision", repo.revision)
                    maybe_set_option(config, section, "repo_branch", repo.branch)
                    maybe_set_option(config, section, "repo_handler", repo.handler)
                # XXX TODO: what to do about options?
                # XXX Maybe store: option:<key> = '<value>'
                # XXX (do we require option values to be strings? Not at the moment)
                # XXX Or should we lost options and just add a (specific)
                # XXX 'shallow' value to our VersionControlHandler?

        config.write(fd)

        if self.problems:
            config = RawConfigParser(None, dict_type=MuddleSortedDict)
            section = 'PROBLEMS'
            config.add_section(section)
            for index, item in enumerate(self.problems):
                # Let's remove any newlines
                item = ' '.join(item.split())
                config.set(section, 'problem%d'%(index+1), item)
            config.write(fd)

    def print_problems(self, output=None, truncate=None, indent=''):
        """Print out any problems.

        If 'output' is not specified, then it will be STDOUT, otherwise it
        should be a file-like object (supporting 'write').

        If 'truncate' is None (or zero, non-true, etc.) then the problems
        will be truncated to the same length as when writing them to a
        stamp file.

        'indent' should be a string to print in front of every line.

        If there are no problems, this method does not print anything out.
        """
        if not output:
            output = sys.stdout
        if not truncate:
            truncate = self.MAX_PROBLEM_LEN

        for index, item in enumerate(self.problems):
            item = item.rstrip()
            output.write('%sProblem %2d: %s\n'%(indent, index+1,
                                truncate(str(item), columns=truncate)))

    @staticmethod
    def from_builder(builder, force=False, just_use_head=False, quiet=False):
        """Construct a VersionStamp from a muddle build description.

        'builder' is the muddle Builder for our build description.

        If '-force' is true, then attempt to "force" a revision id, even if it
        is not necessarily correct. For instance, if a local working directory
        contains uncommitted changes, then ignore this and use the revision id
        of the committed data. If it is actually impossible to determine a
        sensible revision id, then use the revision specified by the build
        description (which defaults to HEAD). For really serious problems, this
        may refuse to guess a revision id.

            (Typical use of this is expected to be when a trying to calculate a
            stamp reports problems in particular checkouts, but inspection
            shows that these are artefacts that may be ignored, such as an
            executable built in the source directory.)

        If '-head' is true, then HEAD will be used for all checkouts.  In this
        case, the repository specified in the build description is used, and
        the revision id and status of each checkout is not checked.

        If 'quiet' is True, then we will not print information about what
        we are doing, and we will not print out problems as they are found.

        Returns a tuple of:

            * the new VersionStamp instance
            * a (possibly empty) list of problem summaries. If this is
              empty, then the stamp was calculated fully. Note that this
              is the same list as held withing the VersionStamp instance.
        """
        stamp = VersionStamp()

        stamp.repository = builder.invocation.db.repo.get()
        stamp.description = builder.invocation.db.build_desc.get()

        if not quiet:
            print 'Finding all checkouts...',
        checkout_rules = list(builder.invocation.all_checkout_rules())
        if not quiet:
            print 'found %d'%len(checkout_rules)

        revisions = MuddleSortedDict()
        checkout_rules.sort()
        for rule in checkout_rules:
            try:
                label = rule.target
                try:
                    vcs = rule.action.vcs
                except AttributeError:
                    stamp.problems.append("Rule for label '%s' has no VCS"%(label))
                    if not quiet:
                        print stamp.problems[-1]
                    continue
                if not quiet:
                    print "Processing %s checkout '%s'"%(vcs.short_name(),
                                                 '(%s)%s'%(label.domain,label.name)
                                                           if label.domain
                                                           else label.name)
                if label.domain:
                    domain_name = label.domain
                    domain_repo, domain_desc = builder.invocation.db.get_subdomain_info(domain_name)
                    stamp.domains[domain_name] = (domain_repo, domain_desc)

                if just_use_head:
                    if not quiet:
                        print 'Forcing head'
                    rev = "HEAD"
                else:
                    rev = vcs.revision_to_checkout(force=force, verbose=True)

                # Our tuple is made up of:
                # 
                # - the repository base URL (nb: this is the VCS + URL form)
                # - the directory within src/ that contains our checkout
                # - the revision checked out
                # - the repository path relative to the base URL, including the
                #   leaf name
                # - the checkout leaf directory (if not the same as the checkout name)
                # - the branch checked out
                #
                # (this is an attempt to reconstruct what previous versions of
                # muddle, before the use of Repository, would have done.)
                #
                # XXX For the new Repository mechanism, we also need to add:
                #
                # - inner_path
                # - prefix_as_is
                # - suffix
                # - handler
                if vcs.repo.prefix:
                    relative = os.path.join(vcs.repo.prefix, vcs.repo.repo_name)
                else:
                    relative = vcs.repo.repo_name
                revisions[label] = ('%s+%s'%(vcs.repo.vcs, vcs.repo.base_url),
                                    vcs.checkout_dir,
                                    rev,
                                    relative,
                                    vcs.checkout_leaf,
                                    vcs.repo.branch)
            except GiveUp as exc:
                print exc
                stamp.problems.append(str(exc))

        if stamp.domains and not quiet:
            print 'Found domains:',stamp.domains

        for label, (repo, dir, rev, rel, co_leaf, branch) in revisions.items():
            stamp.checkouts.append(CheckoutTupleV1(label.name, repo, rev, rel, dir,
                                                 label.domain, co_leaf, branch))

        if len(revisions) != len(checkout_rules):
            if not quiet:
                print
                print 'Unable to work out revision ids for all the checkouts'
                if revisions:
                    print '- although we did work out %d of %s'%(len(revisions),
                            len(checkout_rules))
                if stamp.problems:
                    print 'Problems were:'
                    for item in stamp.problems:
                        item.rstrip()
                        print '* %s'%truncate(str(item),less=2)
            if not stamp.problems:
                # This should not, I think, happen, but just in case...
                stamp.problems.append('Unable to work out revision ids for all the checkouts')

        stamp._update_checkout_dict()
        return stamp, stamp.problems

    @staticmethod
    def from_file(filename):
        """Construct a VersionStamp by reading in a stamp file.

        Returns a new VersionStamp instance.
        """

        stamp = VersionStamp()

        print 'Reading stamp file %s'%filename
        fd = HashFile(filename)

        config = RawConfigParser()
        config.readfp(fd)

        if config.has_section("STAMP"):
            # It is at least a version 2 stamp file
            stamp.version = config.get("STAMP", "version")
            if stamp.version != 2:
                raise GiveUp("This version of muddle does not know how to"
                             " parse a version %d stamp file"%stamp.version)
        else:
            stamp.version = 1

        stamp.repository = config.get("ROOT", "repository")
        stamp.description = config.get("ROOT", "description")

        sections = config.sections()
        sections.remove("STAMP")
        sections.remove("ROOT")
        for section in sections:
            if section.startswith("DOMAIN"):
                # Because we are using a set, we will not grumble if we
                # find the exact same domain definition more than once
                # - we'll just remember it once, so we don't really care.
                domain_name = config.get(section, 'name')
                domain_repo = config.get(section, 'repository')
                domain_desc = config.get(section, 'description')
                stamp.domains.add(DomainTuple(domain_name, domain_repo, domain_desc))
            elif section.startswith("CHECKOUT"):
                # Because we are using a list, we will not grumble if we
                # find the exact same checkout definition more than once
                # - we'll just keep it twice. So let's hope that doesn't
                # happen.
                if stamp.version == 1:
                    name = config.get(section, 'name')
                    vcs_repo_url = config.get(section, 'repository')
                    revision = config.get(section, 'revision')

                    relative = maybe_get_option(config, section, 'relative')
                    co_dir = maybe_get_option(config, section, 'directory')
                    domain = maybe_get_option(config, section, 'domain')
                    co_leaf = maybe_get_option(config, section, 'co_leaf')
                    if co_leaf is None:
                        co_leaf = name  # NB: this is deliberate - see the unstamp command
                    branch = maybe_get_option(config, section, 'branch')

                    # =========================================================
                    # Try to pretend to be a version 2 stamp file
                    label = Label(LabelType.Checkout, name, domain=domain)
                    vcs, base_url = split_vcs_url(vcs_repo_url)
                    if relative:
                        # 'relative' is the full path to the checkout (with src/),
                        # including the checkout name/leaf
                        parts = posixpath.split(relative)
                        if parts[-1] == co_leaf:
                            repo_name = co_leaf
                            prefix = posixpath.join(*parts[:-1])
                        else:
                            repo_name = parts[-1]
                            prefix = posixpath.join(*parts[:-1])
                        repo = Repository(vcs, base_url, repo_name, prefix=prefix,
                                          revision=revision, branch=branch)
                    else:
                        repo = Repository.from_url(vcs, base_url,
                                                   revision=revision, branch=branch)
                    # =========================================================
                else:
                    co_label_str = config.get(section, 'co_label')
                    try:
                        co_label = Label.from_string(co_label_str)
                    except GiveUp as e:
                        raise GiveUp("Error reading 'co_label=%s' in stamp"
                                     " file: %s"%(co_label_str, e))
                    co_dir = maybe_get_option(config, section, 'co_dir')
                    co_leaf = maybe_get_option(config, section, 'co_leaf')

                    repo_vcs = config.get(section, 'repo_vcs')
                    repo_from_url_string = maybe_get_option(config, section,
                            'repo_from_url_string')

                    if repo_from_url_string:
                        repo = Repository.from_url(repo_vcs, repo_from_url_string)
                    else:
                        base_url = config.get(section, 'repo_base_url')
                        repo_name = config.get(section, 'repo_name')

                        prefix = maybe_get_option(config, section, "repo_prefix")
                        prefix_as_is = maybe_get_option(config, section, "repo_prefix_as_is")
                        suffix = maybe_get_option(config, section, "repo_suffix")
                        inner_path = maybe_get_option(config, section, "repo_inner_path")
                        revision = maybe_get_option(config, section, "repo_revision")
                        branch = maybe_get_option(config, section, "repo_branch")
                        handler = maybe_get_option(config, section, "repo_handler")

                        repo = Repository(repo_vcs, base_url, repo_name, prefix,
                                          prefix_as_is, suffix, inner_path,
                                          revision, branch, handler)

                self.checkouts[label] = (co_dir, co_leaf, repo)

            elif section == "PROBLEMS":
                for name, value in config.items("PROBLEMS"):
                    stamp.problems.append(value)
            else:
                print 'Ignoring configuration section [%s]'%section

        stamp._update_checkout_dict()
        print 'File has SHA1 hash %s'%fd.hash()
        return stamp

    def compare_checkouts(self, other, quiet=False):
        """Compare the checkouts in this VersionStamp with those in another.

        'other' is another VersionStamp.

        If 'quiet', then don't output messages about the comparison.

        Note that this only compares the checkouts - it does not compare any
        of the other fields in a VersionStamp.

        Returns a tuple of (deleted, new, changed, problems) sequences, where
        these are:

            * a sequence of checkout tuples for checkouts that are in this
              VersionStamp but not in the 'other' - i.e., "deleted" checkouts

            * a sequence of checkout tuples for checkouts that are in the
              'other' VersionStamp but not in this - i.e., "new" checkouts

            * a sequence of tuples for any checkouts with differing revisions,
              of the form:

                  (checkout_name, this_revision, other_revision)

              where 'this_revision' and 'other_revision' are the 'rev' entries
              from the relevant checkout tuples.

            * a sequence of (checkout_name, problem_string) for checkouts that
              are present in both VersionStamps, but differ in something other
              than revision.
        """
        deleted = set()
        new = set()
        changed = set()
        problems = []

        names = set(self.keys() + other.keys())

        # Drat - can't sort sets
        names = list(names)
        names.sort()

        for name in names:
            try:
                if self[name] != other[name]:
                    if not quiet:
                        print 'Checkout %s has changed'%name
                    name1, repo1, rev1, rel1, dir1, domain1, co_leaf1, branch1 = self[name]
                    name2, repo2, rev2, rel2, dir2, domain2, co_leaf2, branch2 = other[name]
                    # For the moment, be *very* conservative on what we allow
                    # to have changed - basically, just the revision
                    # (arguably we shouldn't care about domain...)
                    errors = []
                    if repo2 != repo1:
                        errors.append('repository')
                        if not quiet:
                            print '  Repository mismatch:',repo1,repo2
                    if rel1 != rel2:
                        errors.append('relative')
                        if not quiet:
                            print '  Relative directory mismatch:',rel1,rel2
                    if dir1 != dir2:
                        errors.append('directory')
                        if not quiet:
                            print '  Directory mismatch:',dir1,dir2
                    if domain1 != domain2:
                        errors.append('domain')
                        if not quiet:
                            print '  Domain mismatch:',domain1,domain2
                    if co_leaf1 != co_leaf2:
                        errors.append('co_leaf')
                        if not quiet:
                            print '  Checkout leaf mismatch:',co_leaf1,co_leaf2
                    if branch1 != branch2:
                        errors.append('branch')
                        if not quiet:
                            print '  Checkout branch mismatch:',branch1,branch2
                    if errors:
                        if not quiet:
                            print '  ...only revision mismatch is allowed'
                        problems.append((name1, 'Checkout %s does not match: %s'%(name,
                                                        ', '.join(errors))))
                        continue
                    changed.add((name1, rev1, rev2))
            except KeyError:
                if name in self._checkout_dict:
                    if not quiet:
                        print 'Checkout %s was deleted'%name
                    deleted.add(self[name])
                else:
                    if not quiet:
                        print 'Checkout %s is new'%name
                    new.add(other[name])

        return deleted, new, changed, problems

