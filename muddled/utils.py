"""
Muddle utilities.
"""

import string
import re
import os
import os.path
import subprocess
import time
import hashlib
import imp
import xml.dom
import xml.dom.minidom
import traceback

class Error(Exception):
    """
    Used to signal an error from muddle, which should be traced.
    """
    pass

class Failure(Exception):
    """
    Used to signal an error which shouldn't be backtraced
    """
    pass

class Tags:
    """
    Tags commonly used by packages and dependencies
    """
    
    # For checkouts.
    
    CheckedOut = "checked_out"
    Pulled = "pulled"
    UpToDate = "up_to_date"
    ChangesCommitted = "changes_committed"
    ChangesPushed = "changes_pushed"
    
    # For packages

    PreConfig = "preconfig"
    Configured = "configured"
    Built = "built"
    Installed = "installed"
    PostInstalled = "postinstalled"

    Clean = "clean"
    DistClean = "distclean"
    
    # For deployments. These must be independent of each other
    # and transient or deployment will get awfully confused.
    # instructionsapplied is used to separate deployment and
    # instruction application - they need to run in different
    # address spaces so that application can be privileged.
    
    Deployed = "deployed"
    InstructionsApplied = "instructionsapplied"

    # Special tag used to dynamically load extensions
    # (e.g. the build description)

    Loaded = "loaded"

    # Used to denote a temporary label that should never
    # be stored beyond the scope of the current function call
    Temporary = "temporary"

    # Used by the initscripts package to store runtime environments.
    RuntimeEnv = "runtime_env"


class LabelKind:
    """
    What sorts of objects support labels?
    """
    
    Checkout = "checkout"
    Package = "package"
    Deployment = "deployment"
    
    # Synthetic labels used purely to trick the dependency
    # mechanism into doing what I want.
    Synthetic = "synth"
    

def label_kind_to_string(val):
    """
    Convert a label kind to a string. Remember that the
    return value here is used as a directory name for
    tag tracking
    """
    return val

class DirType:
    """
    Provides a uniform vocabulary in which we can talk about
    the types of directory we support.

    CheckOut denotes a source checkout.
    Object   denotes an object directory (one per package)
    Deployed denotes the deployment directory.
    Install  denotes an install directory.
    Builds   denotes the builds directory.
    Root     directly under the root of the build tree

    dict     maps directory names to values.

    """
    CheckOut = 1
    Object = 2
    Deployed = 3
    Install = 4
    Builds = 5
    Root = 6

    
    dict = { "builds" : Builds, 
             "install" : Install, 
             "deployed" : Deployed, 
             "src"  : CheckOut, 
             "obj"  : Object }




def string_cmp(a,b):
    """
    Return -1 if a < b, 0 if a == b,  +1 if a > b 
    """
    if (a is None) and (b is None):
        return 0
    if (a is None):
        return -1
    if (b is None):
        return 1

    if (a < b):
        return -1
    elif (a==b):
        return 0
    else:
        return 1

def find_root(dir):
    """
    Find the build tree root starting at dir
    """
    
    # Normalise so path.split() doesn't produce confusing
    # junk.
    dir = os.path.normcase(os.path.normpath(dir))

    while True:
        # Might this be a tree root?
        if (os.path.exists(os.path.join(dir, ".muddle"))):
            # Yes!
            return dir

        # Else ..
        (up1, basename) = os.path.split(dir)
        if (up1 == dir or dir == '/'):
            # We're done
            break

        dir = up1

    # Didn't find a directory.
    return None


def find_local_packages(dir, root, inv):
    """
    This is slightly horrible because if you're in a source checkout
    (as you normally will be), there could be several packages. 

    @return A list of the package names (or package/role names) involved.
    """

    tloc = find_location_in_tree(dir, root)
    if (tloc is None):
        return None

    (what, loc, role) = tloc

    
    if (what == DirType.CheckOut):
        rv = [  ]
        for p in inv.packages_for_checkout(loc):
            if (p.role is None):
                rv.append(p.name)
            else:
                rv.append("%s{%s}"%(p.name, p.role))
        return rv
    elif (what == DirType.Object):
        if (role is not None):
            return [ "%s{%s}"%(loc, role) ]
        else:
            return [ loc ]
    else:
        return None


def find_location_in_tree(dir, root):
    """
    Find the directory type and name of subdirectory in a repository.
    This is mainly used by find_local_packages to work out which
    packages to rebuild

    @param[in] dir  The directory to analyse
    @param[in] root The root directory.
    @return a pair (DirType, pkg_name, role_name) or None if no information
    can be gained.
    """

    dir = os.path.normcase(os.path.normpath(dir))
    root = os.path.normcase(os.path.normpath(root))
    
    if (dir == root):
        return (DirType.Root, root, None)

    # Dir is (hopefully) a bit like 
    # root / X , so we walk up it  ...
    rest = [ ]
    while dir != '/':
        (base, cur) = os.path.split(dir)
        # Prepend .. 
        rest.insert(0, cur)
        
        if (base == root):
            # Rest is now the rest of the path.
            if (len(rest) == 0):
                # We were at the root
                return (DirType.Root, dir, None)
            else:
                # We weren't
                sub_dir = None

                if (len(rest) > 1):
                    sub_dir = rest[1]
                else:
                    sub_dir = None
                    
                if (rest[0] == "src"):
                    return (DirType.CheckOut, sub_dir, None)
                elif (rest[0] == "obj"):
                    if (len(rest) > 2):
                        role = rest[2]
                    else:
                        role = None
                    
                    return (DirType.Object, sub_dir, role)
                elif (rest[0] == "install"):
                    return (DirType.Install, sub_dir, None)
                else:
                    return None
        else:
            dir = base

    return None

def ensure_dir(dir):
    """
    Ensure that dir exists and is a directory, or throw an error
    """
    if os.path.isdir(dir):
        return True
    elif os.path.exists(dir):
        raise Error("%s exists but is not a directory"%dir)
    else:
        print "> Make directory %s"%dir
        os.makedirs(dir)

def pad_to(str, val, pad_with = " "):
    """
    Pad the given string to the given number of characters with the given string.
    """
    to_pad = (val - len(str)) / len(pad_with)
    arr =  [ str ]
    for i in range(0, to_pad):
        arr.append(pad_with)

    return "".join(arr)


def unix_time():
    """
    Return the current UNIX time since the epoch
    """
    return int(time.time())

def iso_time():
    """
    Retrieve the current time and date in ISO style YYYY-MM-DD HH:MM:SS
    """
    return time.strftime("%Y-%m-%d %H:%M:%S")

def run_cmd(cmd, env = os.environ, allowFailure = False, isSystem = False):
    """
   Run a command via the shell, throwing on failure

   @param isSystem   If True, this is a command being run by the system and
                      failure should be reported with an Error. Else, it's
                      being run on behalf of the user and failure should be
                      reported with Failure.
    """
    print "> %s"%cmd
    rv = subprocess.call(cmd, shell = True, env = env)
    if (not allowFailure) and rv != 0:
        if isSystem:
            raise Error("Command execution failed - %d"%rv)
        else:
            raise Failure("Command exection failed - %d"%rv)

    return rv
                    

def dynamic_load(filename):
    mod = None
    if (filename == None):
        raise Error(\
            "Attempt to call DynamicLoad() with filename None")
    try:
        fin = open(filename, 'rb')
        contents = fin.read()
        hasher = hashlib.md5()
        hasher.update(contents)
        md5_digest = hasher.hexdigest()
        fin.close()

        mod = imp.load_source(md5_digest, filename)
    except Exception, e:
        print "Cannot load %s - %s \n"%(filename,e)
        traceback.print_exc()
        try:
            fin.close()
        except: pass
        raise Failure("Cannot load build description %s - %s"%(filename, e))

    return mod


def maybe_shell_quote(str, doQuote):
    """
    If doQuote is False, do nothing, else shell-quote str
    """
    if doQuote:
        result = [ "\"" ]
        for i in str:
            if i=="\"" or i=="\\":
                result.append("\\")
            result.append(i)
        result.append("\"")

        return "".join(result)
    else:
        return str

def text_in_node(in_xml_node):
    """
    Return all the text in this node.
    """
    in_xml_node.normalize()
    return_list = [ ]
    for c in in_xml_node.childNodes:
        if (c.nodeType == xml.dom.Node.TEXT_NODE):
            return_list.append(c.data)

    return "".join(return_list)


def recursively_remove(a_dir):
    """
    Recursively demove a directory
    """
    if (os.path.exists(a_dir)):
        # Again, the most efficient way to do this is to tell UNIX to do it
        # for us.
        run_cmd("rm -rf \"%s\""%(a_dir))

def copy_file(from_name, to_name, object_exactly = False):
    """
    Just like recursively_copy, only not recursive :-)
    """
    extra_options = ""
    if object_exactly:
        extra_options = "-d"
    run_cmd("cp %s \"%s\" \"%s\""%(extra_options, from_name, to_name))

def recursively_copy(from_dir, to_dir, object_exactly = False):
    """
    Take everything in from_dir and copy it to to_dir, overwriting
    anything that might already be there.

    The easiest way to do this is to make the system do it for us.
    But we need to enumerate the top level to make sure that dotfiles
    get included.

    -p is needed under some special circumstances - specifically,
    when copying as a privileged user.
    
    @param object_exactly  If True, don't dereference symlinks.x
    """
    
    files_in_src = os.listdir(from_dir)

    extra_options = ""
    if (object_exactly):
        extra_options = "d"

    for i in files_in_src:
        run_cmd("cp -rp%sf -t \"%s\" \"%s\""%(extra_options, 
                                              to_dir, os.path.join(from_dir, i)))
            

def split_path_left(in_path):
    """
    Given a path a/b/c .., return a pair
    (a, b/c..) - ie. like os.path.split(), but leftward.

    What we actually do here is to split the path until we have
    nothing left, then take the head and rest of the resulting list.
    """
    
    remains = in_path
    lst = [ ]

    while len(remains) > 0 and remains != "/":
        (a,b) = os.path.split(remains)
        lst.append(b)
        remains = a

    if (remains == "/"):
        lst.append("")

    # Our list is in reverse order, so ..
    lst.reverse()
    rp = lst[1]
    for i in lst[2:]:
        rp = os.path.join(rp, i)

    return (lst[0], rp)
    

def print_string_set(ss):
    """
    Given a string set, return a string representing it.
    """
    result = [ ]
    for s in ss:
        result.append(s)

    return " ".join(result)

def c_escape(v):
    """
    Escape sensitive characters in v.
    """
    
    return re.sub(r'([\r\n"\'\\])', r'\\\1', v)

def replace_root_name(base, replacement, filename):
    """
    Given a filename, a base and a replacement, replace base with replacement
    at the start of filename.    
    """
    #print "replace_root_name %s, %s, %s"%(base,replacement, filename)
    base_len = len(base)
    if (filename.startswith(base)):
        left = replacement + filename[base_len:]
        if len(left) > 1 and left[:2] == '//':
            left = left[1:]
        return left
    else:
        return filename


def parse_mode(in_mode):
    """
    Parse a UNIX mode specification into a pair (clear_bits, set_bits).
    """
    if (in_mode[0] == '0'):
        # It's octal.
        clear_bits = 0777
        set_bits = int(in_mode, 8)

        return (clear_bits, set_bits)
    else:
        # @todo Parse symbolic modes here.
        raise utils.Failure("Unsupported UNIX modespec %s"%in_mode)

def parse_uid(builder, text_uid):
    """
    @todo  One day, we should do something more intelligent than just assuming 
           your uid is numeric
    """
    return int(text_uid)

def parse_gid(builder, text_gid):
    """
    @todo  One day, we should do something more intelligent than just assuming 
           your gid is numeric
    """
    return int(text_gid)
        
    

# End file.
