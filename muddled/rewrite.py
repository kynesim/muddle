"""
This module provides for rewrites of .al and pkgconfig
files to reflect the realities of existing inside a muddle
build tree.

Specifically, it allows you to rewrite the .la and .pkgconfig
files from an autoconf'd package (typically created with
make install DESTDIR=$(MUDDLE_OBJ_DIR) ) so that future
packages will pick up libraries in the right places.

It is, of course, up to those packages to not use
-rpath-link to force your build tree locations into the
target filesystem.

"""

import utils
import stat
import os
import re

def parse_line(l):
    """
    Parse the given line, returning (key, value) or (None, None) if it
    wasn't valid
    """
    
    idx = l.find('=')
    if (idx < 0):
        return (None, None)
    else:
        return (l[:idx], l[idx+1:])


def subst_la(builder, current, dir, libPath, includePath, execPrefix):
    """
    Substitute a .la file.
    """

    an_re = re.compile('^libdir=')
    
    if (libPath is None):
        libPath = os.path.join(dir, "lib")

    # Read the file in .
    f = open(current, 'r')
    lines = f.readlines()
    f.close()
    outlines = []

    for l in lines:
        # Find an '=' sign.
        (key, value) = parse_line(l)
        done = False

        

        if (key is not None):
            if (key == "libdir"):
                # Excellent.
                outlines.append("libdir=%s\n"%(libPath))
                done = True
            elif (key == "dependency_libs"):
                # This one is a bit trickier. This is a list of libraries
                # and we need to prepend dir to all of them.
                elems = utils.unquote_list(value)
                new_elems = []

                dirlen = len(dir)
                for i in elems:
                    #print "> Rewriting .la found %s"%i
                    # This is even harder: some of the dependencies
                    #  will be proper, some will be to '/lib' or '//lib',
                    #  since that's where we name ourselves.
                    #
                    # Remove leading double slashes - they're not awfully elegant
                    v = re.sub(r'//', r'/', i)

                    base_dir = os.path.dirname(v)

                    
                    if (base_dir == "/lib" or base_dir == "//lib" or
                        base_dir == "/usr/lib" or base_dir == "//usr/lib"):
                        # It's supposed to be ..
                        new_v = "%s/%s"%(dir,v)
                        # Be elegant ..
                        new_v = re.sub(r'//',r'/', new_v)
                        new_elems.append(new_v)
                    else:
                        new_elems.append(v)

                outlines.append("dependency_libs='%s'\n"%utils.quote_list(new_elems))
                done = True
        
        if not done:
            outlines.append(l)

    outstring = "".join(outlines)
    f = open(current, 'w')
    f.write(outstring)
    f.close()


def subst_pc(builder, current, dir, libPath, includePath, execPrefix):
    """
    Substitute a pkgconfig (.pc) file.
    """
    
    if (libPath is None):
        libPath = os.path.join(dir, "lib")

    if (execPrefix is None):
        execPrefix = dir

    f = open(current, "r")
    lines = f.readlines()
    f.close()
    outlines = [ ]

    for l in lines:
        done = False
        (key, value) = parse_line(l)
        if (key is not None):
            if (key == "prefix"):
                outlines.append("prefix=%s\n"%(dir))
                done = True
            elif (key == "exec_prefix"):
                outlines.append("exec_prefix=%s\n"%(execPrefix))
                done = True
            elif ((includePath is not None) and
                  key == "includedir"):
                outlines.append("includedir=%s\n"%(includePath))
                done = True

        if not done:
            outlines.append(l)
            
    outText = "".join(outlines)
    f = open(current, "w")
    f.write(outText)
    f.close()



def fix_up_pkgconfig_and_la(builder, dir,
                            subdir = None,
                            libPath = None,
                            includePath = None, 
                            execPrefix = None):
    """
    Given a directory, dir, in which there may be 
    .pc and .la files lurking, identify the .pc and
    .la files and rewrite them.

    subdir, if present, is the subdirectory to search.
    libPath, if present, is the directory in which the target
     libraries are installed (typically dir/lib)
    includePath, if present, is where the target include
     files are installed (typically dir/include).

    execPrefix is where the package will be installed. 
     This is a bit tricky for us, since we're cross-compiling:
     we will actually define it, by default, to be dir, since
     in practice most packages want this (they use it to locate
     tools, not -rpath-link). But you can set it to whatever
     you like :-)
     
    For the moment, we work by rewriting.

    in a .la file:

    libdir  - gets prefixed with 'dir'
    

    in a .pc file:

    prefix -> dir 
    exec_prefix -> execDir
    libdir -> libPath (if present)
    includedir -> includePath (if present)
    """

    # This is essentially a recursive descent .. 
    stack = [ ]
    
    la_re = re.compile(r"(.*)\.la$")
    pc_re = re.compile(r"(.*)\.pc$")

    base = dir

    if (subdir is not None):
        base = os.path.join(dir, subdir)

    stack.append(base)

    while len(stack) > 0 :
        current = stack.pop()
        
        st_rec = os.lstat(current)
        if (stat.S_ISDIR(st_rec.st_mode)):
            # Bah. Trace it.
            things_here = os.listdir(current)
            for i in things_here:
                stack.append(os.path.join(current, i))

        elif stat.S_ISREG(st_rec.st_mode):
            if (la_re.match(current) is not None):
                # It's a .al file
                print "> Substitute (LA) %s"%current
                subst_la(builder, current, dir, libPath, includePath, execPrefix)
            elif (pc_re.match(current) is not None):
                print "> Substitute (PC) %s"%current
                subst_pc(builder, current, dir, libPath, includePath, execPrefix)
            

    # OK. All done.

               

    








