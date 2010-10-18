"""
Main command line support for the muddle program
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
    result_array.append("\n  muddle help <cmd>          for help on a single command")
    result_array.append("\n  muddle help <cmd1> <cmd2>  for help on two commands (and so on)")
    result_array.append("\n  muddle help all            for help on all commands")
    result_array.append("\n  muddle help _all           is the same as 'help all'")
    result_array.append("\n  muddle help aliases        says which commands have more than one name")
    result_array.append("\n")

    return "".join(result_array)


def help_all(cmd_dict):
    """
    Return help for all commands
    """
    result_array = []
    result_array.append("Commands:\n")

    # However, we only want to give help by the "main" name for each command,
    # ignoring any aliases
    keys = commands.g_command_names

    for k in keys:
        v = cmd_dict[k]
        result_array.append("%s\n%s"%(k, v.help()))

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
    result_array.append("\n")

    return "\n".join(result_array)

def help(cmd_dict, about=None):
    """
    Return the help message for things in 'about'.

    If 'about' is None or empty, return help for all commands.
    """

    if not about:
        return help_list(cmd_dict)

    if about[0] in ("all", "_all"):
        return help_all(cmd_dict)   # and ignore the rest of the command line

    if about[0] == "aliases":
        return help_aliases()

    result_array = []
    for cmd in about:
        try:
            v = cmd_dict[cmd]
            result_array.append("%s\n%s"%(cmd, v.help()))
        except KeyError:
            result_array.append("There is no muddle command '%s'\n"%cmd)

    return "\n".join(result_array)

def find_and_load(specified_root, muddle_binary):
    """Find our .muddle root, and then load our builder, and return it.
    """
    try:
        (build_root, build_domain) = utils.find_root(specified_root)
        if build_root:
            builder = mechanics.load_builder(build_root, muddle_binary,
                                             default_domain = build_domain)
        else:
            builder = None
        return builder
    except utils.Failure as f:
        print "Failure trying to load build tree"
        os.chdir(specified_root)        # 'cos it tends to have changed
        raise
    except utils.Error as e:
        print "Error trying to find build tree"
        raise

def _cmdline(args, current_dir, original_env, muddle_binary):
    """
    The actual command line, with no safety net...
    """

    command = None
    command_options = { }
    specified_root = current_dir

    # Command dictionary. Maps command name to a tuple
    # (Boolean, command_fn)
    #
    # The boolean tells us whether this command requires an
    # initialised build tree or not (init obviously doesn't ..)
    #
    # Every command gets:
    #
    #  (invocation, local_package_list)

    while args:
        word = args[0]
        if word in ('-h', '--help', '-?'):
            print __doc__
            return
        elif word == '--tree':
            args = args[1:]
            specified_root = args[0]
        elif word == '-n' or word == "--just-print":
            command_options["no_operation"] = True
        elif word[0] == '-':
            raise utils.Failure, "Unexpected command line option %s"%word
        else:
            break

        args = args[1:]

    if len(args) < 1:
        # The command is implicitly 'build' with the default label, or
        # _all if none was specified.
        command_name = "rebuild"
        guess_what_to_do = True
    else:
        command_name = args[0]
        args = args[1:]
        guess_what_to_do = False

    # First things first, let's look up the command .. 
    cmd_dict = commands.register_commands()

    # The help command needs to be provided here because the 
    # command module doesn't have the necessary information
    if (command_name == "help"):
        print help(cmd_dict, args)
        return

    if (command_name not in cmd_dict):
        raise utils.Failure("There is no muddle command '%s'"%command_name)

    command = cmd_dict[command_name]
    command.set_options(command_options)
    command.set_old_env(original_env)

    builder = find_and_load(specified_root, muddle_binary)

    if builder:
        # There is a build tree...
        if guess_what_to_do:
            # Where are we?
            r = builder.find_location_in_tree(current_dir)
            if r is None:
                raise utils.Failure("Can't seem to determine where you are in the build tree")

            (what, loc, role) = r

            if (what == utils.DirType.Root or loc == None):
                # We're at the root, or at least not in a checkout/package/deployment
                command = cmd_dict["buildlabel"]
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
            print args

        command.with_build_tree(builder, current_dir, args)
    else:
        # There is no build root here .. 
        if guess_what_to_do:
            # Guess that you wanted help.
            print help(cmd_dict)
            return

        if command.requires_build_tree():
            raise utils.Failure("Command %s requires a build tree."%(command_name))

        command.without_build_tree(muddle_binary, specified_root, args)

def cmdline(args, muddle_binary):
    """
    Work out what to do from a muddle command line.

    'args' should be all of the "words" after the actual command name itself.

    'muddle_binary' should be the __file__ value for the Python script that
    is calling us, or whatever other value we wish $(MUDDLE) to be set to
    by muddle itself.
    """

    # This is actually just a wrapper function, to allow us to neatly
    # ensure that we don't muck up the environment and current directory
    # of whoever is calling us.
    original_env = os.environ.copy()
    original_dir = os.getcwd()

    try:
        _cmdline(args, original_dir, original_env, muddle_binary)
    finally:
        os.chdir(original_dir)
        os.environ = original_env

