"""
Contains code which maintains the muddle database, 
held in root/.muddle
"""

import utils
import os
import xml.dom
import xml.dom.minidom
import traceback
import depend

from utils import domain_subpath

class Database(object):
    """
    Represents the muddle database

    Since we expect the user (and code) to edit these files 
    frequently, we deliberately do not cache their values.

    """
    
    def __init__(self, root_path):
        """
        Initialise a muddle database with the given root_path.
        
        * root_path          - The path to the root of the build tree.
        * local_labels       - Transient labels which are asserted.
        * checkout_locations - Maps (checkout, domain) to the directory it's in,
          relative to src/ - if there's no mapping, we believe it's directly
          in src.
        """
        self.root_path = root_path
        utils.ensure_dir(os.path.join(self.root_path, ".muddle"))
        self.repo = PathFile(self.db_file_name("RootRepository"))
        self.build_desc = PathFile(self.db_file_name("Description"))
        self.role_env = { }
        self.checkout_locations = { }

        self.local_tags = set()


    def include_domain(self,other_builder, other_domain_name):
        """
        Include data from other_builder, built in other_name

        This is mainly checkout locations.
        """
        for (k,v) in other_builder.invocation.db.checkout_locations.items():
            (co,dom) = k
            if (dom is None):
                dom = other_domain_name
            else:
                dom = other_domain_name + "." + dom

            self.checkout_locations[(co, dom)] = v
        

    def set_domain(self, domain_name):
        file_name = os.path.join(self.root_path, "domain_name")
        f = open(file_name, "w")
        f.write(domain_name)
        f.write("\n")
        f.close()


    def set_checkout_path(self, checkout, dir, domain = None):
        self.checkout_locations[(checkout, domain)] = dir


    def get_checkout_path(self, checkout, isRelative = False, domain = None):
        """
        'checkout' is the <name> from a "checkout:" label.
        """
        if domain:
            root = os.path.join(self.root_path, domain_subpath(domain))
        else:
            root = self.root_path

        if (checkout is None):
            return os.path.join(root, "src")

        rel_dir = self.checkout_locations.get((checkout, domain), checkout)
        if (isRelative):
            return rel_dir
        else:
            return os.path.join(root, "src", rel_dir)

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
                os.unlink(file_name)
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
                        
                    test_lbl = depend.Label(utils.LabelKind.Package, pkg_name, role, 
                                            utils.Tags.Temporary)
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
        if (label.type != utils.LabelKind.Package):
            raise utils.Error("Attempt to retrieve instruction file "
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
                            utils.label_kind_to_string(label.type),
                            label.name, leaf)
        

    def init(self, repo, build_desc):
        """
        Write the repository and build description files.
        """
        self.repo.set(repo)
        self.build_desc.set(build_desc)
        
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
                os.unlink(self.tag_file_name(label))
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
        """
        if not self.value_valid:
            self.from_disc()
            
        return self.value

    def set(self, val):
        """
        Set the value of the PathFile (possibly to None).
        """
        self.value_valid = True
        self.value = val
        
    def from_disc(self):
        try:
            f = open(self.file_name, "r")
            val = f.readline()
            f.close()
            
            # Remove the trailing '\n' if it exists.
            if val[-1] == '\n':
                val = val[:-1]
                
        except IOError,e:
            val = None
        
        self.value = val
        self.value_valid = True

    def commit(self):
        """
        Write the value of the PathFile to disc.
        """
        
        if not self.value_valid:
            return
 
        if (self.value is None):
            if (os.path.exists(self.file_name)):
                try:
                    os.unlink(self.file_name)
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
        raise utils.Error("Cannot convert Instruction base class to XML")

    def clone_from_xml(self, xmlNode):
        """
        Given an XML node, create a clone of yourself, initialised from that
        XML or raise an error.
        """
        raise utils.Error("Cannot convert XML to Instruction base class")

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
                raise utils.Error("Instruction file %s does not have <instructions> as its document element.",
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
                        raise utils.Error("Could not manufacture an instruction "
                                          "from node %s in file %s."%(i.nodeName, self.file_name))
                    self.values.append(instr)


        except utils.Error, e:
            raise e
        except Exception, x:
            traceback.print_exc()
            raise utils.Error("Cannot read instruction XML from %s - %s"%(self.file_name,x))


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
            raise utils.Error("Could not write instruction file %s - %s"%(file_name,e ))

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
            raise utils.Error("Could not render instruction list - %s"%e)

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
            raise utils.Error("Could not write tagfile %s"%self.file_name)


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


