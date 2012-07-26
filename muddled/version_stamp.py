"""VersionStamp and stamp file support.

Stamp files
===========
Stamp files are INI files, implemented using the Python ConfigParser module
(specifically, RawConfigParser).

INI files are composed of one or more sections, each of the form::

    [header]
    key = value
    key = value

Indentation is allowed, but will be ignored.

Comment lines may be introduced with either '#' or ';', and in-line comments
may be added by following '[header]' or 'key = value' with whitespace and a
';' (but not a '#').

Muddle treats '#' comment lines specially in stamp files, but is not aware
of ';' comments, and we recommend not using them in muddle stamp files.

When a stamp file is written or read, a SHA1 hash is calculated from the lines
of text being written/read. Since mid-July 2012, comment lines starting with
'#', and blank lines (whitespace only) are not included in that SHA1 hash.
Since a stamp file uniquely describes the current state of a muddle build tree,
the hash calculated from its content can be regarded as a version id for the
build tree.

It can sometimes be useful to edit a stamp file. If you do so, it is advisable
to add a comment or comments indicating what has been done and why.

All muddle commands for handling stamp files are subcommands of either "muddle
stamp" or "muddle unstamp".

Version 1 Stamp Files
---------------------
We retain limited support for version 1 stamp files, mainly to allow reading
existing (legacy) files. There *is* provision for writing version 1 stamp
files, but it is not guaranteed to be accurate.

Version 1 stamp files were replaced because they could not unambiguously
store all of the information needed by the Repository class we now use to
remember where a checkout "came from".

Support for version 1 stamp files will be removed at some future time.

Version 2 Stamp Files
---------------------
Version 2 stamp files are the current form of stamp file.

This section describes the current content of a stamp file, as currently
written by muddle. For the rest of this section, "stamp files" should be taken
to mean "version 2 stamp files".

All stamp files start with some standard comment lines::

    # Muddle stamp file
    # Written at 2012-07-12 13:13:13
    #            2012-07-12 12:13:13 UTC

The date and time stamps are in local time and UTC respectively.

This is followed by a general section::

    [STAMP]
    version = 2

which at the moment just identifies the version of the stamp file.

Next comes a section identifying the build description - this repeats
information taken from the RootRepository, Description and VersionsRepository
files in the ``.muddle/`` directory of the build. For instance::

  [ROOT]
  repository = git+ssh://git@palmera.c//opt/kynesim/projects/001
  description = builds/01.py
  versions_repo = git+file:///home/tibs/temp/r/versions

The keys ('repository', etc.) are always presented in the same order - this is
a general principle within stamp file sections, so that stamp files themselves
can be comparable with simple tools such as ``diff``.

Next, if the build tree has subdomains, will come sections describing those
domains. For instance::

    [DOMAIN subdomain1]
    description = builds/01.py
    name = subdomain1
    repository = git+file:///home/tibs/sw/muddle/tests/transient/repo/subdomain1

    [DOMAIN subdomain1(subdomain3)]
    description = builds/01.py
    name = subdomain1(subdomain3)
    repository = git+file:///home/tibs/sw/muddle/tests/transient/repo/subdomain3

Domain sections occur in "C" sort order of the domain names. Note that there
will not be any domain sections if there are no subdomains (i.e., if there is
no ``domains/`` directory in the build tree).

Next come sections for each checkout. For instance::

    [CHECKOUT (subdomain1)builds]
    co_label = checkout:(subdomain1)builds/checked_out
    co_leaf = builds
    repo_vcs = git
    repo_from_url_string = None
    repo_base_url = file:///home/tibs/sw/muddle/tests/transient/repo/subdomain1
    repo_name = builds
    repo_prefix_as_is = False
    repo_revision = 7d8377a18efcd8b3d7b788de8cee26aa6d770005

and::

    [CHECKOUT builds]
    co_label = checkout:builds/checked_out
    co_leaf = builds
    repo_vcs = git
    repo_from_url_string = None
    repo_base_url = ssh://git@palmera.c//opt/kynesim/projects/001
    repo_name = builds
    repo_prefix_as_is = False
    repo_revision = dfb06f29c81828bbdfc48ce53d7bc4203b68a459

    [CHECKOUT busybox-1.17.1]
    co_label = checkout:busybox-1.17.1/checked_out
    co_dir = linux
    co_leaf = busybox-1.17.1
    repo_vcs = git
    repo_from_url_string = None
    repo_base_url = ssh://git@palmera.c//opt/kynesim/projects/001
    repo_name = busybox-1.17.1
    repo_prefix = linux
    repo_prefix_as_is = False
    repo_revision = 965b4809b5ca93df0a4973e043a5a9af0ecf50e3

The values presented give the checkout label, its location in the build tree
('co_dir' and 'co_leaf'), and its Repository instance (the 'repo_xxx' values.
See "muddle doc version_control.checkout_from_repo" for some information on
how the 'co_xxx' values are used, and "muddle doc repository.Repository" for
more information on the Repository class).

Again, these are presented in "C" sort order of the checkout name, including
the domain component - this means that subdomain checkouts will occur before
toplevel checkouts. Also, while not all checkout sections will contain the
same values, the order in which they are presented will always be the same.

Finally, if "muddle stamp" reported any problems in creating the stamp file,
these will be saved in a problems section. For instance::

    [PROBLEMS]
    problem1 = builds: 'svnversion' reports checkout has revision '459M'

(a subversion revision ending in 'M' means that the checkout was modified and
not yet committed). Problems are presented as 'problem1', 'problem2', etc. In
general, the checkout name should be the first part of the message occurring as
the problem value.

Release stamp files
-------------------
Release stamp files are an extension of normal stamp files that also specify
a release. As such, they have an extra section (after the ``[STAMP]`` section)
of the form::

    [RELEASE]
    name = project99
    version = 1.2.3
    archive = tar
    compression = gzip

This indicates that the rest of the stamp file describes a release called (or
for) "project99", and that it is version 1.2.3. The release will be archived
using tar, and the tar file will be compressed using gzip.

Both the ``name`` and ``version`` specified must start with an ASCII
alphanumeric, and may only contain ASCII alphanumerics, and the characters '.',
'-' or '_'. For instance::

    version = v1-2.11
    version = xvii
    version = 0.9.3alpha1

The ``archive`` value must currently be ``tar`` - other values may perhaps be
allowed in the future.

The ``compression`` value must be either ``gzip`` or ``bzip2``.

Note that any release stamp file can be read as a "normal" stamp file - the
extra release-specific information will just be ignored.
"""

import os
import posixpath
import sys
import re

from collections import namedtuple, Mapping
from datetime import datetime
from ConfigParser import RawConfigParser
from StringIO import StringIO

from muddled.depend import Label
from muddled.repository import Repository
from muddled.utils import MuddleSortedDict, MuddleOrderedDict, \
        HashFile, GiveUp, truncate, LabelType, LabelTag
from muddled.version_control import split_vcs_url

CheckoutTupleV1 = namedtuple('CheckoutTupleV1', 'name repo rev rel dir domain co_leaf branch')

# XXX Ideally we'd have a CheckoutTuple for v2 as well!

def maybe_set_option(config, section, name, value):
    """Set an option in a section, if its value is not None.
    """
    if value is not None:
        config.set(section, name, value)

def maybe_get_option(config, section, name, remove=False):
    """Get an option from a section, as a string, or as None.

    If the option is present, return it, otherwise return None.

    If remove is true, and the option was present, also remove it.
    """
    if config.has_option(section, name):
        value = config.get(section, name)
        if remove:
            config.remove_option(section, name)
        return value
    else:
        return None

def get_and_remove_option(config, section, name):
    """Get an option from a section, as a string, and also remove it.
    """
    value = config.get(section, name)
    config.remove_option(section, name)
    return value

def make_RawConfigParser(ordered=False, sorted=False):
    """Make a RawConfigParrser.

    Always tell it we want to preserve the case of keys.

    If 'ordered', then use a MuddleOrderedDict inside it, so that things
    remember their insertion order, and that is used on output.

    If 'sorted', use a MuddleSortedDict, so that things are sorted, and
    thus output in sorted order.

    If neither, don't specify a dict, and random stuff might happen
    """
    if ordered:
        config = RawConfigParser(dict_type=MuddleOrderedDict)
    elif sorted:
        config = RawConfigParser(dict_type=MuddleSortedDict)
    else:
        config = RawConfigParser()
    # Say we want our option value names to retain their case within
    # this configuration - that will matter if we have to write out
    # any VCS options
    config.optionxform = str
    return config

class VersionStamp(object):
    """A representation of the revision state of a build tree's checkouts.

    Our internal data is:

        * 'repository' is a string giving the default repository (as stored
          in ``.muddle/RootRepository``)

        * ``description`` is a string naming the build description (as stored
          in ``.muddle/Description``)

        * 'versions_repo' is a string giving the versions repository (as stored
          in ``.muddle/VersionsRepository``)

        * 'domains' is a dictionary mapping domain names to tuples of the form
          (domain_repo, domain_desc), where:

            * domain_repo is the default repository for the domain
            * domain_desc is the build description for the domain

        * 'checkouts' is a dictionary mapping checkout labels to tuples of the
          form (co_dir, co_leaf, repo), where:

            * co_dir is the sub-path between src/ and the co_leaf
            * co_leaf is the name of the directory within src/ that
              actually contains the checkout
            * repo is a Repository instance, where to find the checkout
              remotely

           These are the appropriate arguments for the checkout_from_repo()
           function in version_control.py.

           The checkout will be in src/<co_dir>/<co_leaf> (if <co_dir> is
           set), or src/<co_leaf> (if it is not).

        * 'options' is a dictionary mapping checkout labels to dictionaries
          of the form {option_name : option_value}. There will only be entries
          for those checkouts which do have options.

        * 'problems' is a list of problems in determining the stamp
          information. This will be of zero length if the stamp if accurate,
          but will otherwise contain a string for each checkout whose revision
          could not be accurately determined.

          Note that when problems descriptions are written to a stamp file,
          they are truncated.
    """

    MAX_PROBLEM_LEN = 100               # At what length to truncate problems

    def __init__(self):
        self.repository = ''    # content of .muddle/RootRepository
        self.description = ''   # content of .muddle/Description
        self.versions_repo = '' # and of .muddle/VersionsRepository
        self.domains = {}       # domain_name -> (domain_repo, domain_desc)
        self.checkouts = {}     # label -> (co_dir, co_leaf, repo)
        self.options = {}       # label -> {option_name : option_value}
        self.problems = []      # one string per problem
        self.before = None      # Set by from_builder() if 'before' is specified

    def __str__(self):
        """Make 'print' do something useful.
        """
        s = StringIO()
        self.write_to_file_object(s)
        rv = s.getvalue()
        s.close()
        return rv.rstrip()

    def write_to_file(self, filename, version=2):
        """Write our data out to a file.

        By default, writes out a version 2 stamp file, as opposed to the older
        version 1 format.

        Returns the SHA1 hash for the file.
        """
        with HashFile(filename, 'w',
                      ignore_comments=True, ignore_blank_lines=True) as fd:
            self.write_to_file_object(fd, version)
            return fd.hash()

    def _set_v1_checkout_for_write(self, config, co_label):
        """Setup a config for a version 1 stamp file.
        """
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
        if relative:
            config.set(section, "relative", relative)
        if co_dir:
            config.set(section, "directory", co_dir)
        if repo.branch:
            config.set(section, "branch", repo.branch)
        # =============================================================

    def _set_v2_checkout_for_write(self, config, co_label):
        """Setup a config for a version 2 stamp file.
        """
        co_dir, co_leaf, repo = self.checkouts[co_label]
        if co_label.domain:
            section = 'CHECKOUT (%s)%s'%(co_label.domain,
                                         co_label.name)
        else:
            section = 'CHECKOUT %s'%co_label.name
        config.add_section(section)
        config.set(section, "co_label", co_label)
        if co_dir:
            config.set(section, "co_dir", co_dir)
        if co_leaf:
            config.set(section, "co_leaf", co_leaf)

        config.set(section, "repo_vcs", repo.vcs)
        # If we got our repository URL as a string, directly, then
        # there is no point in outputting the parts that Repository
        # deduced from it - we just need the original URL
        # This will be written out as None if unset
        config.set(section, "repo_from_url_string", repo.from_url_string)
        if repo.from_url_string is None:
            # We need to specify all the parts
            config.set(section, "repo_base_url", repo.base_url)
            config.set(section, "repo_name", repo.repo_name)
            maybe_set_option(config, section, "repo_prefix", repo.prefix)
            # NB: repo_prefix_as_is should be True or False
            maybe_set_option(config, section, "repo_prefix_as_is", repo.prefix_as_is)
            maybe_set_option(config, section, "repo_suffix", repo.suffix)
            maybe_set_option(config, section, "repo_inner_path", repo.inner_path)
            maybe_set_option(config, section, "repo_handler", repo.handler)
        # But we still may have revision and branch for either/both
        maybe_set_option(config, section, "repo_revision", repo.revision)
        maybe_set_option(config, section, "repo_branch", repo.branch)

        if self.options.has_key(co_label):
            co_options = self.options[co_label]
            co_option_names = co_options.keys()
            co_option_names.sort()
            for key in co_option_names:
                value = co_options[key]
                # Discriminate VERY SIMPLY on type
                if isinstance(value, bool):
                   type_name = 'bool'
                elif isinstance(value, int):
                   type_name = 'int'
                else:
                   type_name = 'str'
                config.set(section, 'option~%s'%key, '%s:%s'%(type_name, value))

    def _write_to_file_object_start(self, fd, version=2):
        # It's nice to include timestamps in the file, so that the user
        # can tell when it was written without relying on file system
        # information (which is not always available). However, we don't
        # want that to affect the hash for the file, so we write it out
        # in comments. On the good side, this means that two stamp files
        # for the same tree, at different times, will have the same hash
        # (which is a good way of saying they are "the same"), but on the
        # bad side it means that VersionStamp can't recover the times when
        # it is reading the file back in. Oh well.
        # We present the time in two forms, in the hope that at least one
        # will make some sense to the user.
        now = datetime.now()
        now = datetime(now.year, now.month, now.day,
                       now.hour, now.minute, now.second, 0, now.tzinfo)
        fd.write("# Written at %s\n"%now.isoformat(' '))
        now = datetime.utcnow()
        # Drop any microseconds!
        now = datetime(now.year, now.month, now.day,
                       now.hour, now.minute, now.second, 0, now.tzinfo)
        fd.write("#            %s UTC\n"%now.isoformat(' '))
        # If we were asked to calculate a stamp "before" a particular time,
        # we might as well say so...
        if self.before:
            fd.write('# Stamp calculated for checkouts at or before %s\n'%self.before)
        fd.write('\n')

        if version > 1:
            config = make_RawConfigParser(ordered=True)
            config.add_section("STAMP")
            config.set("STAMP", "version", version)
            config.write(fd)

    def _write_to_file_object_end(self, fd, version=2):

        # Note we take care to write out the sections by hand, so that they
        # come out in the order we want, other than in some random order (as
        # we're effectively writing out a dictionary)

        config = make_RawConfigParser(ordered=True)

        config.add_section("ROOT")
        config.set("ROOT", "repository", self.repository)
        config.set("ROOT", "description", self.description)
        maybe_set_option(config, "ROOT", 'versions_repo', self.versions_repo)
        config.write(fd)

        if self.domains:
            config = make_RawConfigParser(sorted=True)
            domain_names = self.domains.keys()
            for domain_name in domain_names:
                domain_repo, domain_desc = self.domains[domain_name]
                section = "DOMAIN %s"%domain_name
                config.add_section(section)
                config.set(section, "name", domain_name)
                config.set(section, "repository", domain_repo)
                config.set(section, "description", domain_desc)
            config.write(fd)

        config = make_RawConfigParser(ordered=True)

        if version == 1:
            co_labels = self.checkouts.keys()
            co_labels.sort()
            for co_label in co_labels:
                self._set_v1_checkout_for_write(config, co_label)
        else:
            co_labels = self.checkouts.keys()
            co_labels.sort()
            for co_label in co_labels:
                self._set_v2_checkout_for_write(config, co_label)

        config.write(fd)

        if self.problems:
            config = make_RawConfigParser(sorted=True)
            section = 'PROBLEMS'
            config.add_section(section)
            for index, item in enumerate(self.problems):
                # Let's remove any newlines
                item = ' '.join(item.split())
                config.set(section, 'problem%d'%(index+1), item)
            config.write(fd)

    def write_to_file_object(self, fd, version=2):
        """Write our data out to a file-like object (one with a 'write' method).

        By default, writes out a version 2 stamp file, as opposed to the older
        version 1 format.

        Returns the SHA1 hash for the file.

        Note that the SHA1 does not include blank lines or comment lines that
        start with a '#' (or whitespace and a '#').
        """

        if version not in (1, 2):
            raise GiveUp('Attempt to write version %d stamp file;'
                         ' we only support 1 or 2'%version)

        fd.write('# Muddle stamp file\n')
        self._write_to_file_object_start(fd, version)
        self._write_to_file_object_end(fd, version)

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
    def _from_builder(stamp, builder, force=False, just_use_head=False, before=None, quiet=False):
        """The internal mechanisms of the 'from_builder' static method.
        """
        stamp.repository = builder.invocation.db.repo.get()
        stamp.description = builder.invocation.db.build_desc.get()
        stamp.versions_repo = builder.invocation.db.versions_repo.get()

        stamp.before = before        # remember for annotating the stamp file

        if not quiet:
            print 'Finding all checkouts...',
        checkout_rules = list(builder.invocation.all_checkout_rules())
        if not quiet:
            print 'found %d'%len(checkout_rules)

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
                    rev = vcs.revision_to_checkout(builder, force=force,
                                                   before=before, verbose=True)

                repo = vcs.repo.copy_with_changed_revision(rev)

                stamp.checkouts[label] = (vcs.checkout_dir, vcs.checkout_leaf, repo)

                if vcs.options:
                    stamp.options[label] = vcs.options
            except GiveUp as exc:
                print exc
                stamp.problems.append(str(exc))

        if stamp.domains and not quiet:
            domain_names = stamp.domains.keys()
            domain_names.sort()
            print 'Found domains:',' '.join(domain_names)

        if len(stamp.checkouts) != len(checkout_rules):
            if not quiet:
                print
                print 'Unable to work out revision ids for all the checkouts'
                if stamp.checkouts:
                    print '- although we did work out %d of %s'%(len(stamp.checkouts),
                            len(checkout_rules))
                if stamp.problems:
                    print 'Problems were:'
                    for item in stamp.problems:
                        item.rstrip()
                        print '* %s'%truncate(str(item),less=2)
            if not stamp.problems:
                # This should not, I think, happen, but just in case...
                stamp.problems.append('Unable to work out revision ids for all the checkouts')

    @staticmethod
    def from_builder(builder, force=False, just_use_head=False, before=None, quiet=False):
        """Construct a VersionStamp from a muddle build description.

        'builder' is the muddle Builder for our build description.

        If 'force' is true, then attempt to "force" a revision id, even if it
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

        If 'just_use_head' is true, then HEAD will be used for all checkouts.
        In this case, the repository specified in the build description is
        used, and the revision id and status of each checkout is not checked.

        If 'before' is given, it should be a string describing a date/time, and
        the revision id chosen for each checkout will be the last revision
        at or before that date/time.

        .. note:: This depends upon what the VCS concerned actually supports.
           This feature is experimental.

        If 'quiet' is True, then we will not print information about what
        we are doing, and we will not print out problems as they are found.

        Returns a tuple of:

            * the new VersionStamp instance
            * a (possibly empty) list of problem summaries. If this is empty,
              then the stamp was calculated fully. Note that this is the same
              list as held within the VersionStamp instance itself.
        """
        stamp = VersionStamp()

        VersionStamp._from_builder(stamp, builder,
                                   force=force,
                                   just_use_head=just_use_head,
                                   before=before,
                                   quiet=quiet)

        return stamp, stamp.problems

    @staticmethod
    def _extract_config_header(stamp, config):
        """Part 1 of the internal mechanisms of the 'from_file' static method.

        Extract the STAMP (if any) and ROOT sections. After they've been
        used, they will be removed from the configuration.
        """

        if config.has_section("STAMP"):
            # It is at least a version 2 stamp file
            version_str = config.get("STAMP", "version")
            try:
                stamp.version = int(version_str)
            except Exception as e:
                raise GiveUp("Unexpected version %r - expecting an integer,"
                             " and particularly 1 or 2"%version_str)

            if stamp.version != 2:
                raise GiveUp("This version of muddle does not know how to"
                             " parse a version %d stamp file"%stamp.version)
        else:
            stamp.version = 1

        stamp.repository = config.get("ROOT", "repository")
        stamp.description = config.get("ROOT", "description")
        stamp.versions_repo = maybe_get_option(config, "ROOT", "versions_repo")

        if config.has_section("STAMP"):
            config.remove_section("STAMP")
        config.remove_section("ROOT")

    @staticmethod
    def _extract_config_body(stamp, config):
        """Part 2 of the internal mechanisms of the 'from_file' static method.

        Extract the DOMAIN, CHECKOUT and PROBLEM sections.
        """
        sections = config.sections()
        for section in sections:
            if section.startswith("DOMAIN"):
                # Because we are using a set, we will not grumble if we
                # find the exact same domain definition more than once
                # - we'll just remember it once, so we don't really care.
                domain_name = config.get(section, 'name')
                domain_repo = config.get(section, 'repository')
                domain_desc = config.get(section, 'description')
                stamp.domains[domain_name] = (domain_repo, domain_desc)
            elif section.startswith("CHECKOUT"):
                # Because we are using a list, we will not grumble if we
                # find the exact same checkout definition more than once
                # - we'll just keep it twice. So let's hope that doesn't
                # happen.
                if stamp.version == 1:
                    co_label, co_leaf, co_dir, repo, options = _read_v1_checkout(section, config)
                else:
                    co_label, co_leaf, co_dir, repo, options = _read_v2_checkout(section, config,
                                                                                 stamp.problems)

                stamp.checkouts[co_label] = (co_dir, co_leaf, repo)
                stamp.options[co_label] = options

            elif section == "PROBLEMS":
                for name, value in config.items("PROBLEMS"):
                    stamp.problems.append(value)
            else:
                print 'Ignoring configuration section [%s]'%section

    @staticmethod
    def from_file(filename):
        """Construct a VersionStamp by reading in a stamp file.

        Returns a new VersionStamp instance.

        Note that the SHA1 computed and reported for that VersionStamp does not
        include blank lines or comment lines that start with a '#' (or
        whitespace and a '#').
        """

        stamp = VersionStamp()

        print 'Reading stamp file %s'%filename
        fd = HashFile(filename, ignore_comments=True, ignore_blank_lines=True)

        config = make_RawConfigParser()
        config.readfp(fd)

        VersionStamp._extract_config_header(stamp, config)
        VersionStamp._extract_config_body(stamp, config)

        print 'File has SHA1 hash %s'%fd.hash()
        return stamp

    def compare_checkouts(self, other, fd=sys.stdout):
        """Compare the checkouts in this VersionStamp with those in another.

        'other' is another VersionStamp.

        'fd' is where any messages should be written, defaulting to stdout.
        If this is None, then no messages will be writen.

        Note that this only compares the checkouts (including their options) -
        it does not compare any of the other fields in a VersionStamp.

        Returns a tuple of (deleted, new, changed, problems) sequences, where
        these are:

            * a sequence of tuples of the form:

                  (co_label, co_dir, co_leaf, repo)

              for checkouts that are in this VersionStamp but not in the
              'other' - i.e., "deleted" checkouts

            * a sequence of tuples of the form:

                  (co_label, co_dir, co_leaf, repo)

              for checkouts that are in the 'other' VersionStamp but not in
              this - i.e., "new" checkouts

            * a sequence of tuples for any checkouts with differing revisions,
              of the form:

                  (co_label, revision1, revision2)

              where 'this_repo' and 'other_repo' are relevant Repository
              instances.

            * a sequence of tuples of the form:

                  (co_label, problem_string)

              for checkouts that are present in both VersionStamps, but differ
              in something other than revision.
        """
        deleted = set()
        new = set()
        changed = set()
        problems = []

        co_labels = set(self.checkouts.keys() + other.checkouts.keys())

        # Drat - can't sort sets
        co_labels = list(co_labels)
        co_labels.sort()

        for label in co_labels:
            if label in self.checkouts and label in other.checkouts:
                errors = set()
                named = False
                co_dir1, co_leaf1, repo1 = self.checkouts[label]
                co_dir2, co_leaf2, repo2 = other.checkouts[label]

                if (co_dir1 != co_dir2 or co_leaf1 != co_leaf2 or
                    repo1 != repo2):

                    if repo1.same_ignoring_revision(repo2):
                        if repo1.revision != repo2.revision:
                            changed.add((label, repo1.revision, repo2.revision))
                    else:
                        errors.add('repository')
                        if fd is not None:
                            fd.write('%s\n'%label)
                            fd.write('  Repository mismatch:\n')
                            fd.write('    %s from %s\n'%(repo1.url, repo1))
                            fd.write('    %s from %s\n'%(repo2.url, repo2))
                            named = True

                    # It's a problem if anything but the revision is different

                    if co_dir1 != co_dir2:
                        errors.add('co_dir')
                        if fd is not None:
                            if not named:
                                fd.write('%s\n'%label)
                                named = True
                            fd.write('  Checkout directory mismatch:\n')
                            fd.write('    %s\n'%co_dir1)
                            fd.write('    %s\n'%co_dir2)
                    if co_leaf1 != co_leaf2:
                        errors.add('co_leaf')
                        if fd is not None:
                            if not named:
                                fd.write('%s\n'%label)
                                named = True
                            fd.write('  Checkout leaf mismatch:\n')
                            fd.write('    %s\n'%co_leaf1)
                            fd.write('    %s\n'%co_leaf2)

                if label in self.options:
                    options1 = self.options[label]
                else:
                    options1 = {}

                if label in other.options:
                    options2 = other.options[label]
                else:
                    options2 = {}

                if options1 != options2:
                    errors.add('options')
                    if not named:
                        if fd is not None:
                            fd.write('%s\n'%label)
                        named = True
                    if fd is not None:
                        fd.write('  Options mismatch:\n')
                        keys = set(options1.keys() + options2.keys())
                        keys = list(keys)
                        keys.sort()
                        for key in keys:
                            if key in options1 and key not in options2:
                                fd.write('    option %s was deleted\n'%key)
                            elif key not in options1 and key in options2:
                                fd.write('    option %s is new\n'%key)
                            else:
                                fd.write("    option %s changed from"
                                         " '%s' to '%s'\n"%(key, options1[key], options2[key]))

                if errors:
                    if fd is not None:
                        fd.write('  ...only revision mismatch is allowed\n')
                    problems.append((label, 'Checkout %s does not match:'
                                            ' %s'%(label, ', '.join(sorted(errors)))))
            elif label in self.checkouts:
                if fd is not None:
                    fd.write('Checkout %s was deleted\n'%label)
                co_dir, co_leaf, repo = self.checkouts[label]
                deleted.add( (label, co_dir, co_leaf, repo) )
            else:       # It must be in other.checkouts...
                if fd is not None:
                    fd.write('Checkout %s is new\n'%label)
                co_dir, co_leaf, repo = other.checkouts[label]
                new.add( (label, co_dir, co_leaf, repo) )

        # XXX Doesn't compare options.

        return deleted, new, changed, problems


class ReleaseSpec(object):
    """The basic specification of a Release.

    The following correspond to the [RELEASE] section in a release stamp file:

        * 'name'
        * 'version'
        * 'archive'
        * 'compression'

    'name' and 'version' may be set to None, or to a valid name/version.

    When a 'name' or 'version' of None is written out to a release file, it
    is written out as '<REPLACE THIS>', a carefully invalid value, indicating
    that the user needs to edit the file.

    Otherwise, 'name' and 'version' values must start with ASCII alphanumeric
    and continue with ASCII alphanumeric, hyphen, underscore or dot.

    'archive' and 'compression' may be set to None or a value from the
    'allowed_' lists. If they are set to None, they in fact get set to the
    first 'allowed_' value, so this is a simple way of selecting the default.

    We also allow the SHA1 hash of a stamp file to be remembered:

        * 'hash'

    There is no special handling for this, and it defaults to None.
    """

    # Actually, we use the same regular expression for release versions and names
    version_re = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]+")
    name_re = version_re

    # For both of these, the first value is the default
    allowed_archive_values = ['tar']
    allowed_compression_values = ['gzip', 'bzip2']

    def __init__(self, name=None, version=None, archive=None, compression=None, hash=None):
        self.name = name
        self.version = version
        self.archive = archive
        self.compression = compression
        self.hash = hash

    def __str__(self):
        parts = []
        parts.append(repr(name))
        parts.append(repr(version))
        parts.append(repr(archive))
        parts.append(repr(compression))
        if self.hash:
            parts.append(repr(hash))
        return 'ReleaseSpec(%s)'%(', '.join(parts))

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        if value is None:
            self._name = value
            return

        m = self.name_re.match(value)
        if m is None or m.end() != len(value):
            raise GiveUp("Release name \"%s\" is not allowed (it must start"
                         " with 'A'-'Z', 'a'-'z' or '0'-'9', and may only"
                         " continue with 'A'-'Z', 'a'-'z', '0'-'9', '_' '-'"
                         " or '.')"%value)
        else:
            self._name = value

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, value):
        if value is None:
            self._version = value
            return

        m = self.version_re.match(value)
        if m is None or m.end() != len(value):
            raise GiveUp("Release version \"%s\" is not allowed (it must start"
                         " with 'A'-'Z', 'a'-'z' or '0'-'9', and may only"
                         " continue with 'A'-'Z', 'a'-'z', '0'-'9', '_' '-'"
                         " or '.')"%value)
        else:
            self._version = value

    @property
    def archive(self):
        return self._archive

    @archive.setter
    def archive(self, value):
        if value is None:
            self._archive = self.allowed_archive_values[0]
            return

        if value not in self.allowed_archive_values:
            raise GiveUp('Release archive "%s" is not allowed (it must be %s)'%(
                value, ', '.join(self.allowed_archive_values)))
        else:
            self._archive = value

    @property
    def compression(self):
        return self._compression

    @compression.setter
    def compression(self, value):
        if value is None:
            self._compression = self.allowed_compression_values[0]
            return

        if value not in self.allowed_compression_values:
            raise GiveUp('Release compression "%s" is not allowed (it must be %s)'%(
                value, ', '.join(self.allowed_compression_values)))
        else:
            self._compression = value

    def write_to_file(self, filename):
        """Write a simple representation of ourself out to a file.
        """
        with open(filename, 'w') as fd:
            fd.write('%s\n'%self.name)
            fd.write('%s\n'%self.version)
            fd.write('%s\n'%self.archive)
            fd.write('%s\n'%self.compression)
            fd.write('%s\n'%self.hash)

    @staticmethod
    def from_file(filename):
        """Read a simple representation of ourself from a file.
        """
        with open(filename) as fd:
            name = fd.readline().strip()
            version = fd.readline().strip()
            archive = fd.readline().strip()
            compression = fd.readline().strip()
            hash = fd.readline().strip()
        return ReleaseSpec(name, version, archive, compression, hash)


class ReleaseStamp(VersionStamp):
    """A VersionStamp with extra stuff to describe a release.
    """

    def __init__(self):
        super(ReleaseStamp, self).__init__()
        self.release_spec = ReleaseSpec()

    @staticmethod
    def from_builder(builder, quiet=False):
        """Construct a ReleaseStamp from a muddle build description.

        'builder' is the muddle Builder for our build description.

        If 'quiet' is True, then we will not print information about what
        we are doing, and we will not print out problems as they are found.

        Returns a tuple of:

            * the new ReleaseStamp instance
            * a (possibly empty) list of problem summaries. If this is empty,
              then the stamp was calculated fully. Note that this is the same
              list as held within the ReleaseStamp instance itself.
        """

        stamp = ReleaseStamp()

        VersionStamp._from_builder(stamp, builder,
                                   force=False, just_use_head=False, before=None,
                                   quiet=quiet)

        # and then add in release information
        stamp.release_spec = builder.release_spec

        return stamp, stamp.problems

    @staticmethod
    def from_file(filename):
        """Construct a ReleaseStamp by reading in a stamp file.

        Returns a new ReleaseStamp instance.

        Note that the SHA1 computed and reported for that ReleaseStamp does not
        include blank lines or comment lines that start with a '#' (or
        whitespace and a '#').
        """

        stamp = ReleaseStamp()

        print 'Reading release file %s'%filename
        fd = HashFile(filename, ignore_comments=True, ignore_blank_lines=True)

        config = make_RawConfigParser()
        config.readfp(fd)

        # Extract the stamp file header from the configuration
        VersionStamp._extract_config_header(stamp, config)

        if stamp.version < 2:
            raise GiveUp('Release stamp files must be version 2 stamp files or later')

        # and then read whatever other configuration values we want to read
        name = config.get("RELEASE", "name")
        version = config.get("RELEASE", "version")
        archive = config.get("RELEASE", "archive")
        compression = config.get("RELEASE", "compression")
        # and follow precedent by removing that entire section
        config.remove_section("RELEASE")

        stamp.release_spec = ReleaseSpec(name=name, version=version,
                                         archive=archive, compression=compression)

        # And extract the rest of the data from the configuration
        VersionStamp._extract_config_body(stamp, config)

        hash = fd.hash()
        print 'File has SHA1 hash %s'%hash

        stamp.release_spec.hash = hash

        return stamp

    def write_to_file_object(self, fd, version=2):
        """Write our data out to a file-like object (one with a 'write' method).
        """

        if version != 2:
            raise GiveUp('Release stamp files must be version 2 stamp files,'
                         ' not version %s'%version)

        fd.write('# Muddle release stamp file\n')
        self._write_to_file_object_start(fd, version=2)

        config = make_RawConfigParser(ordered=True)
        config.add_section("RELEASE")

        # If the user has not specified the release name or version, then
        # we write out illegal (and obvious) values, which they can replace
        # later on with a text editor.
        if self.release_spec.name:
            config.set("RELEASE", "name", self.release_spec.name)
        else:
            config.set("RELEASE", "name", '<REPLACE THIS>')

        if self.release_spec.version:
            config.set("RELEASE", "version", self.release_spec.version)
        else:
            config.set("RELEASE", "version", '<REPLACE THIS>')

        config.set("RELEASE", "archive", self.release_spec.archive)
        config.set("RELEASE", "compression", self.release_spec.compression)

        config.write(fd)
        self._write_to_file_object_end(fd)


def _read_v2_checkout(section, config, problems):
    """Read a version 2 stamp file CHECKOUT section.

    Returns a tuple of the form (co_label, co_leaf, co_dir, repo, options)

    Note that this is destructive, as it removes options from the section
    as it interrogates them.
    """
    co_label_str = get_and_remove_option(config, section, 'co_label')
    try:
        co_label = Label.from_string(co_label_str)
    except GiveUp as e:
        raise GiveUp("Error reading 'co_label=%s' in stamp"
                     " file: %s"%(co_label_str, e))
    co_dir = maybe_get_option(config, section, 'co_dir', True)
    co_leaf = maybe_get_option(config, section, 'co_leaf', True)

    repo_vcs = get_and_remove_option(config, section, 'repo_vcs')
    repo_from_url_string = maybe_get_option(config, section,
            'repo_from_url_string', True)

    # Revision and branch may apply to any repository
    revision = maybe_get_option(config, section, "repo_revision", True)
    branch = maybe_get_option(config, section, "repo_branch", True)

    if repo_from_url_string == 'None' or repo_from_url_string is None:
        base_url = get_and_remove_option(config, section, 'repo_base_url')
        repo_name = get_and_remove_option(config, section, 'repo_name')

        prefix = maybe_get_option(config, section, "repo_prefix", True)
        prefix_as_is = maybe_get_option(config, section, "repo_prefix_as_is", True)
        suffix = maybe_get_option(config, section, "repo_suffix", True)
        inner_path = maybe_get_option(config, section, "repo_inner_path", True)
        handler = maybe_get_option(config, section, "repo_handler", True)

        if prefix_as_is == 'True':
            prefix_as_is = True
        elif prefix_as_is == 'False' or prefix_as_is is None:
            prefix_as_is = False
        else:
            raise GiveUp("Unexpected value '%s' for prefix_as_is in  stamp"
                         " file for %s"%(prefix_as_is, co_label_str))

        repo = Repository(repo_vcs, base_url, repo_name, prefix,
                          prefix_as_is, suffix, inner_path,
                          revision, branch, handler)
    else:
        repo = Repository.from_url(repo_vcs, repo_from_url_string,
                                   revision=revision, branch=branch)

    options = {}
    for key in config.options(section):
        if key.startswith('option~'):
            try:
                option_name, option_value = _parse_option(section, config, key)
                options[option_name] = option_value
            except GiveUp as e:
                problems.append(str(e))
        else:
            # Remember, we removed all the items we *expected*
            problems.append('Unexpected "%s" in section [%s]'%(key, section))

    return (co_label, co_leaf, co_dir, repo, options)

def _parse_option(section, config, key):
    """Parse an option from the stamp file.

    Return a tuple (option_name, option_value), or raise GiveUp
    """
    value = config.get(section, key)
    option_name = key[7:]
    colon_at = value.find(':')
    if colon_at == -1:
        raise GiveUp("No datatype (no colon in value),"
                     " for '%s = %s' in [%s]"%(key, value, section))
    option_type = value[:colon_at]
    option_value = value[colon_at+1:]
    if option_type == 'int':
        try:
            option_value = int(option_value)
        except Exception as e:
            raise GiveUp("Cannot convert value to integer,"
                         " for '%s = %s' in [%s]"%(key, value, section))
    elif option_type == 'bool':
        if option_value == 'True':
            option_value = True
        elif option_value == 'False':
            option_value = False
        else:
            raise GiveUp("Value is not True or False,"
                         " for '%s = %s' in [%s]"%(key, value, section))
    elif option_type != "str":
        raise GiveUp("Unrecognised datatype '%s' (not bool, int or str),"
                     " for '%s = %s' in [%s]"%(option_type, key, value, section))

    return option_name, option_value

def _read_v1_checkout(section, config):
    """Read a version 1 stamp file CHECKOUT section.

    Returns a tuple of the form (co_label, co_leaf, co_dir, repo, {})
    """
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
    co_label = Label(LabelType.Checkout, name, tag=LabelTag.CheckedOut,
                     domain=domain)
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
    return (co_label, co_leaf, co_dir, repo, {})

