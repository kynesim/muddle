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

    Since we expect the user (and code) to edit these files
    frequently, we deliberately do not cache their values.

    """

    def __init__(self, root_path):
        """
        Initialise a muddle database with the given root_path.

        Useful internal values include:

        * root_path          - The path to the root of the build tree.
        * local_labels       - Transient labels which are asserted.
        * checkout_locations - Maps checkout_label to the directory the
          checkout is in, relative to src/ - if there's no mapping, we believe
          it's directly in src.
        * checkout_repositories - Maps checkout_label to a Repository instance,
          representing where it is checked out from

        NB: the existence of an entry in the checkout_locations dictionary
        does not necessarily imply that such a checkout exists. It may, for
        instance, have gone away during a ``builder.unify()`` operation.
        Thus it is not safe to try to deduce all of the checkout labels
        from the keys to this dictionary. And the same goes for the
        checkout_repositories dictionary.
        """
        self.root_path = root_path
        utils.ensure_dir(os.path.join(self.root_path, ".muddle"))
        self.repo = PathFile(self.db_file_name("RootRepository"))
        self.build_desc = PathFile(self.db_file_name("Description"))
        self.versions_repo = PathFile(self.db_file_name("VersionsRepository"))
        self.role_env = { }
        self.checkout_locations = { }
        self.checkout_repositories = { }

        self.local_tags = set()

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

        This is mainly checkout locations.
        """

        other_db = other_builder.invocation.db

        # Both checkout_xxx dictionaries *should* have identical sets of keys,
        # but just in case...
        keys = set()
        keys.update(other_db.checkout_locations.keys())
        keys.update(other_db.checkout_repositories.keys())

        # We really only want to transform the key labels once for both
        # dictionaries
        new_labels = {}
        for co_label in keys:
            new_co_label = self.normalise_checkout_label(co_label)
            new_co_label._mark_unswept()
            new_co_label._change_domain(other_domain_name)
            new_labels[co_label] = new_co_label

        #print 'include domain:', other_domain_name
        for co_label, co_dir in other_db.checkout_locations.items():
            #print "Including %s -> %s -- %s"%(co_label,co_dir, other_domain_name)
            new_label = new_labels[co_label]
            new_dir = os.path.join(utils.domain_subpath(other_domain_name), co_dir)
            #print "          %s -> %s"%(new_label, new_dir)
            self.checkout_locations[new_label] = new_dir

        for co_label, repo in other_db.checkout_repositories.items():
            new_label = new_labels[co_label]
            self.checkout_repositories[new_label] = repo

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

        NB: We assume that the caller has made sure that its label
        type really is "checkout:".

        For instance, if the caller filled in the role (which we don't
        care about), we need to remove it. Similarly, they might have
        given us various tags, and we want to reduce that to '*' for
        the purpose of using our label as a key.

        Returns a normalised label.

        (NB: This is not guaranteed to be a different Label instance,
        since in theory this method need not do anything if the label
        was already normalised. However, don't assume it is *not* a new
        instance either...)
        """
        new = depend.Label(label.type, label.name,
                           role=None,
                           tag='*',
                           domain=label.domain)
        return new

    def set_checkout_path(self, checkout_label, dir):
        assert checkout_label.type == utils.LabelType.Checkout
        key = self.normalise_checkout_label(checkout_label)

	#print '### set_checkout_path for %s'%checkout_label
	#print '... dir',dir

        self.checkout_locations[key] = os.path.join('src', dir)

    def dump_checkout_paths(self):
        print "> Checkout paths .. "
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

        assert checkout_label.type == utils.LabelType.Checkout

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

        assert checkout_label.type == utils.LabelType.Checkout

        key = self.normalise_checkout_label(checkout_label)
        try:
            return self.checkout_locations[key]
        except KeyError:
            raise utils.GiveUp('There is no checkout path registered for label %s'%checkout_label)

    def set_checkout_repo(self, checkout_label, repo):
        assert checkout_label.type == utils.LabelType.Checkout
        key = self.normalise_checkout_label(checkout_label)
        self.checkout_repositories[key] = repo

    def dump_checkout_repos(self, just_url=False):
        """
        Report on the repositories associated with our checkouts.

        If 'just_url' is true, then report the repository URL, otherwise
        report the full Repository definition (which shows branch and revision
        as well).
        """
        print "> Checkout repositories .. "
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
        assert checkout_label.type == utils.LabelType.Checkout
        key = self.normalise_checkout_label(checkout_label)
        try:
            return self.checkout_repositories[key]
        except KeyError:
            raise utils.GiveUp('There is no repository registered for label %s'%checkout_label)

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


