"""
Utilities to write cpio archives. 

There is apparently no standard way to do this from python.
Ugh.
"""

import utils
import stat
import filespec
import os

class File:
    """
    Represents a file in a CPIO archive.
    """

    # Raided from some old docs on cpio file formats: these are
    # all bits in st_mode

    S_SOCKET = 0140000
    S_LINK   = 0120000
    S_REG    = 0100000
    S_BLK    = 0060000
    S_DIR    = 0040000
    S_CHAR   = 0020000
    S_SUID   = 0004000
    S_SGID   = 0002000
    S_STICKY = 0001000

    

    def __init__(self):
        """
        Create a new, empty file. Some more or less sensible
        defaults are set up so that if you do try to synthesise
        a cpio archive from a default-constructed File you don't
        get utter rubbish. No guarantees you get a valid 
        archive either though .. 

        * key_name is the name of the key under which this file is stored
          in the parent heirarchy. It's a complete hack, but essential for
          finding a file in the key map quickly without which deletion 
          becomes an O(n^2) operation (and N = number of files in the root
          fs, so it's quite high).

        * self.name      - is the name of the file in the target archive.
        * self.fs_name   - is the name of the file in the underlying filesystem.
        * self.orig_file - is the name of the file from which the data in this
          file object comes.

        """
        self.dev = 0
        self.ino = 0
        self.mode = 0644
        self.uid = 0
        self.gid = 0
        self.nlink = 1
        self.rdev = 0
        self.mtime = utils.unix_time()
        self.name = None
        self.data = None
        self.orig_file = None
        # Children of this directory, if it is one.
        self.children = [ ]
        self.fs_name = None

    def delete_child_with_name(self, in_name):
        for i in range(0, len(self.children)):
            if self.children[i].name == in_name:
                del self.children[i]
                return


    def rename(self, name):
        self.name = name

    def set_contents(self, data):
        self.orig_file = None
        self.data = data

    def set_contents_from_file(self, file_name):
        self.orig_file = file_name
        self.data = None

    def __str__(self):
        return "[ %s (fs %s) mode = %o uid = %d gid = %d kids = %s]"%\
            (self.name, 
             self.fs_name, 
             self.mode, self.uid, 
             self.gid, 
             " ".join(map(lambda x: x.name, self.children)))

class Heirarchy:
    
    def __init__(self, map, roots):
        """
        * self.map   - maps names in the target archive to file objects.
        * self.roots - is a subset of self.map that just maps the root objects.
        """
        self.map = map
        self.roots = roots

    def merge(self, other):
        """
        Merge other with self.

        We need to keep the heirarchy sensibly updated.

        We merge the maps. We then kill all children and iterate over
        everything in the resulting map, finding a parent to add it
        to. This fails to preserve the order of files in directories,
        but the result is correct in every other way.

        Anything in the result that does not have a parent is a root.
        """
        
        # Merge
        for (k,v) in other.map.items():
            self.map[k] = v

        # Obliterate any children.
        for v in self.map.values():
            v.children =  [ ]

        # Wipe roots
        self.roots = { }

        for (k,v) in self.map.items():
            (a,b) = os.path.split(k)

            parent_node = self.map.get(a)

            #print "Merge: k = %s a = %s b = %s parent_node = %s"%(k,a,b,parent_node)
            if (parent_node is None) or (a=="/" and b==""):
                #print "root[k] = v (%s -> %s)"%(k, v.key_name)
                self.roots[k] = v
            elif (parent_node.mode & File.S_DIR) != 0:
                # Got a parent.
                parent_node.children.append(v)
            else:
                raise utils.Failure("Attempt to merge file %s when parent '%s' ('%s') is not a directory: dir mode flag = 0x%x"%(k,parent_node,a, File.S_DIR))

        # .. and that's all, folks.

    def normalise(self):
        """
        Normalise the heirarchy into one with a single root.
        
        We do this by taking each root in turn and removing a component, creating
        a directory in the process. If the resulting root is in roots, we add it
        to the children of that root and eliminate it from the map.

        Iterate until there is only one root left.
        """

        while len(self.roots) > 1:
            # Pick a key .. 
            did_something = False
            new_roots = { }
        
            for (k,v) in self.roots.items():
                #print "Normalise %s => "%k
                if (k != "/"):
                    # It can be shortened ..
                    (dir, name) = os.path.split(k)

                    did_something = True

                    #print "=> dir = %s"%dir
                    if (dir not in self.map):

                        # Curses. Don't already have that directory - 
                        # must build it.
                        new_dir = File()
                        new_dir.mode = 0755 | File.S_DIR
                        new_dir.name = dir
                        new_dir.children.append(v)
                        # The directory wasn't present, so must be 
                        # a new root .
                        new_roots[dir] = new_dir
                        self.map[dir] = new_dir
                    else:
                        new_dir = self.map[dir]
                        new_dir.children.append(v)

                else:
                    new_roots[k] = v

            self.roots = new_roots
            if (not did_something):
                raise utils.Failure("Failed to normalise a heirarchy -"
                                    " circular roots?: %s"%self)
            
    
    def render(self, to_file, logProgress = False):
        
        # Right. Trace each root into a list ..
        file_list = [ ]
        for r in self.roots.values():
            trace_files(file_list, r)

        ar = Archive()
        # We know this is in the right order, so we can hack a bit ..
        ar.files = file_list
        ar.render(to_file, logProgress)

    def erase_target(self, file_name):
        """
        Recursively remove file_name and all its descendants from the
        heirarchy.
        """
        
        #print "Erase %s .. "%file_name
        # Irritatingly, we need to iterate to find the name, since
        # the map doesn't contain target names - only source ones :-(

        if (file_name in self.roots):
            del self.roots[file_name]

        if (file_name in self.map):
            obj = self.map[file_name]
            for c in obj.children:
                self.erase_target(c.name)

        par = self.parent_from_key(file_name)
        if (par is not None):
            par.delete_child_with_name(file_name)
    

    def parent_from_key(self, key_name):
        up = os.path.dirname(key_name)

        if (up in self.map):
            return self.map[up]
        else:
            return None                

    def put_target_file(self, name, obj):
        """
        Put a file into the archive. The directory
        for it must already exist.
        
        * name - The name of the file in the target archive.
        * obj  - The file object to insert.
        """
        
        # Make sure we have referential integrity .. 
        obj.name = name

        # Find a parent .. 
        par = self.parent_from_key(name)
        if (par is None):
            raise utils.Failure("Cannot find a parent for %s in put_target_file()"%name)

        par.children.append(obj)
        self.map[name] = obj        

    def __str__(self):
        rv = [ ]
        rv.append("---Roots---\n")
        for (k,v) in self.roots.items():
            rv.append("%s -> %s\n"%(k,v))
        rv.append("---Map---\n")
        for (k,v) in self.map.items():
            rv.append("%s -> %s\n"%(k,v))
        rv.append("---\n")
        return "".join(rv)



class CpioFileDataProvider(filespec.FileSpecDataProvider):    
    def __init__(self, heirarchy):
        """
        Given a file map like that returned from files_from_fs()
        and a root name, create a filespec data provider.

        name is the root of the effective heirarchy.
        """
        self.heirarchy = heirarchy

        
    def list_files_under(self, dir, recursively = False, 
                         vroot = None):
        """
        Return a list of the files under dir.
        """
        
        if (dir[0] == '/'):
            dir = dir[1:]

        #print "l_f_u = %s (vroot = %s)"%(dir,vroot)

        for r in self.heirarchy.roots.keys():
            to_find = utils.rel_join(vroot, dir)
        
            abs_path = os.path.join(r, to_find)

            # Trim any trailing '/'s for normalisation reasons.
            if (len(abs_path) > 1 and abs_path[-1] == '/'):
                abs_path = abs_path[:-1]

            # Find the File representing this directory
            obj = self.heirarchy.map.get(abs_path)
            if (obj is not None):
                break

        if (obj is None):
            print "> Warning: No files in %s [vroot = %s] in this cpio archive.. "%(dir,vroot)
            return [ ]
        
        # Read everything in this directory.
        result = [ ]
        for elem in obj.children:
            last_elem = os.path.basename(elem.name)
            # We want the last element only ..
            result.append(last_elem)
            
            if (recursively):
                # .. and recurse ..
                #print "> l_f_u recurse dir = %s, elem.name = %s last = %s"%(dir, elem.name, last_elem)
                result.extend(self.list_files_under(os.path.join(dir, last_elem), True, 
                                                    vroot = vroot))
        
        return result

    def abs_match(self, filespec, vroot = None):
        """
        Return a list of the file object for each file that matches
        filespec.
        """
        files = filespec.match(self, vroot = vroot)

        rv = [ ]
        for f in files:
            if (f in self.heirarchy.map):
                #print "--> Abs_match result = %s"%f
                rv.append(self.heirarchy.map[f])

        return rv
    


def file_for_dir(name):
    """
    Create a vague attempt at a directory entry.
    """
    outfile = File()
    outfile.mode = File.S_DIR | 0755
    outfile.name = name
    return outfile

def file_from_data(name, data):
    """
    Creates a File object from some explicit data you give it.
    """
    outfile = File()
    outfile.name = name
    outfile.data = data
    # Last modified just now .. 
    outfile.mtime = utils.unix_time()
    outfile.orig_file = None
    return outfile

    

def merge_maps(dest, src):
    """ 
    Merge src into dest. This needs special handling because we need to
    keep the heirarchy intact

    We merge dest and src and then just rebuild the entire heirarchy - it's
    the easiest way, frankly.
    
    For everything in the merged list, zap its children.

    Now iterate over everything, os.path.split() it to find its parent 
    and add it to its parents' child list.

    If its parent doesn't exist, it's a root - mark and ignore it.
    """
    
    
    

def heirarchy_from_fs(name, base_name):
    """
    Create a heirarchy of files from a named object in the
    filesystem.

    The files will be named with 'base_name' substituted for 'name'.

    Returns a Heirarchy with everything filled in.
    """

    # A map of filename to file object, so you can find 'em eas
    file_map = { }
    
    # Add the root .. 
    file_map[base_name] = file_from_fs(name,
                                  base_name)

    # Same as file_map, but indexed by the name in the fs rather
    # than in the resulting archive - used to find directories 
    # quickly.
    by_tgt_map = { }

    by_tgt_map[name] = file_map[base_name]

    the_paths = os.walk(name)
    for p in the_paths:
        (root, dirs, files) = p
        
        # This is legit - top-down means that root must have been
        # visited first. If it isn't, our ordering will collapse
        # and the cpio archive when we generate it will at the
        # least be extremely odd.
        #
        root_file = by_tgt_map[root]

        for d in dirs:
            new_obj = os.path.join(root, d)
            # Lop off the initial name and replace with base_name            
            tgt_name =  utils.replace_root_name(name, base_name, 
                                                new_obj)
            new_file = file_from_fs(new_obj, tgt_name)
            file_map[tgt_name] = new_file
            by_tgt_map[new_obj] = new_file
            root_file.children.append(new_file)

        for f in files:
            new_obj = os.path.join(root, f)
            #print "new_obj = %s"%new_obj
            tgt_name =  utils.replace_root_name(name, base_name, 
                                                new_obj)
            new_file = file_from_fs(new_obj, tgt_name)
            file_map[tgt_name] = new_file
            by_tgt_map[new_obj] = new_file
            root_file.children.append(new_file)

    return Heirarchy(file_map, { base_name : file_map[base_name] })


def file_from_fs(orig_file, new_name = None):
    """
    Create a file object from a file on disc. You'll want to rename() it, unless
    you meant the file in the CPIO archive to have the same name as the one
    you passed in.
    """

    # Make sure we use lstat or bad things will happen to symlinks.
    stinfo = os.lstat(orig_file)

    if (new_name is None):
        new_name = orig_file

    outfile = File()
    outfile.dev = stinfo.st_dev
    outfile.ino = stinfo.st_ino
    outfile.mode = stinfo.st_mode
    outfile.uid = stinfo.st_uid
    outfile.gid = stinfo.st_gid
    outfile.nlink = stinfo.st_nlink
    outfile.rdev = stinfo.st_rdev
    outfile.mtime = stinfo.st_mtime
    outfile.name = new_name
    outfile.data = None
    outfile.orig_file = orig_file
    outfile.fs_name = orig_file
    if new_name is not None:
        outfile.name = new_name

    return outfile

def trace_files(file_list, root):
    """
    Given a File, add it and all its children, top-down, into
    file_list. Used as a utility routine by Heirarchy.
    """
    file_list.append(root)
    for c in root.children:
        trace_files(file_list, c)
    

class Archive:
    """
    Represents a CPIO archive.

    Files are represented by their header information and the name of
    a file in the filesystem where they live. When render() is called,
    the appropriate data is written out to disc.
    """

    def __init__(self):
        self.files = [ ]


    def add_file(self, a_file):
        """
        DANGER WILL ROBINSON! You need to add files in the right order
        here or cpio will get very confused. 

        .. todo:: Reorder files in render() so that we get them in the right
           order, and remember to create intermediate directories.
        """
        self.files.append(a_file)

    def add_files(self, in_files):
        for f in in_files:
            self.add_file(f)


    def render(self, to_file, logProgress = False):
        """
        Render a CPIO archive to the given file.
        """
        
        f_out = open(to_file, "wb")
        
        file_list = list(self.files)
        # There's a trailer on every cpio archive .. 
        file_list.append(file_from_data("TRAILER!!!", ""))

        for f in file_list:
            # We need to know our data size, so pull in the data now.
            if (f.orig_file is not None):
                # Is this a real file at all?
                orig_stat = os.lstat(f.orig_file)

                if (stat.S_ISREG(orig_stat.st_mode)):
                    f_in = open(f.orig_file, "rb")
                    file_data = f_in.read()
                    f_in.close()
                elif (stat.S_ISLNK(orig_stat.st_mode)):
                    file_data = os.readlink(f.orig_file)
                else:
                    # No data
                    file_data = None
            else:
                file_data = f.data

            if (file_data is None):
                # There is actually no data.
                data_size = 0
            else:
                # There is data, but it may be a zero-length string.
                data_size = len(file_data)

            # name_size includes the terminating NUL
            name_size = len(f.name) + 1

            # This is a bit inefficient, but it has the advantage of clarity.
            hdr_array = [ ]

            # cpio, as is UNIX's wont, is almost entirely undocumented:
            # http://refspecs.freestandards.org/LSB_3.1.0/LSB-Core-generic/LSB-Core-generic/pkgformat.html
            # has a spec for the SVR4 portable format (-Hnewc), which is 
            # understood by newer Linux kernels as an initrd format.


            # Magic
            hdr_array.append("070701")  
            hdr_array.append("%08X"%f.ino)
            hdr_array.append("%08X"%f.mode)
            hdr_array.append("%08X"%f.uid)
            hdr_array.append("%08X"%f.gid)
            hdr_array.append("%08X"%f.nlink)
            hdr_array.append("%08X"%f.mtime)
            hdr_array.append("%08X"%data_size)
            hdr_array.append("%08X"%os.major(f.dev))
            hdr_array.append("%08X"%os.minor(f.dev))
            hdr_array.append("%08X"%os.major(f.rdev))
            hdr_array.append("%08X"%os.minor(f.rdev))
            hdr_array.append("%08X"%name_size)
            # And a zero checksum (?!)
            hdr_array.append("%08x"%0)

            if (logProgress):
                print "> Packing %s .. "%(f.name)

            f_out.write("".join(hdr_array))
            f_out.write(f.name)
            f_out.write("\0")

            # Now we need to pad to a 4-byte boundary.
            pos = f_out.tell()
            if (pos%4):
                for i in range(0, 4-(pos%4)):
                    f_out.write("\0")
        

            if (file_data is not None):
                f_out.write(file_data)

            # .. and pad again.
            pos = f_out.tell()
            if (pos%4):
                for i in range(0, 4-(pos%4)):
                    f_out.write("\0")

            # Make very sure we throw this data away after we're done
            # using it - it's typically several megabytes.
            file_data = None

            
        f_out.close()
        # And that's all, folks.


# End file.

