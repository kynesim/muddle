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
from muddled.utils import LabelType, LabelTag, DirType, Directory

def show_version():
    """Show something akin to a version of this muddle.

    Simply run git to do it for us. Of course, this will fail if we don't
    have git...
    """
    this_dir = os.path.split(__file__)[0]
    muddle_dir = os.path.split(this_dir)[0]
    cmd_tag = ['git', 'describe', '--dirty=-modified', '--long', '--tags']
    cmd_all = ['git', 'describe', '--dirty=-modified', '--long', '--all']
    with Directory(muddle_dir, show_pushd=False):
        # First try looking for a version using tags, which should normally
        # work. However, if it doesn't try --all
        try:
            p = subprocess.Popen(cmd_tag, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            out, err = p.communicate()
            if p.returncode == 0:
                print 'muddle %s in %s'%(out.strip(), muddle_dir)
                return
            else:
                raise utils.GiveUp("Problem determining muddle version: 'git' returned %s\n\n"
                                   "$ %s\n"
                                   "%s\n"%(p.returncode, ' '.join(cmd), out.strip()))
        except Exception:
            pass

        try:
            p = subprocess.Popen(cmd_all, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            out, err = p.communicate()
            if p.returncode == 0:
                print 'muddle %s in %s'%(out.strip(), muddle_dir)
                return
            else:
                raise utils.GiveUp("Problem determining muddle version: 'git' returned %s\n\n"
                                   "$ %s\n"
                                   "%s\n"%(p.returncode, ' '.join(cmd), out.strip()))
        except OSError as e:
            if e.errno == errno.ENOENT:
                raise utils.GiveUp("Unable to determine 'muddle --version' - cannot find 'git'")
            else:
                raise


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
    except utils.GiveUp:
        print "Failure trying to load build tree"
        raise
    except utils.MuddleBug:
        print "Error trying to find build tree"
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

def _cmdline(args, current_dir, original_env, muddle_binary):
    """
    The actual command line, with no safety net...
    """

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
            raise utils.GiveUp, "Unexpected command line option %s"%word
        else:
            break

        args = args[1:]

    if len(args) < 1:
        # Make a first guess at a plausible command
        command_name = "rebuild"            # We rely on knowing this exists
        guess_what_to_do = True             # but it's only our best guess
    else:
        command_name = args[0]
        args = args[1:]
        guess_what_to_do = False

    # First things first, let's look up the command ..
    cmd_dict = commands.g_command_dict
    subcmd_dict = commands.g_subcommand_dict

    command, args = lookup_command(command_name, args, cmd_dict, subcmd_dict)
    command.set_options(command_options)
    command.set_old_env(original_env)

    builder = find_and_load(specified_root, muddle_binary)
    if builder:
        # There is a build tree...
        if guess_what_to_do:
            # Where are we?
            where = builder.find_location_in_tree(current_dir)
            if where is None:
                raise utils.GiveUp("Can't seem to determine where you are in the build tree")

            (what, label, domain) = where

            if what == DirType.Root:
                # We're at the very top of the build tree
                #
                # As such, our default is to build labels:
                command_class = cmd_dict["buildlabel"]
                command = command_class()
                command.set_options(command_options)

                # and the labels to build are the default deployments
                args = map(str, builder.invocation.default_deployment_labels)

                # and the default roles
                for role in builder.invocation.default_roles:
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
                command_class = cmd_dict["buildlabel"]
                command = command_class()
                command.set_options(command_options)

                # Choose all the packages from this domain that are needed by
                # our build tree. Also, all the deployments that it contributes
                # to our build tree. It is possible we might end up "over building"
                # if any of those are not implied by the top-level build defaults,
                # but that would be somewhate more complex to determine.
                args = []
                for name in domains:
                    args.append('deployment:({domain})*/deployed'.format(domain=name))
                    args.append('package:({domain})*{{*}}/postinstalled'.format(domain=name))

            elif what == DirType.Deployed:
                # We're in a deploy/ directory, so redeploying sounds sensible
                command_class = cmd_dict["redeploy"]
                command = command_class()
                command.set_options(command_options)

                args = []
                if label:       # Given a specific deployment, choose it
                    args.append(str(label))

        command.with_build_tree(builder, current_dir, args)
    else:
        # There is no build tree here ..
        if guess_what_to_do:
            # Guess that you wanted help.
            command_class = cmd_dict["help"]
            command = command_class()

        if command.requires_build_tree():
            raise utils.GiveUp("Command %s requires a build tree."%(command_name))

        command.without_build_tree(muddle_binary, specified_root, args)

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
        _cmdline(args, original_dir, original_env, muddle_binary)
    finally:
        os.chdir(original_dir)          # Should not really be necessary...
        os.environ = original_env

