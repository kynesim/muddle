"""
Main command line support for the muddle program.

Usage:

  muddle [<options>] <command> [<arg> ...]

Options include:

  --help, -h, -?      This help text
  --tree <dir>        Use the muddle build tree at <dir>
  --just-print, -n    Just print what muddle would have done. This is currently
                      only partially supported - please do not trust it.

If you don't give --tree, muddle will traverse directories up to the root to
try and find a .muddle directory, which signifies the top of the build tree.

To get help on commands, use:

  muddle help [<command>]
"""
import os

import muddled.commands as commands
import muddled.utils as utils
import muddled.mechanics as mechanics

def help_list(cmd_dict):
    """
    Return a list of all commands
    """
    result_array = [ __doc__, "\n" ]

    # Use the entire set of command names, including any aliases
    keys = cmd_dict.keys()
    keys.sort()
    keys_text = ", ".join(keys)

    result_array.append(utils.wrap('Commands are: %s'%keys_text,
                                   # I'd like to do this, but it's not in Python 2.6.5
                                   #break_on_hyphens=False,
                                   subsequent_indent='              '))

    result_array.append("\n\nUse:\n")
    result_array.append("\n  muddle help <cmd>          for help on a command")
    result_array.append("\n  muddle help <cmd> <subcmd> for help on a subcommand")
    result_array.append("\n  muddle help all            for help on all commands")
    result_array.append("\n  muddle help _all           is the same as 'help all'")
    result_array.append("\n  muddle help <cmd> all      for help on all <cmd> subcommands")
    result_array.append("\n  muddle help <cmd> _all     is the same as 'help <cmd> all'")
    result_array.append("\n  muddle help aliases        says which commands have more than one name")
    result_array.append("\n")

    # Temporarily
    result_array.append("\nPlease note that 'muddle pull' and 'muddle update' are deprecated.")
    result_array.append("\nUse 'fetch' or 'merge', as appropriate, instead.")
    # Temporarily

    return "".join(result_array)


def help_all(cmd_dict, subcmd_dict):
    """
    Return help for all commands
    """
    result_array = []
    result_array.append("Commands:\n")

    cmd_list = []

    # First, all the main command names (without any aliases)
    for name in commands.g_command_names:
        v = cmd_dict[name]
        cmd_list.append((name, v()))

    # Then, all the subcommands (ditto)
    for main, sub in commands.g_subcommand_names:
        v = subcmd_dict[main][sub]
        cmd_list.append(('%s %s'%(main, sub), v()))

    cmd_list.sort()

    for name, obj in cmd_list:
        result_array.append("%s\n%s"%(name, v().help()))

    return "\n".join(result_array)

def help_subcmd_all(cmd_name, cmd_dict):
    """
    Return help for all commands in this dictionary
    """
    result_array = []
    result_array.append("Subcommands for '%s' are:\n"%cmd_name)

    keys = cmd_dict.keys()
    keys.sort()

    for name in keys:
        v = cmd_dict[name]
        result_array.append('%s\n%s'%(name, v().help()))

    return "\n".join(result_array)

def help_aliases():
    """
    Return a list of all commands with aliases
    """
    result_array = []
    result_array.append("Commands aliases are:\n")

    aliases = commands.g_command_aliases

    keys = aliases.keys()
    keys.sort()

    for alias in keys:
        result_array.append("  %-10s  %s"%(alias, aliases[alias]))

    aliases = commands.g_subcommand_aliases
    if aliases:
        result_array.append("\nSubcommand aliases are:\n")

        main_keys = aliases.keys()
        main_keys.sort()
        for cmd in main_keys:
            sub_keys = aliases[cmd].keys()
            sub_keys.sort()
            for alias in sub_keys:
                result_array.append("  %-20s %s"%("%s %s"%(cmd, alias),
                                                        "%s %s"%(cmd, aliases[cmd][alias])))

    return "\n".join(result_array)

def help(cmd_dict, subcmd_dict, about=None):
    """
    Return the help message for 'about'.

    If 'about' is None or empty, return summary of all commands.
    """

    if not about:
        return help_list(cmd_dict)

    if about[0] in ("all", "_all"):
        return help_all(cmd_dict, subcmd_dict)   # and ignore the rest of the command line

    if about[0] == "aliases":
        return help_aliases()

    if len(about) == 1:
        cmd = about[0]
        try:
            v = cmd_dict[cmd]
            if v is None:
                keys = subcmd_dict[cmd].keys()
                keys.sort()
                keys_text = ", ".join(keys)
                return utils.wrap("Subcommands of '%s' are: %s"%(cmd,keys_text),
                                  # I'd like to do this, but it's not in Python 2.6.5
                                  #break_on_hyphens=False,
                                  subsequent_indent='              ')
            else:
                return "%s\n%s"%(cmd, v().help())
        except KeyError:
            return "There is no muddle command '%s'"%cmd
    elif len(about) == 2:
        cmd = about[0]
        subcmd = about[1]
        try:
            sub_dict = subcmd_dict[cmd]
        except KeyError:
            if cmd in cmd_dict:
                return "Muddle command '%s' does not take a subcommand"%cmd
            else:
                return "There is no muddle command '%s %s'"%(cmd, subcmd)

        if subcmd in ("all", "_all"):
            return help_subcmd_all(cmd, sub_dict)

        try:
            v = sub_dict[subcmd]
            return "%s %s\n%s"%(cmd, subcmd, v().help())
        except KeyError:
            return "There is no muddle command '%s %s'"%(cmd, subcmd)
    else:
        return "There is no muddle command '%s'"%' '.join(about)
    result_array = []
    for cmd in about:
        try:
            v = cmd_dict[cmd]
            result_array.append("%s\n%s"%(cmd, v().help()))
        except KeyError:
            result_array.append("There is no muddle command '%s'\n"%cmd)

    return "\n".join(result_array)

def find_and_load(specified_root, muddle_binary):
    """Find our .muddle root, and then load our builder, and return it.
    """
    try:
        (build_root, build_domain) = utils.find_root_and_domain(specified_root)
        if build_root:
            builder = mechanics.load_builder(build_root, muddle_binary,
                                             default_domain = build_domain)
        else:
            builder = None
        return builder
    except utils.GiveUp:
        print "Failure trying to load build tree"
        raise
    except utils.MuddleBug:
        print "Error trying to find build tree"
        raise

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
            print __doc__
            return
        elif word == '--tree':
            args = args[1:]
            specified_root = args[0]
        elif word == '-n' or word == "--just-print":
            command_options["no_operation"] = True
        elif word[0] == '-':
            raise utils.GiveUp, "Unexpected command line option %s"%word
        else:
            break

        args = args[1:]

    if len(args) < 1:
        # The command is implicitly 'rebuild' with the default label, or
        # _all if none was specified.
        command_name = "rebuild"            # We rely on knowing this exists
        guess_what_to_do = True             # but it's only our best guess
    else:
        command_name = args[0]
        args = args[1:]
        guess_what_to_do = False

    # First things first, let's look up the command .. 
    cmd_dict = commands.g_command_dict
    subcmd_dict = commands.g_subcommand_dict

    # The help command needs to be provided here because the 
    # command module doesn't have the necessary information
    if (command_name == "help"):
        print help(cmd_dict, subcmd_dict, args)
        return

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

    command = command_class()
    command.set_options(command_options)
    command.set_old_env(original_env)

    builder = find_and_load(specified_root, muddle_binary)

    if builder:
        # There is a build tree...
        if guess_what_to_do:
            # Where are we?
            r = builder.find_location_in_tree(current_dir)
            if r is None:
                raise utils.GiveUp("Can't seem to determine where you are in the build tree")

            (what, loc, role) = r

            if (what == utils.DirType.Root or loc == None):
                # We're at the root, or at least not in a checkout/package/deployment
                command_class = cmd_dict["buildlabel"]
                command = command_class()
                command.set_options(command_options)

                # Add in the default labels - this includes any default
                # deployments
                args = map(str, builder.invocation.default_labels)

                # Default roles will not yet have been turned into labels
                # - we need to do this lazily so we know we get all the
                # labels for each role.
                # This is doubtless not the most compact way of doing this,
                # but it makes what we are doing fairly clear...
                for role in builder.invocation.default_roles:
                    labels = commands.labels_from_pkg_args(builder,
                                                           ['_all{%s}'%role],
                                                           current_dir,
                                                           utils.LabelTag.PostInstalled)
                    args += map(str, labels)

        command.with_build_tree(builder, current_dir, args)
    else:
        # There is no build root here .. 
        if guess_what_to_do:
            # Guess that you wanted help.
            print help(cmd_dict, subcmd_dict)
            return

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

