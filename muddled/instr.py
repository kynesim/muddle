"""
Routines and classes which cope with instructions
"""

import xml.dom
import xml.dom.minidom

import muddled.db as db
import muddled.utils as utils
import muddled.filespec as filespec

class ChangeUserInstruction(db.Instruction):
    """
    An instruction that takes a username, groupname and filespec.
    
    This is the base class for chown and chgrp.
    """

    def __init__(self, filespec, new_user, new_group, name):
        self.filespec = filespec
        self.new_user = new_user
        self.new_group = new_group
        self.name = name
        

    def to_xml(self, doc):
        elem = doc.createElement(self.name)
        
        fspec = self.filespec.to_xml(doc)

        if (self.new_user is not None):
            user_elem = doc.createElement("user")
            user_elem.appendChild(doc.createTextNode(self.new_user))
            elem.appendChild(user_elem)

        if (self.new_group is not None):
            group_elem = doc.createElement("group")
            group_elem.appendChild(doc.createTextNode(self.new_group))
            elem.appendChild(group_elem)

        elem.appendChild(fspec)
        return elem

    def clone_from_xml(self, node):
        if (node.nodeType != node.ELEMENT_NODE or 
            node.nodeName != self.name):
            raise utils.MuddleBug(
                "Invalid outer element for %s user instruction - %s"%(self.name, node))

        new_spec = None
        new_user = None
        new_group = None

        for c in node.childNodes:
            if (c.nodeType == c.ELEMENT_NODE):
                if (c.nodeName == filespec.proto.outer_elem_name()):
                    new_spec = filespec.proto.clone_from_xml(c)
                elif (c.nodeName == "user"):
                    new_user = utils.text_in_node(c)
                elif (c.nodeName == "group"):
                    new_group = utils.text_in_node(c)
                else:
                    raise utils.MuddleBug("Invalid element in %s instruction: %s"%(self.name,
                                                                               c.nodeName))
        if (new_spec is None) or ((new_user is None) and (new_group is None)):
            raise utils.MuddleBug("Either user/group or filespec is not specified in XML.")
    
        return ChangeUserInstruction(new_spec, new_user, new_group, self.name)
    
    def outer_elem_name(self):
        return self.name

    def equal(self, other):
        #if (not db.Instruction.equal(self,other)):
        if not super(ChangeUserInstruction,self).equal(other):
            return False

        if (self.name != other.name):
            return False

        if (not self.filespec.equal(other.filespec)):
            return False

        if self.new_user != other.new_user:
            return False


class ChangeModeInstruction(db.Instruction):
    """
    Change the mode of a filespec (``chown``).
    """
    
    def __init__(self, filespec, new_mode, name):
        self.filespec = filespec
        self.new_mode = new_mode
        self.name = name

    def to_xml(self, doc):
        elem = doc.createElement(self.name)
        
        fspec = self.filespec.to_xml(doc)
        user_elem = doc.createElement("mode")
        user_elem.appendChild(doc.createTextNode(self.new_mode))

        elem.appendChild(fspec)
        elem.appendChild(user_elem)
        return elem

    def clone_from_xml(self, node):
        if (node.nodeType != node.ELEMENT_NODE or 
            node.nodeName != self.name):
            raise utils.MuddleBug(
                "Invalid outer element for %s user instruction - %s"%(self.name, node))

        new_spec = None
        new_mode = None

        for c in node.childNodes:
            if (c.nodeType == c.ELEMENT_NODE):
                if (c.nodeName == filespec.proto.outer_elem_name()):
                    new_spec = filespec.proto.clone_from_xml(c)
                elif (c.nodeName == "mode"):
                    new_mode = utils.text_in_node(c)
                else:
                    raise utils.MuddleBug("Invalid element in %s instruction: %s"%(self.name,
                                                                               c.nodeName))
        if (new_mode is None) or (new_spec is None):
            raise utils.MuddleBug("Either mode or filespec is not specified in XML.")
    
        return ChangeModeInstruction(new_spec, new_mode, self.name)
    
    def outer_elem_name(self):
        return self.name

    def equal(self, other):
        #if (not db.Instruction.equal(self,other)):
        if not super(ChangeModeInstruction,self).equal(other):
            return False

        if (self.name != other.name):
            return False

        if (not self.filespec.equal(other.filespec)):
            return False

        if self.new_mode != other.new_mode:
            return False

def sanitise_filename(name):
    """Sanitise a <name>filename</name>.

    We want to make sure that the name is relative to the muddle
    directories. Specifically, we want to make sure that if the
    filename is <name>/etc/passwd</name> then we do not try to
    access the host system's ``/etc/passwd`` file, but rather
    a local ``.../etc/passwd``.

    It turns out the simplest thing to do is to remove any initial
    "/", rendering the name relative...
    """
    while name.startswith('/'):
        name = name[1:]
    return name

class MakeDeviceInstruction(db.Instruction):
    """
    Create a device file - this is essentially ``mknod``.
    """

    def __init__(self):
        self.file_name = None
        self.uid = None
        self.gid = None
        self.type = None # 'block' for a block device, 'char' for a character device

        self.major = None
        self.minor = None
        self.mode = None

    def to_xml(self, doc):
        elem = doc.createElement("mknod")
        
        elem.appendChild(utils.xml_elem_with_child(doc, "name", self.file_name))
        elem.appendChild(utils.xml_elem_with_child(doc, "uid", self.uid))
        elem.appendChild(utils.xml_elem_with_child(doc, "gid", self.gid))
        elem.appendChild(utils.xml_elem_with_child(doc, "type", self.type))
        elem.appendChild(utils.xml_elem_with_child(doc, "major", self.major))
        elem.appendChild(utils.xml_elem_with_child(doc, "minor", self.minor))
        elem.appendChild(utils.xml_elem_with_child(doc, "mode", self.mode))
        
        return elem

    def clone_from_xml(self, node):
        if (node.nodeType != node.ELEMENT_NODE or 
            node.nodeName != "mknod"):
            raise utils.GiveUp("Invalid outer element for %s user instruction - %s"%("mknod", 
                                                                                      node))
        result = MakeDeviceInstruction()
        
        for c in node.childNodes:
            if (c.nodeType == c.ELEMENT_NODE):
                if (c.nodeName == "name"):
                    result.file_name = sanitise_filename(utils.text_in_node(c))
                elif (c.nodeName == "uid"):
                    result.uid = utils.text_in_node(c)
                elif (c.nodeName == "gid"):
                    result.gid = utils.text_in_node(c)
                elif (c.nodeName == "type"):
                    result.type = utils.text_in_node(c)
                elif (c.nodeName == "major"):
                    result.major = utils.text_in_node(c)
                elif (c.nodeName == "minor"):
                    result.minor = utils.text_in_node(c)
                elif (c.nodeName == "mode"):
                    result.mode = utils.text_in_node(c)
                else:
                    raise utils.GiveUp("Invalid node in mknod instruction: %s"%(c.nodeName))
        
        result.validate()
        return result

    def validate(self):
        if (self.file_name is None):
            raise utils.GiveUp("Invalid mknod node - no file name")

        if (self.uid is None):
            raise utils.GiveUp("Invalid mknod node - no uid")
        if (self.gid is None):
            raise utils.GiveUp("Invalid mknod node - no gid")
        if (self.type is None):
            raise utils.GiveUp("Invalid mknod node - no device type (block or char)")
        if (self.major is None):
            raise utils.GiveUp("Invalid mknod node - no major number")
        if (self.minor is None):
            raise utils.GiveUp("Invalid mknod node - no minor number")
        if (self.mode is None):
            raise utils.GiveUp("Invalid mknod node - no mode")

        
        
    def outer_elem_name(self):
        return "mknod"

    def equal(self, other):
        #if (not db.Instruction.equal(self, other)):
        if not super(MakeDeviceInstruction,self).equal(other):
            return False

        return (self.file_name == other.file_name and
                self.uid == other.uid and
                self.gid == other.gid and
                self.type == other.type and
                self.major == other.major and
                self.minor == other.minor and
                self.mode == other.mode)
        


class BuiltinInstructionFactory(db.InstructionFactory):
    """
    An instruction factory that can build all the built-in instructions.
    You can extend or augment this class to generate a factory which 
    builds your favourite add-on instructions.

    (though note that your favourite deployment will need to understand
    them in order to to obey them)
    """
    
    def __init__(self):
        """
        instr_map    Maps instruction names to prototype classes, which can then be cloned
        """

        self.instr_map = { } 
    
    def register(self, name, instruction):
        self.instr_map[name] = instruction

    def from_xml(self, xmlNode):
        n = xmlNode.nodeName

        if (n is None):
            raise utils.MuddleBug("Attempt to initialise an instruction from %s which has no name."%(str(n)))
        
        # Otherwise ..
        if (n in self.instr_map):
            return self.instr_map[n].clone_from_xml(xmlNode)
        else:
            raise utils.MuddleBug("No instruction corresponding to tag %s"%n)



# DANGER WILL ROBINSON!
#
# The nature of deployments is that they must understand instructions themselves - 
# the instructions can only be syntax. Semantics depend on exactly how deployments
# package files (tarfile, copy to filesystem, privileged/unprivileged, etc.)
# the names of these instructions (or rather their outer elem names) are therefore
# exceptionally sensitive and you _must_ not change them without good reason.
#
# Note specifically that people can happily customise deployments in their build
# scripts. If you change the recognised instructions here, those customised 
# deployments will die horribly. You can, of course, add new instructions just 
# so long as you don't try to give them to a deployment that doesn't understand
# them.
#
# Don't say you weren't warned.
#
# <rrw@kynesim.co.uk> 2009-06-04 19:00

factory = BuiltinInstructionFactory()
factory.register("chown", ChangeUserInstruction(None, None, None, "chown"))
factory.register("chmod", ChangeModeInstruction(None, None, "chmod"))
factory.register("mknod", MakeDeviceInstruction())


# End file.


