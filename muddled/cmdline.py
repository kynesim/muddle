"""
Main command line support for the muddle program.

See:

  muddle help

for help on how to use it.
"""

import errno
import os
import subprocess

import muddled.commands as commands
import muddled.utils as utils
import muddled.mechanics as mechanics

from muddled.depend import Label
from muddled.utils import LabelType, LabelTag, DirType
from muddled.withdir import Directory

def our_cmd(cmd_list, error_ok=True):
    """Command processing for calculating muddle version
    """
    try:
        p = subprocess.Popen(cmd_list, shell=False, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        out, err = p.communicate()
        if p.returncode == 0:
            return out.strip()
        elif error_ok:
            return ''
        else:
            raise utils.GiveUp("Problem determining muddle version: 'git' returned %s\n\n"
                               "$ %s\n"
                               "%s\n"%(p.returncode, ' '.join(cmd_list), out.strip()))
    except OSError as e:
        if e.errno == errno.ENOENT:
            raise utils.GiveUp("Unable to determine 'muddle --version' - cannot find 'git'")

def show_version():
    """Show something akin to a version of this muddle.

    Simply run git to do it for us. Of course, this will fail if we don't
    have git...
    """
    this_dir = os.path.split(__file__)[0]
    muddle_dir = os.path.split(this_dir)[0]
    cmd_tag = ['git', 'describe', '--dirty=-modified', '--long', '--tags']
    cmd_all = ['git', 'describe', '--dirty=-modified', '--long', '--all']
    branch  = ['git', 'symbolic-ref', '-q', 'HEAD']
    version = "<unknown>"
    with Directory(muddle_dir, show_pushd=False):
        # First try looking for a version using tags, which should normally
        # work.
        version = our_cmd(cmd_tag, error_ok=True)
        # If that failed, try with --all
        if not version:
            version = our_cmd(cmd_tag, error_ok=False)

        # Are we on a branch?
        branch = our_cmd(branch)
        if branch:
            if branch.startswith('refs/heads/'):
                branch = branch[11:]
            if branch == 'master':
                branch = None

        if branch:
            print '%s on branch %s in %s'%(version, branch, muddle_dir)
        else:
            print '%s in %s'%(version, muddle_dir)

def find_and_load(specified_root, muddle_binary):
    """Find our .muddle root, and then load our builder, and return it.
    """
    try:
        (build_root, build_domain) = utils.find_root_and_domain(specified_root)
        if build_root:
            builder = mechanics.load_builder(build_root, muddle_binary,
                                             #default_domain = build_domain)
                                             default_domain = None) # 'cos it's the toplevel
        else:
            builder = None
        return builder
    except utils.MuddleBug:
        print "Error trying to find build tree"
        raise
    except utils.GiveUp:
        print "Failure trying to load build tree"
        raise

def lookup_command(command_name, args, cmd_dict, subcmd_dict):
    """
    Look the command up, and return an instance of it and any remaining args
    """
    try:
        command_class = cmd_dict[command_name]
    except KeyError:
        raise utils.GiveUp("There is no muddle command '%s'"%command_name)

    if command_class is None:
        try:
            subcommand_name = args[0]
        except IndexError:
            raise utils.GiveUp("Command '%s' needs a subcommand"%command_name)
        args = args[1:]
        try:
            command_class = subcmd_dict[command_name][subcommand_name]
        except KeyError:
            raise utils.GiveUp("There is no muddle command"
                                " '%s %s'"%(command_name, subcommand_name))
    return command_class(), args

def guess_cmd_in_build(builder, current_dir):
    """Returns a tuple (command_name, args)
    """
    # Where are we?
    where = builder.find_location_in_tree(current_dir)
    if where is None:
        raise utils.GiveUp("Can't decide what to do, can't seem to"
                           " determine where you are in the build tree")

    what, label, domain = where

    args = []
    if what == DirType.Root:
        # We're at the very top of the build tree
        #
        # As such, our default is to build labels:
        command_name = "buildlabel"

        # and the labels to build are the default deployments
        args = map(str, builder.default_deployment_labels)

        # and the default roles
        for role in builder.default_roles:
            label = Label(LabelType.Package, '*', role, LabelTag.PostInstalled)
            args.append(str(label))

    elif what == DirType.DomainRoot:
        domains = []
        if domain is None:
            subdirs = os.listdir(current_dir)
            # Make a quick plausibility check
            for dir in subdirs:
                if os.path.isdir(os.path.join(current_dir, dir, '.muddle')):
                    domains.append(dir)

        else:
            domains.append(domain)

        # We're in domains/<somewhere>, so build everything specific
        # to (just) this subdomain
        command_name = "buildlabel"

        # Choose all the packages from this domain that are needed by
        # our build tree. Also, all the deployments that it contributes
        # to our build tree. It is possible we might end up "over building"
        # if any of those are not implied by the top-level build defaults,
        # but that would be somewhate more complex to determine.
        for name in domains:
            args.append('deployment:({domain})*/deployed'.format(domain=name))
            args.append('package:({domain})*{{*}}/postinstalled'.format(domain=name))

    elif what == DirType.Deployed:
        # We're in a deploy/ directory, so redeploying sounds sensible
        # The redeploy command knows to "look around" and decide *what*
        # needs redeploying
        command_name = "redeploy"

        if label:       # Given a specific deployment, choose it
            args.append(str(label))

    elif what == DirType.Object or what == DirType.Install:
        # We're in obj/ or install/, so rebuilding is what we want to do
        # The rebuild command knows to "look around" and decide *what*
        # needs rebuilding
        command_name = "rebuild"

    elif what == DirType.Checkout:
        # We're in src/, so we want to build, not rebuild
        # The build command knows to "look around" and decide *what*
        # needs building
        command_name = "build"

    else:
        raise utils.GiveUp("Don't know what to do in this location: %s"%what)

    return command_name, args

def _cmdline(args, current_dir, original_env, muddle_binary):
    """
    The actual command line, with no safety net...
    """

    guess_what_to_do = False
    command_name = ""

    command = None
    command_options = { }
    specified_root = current_dir

    while args:
        word = args[0]
        if word in ('-h', '-help', '--help', '-?'):
            args = ['help']      # Ignore any other command words
            break
        elif word == '--tree':
            args = args[1:]
            specified_root = args[0]
        elif word == '--version':
            show_version()
            return
        elif word in ('-n', "--just-print"):
            command_options["no_operation"] = True
        elif word[0] == '-':
            raise utils.GiveUp, 'Unexpected command line option %s - see "muddle help"'%word
        else:
            break

        args = args[1:]

    if args:
        command_name = args[0]
        args = args[1:]
    else:
        guess_what_to_do = True

    # Are we in a muddle build?
    builder = find_and_load(specified_root, muddle_binary)
    if builder and guess_what_to_do:
        # We are, but we have to "guess" what to do
        command_name, args = guess_cmd_in_build(builder, current_dir)

    if not builder and guess_what_to_do:
        # Guess that you wanted help.
        command_name = "help"

    # Now we've definitely got a command, we can look it up
    cmd_dict = commands.g_command_dict
    subcmd_dict = commands.g_subcommand_dict

    command, args = lookup_command(command_name, args, cmd_dict, subcmd_dict)
    command.set_options(command_options)
    command.set_old_env(original_env)

    # And armed with that, we can try to obey it
    if builder:
        if builder.is_release_build() and not command.allowed_in_release_build():
            raise utils.GiveUp("Command %s is not allowed in a release build"%command_name)
        command.with_build_tree(builder, current_dir, args)
    else:
        if command.requires_build_tree():
            raise utils.GiveUp("Command %s requires a build tree."%(command_name))
        command.without_build_tree(muddle_binary, current_dir, args)

def cmdline(args, muddle_binary=None):
    """
    Work out what to do from a muddle command line.

    'args' should be all of the "words" after the actual command name itself.

    'muddle_binary' should be the __file__ value for the Python script that
    is calling us, or whatever other value we wish $(MUDDLE) to be set to
    by muddle itself. It is important to get this right, as it is used in
    Makefiles to run muddle itself. If it is given as None then we shall
    make up what should be a sensible value.
    """

    # This is actually just a wrapper function, to allow us to neatly
    # ensure that we don't muck up the environment and current directory
    # of whoever is calling us.
    original_env = os.environ.copy()
    original_dir = os.getcwd()
    shell_dir = os.getenv('PWD')
    if shell_dir and shell_dir != original_dir:
        original_dir = shell_dir

    if muddle_binary is None:
        # The 'muddle' comamnd is actually just a link to our __main__.py
        # so we should be able to work with that...
        this_dir, this_file = os.path.split(__file__)
        muddle_binary = os.path.join(this_dir, '__main__.py')

    try:
        os.chdir(original_dir)          # In case we set it to shell_dir
        _cmdline(args, original_dir, original_env, muddle_binary)
    finally:
        os.chdir(original_dir)          # Should not really be necessary...
        os.environ = original_env

