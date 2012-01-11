"""
Muddle utilities.
"""

import hashlib
import imp
import os
import pwd
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
import errno
import xml.dom
import xml.dom.minidom
from collections import MutableMapping, Mapping, namedtuple
from ConfigParser import RawConfigParser
from StringIO import StringIO

try:
    import curses
except:
    curses = None

class MuddleBug(Exception):
    """
    Use this to indicate that something has gone wrong with muddle itself.

    We thus expect that a traceback will be produced.
    """
    pass

class GiveUp(Exception):
    """
    Use this to indicate that something has gone wrong and we are giving up.

    This is not an error in muddle itself, however, so there is no need for
    a traceback.
    """
    pass

class Unsupported(GiveUp):
    """
    Use this to indicate that an action is unsupported.

    This is used, for instance, when git reports that it will not pull to a
    shallow clone, which is not an error, but the user will want to know.

    This is deliberately a subclass of GiveUp, because it *is* telling muddle
    to give up an operation.
    """
    pass

# Keep the old exception names for the moment, as well
Failure = GiveUp
Error = MuddleBug

# Start with the known label tags. Keys are the "in program" representation,
# values are the tag as used in labels themselves.
__label_tags = {# For checkouts.
                'CheckedOut' : "checked_out",
                'Fetched' : "fetched",
                'Merged' : "merged",
                'ChangesCommitted' : "changes_committed",
                'ChangesPushed' : "changes_pushed",

                # For packages
                'PreConfig' : "preconfig",
                'Configured' : "configured",
                'Built' : "built",
                'Installed' : "installed",
                'PostInstalled' : "postinstalled",

                'Clean' : "clean",
                'DistClean' : "distclean",

                # For deployments. These must be independent of each other and
                # transient or deployment will get awfully confused.
                # instructionsapplied is used to separate deployment and
                # instruction application - they need to run in different
                # address spaces so that application can be privileged.
                'Deployed' : "deployed",
                'InstructionsApplied' : "instructionsapplied",

                # Special tag used to dynamically load extensions
                # (e.g. the build description)
                'Loaded' : "loaded",

                # Used to denote a temporary label that should never
                # be stored beyond the scope of the current function call
                'Temporary' : "temporary",

                # Used by the initscripts package to store runtime environments.
                'RuntimeEnv' : "runtime_env",
                }

# We shall produce a named tuple type using the "in program" names
__label_tag_type = namedtuple('LabelTag',
                              ' '.join(__label_tags.keys()))

# And populate it from the dictionary. This means that we can do things
# like::
#
#    a = LabelTag.CheckedOut
#
# (which we could do if we defined a LabelTag class, with appropriate values),
# but we can also do things like::
#
#    if a in LabelTag:
#       print True
#
LabelTag = __label_tag_type(**__label_tags)

# And, on the same principle, the standard label types
__label_types = {'Checkout' : "checkout",
                 'Package' : "package",
                 'Deployment' : "deployment",

                 # Synthetic labels used purely to trick the dependency
                 # mechanism into doing what I want.
                 'Synthetic' : "synth",
                 }

__label_type_type = namedtuple('LabelType',
                               ' '.join(__label_types.keys()))

LabelType = __label_type_type(**__label_types)

# Sometimes, we want to map a package type to a default tag
# - these are the tags that we want to reach in our rules for each type
package_type_to_tag = {
        LabelType.Checkout   : LabelTag.CheckedOut,
        LabelType.Package    : LabelTag.PostInstalled,
        LabelType.Deployment : LabelTag.Deployed,
        }

# And directory types - i.e., what is the purpose of a particular directory?
# We use a description of the purpose of the directory type as its value,
# and trust to Python to be kind to us
DirTypeDict = {'Checkout'  : 'Checkout directory',
               'Object'    : 'Package object directory',
               'Deployed'  : 'Deployment directory',
               'Install'   : 'Install directory',
               'Root'      : 'Root of the build tree',
               'DomainRoot': 'Root of subdomain',
               'MuddleDir' : '.muddle directory',
               'Versions'  : 'Versions directory',
               'Unexpected': 'An unexpected place',
               }

__directory_type_type = namedtuple('DirType', ' '.join(DirTypeDict.keys()))

# Sometimes the reverse is useful
ReverseDirTypeDict = {}
for key, value in DirTypeDict.items():
    ReverseDirTypeDict[value] = key

DirType = __directory_type_type(**DirTypeDict)

def string_cmp(a,b):
    """
    Return -1 if a < b, 0 if a == b,  +1 if a > b.
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

def mark_as_domain(dir, domain_name):
    """
    Mark the build in 'dir' as a (sub)domain

    This is done by creating a file ``.muddle/am_subdomain``

    'dir' should be the path to the directory contining the sub-build's
    ``.muddle`` directory (the "top" of the sub-build).

    'dir' should thus be of the form "<somewhere>/domains/<domain_name>",
    but we do not check this.

    The given 'domain_name' is written to the file, but this should
    not be particularly trusted - refer to the containing directory
    structure for the canonical domain name.
    """
    file_name = os.path.join(dir, '.muddle', "am_subdomain")
    with open(file_name, "w") as f:
        f.write(domain_name)
        f.write("\n")

def is_subdomain(dir):
    """
    Check if the given 'dir' is a (sub)domain.

    'dir' should be the path to the directory contining the build's
    ``.muddle`` directory (the "top" of the build).

    The build is assumed to be a (sub)domain if there is a file called
    ``.muddle/am_subdomain``.
    """
    file_name = os.path.join(dir, '.muddle', "am_subdomain")
    return os.path.exists(file_name)

def get_domain_name_from(dir):
    """
    Given a directory 'dir', extract the domain name.

    'dir' should not end with a trailing slash.

    It is assumed that 'dir' is of the form "<something>/domains/<domain_name>",
    and we want to return <domain_name>.
    """
    head, domain_name = os.path.split(dir)
    head, should_be_domains = os.path.split(head)
    if should_be_domains == 'domains':
        return domain_name
    else:
        raise MuddleBug("Cannot find domain name for '%s' because it is not"
                    " '<something>/domains/<domain_name>' (unexpected '%s')"%(dir,should_be_domains))


def find_domain(root_dir, dir):
    """
    Find the domain of 'dir'.

    'root_dir' is the root of the (entire) muddle build tree.

    This function basically works backwards through the path of 'dir', until it
    reaches 'root_dir'. As it goes, it assembles the full domain name for the
    domain enclosing 'dir'.

    Returns the domain name, or None if 'dir' is not within a subdomain, and
    the directory of the root of the domain. That is:

        (domain_name, domain_dir)  or  (None, None)
    """

    # Normalise so path.split() doesn't produce confusing junk.
    dir = os.path.normcase(os.path.normpath(dir))

    if not dir.startswith(root_dir):
        raise GiveUp("Directory '%s' is not within muddle build tree '%s'"%(
            dir, root_dir))

    domain_name = None
    domain_dir = None

    # Note that we assume a proper layout of the tree structure
    while dir != root_dir:
        # Might this be a subdomain root?
        if os.path.exists(os.path.join(dir, ".muddle")):
            if is_subdomain(dir):
                new_domain = get_domain_name_from(dir)
                if (domain_name is None):
                    domain_name = new_domain
                else:
                    domain_name = "%s(%s)"%(new_domain,domain_name)

                if domain_dir is None:
                    domain_dir = dir
            else:
                raise GiveUp("Directory '%s' contains a '.muddle' directory,\n"
                        "and is within the build tree at '%s'\n"
                        "but is marked as a subdomain"%(dir, root_dir))
        dir, tail = os.path.split(dir)

    return (domain_name, domain_dir)

def find_root_and_domain(dir):
    """
    Find the build tree root containing 'dir', and find the domain of 'dir'.

    This function basically works backwards through the path of 'dir', until it
    finds a directory containing a '.muddle/' directory, that is not within a
    subdomain. As it goes, it assembles the full domain name for the domain
    enclosing 'dir'.

    Returns a pair (root_dir, current_domain).

    If 'dir' is not within a subdomain, then 'current_domain' will be None.

    If 'dir' is not within a muddle build tree, then 'root_dir' will also
    be None.
    """

    # Normalise so path.split() doesn't produce confusing junk.
    dir = os.path.normcase(os.path.normpath(dir))
    current_domain = None

    while True:
        # Might this be a tree root?
        if os.path.exists(os.path.join(dir, ".muddle")):
            if is_subdomain(dir):
                new_domain = get_domain_name_from(dir)

                if (current_domain is None):
                    current_domain = new_domain
                else:
                    current_domain = "%s(%s)"%(new_domain,current_domain)
            else:
                return (dir, current_domain)

        up1, basename = os.path.split(dir)
        if up1 == dir or dir == '/':    # We're done
            break

        dir = up1

    # Didn't find a directory.
    return (None, None)


def ensure_dir(dir, verbose=True):
    """
    Ensure that dir exists and is a directory, or throw an error.
    """
    if os.path.isdir(dir):
        return True
    elif os.path.exists(dir):
        raise MuddleBug("%s exists but is not a directory"%dir)
    else:
        if verbose:
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
    Return the current UNIX time since the epoch.
    """
    return int(time.time())

def iso_time():
    """
    Retrieve the current time and date in ISO style ``YYYY-MM-DD HH:MM:SS``.
    """
    return time.strftime("%Y-%m-%d %H:%M:%S")

def current_user():
    """
    Return the identity of the current user, as an email address if possible,
    but otherwise as a UNIX uid
    """
    uid = os.getuid()
    a_pwd = pwd.getpwuid(uid)
    if (a_pwd is not None):
        return a_pwd.pw_name
    else:
        return None

def current_machine_name():
    """
    Return the identity of the current machine - possibly including the
    domain name, possibly not
    """
    return socket.gethostname()

def page_text(progname, text):
    """
    Try paging 'text' by piping it through 'progname'.

    Looks for 'progname' on the PATH, and if os.environ['PATH'] doesn't exist,
    tries looking for it on os.defpath.

    If an executable version of 'progname' can't be found, just prints the
    text out.

    If 'progname' is None (or an empty string, or otherwise false), then
    just print 'text'.
    """
    if progname:
        path = os.environ.get('PATH', os.defpath)
        path = path.split(os.pathsep)
        for locn in path:
            locn = normalise_dir(locn)
            prog = os.path.join(locn, progname)
            if os.path.exists(prog):
                try:
                    proc = subprocess.Popen([prog],
                                            stdin=subprocess.PIPE,
                                            stderr=subprocess.STDOUT)
                    proc.communicate(text)
                    return
                except OSError:
                    # We're not allowed to run it, or some other problem,
                    # so look for another candidate
                    continue
    print text

def run_cmd_for_output(cmd_array, env = None, useShell = False, verbose = True):
    """
    Run a command and return a tuple (return value, stdour output, stderr output).
    """
    a_process = subprocess.Popen(cmd_array, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 shell = useShell)
    (out, err) = a_process.communicate()
    return (a_process.wait(), out, err)


def run_cmd(cmd, env=None, allowFailure=False, isSystem=False, verbose=True):
    """
    Run a command via the shell, raising an exception on failure,

    * env is the environment to use when running the command.  If this is None,
      then ``os.environ`` is used.
    * if allowFailure is true, then failure of the command will be ignored.
    * otherwise, isSystem is used to decide what to do if the command fails.
      If isSystem is true, then this is a command being run by the system and
      failure should be reported by raising utils.MuddleBug. otherwise, it's being
      run on behalf of the user and failure should be reported by raising
      utils.GiveUp.
    * if verbose is true, then print out the command before executing it

    The command's stdout and stderr are redirected through Python's sys.stdout
    and sys.stderr respectively.

    Return the exit code of this command.
    """
    if env is None: # so, for instance, an empty dictionary is allowed
        env = os.environ
    if verbose:
        print "> %s"%cmd
    rv = subprocess.call(cmd, shell=True, env=env, stdout=sys.stdout, stderr=subprocess.STDOUT)
    if allowFailure or rv == 0:
        return rv
    else:
        if isSystem:
            raise MuddleBug("Command '%s' execution failed - %d"%(cmd,rv))
        else:
            raise GiveUp("Command '%s' execution failed - %d"%(cmd,rv))


def get_cmd_data(cmd, env=None, isSystem=False, fold_stderr=True,
                 verbose=False, fail_nonzero=True):
    """
    Run the given command, and return its (returncode, stdout, stderr).

    If 'fold_stderr', then "fold" stderr into stdout, and return
    (returncode, stdout_data, NONE).

    If 'fail_nonzero' then if the return code is non-0, raise an explanatory
    exception (MuddleBug is 'isSystem', otherwise GiveUp).

    And yes, that means the default use-case returns a tuple of the form
    (0, <string>, None), but otherwise it gets rather awkward handling all
    the options.
    """
    if env is None:
        env = os.environ
    if verbose:
        print "> %s"%cmd
    p = subprocess.Popen(cmd, shell=True, env=env,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT if fold_stderr
                                                  else subprocess.PIPE)
    stdoutdata, stderrdata = p.communicate()
    returncode = p.returncode
    if fail_nonzero and returncode:
        if isSystem:
            raise MuddleBug("Command '%s' execution failed - %d"%(cmd,returncode))
        else:
            raise GiveUp("Command '%s' execution failed - %d"%(cmd,returncode))
    return returncode, stdoutdata, stderrdata


def indent(text, indent):
    """Return the text indented with the 'indent' string.

    (i.e., place 'indent' in front of each line of text).
    """
    lines = text.split('\n')
    stuff = []
    for line in lines:
        stuff.append('%s%s'%(indent,line))
    return '\n'.join(stuff)

def wrap(text, width=None, **kwargs):
    """A convenience wrapper around textwrap.wrap()

    (basically because muddled users will have imported utils already).
    """
    if not width:
        width = num_cols()

    return "\n".join(textwrap.wrap(text, width=width, **kwargs))

def num_cols():
    """How many columns on our terminal?

    If it can't tell (e.g., because it curses is not available), returns 70.
    """
    if curses:
        curses.setupterm()
        cols = curses.tigetnum('cols')
        if cols <= 0:
            return 70
        else:
            return cols
    else:
        return 70

def truncate(text, columns=None, less=0):
    """Truncate the given text to fit the terminal.

    More specifically:

    1. Split on newlines
    2. If the first line is too long, cut it and add '...' to the end.
    3. Return the first line

    If 'columns' is 0, then don't do the truncation of the first line.

    If 'columns' is None, then try to work out the current terminal width
    (using "curses"), and otherwise use 80.

    If 'less' is specified, then the actual width used will be the calculated
    or given width, minus 'less' (so if columns=80 and less=2, then the maximum
    line length would be 78). Clearly this is ignored if 'columns' is 0.
    """
    text = text.split('\n')[0]
    if columns == 0:
        return text

    if columns is None:
        columns = num_cols()
    max_width = columns - less
    if len(text) > max_width:
        text = text[:max_width-3]+'...'
    return text


def dynamic_load(filename):
    if (filename == None):
        raise MuddleBug(\
            "Attempt to call DynamicLoad() with filename None")
    try:
        with open(filename, 'rb') as fin:
            contents = fin.read()
        hasher = hashlib.md5()
        hasher.update(contents)
        md5_digest = hasher.hexdigest()
        return imp.load_source(md5_digest, filename)
    except Exception:
        raise GiveUp("Cannot load build description %s:\n"
                       "%s"%(filename, traceback.format_exc()))

def do_shell_quote(str):
    return maybe_shell_quote(str, True)

def maybe_shell_quote(str, doQuote):
    """
    If doQuote is False, do nothing, else shell-quote ``str``.

    Annoyingly, shell quoting things correctly must use backslashes, since
    quotes can (and will) be misinterpreted. Bah.

    NB: Despite the name, this is actually "escaping", rather then "quoting".
    Specifically, any single quote, double quote or backslash characters in
    the original string will be converted to a backslash followed by the
    original character, in the final string.
    """
    if doQuote:
        result = []
        for i in str:
            if i=='"' or i=="\\" or i=="'" or i==" ":
                result.append("\\")
            result.append(i)
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
    Recursively demove a directory.
    """
    if (os.path.exists(a_dir)):
        # Again, the most efficient way to do this is to tell UNIX to do it
        # for us.
        run_cmd("rm -rf \"%s\""%(a_dir))


def copy_file_metadata(from_path, to_path):
    """
    Copy file metadata.

    If 'to_path' is a link, then it tries to copy whatever it can from
    'from_path', treated as a link.

    If 'to_path' is not a link, then it copies from 'from_path', or, if
    'from_path' is a link, whatever 'from_path' references.

    Metadata is: mode bits, atime, mtime, flags and (if the process has an
    effective UID of 0) the ownership (uid and gid).
    """

    if os.path.islink(to_path):
        st = os.lstat(from_path)

        if hasattr(os, 'lchmod'):
            mode = stat.S_IMODE(st.st_mode)
            os.lchmod(to_path, mode)

        if hasattr(os, 'lchflags'):
            os.lchflags(to_path, st.st_flags)

        if os.geteuid() == 0 and hasattr(os, 'lchown'):
            os.lchown(to_path, st.st_uid, st.st_gid)
    else:
        st = os.stat(from_path)
        mode = stat.S_IMODE(st.st_mode)
        os.chmod(to_path, mode)
        os.utime(to_path, (st.st_atime, st.st_mtime))
        if hasattr(os, 'chflags'):
            os.chflags(to_path, st.st_flags)
        if os.geteuid() == 0:
            os.chown(to_path, st.st_uid, st.st_gid)

def copy_file(from_path, to_path, object_exactly=False, preserve=False, force=False):
    """
    Copy a file (either a "proper" file, not a directory, or a symbolic link).

    Just like recursively_copy, only not recursive :-)

    If the target file already exists, it is overwritten.

       Caveat: if the target file is a directory, it will not be overwritten.
       If the source file is a link, being copied as a link, and the target
       file is not a link, it will not be overwritten.

    If 'object_exactly' is true, then if 'from_path' is a symbolic link, it
    will be copied as a link, otherwise the referenced file will be copied.

    If 'preserve' is true, then the file's mode, ownership and timestamp will
    be copied, if possible. Note that on Un*x file ownership can only be copied
    if the process is running as 'root' (or within 'sudo').

    If 'force' is true, then if a target file is not writeable, try removing it
    and then copying it.
    """

    if object_exactly and os.path.islink(from_path):
        linkto = os.readlink(from_path)
        if os.path.islink(to_path):
            os.remove(to_path)
        os.symlink(linkto, to_path)
    else:
        try:
            shutil.copyfile(from_path, to_path)
        except IOError as e:
            if force and e.errno == errno.EACCES:
                os.remove(to_path)
                shutil.copyfile(from_path, to_path)
            else:
                raise

    if preserve:
        copy_file_metadata(from_path, to_path)

def recursively_copy(from_dir, to_dir, object_exactly=False, preserve=True, force=False):
    """
    Take everything in from_dir and copy it to to_dir, overwriting
    anything that might already be there.

    Dot files are included in the copying.

    If object_exactly is true, then symbolic links will be copied as links,
    otherwise the referenced file will be copied.

    If preserve is true, then the file's mode, ownership and timestamp will be
    copied, if possible. This is only really useful when copying as a
    privileged user.

    If 'force' is true, then if a target file is not writeable, try removing it
    and then copying it.
    """

    copy_without(from_dir, to_dir, object_exactly=object_exactly,
                 preserve=preserve, force=force)


def split_path_left(in_path):
    """
    Given a path ``a/b/c ...``, return a pair
    ``(a, b/c..)`` - ie. like ``os.path.split()``, but leftward.

    What we actually do here is to split the path until we have
    nothing left, then take the head and rest of the resulting list.

    For instance:

        >>> split_path_left('a/b/c')
        ('a', 'b/c')
        >>> split_path_left('a/b')
        ('a', 'b')

    For a single element, behave in sympathy (but, of course, reversed) to
    ``os.path.split``:

        >>> import os
        >>> os.path.split('a')
        ('', 'a')
        >>> split_path_left('a')
        ('a', '')

    The empty string isn't really a sensible input, but we cope:

        >>> split_path_left('')
        ('', '')

    And we take some care with delimiters (hopefully the right sort of care):

        >>> split_path_left('/a///b/c')
        ('', 'a/b/c')
        >>> split_path_left('//a/b/c')
        ('', 'a/b/c')
        >>> split_path_left('///a/b/c')
        ('', 'a/b/c')

    """

    if not in_path:
        return ('', '')

    # Remove redundant sequences of '//'
    # This reduces paths like '///a//b/c' to '/a/b/c', but unfortunately
    # it leaves '//a/b/c' untouched
    in_path = os.path.normpath(in_path)

    remains = in_path
    lst = [ ]

    while remains and remains not in ("/", "//"):
        remains, end = os.path.split(remains)
        lst.append(end)

    if remains in ("/", "//"):
        lst.append("")

    # Our list is in reverse order, so ..
    lst.reverse()

    if False:
        rp = lst[1]
        for i in lst[2:]:
            rp = os.path.join(rp, i)
    else:
        if len(lst) > 1:
            rp = os.path.join(*lst[1:])
        else:
            rp = ""

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

    # Annoyingly, people do write modes as '6755' etc..
    if (in_mode[0] >= '0' and in_mode[0] <= '9'):
        # It's octal.
        clear_bits = 07777
        set_bits = int(in_mode, 8)

        return (clear_bits, set_bits)
    else:
        # @todo Parse symbolic modes here.
        raise GiveUp("Unsupported UNIX modespec %s"%in_mode)

def parse_uid(builder, text_uid):
    """
    .. todo::  One day, we should do something more intelligent than just assuming
               your uid is numeric
    """
    return int(text_uid)

def parse_gid(builder, text_gid):
    """
    .. todo::  One day, we should do something more intelligent than just assuming
               your gid is numeric
    """
    return int(text_gid)


def xml_elem_with_child(doc, elem_name, child_text):
    """
    Return an element 'elem_name' containing the text child_text in doc.
    """
    el = doc.createElement(elem_name)
    el.appendChild(doc.createTextNode(child_text))
    return el


def _copy_without(src, dst, ignored_names, object_exactly, preserve, force):
    """
    The insides of copy_without. See that for more documentation.

    'ignored_names' must be a sequence of filenames to ignore (but may be empty).
    """

    # Inspired by the example for shutil.copytree in the Python 2.6 documentation

    names = os.listdir(src)

    if True:
        ensure_dir(dst, verbose=False)
    else:
        if not os.path.exists(dst):
            os.makedirs(dst)

    for name in names:
        if name in ignored_names:
            continue

        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        try:
            if object_exactly and os.path.islink(srcname):
                copy_file(srcname, dstname, object_exactly=True, preserve=preserve)
            elif os.path.isdir(srcname):
                _copy_without(srcname, dstname, ignored_names=ignored_names,
                              object_exactly=object_exactly, preserve=preserve,
                              force=force)
            else:
                copy_file(srcname, dstname, object_exactly=object_exactly,
                          preserve=preserve, force=force)
        except (IOError, os.error), why:
            raise GiveUp('Unable to copy %s to %s: %s'%(srcname, dstname, why))

    try:
        copy_file_metadata(src, dst)
    except OSError, why:
        raise GiveUp('Unable to copy properties of %s to %s: %s'%(src, dst, why))

def copy_without(src, dst, without=None, object_exactly=True, preserve=False, force=False):
    """
    Copy files from the 'src' directory to the 'dst' directory, without those in 'without'

    If given, 'without' should be a sequence of filenames - for instance,
    ['.bzr', '.svn'].

    If 'object_exactly' is true, then symbolic links will be copied as links,
    otherwise the referenced file will be copied.

    If 'preserve' is true, then the file's mode, ownership and timestamp will
    be copied, if possible. Note that on Un*x file ownership can only be copied
    if the process is running as 'root' (or within 'sudo').

    If 'force' is true, then if a target file is not writeable, try removing it
    and then copying it.

    Creates directories in the destination, if necessary.

    Uses copy_file() to copy each file.
    """

    if without is not None:
        ignored_names = without
    else:
        ignored_names = set()

    print 'Copying %s to %s'%(src, dst),
    if without:
        print 'ignoring %s'%without
    print

    _copy_without(src, dst, ignored_names, object_exactly, preserve, force)

def copy_name_list_with_dirs(file_list, old_root, new_root,
                             object_exactly = True, preserve = False):
    """

    Given file_list, create file_list[new_root/old_root], creating
    any directories you need on the way.

    file_list is a list of full path names.
    old_root is the old root directory
    new_root is where we want them copied
    """
    for f in file_list:
        tgt_name = replace_root_name(old_root, new_root, f)
        target_dir = os.path.dirname(tgt_name)
        ensure_dir(target_dir)
        copy_file(f, tgt_name, object_exactly, preserve)


def get_prefix_pair(prefix_one, value_one, prefix_two, value_two):
    """
    Returns a pair (prefix_onevalue_one, prefix_twovalue_two) - used
    by rrw.py as a utility function
    """
    return ("%s%s"%(prefix_one, value_one), "%s%s"%(prefix_two, value_two))

def rel_join(vroot, path):
    """
    Find what path would be called if it existed inside vroot. Differs from
    os.path.join() in that if path contains a leading '/', it is not
    assumed to override vroot.

    If vroot is none, we just return path.
    """

    if (vroot is None):
        return path

    if (len(path) == 0):
        return vroot

    if path[0] == '/':
        path = path[1:]

    return os.path.join(vroot, path)


def split_domain(domain_name):
    """
    Given a domain name, return a tuple of the hierarchy of sub-domains.

    For instance:

        >>> split_domain('a')
        ['a']
        >>> split_domain('a(b)')
        ['a', 'b']
        >>> split_domain('a(b(c))')
        ['a', 'b', 'c']
        >>> split_domain('a(b(c)')
        Traceback (most recent call last):
        ...
        GiveUp: Domain name "a(b(c)" has mis-matched parentheses

    We don't actually allow "sibling" sub-domains, so we try to complain
    helpfully:

        >>> split_domain('a(b(c)(d))')
        Traceback (most recent call last):
        ...
        GiveUp: Domain name "a(b(c)(d))" has 'sibling' sub-domains

    """

    if '(' not in domain_name:
        return [domain_name]

    if ')(' in domain_name:
        raise GiveUp('Domain name "%s" has '
                      "'sibling' sub-domains"%domain_name)

    parts = domain_name.split('(')

    num_closing = len(parts) - 1
    if not parts[-1].endswith( num_closing * ')' ):
        raise GiveUp('Domain name "%s" has mis-matched parentheses'%domain_name)

    parts[-1] = parts[-1][:- num_closing]
    return parts

def domain_subpath(domain_name):
    """Calculate the sub-path for a given domain name.

    For instance:

        >>> domain_subpath('a')
        'domains/a'
        >>> domain_subpath('a(b)')
        'domains/a/domains/b'
        >>> domain_subpath('a(b(c))')
        'domains/a/domains/b/domains/c'
        >>> domain_subpath('a(b(c)')
        Traceback (most recent call last):
        ...
        GiveUp: Domain name "a(b(c)" has mis-matched parentheses

    """
    if domain_name is None:
        return ''

    parts = []
    for thing in split_domain(domain_name):
        parts.append('domains')
        parts.append(thing)

    return os.path.join(*parts)


gArchName = None

def arch_name():
    """
    Retrieve the name of the architecture on which we're running.
    Some builds require packages to be built on a particular (odd) architecture.
    """
    global gArchName

    if (gArchName is None):
        # This is what the docs say you should do. Ugh.
        x = subprocess.Popen(["uname", "-m"], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE).communicate()[0]
        gArchName = x.strip()

    return gArchName


def unescape_backslashes(str):
    """
    Replace every string '\\X' with X, as if you were a shell
    """

    wasBackslash = False
    result = [ ]
    for i in str:
        if (wasBackslash):
            result.append(i)
            wasBackslash = False
        else:
            if (i == '\\'):
                wasBackslash = True
            else:
                result.append(i)

    return "".join(result)



def quote_list(lst):
    """
    Given a list, quote each element of it and return them, space separated
    """
    return " ".join(map(do_shell_quote, lst))


def unquote_list(lst):
    """
    Given a list of objects, potentially enclosed in quotation marks or other
    shell weirdness, return a list of the actual objects.
    """

    # OK. First, dispose of any enclosing quotes.
    result = [ ]
    lst = lst.strip()
    if (lst[0] == '\'' or lst[0] == "\""):
        lst = lst[1:-1]

    initial = lst.split(' ')
    last = None

    for i in initial:
        if (last is not None):
            last = last + i
        else:
            last = i

        # If last ended in a backslash, round again
        if (len(last) > 0 and last[-1] == '\\'):
            last = last[:-1]
            continue

        # Otherwise, dump it, unescaping everything else
        # as we do so
        result.append(unescape_backslashes(last))
        last = None

    if (last is not None):
        result.append(unescape_backslashes(last))

    return result

def find_by_predicate(source_dir, accept_fn, links_are_symbolic = True):
    """
    Given a source directory and an acceptance function
     fn(source_base, file_name) -> result

    Obtain a list of [result] if result is not None.
    """

    result = [ ]

    r = accept_fn(source_dir)
    if (r is not None):
        result.append(r)


    if (links_are_symbolic and os.path.islink(source_dir)):
        # Bah
        return result

    if (os.path.isdir(source_dir)):
        # We may need to recurse...
        names = os.listdir(source_dir)

        for name in names:
            full_name = os.path.join(source_dir, name)
            r = accept_fn(full_name)
            if (r is not None):
                result.append(r)

            # os.listdir() doesn't return . and ..
            if (os.path.isdir(full_name)):
                result.extend(find_by_predicate(full_name, accept_fn, links_are_symbolic))

    return result

class MuddleSortedDict(MutableMapping):
    """
    A simple dictionary-like class that returns keys in sorted order.
    """
    def __init__(self):
        self._keys = set()
        self._dict = {}

    def __setitem__(self, key, value):
        self._dict[key] = value
        self._keys.add(key)

    def __getitem__(self, key):
        return self._dict[key]

    def __delitem__(self, key):
        del self._dict[key]
        self._keys.discard(key)

    def __len__(self):
        return len(self._keys)

    def __contains__(self, key):
        return key in self._dict

    def __iter__(self):
        keys = list(self._keys)
        keys.sort()
        return iter(keys)

class MuddleOrderedDict(MutableMapping):
    """
    A simple dictionary-like class that returns keys in order of (first)
    insertion.
    """
    def __init__(self):
        self._keys = []
        self._dict = {}

    def __setitem__(self, key, value):
        if key not in self._dict:
            self._keys.append(key)
        self._dict[key] = value

    def __getitem__(self, key):
        return self._dict[key]

    def __delitem__(self, key):
        del self._dict[key]
        self._keys.remove(key)

    def __len__(self):
        return len(self._keys)

    def __contains__(self, key):
        return key in self._dict

    def __iter__(self):
        return iter(self._keys)

def calc_file_hash(filename):
    """Calculate and return the SHA1 hash for the named file.
    """
    with HashFile(filename) as fd:
        for line in fd:
            pass
    return fd.hash()

class HashFile(object):
    """
    A very simple class for handling files and calculating their SHA1 hash.

    We support a subset of the normal file class, but as lines are read
    or written, we calculate a SHA1 hash for the file.
    """

    def __init__(self, name, mode='r'):
        """
        Open the file, for read or write.
        """
        if mode not in ('r', 'w'):
            raise ValueError("HashFile 'mode' must be one of 'r' or 'w', not '%s'"%mode)
        self.name = name
        self.mode = mode
        self.fd = open(name, mode)
        self.sha = hashlib.sha1()

    def write(self, text):
        r"""
        Write the give text to the file, and add it to the SHA1 hash as well.

        As is normal for file writes, the '\n' at the end of a line must be
        specified.
        """
        if self.mode != 'w':
            raise MuddleBug("Cannot write to HashFile '%s', opened for read"%self.name)
        self.fd.write(text)
        self.sha.update(text)

    def readline(self):
        """
        Read the next line from the file, and add it to the SHA1 hash as well.

        Returns '' if there is no next line (i.e., EOF is reached).
        """
        if self.mode != 'r':
            raise MuddleBug("Cannot read from HashFile '%s', opened for write"%self.name)
        text = self.fd.readline()

        if text == '':
            return ''
        else:
            self.sha.update(text)
            return text

    def hash(self):
        """
        Return the SHA1 hash, calculated from the lines so far, as a hex string.
        """
        return self.sha.hexdigest()

    def close(self):
        """
        Close the file.
        """
        self.fd.close()

    # Support for "with"
    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        if tb is None:
            # No exception, so just finish normally
            self.close()
        else:
            # An exception occurred, so do any tidying up necessary
            # - well, there isn't anything special to do, really
            self.close()
            # And allow the exception to be re-raised
            return False

    # Support for iteration (over lines)
    def __iter__(self):
        if self.mode != 'r':
            raise MuddleBug("Cannot iterate over HashFile '%s', opened for write"%self.name)
        return self

    def next(self):
        text = self.readline()
        if text == '':
            raise StopIteration
        else:
            return text

DomainTuple = namedtuple('DomainTuple', 'name repository description')
CheckoutTuple = namedtuple('CheckoutTuple', 'name repo rev rel dir domain co_leaf branch')

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

        * 'checkouts' is a list of named tuples (specifically, CheckoutTuple)
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
        description = src/builds/01.py
        repository = Somewhere
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
        CheckoutTuple(name='jim', repo='Elsewhere', rev=7, rel=None, dir='jim', domain=None, co_leaf='sheila', branch=None)

    Note that this is *not* intended to be a mutable class, so please do not
    change any of its internals directly. In particular, if you *did* change
    the checkouts sequence, you would definitely need to remember to update
    the checkouts dictionary, and vice versa. And you would need to remember
    that the checkouts list is composed of CheckoutTuples, and the domains
    list of DomainTuples, or otherwise stuff would go wrong.
    """

    MAX_PROBLEM_LEN = 100               # At what length to truncate problems

    def __init__(self, repository=None, description=None,
                 domains=None, checkouts=None, problems=None):
        if repository is None:
            self.repository = ''
        else:
            self.repository = repository

        if description is None:
            self.description = ''
        else:
            self.description = description

        self.domains = set()
        if domains:
            for x in domains:
                self.domains.add(DomainTuple(*x))

        self.checkouts = []
        if checkouts:
            for x in checkouts:
                self.checkouts.append(CheckoutTuple(*x))

        if problems is None:
            self.problems = []
        else:
            self.problems = problems

        self._update_checkout_dict()

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

    def write_to_file(self, filename):
        """Write our data out to a file.

        Returns the SHA1 hash for the file.
        """
        with HashFile(filename, 'w') as fd:
            self.write_to_file_object(fd)
            return fd.hash()

    def write_to_file_object(self, fd):
        """Write our data out to a file-like object (one with a 'write' method).

        Returns the SHA1 hash for the file.
        """
        # The following makes sure we write the [ROOT] out first, otherwise
        # things will come out in some random order (because that's how a
        # dictionary works, and that's what its using)
        config = RawConfigParser()
        config.add_section("ROOT")
        config.set("ROOT", "repository", self.repository)
        config.set("ROOT", "description", self.description)
        config.write(fd)

        if self.domains:
            config = RawConfigParser(None, dict_type=MuddleSortedDict)
            for domain_name, domain_repo, domain_desc in self.domains:
                section = "DOMAIN %s"%domain_name
                config.add_section(section)
                config.set(section, "name", domain_name)
                config.set(section, "repository", domain_repo)
                config.set(section, "description", domain_desc)
            config.write(fd)

        config = RawConfigParser(None, dict_type=MuddleSortedDict)
        for name, repo, rev, rel, dir, domain, co_leaf, branch in self.checkouts:
            if domain:
                section = 'CHECKOUT (%s)%s'%(domain,name)
            else:
                section = 'CHECKOUT %s'%name
            config.add_section(section)
            if domain:
                config.set(section, "domain", domain)
            config.set(section, "name", name)
            config.set(section, "repository", repo)
            config.set(section, "revision", rev)
            if co_leaf:
                config.set(section, "co_leaf", co_leaf)
            if rel:
                config.set(section, "relative", rel)
            if dir:
                config.set(section, "directory", dir)
            if branch:
                config.set(section, "branch", branch)
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
                    stamp.domains.add(DomainTuple(domain_name, domain_repo, domain_desc))

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
                # - the repository path relative to the base URL, the Repository prefix
                # - the checkout leaf directory (if not the same as the checkout name)
                # - the branch checked out
                #
                # XXX For the new Repository mechanism, we also need to add:
                #
                # - inner_path
                # - prefix_as_is
                # - suffix
                # - handler
                revisions[label] = ('%s+%s'%(vcs.repo.vcs, vcs.repo.base_url),
                                    vcs.checkout_dir,
                                    rev,
                                    vcs.repo.prefix,
                                    vcs.checkout_leaf,
                                    vcs.repo.branch)
            except GiveUp as exc:
                print exc
                stamp.problems.append(str(exc))

        if stamp.domains and not quiet:
            print 'Found domains:',stamp.domains

        for label, (repo, dir, rev, rel, co_leaf, branch) in revisions.items():
            stamp.checkouts.append(CheckoutTuple(label.name, repo, rev, rel, dir,
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

        stamp.repository = config.get("ROOT", "repository")
        stamp.description = config.get("ROOT", "description")

        sections = config.sections()
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
                name = config.get(section, 'name')
                repo = config.get(section, 'repository')
                rev = config.get(section, 'revision')
                if config.has_option(section, "relative"):
                    rel = config.get(section, 'relative')
                else:
                    rel = None
                if config.has_option(section, "directory"):
                    dir = config.get(section, 'directory')
                else:
                    dir = None
                if config.has_option(section, "domain"):
                    domain = config.get(section, 'domain')
                else:
                    domain = None
                if config.has_option(section, "co_leaf"):
                    co_leaf = config.get(section, "co_leaf")
                else:
                    co_leaf = name  # NB: this is deliberate - see the unstamp command
                if config.has_option(section, "branch"):
                    branch = config.get(section, 'branch')
                else:
                    branch = None
                stamp.checkouts.append(CheckoutTuple(name, repo, rev, rel, dir,
                                                     domain, co_leaf, branch))
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

def normalise_dir(dir):
    dir = os.path.expanduser(dir)
    dir = os.path.abspath(dir)
    return dir

class Directory(object):
    """A class to facilitate pushd/popd behaviour

    It is intended for use with 'with', as in::

        with Directory('~'):
            print 'My home directory contains'
            print ' ',' '.join(os.listdir('.'))

    or::

        with Directory('fred') as d:
            print 'In directory', d.where

    If 'stay_on_error' is true, then the directory will not be left ("popd"
    will not be done) if an exception occurs in its 'with' clause.

    If 'show_pushd' is true, then a message will be printed out showing the
    directory that is being 'cd'ed into.

    If 'show_popd' is true, then a message will be printed out showing the
    directory that is being returned to. An extra "wrapper" message for any
    exception being propagated out will also be shown.

    If 'set_PWD' is true, then set the os.environ['PWD'] to the directory
    that is being "cd"ed into. This emulates the behaviour of "cd" in bash.
    Checking the value of PWD is often used to find out what directory the
    user thinks they are in, especially in the presence of soft links in
    directory trees.
    """
    def __init__(self, where, stay_on_error=False, show_pushd=True,
                 show_popd=False, set_PWD=True):
        self.start = normalise_dir(os.getcwd())
        self.where = normalise_dir(where)
        self.close_on_error = not stay_on_error
        self.show_pushd = show_pushd
        self.show_popd = show_popd
        self.set_PWD = set_PWD
        try:
            os.chdir(self.where)
        except OSError as e:
            raise GiveUp('Cannot change to directory %s: %s\n'%(where, e))

        if set_PWD:
            if 'PWD' in os.environ:
                self.got_old_PWD = True
                self.old_PWD = os.environ['PWD']
            else:
                self.got_old_PWD = False
                self.old_PWD = None
            os.environ['PWD'] = self.where

        if show_pushd:
            print '++ pushd to %s'%self.where

    def join(self, *args):
        """Return os.path.join(self.where, *args).
        """
        return os.path.join(self.where, *args)

    def close(self):
        os.chdir(self.start)

        if self.set_PWD:
            if self.got_old_PWD:
                os.environ['PWD'] = self.old_PWD
            else:
                del os.environ['PWD']

        if self.show_popd:
            print '++ popd to  %s'%self.start

    def __enter__(self):
        return self

    def __exit__(self, etype, value, tb):
        if tb is None:
            # No exception, so just finish normally
            self.close()
        else:
            # An exception occurred, so do any tidying up necessary
            if self.show_popd:
                print '** Oops, an exception occurred - %s tidying up'%self.__class__.__name__
            # well, there isn't anything special to do, really
            if self.close_on_error:
                self.close()
            if self.show_popd:
                print '** ----------------------------------------------------------------------'
            # And allow the exception to be re-raised
            return False

class NewDirectory(Directory):
    """A pushd/popd directory that gets created first.

    It is an error if the directory already exists, and a MuddleBug exception
    will be raised.

    If 'where' is None, then tempfile.mkdtemp() will be used to create the
    directory, and 'self.where' will be set to its path.

    If 'stay_on_error' is True, then the directory will not be left ("popd"
    will not be done) if an exception occurs in its 'with' clause.

    If 'show_pushd' is true, then a message will be printed out showing the
    directory that is being 'cd'ed into.

    If 'show_popd' is true, then a message will be printed out showing the
    directory that is being returned to. An extra "wrapper" message for any
    exception being propagated out will also be shown.

    If 'set_PWD' is true, then set the os.environ['PWD'] to the directory
    that is being "cd"ed into. This emulates the behaviour of "cd" in bash.
    Checking the value of PWD is often used to find out what directory the
    user thinks they are in, especially in the presence of soft links in
    directory trees.

    If 'show_dirops' is true, then a message will be printed out showing the
    'mkdir' command used to create the new directory.
    """
    def __init__(self, where, stay_on_error=False, show_pushd=True,
                 show_popd=False, set_PWD=True, show_dirops=True):
        self.show_dirops = show_dirops
        if where is None:
            where = tempfile.mkdtemp()
            if show_dirops:     # Obviously, this is a bit of a bluff
                # The extra spaces are to line up with 'pushd to'
                print '++ mkdir    %s'%where
        else:
            where = normalise_dir(where)
            if os.path.exists(where):
                raise MuddleBug('Directory %s already exists'%where)
            if show_dirops:
                # The extra spaces are to line up with 'pushd to'
                print '++ mkdir    %s'%where
            os.makedirs(where)
        super(NewDirectory, self).__init__(where, stay_on_error, show_pushd,
                                           show_popd, set_PWD)

class TransientDirectory(NewDirectory):
    """A pushd/popd directory that gets created first and deleted afterwards

    It is an error if the directory already exists, and a MuddleBug exception
    will be raised.

    If 'where' is None, then tempfile.mkdtemp() will be used to create the
    directory, and 'self.where' will be set to its path.

    If 'stay_on_error' is True, then the directory will not be left ("popd"
    will not be done) if an exception occurs in its 'with' clause.

    If 'keep_on_error' is True, then the directory will not be deleted
    if an exception occurs in its 'with' clause.

    If 'show_pushd' is true, then a message will be printed out showing the
    directory that is being 'cd'ed into.

    If 'show_popd' is true, then a message will be printed out showing the
    directory that is being returned to. An extra "wrapper" message for any
    exception being propagated out will also be shown.

    If 'set_PWD' is true, then set the os.environ['PWD'] to the directory
    that is being "cd"ed into. This emulates the behaviour of "cd" in bash.
    Checking the value of PWD is often used to find out what directory the
    user thinks they are in, especially in the presence of soft links in
    directory trees.

    If 'show_dirops' is true, then a message will be printed out showing the
    'mkdir' command used to create and the 'rmtree' command used to delete the
    transient directory.
    """
    def __init__(self, where=None, stay_on_error=False, keep_on_error=False,
                 show_pushd=True, show_popd=False, set_PWD=True, show_dirops=True):
        self.rmtree_on_error = not keep_on_error
        super(TransientDirectory, self).__init__(where, stay_on_error,
                                                 show_pushd, show_popd,
                                                 set_PWD, show_dirops)

    def close(self, delete_tree):
        # Don't delete the tree unless asked to
        super(TransientDirectory, self).close()
        if delete_tree:
            if self.show_dirops:
                # The extra space after 'rmtree' is so the directory name
                # left aligns with any previous 'popd  to' message
                print '++ rmtree   %s'%self.where
            shutil.rmtree(self.where)

    def __exit__(self, etype, value, tb):
        if tb is None:
            # No exception, so just finish normally
            self.close(True)
        else:
            # An exception occurred, so do any tidying up necessary
            if self.show_popd:
                print '** Oops, an exception occurred - %s tidying up'%self.__class__.__name__
            if self.close_on_error:
                self.close(self.rmtree_on_error)
            if self.show_popd:
                print '** ----------------------------------------------------------------------'
            # And allow the exception to be re-raised
            return False


# End file.
