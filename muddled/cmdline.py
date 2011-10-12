"""
Main command line support for the muddle program.

See:

  muddle help

for help on how to use it.
"""
import os

import muddled.commands as commands
import muddled.utils as utils
import muddled.mechanics as mechanics

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
            args = ['help']      # Ignore any other command words
            break
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

            (what, label, domain) = r

            if (what == utils.DirType.Root or
                (domain is None and label is None)):
                # We're either (1) actually at the root of the entire tree, or
                # (2) we're not anywhere particularly identifiable but near the
                # top of the entire tree.
                #
                # As such, our default is to build labels:
                command_class = cmd_dict["buildlabel"]
                command = command_class()
                command.set_options(command_options)

                # and the labels to build are the default labels - this
                # includes any default deployments
                args = map(str, builder.invocation.default_labels)

                # Default roles will not yet have been turned into labels
                # - we need to do this lazily so we know we get all the
                # labels for each role.
                # This is doubtless not the most compact way of doing this,
                # but it makes what we are doing fairly clear...
                for role in builder.invocation.default_roles:
                    labels = commands.decode_package_arguments(builder,
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

