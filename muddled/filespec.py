"""
FileSpecs: a cheap and cheerful way to specify files for the
purposes of deployment instructions
"""

import re
import os

import muddled.utils as utils

class FileSpecDataProvider(object):
    """
    Provides data to a filespec so it can decide what it matches.
    """

    def list_files_under(self, dir, recursively = False, vroot = None):
        """
        Return a list of the files under dir. If dir is not a directory,
        returns an empty list.

        The files are returned without 'dir', so::

            list_files_under("/fred/wombat", False)

        gives::

            [ "a", "b", "c" ]

        *not*::

            [ "/fred/wombat/a" .. ]

        whilst::

            list_files_under("/fred", True)

        gives::

            [ "wombat", "wombat/a", "wombat/b", "wombat/c" ]
        """
        raise utils.MuddleBug("Cannot call FileSpecDataProvider.list_files_under() - "
                          "try a subclass")


class FileSpec(object):
    """
    Represents a (possibly recursive) file specification. Filespecs are
    essentially python regular expressions with a recursion flag.

    Matching for these objects is slightly special, since they need
    to apply to objects in the filesystem. Filespecs contain a root,
    which bounds the spec, a specifier, which is a regular expression
    indicating which files in that spec should match, and two recursion
    flags:

    * all_under - This filespec applies to all files under any directories
      that match the base filespec.

    * all_regex - The specifier applies as a regex to all files under the
      root. This can be very slow if there are many files under the filespec
      root.
    """

    def __init__(self, root, spec, allUnder = False, allRegex = False):
        self.root = root
        self.spec = spec
        # Add a synthetic $ or we'll get a lot of odd prefix matches.
        self.spec_re = re.compile("%s$"%spec)
        self.all_under = allUnder
        self.all_regex = allRegex

    def equal(self, other):
        if (self is None) and (other is None):
            return True # Um .. I suppose ..

        if (other is None) or (self is None):
            return False

        if (self.__class__ != other.__class__):
            return False

        if (self.root != other.root or self.spec != other.spec or
            self.all_under != other.all_under or self.all_regex != other.all_regex):
            return False

        # Hmm .. it appears we have no choice.
        return True

    def match(self, data_provider, vroot=None):
        """
        Match this filespec with a data provider, returning a set of
        file- and directory- names upon which to operate.

        Since we have no idea what the root path of the data provider
        might be, you probably need to stitch together the filenames
        yourself.

        ``FSFileSpecDataProvider.abs_match()`` is probably your friend -
        if you're using the filesystem to provide data for a filespec,
        call it, not us.

        vroot is a 'virtual root' - the data provider transparently
        returns the subset of files that would be present if 'vroot'
        in the data provider were the root. It is used by remappings
        in the cpio deployment, among others.
        """
        # OK. Find everything under root .
        return_set = set()


        all_in_root = data_provider.list_files_under(self.root, self.all_under,
                                                     vroot = vroot)
        #print 'all_in_root=%s'%all_in_root
        for f in all_in_root:
            #print "Match f  = %s against spec = %s"%(f, self.spec)
            if self.spec_re.match(f) is not None:
                # Gotcha
                #print "Found match = %s"%os.path.join(self.root, f)
                return_set.add(os.path.join(self.root, f))

        #print 'RETURN SET', return_set

        # Right. Now, if we're recursive, recurse.
        if self.all_under:
            extras = set()

            def maybe_add_and_recurse(i):
                #print "i = %s"%i
                under = data_provider.list_files_under(i, True,
                                                       vroot = vroot)
                for u in under:
                    #print "u = %s"%u
                    to_add = os.path.join(self.root, i, u)
                    if to_add not in return_set:
                        extras.add(to_add)
                        maybe_add_and_recurse(os.path.join(i,u))

            for i in return_set:
                maybe_add_and_recurse(i)

            return_set.update(extras)

        #print "Return return_set len = %d "%(len(return_set))
        return return_set



    def clone_from_xml(self, xmlNode):
        """
        Clone a filespec from some XML like::

            <filespec>
             <root>..</root>
             <spec> ..</spec>
             <all-under />
             <all-regex />
            </filespec>
        """
        if (xmlNode.nodeName != "filespec"):
            raise utils.GiveUp("Filespec xml node is called %s , not filespec."%(xmlNode.nodeName))

        new_root = None
        new_spec = None
        new_all_under = False
        new_all_regex = False

        for c in xmlNode.childNodes:
            if (c.nodeType == c.ELEMENT_NODE):
                if (c.nodeName == "root"):
                    new_root = utils.text_in_node(c)
                elif (c.nodeName == "spec"):
                    new_spec = utils.text_in_node(c)
                elif (c.nodeName == "all-under"):
                    new_all_under = True
                elif (c.nodeName == "all-regex"):
                    new_all_regex = True
                else:
                    raise utils.GiveUp("Unknown element %s in filespec"%(c.nodeName))

        return FileSpec(new_root, new_spec, new_all_under, new_all_regex)

    def outer_elem_name(self):
        return "filespec"

    def is_filespec_node(self, inXmlNode):
        """
        Given an XML node, decide if this is likely to be a filespec
        (really just checks if it's an element of the right name).
        Useful for parsing documents that may contain filespecs.
        """
        return (inXmlNode.nodeType == inXmlNode.ELEMENT_NODE and
                inXmlNode.nodeName == "filespec")

    def to_xml(self, doc):
        """
        Create some XML from this filespec.
        """
        ext_node = doc.createElement("filespec")

        root_node = doc.createElement("root")
        root_node.appendChild(doc.createTextNode(self.root))
        ext_node.appendChild(root_node)

        spec_node = doc.createElement("spec")
        spec_node.appendChild(doc.createTextNode(self.spec))
        ext_node.appendChild(spec_node)

        if (self.all_under):
            under_node = doc.createElement("all-under")
            ext_node.appendChild(under_node)

        if (self.all_regex):
            regex_node = doc.createElement("all-regex")
            ext_node.appendChild(regex_node)

        return ext_node


class ListFileSpecDataProvider(object):
    """
    A FileSpecDataProvider that uses a file list. Used to test the
    FileSpec matching code.
    """

    def __init__(self, file_list):
        self.file_list = file_list

    def list_files_under(self, dir, recursively = False, vroot = None):
        # _really_ simple-minded ..
        result = [ ]
        for f in self.file_list:
            d = dir

            # Remove any common prefix
            while d and f:
                ld, restd = utils.split_path_left(d)
                fd, restf = utils.split_path_left(f)
                if ld != fd:
                    break
                d, f = restd, restf

            if d:               # We don't actually start with 'dir'
                continue

            if not f:           # We *were* 'dir'
                continue

            if recursively:
                result.append(f)
            else:
                if f.find("/") == -1:
                    # Yep
                    result.append(f)

        return result


class FSFileSpecDataProvider(object):
    """
    A FileSpecDataProvider rooted at a particular point in the filesystem
    """

    def __init__(self, base_dir):
        self.base_dir = os.path.abspath(base_dir)

    def list_files_under(self, dir, recursively = False, vroot = None):
        # dir is relative to base_dir, so ..

        # Don't absolutise a path needlessly.
        if (dir[0] == '/'):
            dir = dir[1:]

        abs_path = os.path.join(self.base_dir, dir)

        #print "base_dir = %s dir = %s abs_path = %s"%(self.base_dir, dir, abs_path)

        # Read all the files in this directory ..
        if (not os.path.isdir(abs_path)):
            return [ ]

        lst = os.listdir(abs_path)
        result = [ ]
        for elem in lst:
            result.append(elem)

            abs_elem = os.path.join(abs_path, elem)
            # NB: Take care not to follow links, lest we end up in a loop
            if (recursively and os.path.isdir(abs_elem) and not os.path.islink(abs_elem)):
                result.extend(
                    map(lambda v: os.path.join(elem, v),
                        self.list_files_under(os.path.join(dir, elem), True)))

        return result

    def abs_match(self, filespec):
        """
        Match the filespec to this data provider and return a list
        of actual absolute filenames on which to operate
        """
        files = filespec.match(self)

        rv = [ ]
        for f in files:
            # Avoid accidental absolutisation ..
            if (f[0] == '/'):
                f = f[1:]
            rv.append(os.path.join(self.base_dir, f))
            #print "base_dir = %s f = %s rv = %s"%(self.base_dir, f, rv)

        return rv

# A singleton, empty, filespec you can use to parse out other filespecs by
# calling clone_from_xml()
proto = FileSpec("/", "/")

# End file.




