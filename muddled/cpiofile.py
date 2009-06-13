"""
Utilities to write cpio archives. 

There is apparently no standard way to do this from python.
Ugh.
"""

import utils
import stat
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

    def rename(self, name):
        self.name = name

    def set_contents(self, data):
        self.orig_file = None
        self.data = data

    def set_contents_from_file(self, file_name):
        self.orig_file = file_name
        self.data = None

def file_for_dir(name):
    """
    Create a vague attempt at a directory entry
    """
    outfile = File()
    outfile.mode = File.S_DIR | 0755
    outfile.name = name
    return outfile

def file_from_data(name, data):
    """
    Creates a File object from some explicit data you give it
    """
    outfile = File()
    outfile.name = name
    outfile.data = data
    # Last modified just now .. 
    outfile.mtime = utils.unix_time()
    outfile.orig_file = None
    return outfile


def file_from_fs(orig_file):
    """
    Create a file object from a file on disc. You'll want to rename() it, unless
    you meant the file in the CPIO archive to have the same name as the one
    you passed in.
    """

    # Make sure we use lstat or bad things will happen to symlinks.
    stinfo = os.lstat(orig_file)

    outfile = File()
    outfile.dev = stinfo.st_dev
    outfile.ino = stinfo.st_ino
    outfile.mode = stinfo.st_mode
    outfile.uid = stinfo.st_uid
    outfile.gid = stinfo.st_gid
    outfile.nlink = stinfo.st_nlink
    outfile.rdev = stinfo.st_rdev
    outfile.mtime = stinfo.st_mtime
    outfile.name = orig_file
    outfile.data = None
    outfile.orig_file = orig_file

    return outfile
    


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

        @todo Reorder files in render() so that we get them in the right order, 
         and remember to create intermediate directories.
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
                orig_stat = os.stat(f.orig_file)

                if (stat.S_ISREG(orig_stat.st_mode)):
                    f_in = open(f.orig_file, "rb")
                    file_data = f_in.read()
                    f_in.close()
                elif (stat.S_ISLINK(orig_stat.st_mode)):
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
                f_out.write("\0")

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

