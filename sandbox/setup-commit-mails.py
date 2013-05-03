#! /usr/bin/env python

"""
This is a helper script to automatically set up commit mails in the
repositories behind the checkouts of an instance of muddle.

Invoke this script from somewhere within a muddle tree:

    python /path/to/setup-commit-mails.py [<options>] email-destination

Options are:

    --help, -h, -?  Shows this help text
    --dry-run, -n   Don't actually make any changes, just describe what
                    you would have done.

This is a very simple script for very simple use.

1. It only understands git plugins
2. It assumes the system at the far end is running Ubuntu
3. It does not understand subdomains, and will ignore any checkouts in a
   subdomain
4. It assumes that checkouts at the far end are laid out in a manner that
   it can guess from their layout on the local machine.
5. If there is a 'versions/' directory, it is ignored, even if it is in
   revision control.
"""

import os
import sys
import subprocess
import re
import tempfile

try:
    from muddled.utils import GiveUp
except ImportError:
    # try one dir up.
    this_file = os.path.abspath(__file__)
    this_dir = os.path.split(this_file)[0]
    parent_dir = os.path.split(this_dir)[0]
    sys.path.insert(0, parent_dir)
    from muddled.utils import GiveUp
    # This still fails? add the directory containing muddled to your PYTHONPATH

from muddled.utils import run0
from muddled.cmdline import find_and_load
from muddled.depend import normalise_checkout_label

##########################################################

class RepositoryBase(object):
    """
        Base class for a repository we can meddle with over ssh.

        TODO: build repo URL parsing into these classes?
    """
    def __init__(self, ssh_access):
        self.ssh_access = ssh_access

    def get_script(self):
        """
            Returns the text of a script (with shebang) that knows how to
            deal with this sort of repository.
            Subclasses must override!

            The script will be executed as follows:
                ./SCRIPT rootdir build-name mail-destination@some.domain

              The build name (same as "muddle query name" reports) is provided
              to allow the script to configure the VCS hook to add some
              suitable identifying tag to the subject lines of the emails it sends.

            The script is expected to read a line at a time from stdin,
            each line being a directory name relative to "rootdir",
            and do whatever is appropriate to that directory.
            The script must cope with any vcs-specific quirks
            (e.g. git repos may be bare and may need to have ".git"
            appended to their names).
        """
        raise Exception("get_script not defined")

    def run_script(self, dirs, build_name, email_dest, dry_run=False):
        """
            Runs this instance's _script_ on the target _sshdir_,
            with the customary args,
            passing it as input the members of _dirs_ in turn.
        """

        try:
            local_tempfile = "<local tempfile>"
            remote_tempfile = "<remote tempfile>"
            if dry_run:
                print "Script to use:\n%s<<< END SCRIPT >>>"%self.get_script()
            else:
                localtemp_raw = tempfile.mkstemp(prefix="mcms-", suffix=".tmp", text=True)
                local_tempfile = localtemp_raw[1]
                os.chmod(local_tempfile, 0755)
                remote_tempfile = os.path.basename(local_tempfile)
                lt_f = os.fdopen(localtemp_raw[0],'w')
                lt_f.write(self.get_script()+"\n")
                lt_f.close()

            # First, copy the script over to the remote host
            self.ssh_access.scp_remote_cmd(local_tempfile, remote_tempfile, dry_run)

            # Then run it remotely
            remote_cmd = [ './'+remote_tempfile, self.ssh_access.path, build_name, email_dest ]
            self.ssh_access.ssh_remote_cmd(remote_cmd, dirs, dry_run)

        finally:
            if local_tempfile is not "<local tempfile>":
                if dry_run:
                    print "Would remove %s"%local_tempfile
                else:
                    os.remove(local_tempfile)
            if remote_tempfile is not "<remote tempfile>":
                self.ssh_access.ssh_remote_cmd(['rm', remote_tempfile], dry_run)


##############################

class GitRepository(RepositoryBase):

    def get_script(self):
        return """
#!/bin/bash -e

if [ -z "$3" ] || [ ! -z "$4" ]; then
    echo "Wrong number of arguments (expected 3: REPOROOT BUILDNAME EMAILDEST)"
    exit 5
fi

REPOROOT=$1
BUILDNAME=$2
EMAILDEST=$3

OLDPWD=`pwd`

# Contributed hooks are meant to be stored in a standard place.
# On Ubuntu 10.04, they were in:

CONTRIB_HOOKS_DIR_1=/usr/share/doc/git-core/contrib/hooks

# but in Ubuntu 11.04 they are now in:

CONTRIB_HOOKS_DIR_2=/usr/share/doc/git/contrib/hooks

# So, which do we have?
if [ -d "${CONTRIB_HOOKS_DIR_1}" ]; then
    CONTRIB_HOOKS_DIR=${CONTRIB_HOOKS_DIR_1}
    CONTRIB_HOOKS_OTHER_DIR=${CONTRIB_HOOKS_DIR_2}
elif [ -d "${CONTRIB_HOOKS_DIR_2}" ]; then
    CONTRIB_HOOKS_DIR=${CONTRIB_HOOKS_DIR_2}
    CONTRIB_HOOKS_OTHER_DIR=${CONTRIB_HOOKS_DIR_1}
else
    echo "error: cannot find git contributed hooks directory"
    echo "it is not ${CONTRIB_HOOKS_DIR_1}"
    echo "       or ${CONTRIB_HOOKS_DIR_2}"
    exit 1
fi

# The hook we want is
POST_RECEIVE_EMAIL_HOOK=${CONTRIB_HOOKS_DIR}/post-receive-email
# and if we find this hook, we might expect to replace it
OTHER_POST_RECEIVE_EMAIL_HOOK=${CONTRIB_HOOKS_OTHER_DIR}/post-receive-email

# Older versions of this script linked to:
LEGACY_LINK=/usr/local/lib/git-post-receive-email


while read srcdir; do
    cd $OLDPWD
    cd $REPOROOT

    #echo "Processing $srcdir"

    if [ -d "$srcdir/.git" ]; then
        # non-bare
        gitdir="${srcdir}/.git"
    elif [ -d "$srcdir".git ]; then
        # bare with .git
        gitdir="${srcdir}.git"
    elif [ -d "$srcdir"/hooks ]; then
        # bare without .git
        gitdir=${srcdir}
    else
        echo "error: no such dir ${REPOROOT}/${srcdir} (nor $srcdir.git)"
        exit 1
    fi

    hooksdir="$gitdir/hooks"
    if [ ! -d "${hooksdir}" ]; then
        echo "error: ${REPOROOT}/$gitdir has no hooks dir"
        exit 1
    fi

    cd ${hooksdir}
    if [ -L post-receive ]; then
        # it's a symlink: is it one we recognise?
        dest=`readlink post-receive`
        if [ "${dest}" == "${POST_RECEIVE_EMAIL_HOOK}" ]; then
            # It's the right sumlink - is it to the correct email address?
            CUR=`git config hooks.mailinglist`
            PREF=`git config hooks.emailprefix`
            if [ "${CUR}" != "${EMAILDEST}" ]; then
                if [ ! -z "${PREF}" ]; then
                    prefwords=" (and emailprefix: ${CUR} -> \"\")"
                fi
                git config --replace-all hooks.mailinglist "${EMAILDEST}"
                git config --replace-all hooks.emailprefix ""
                echo "changed email address: ${gitdir}: ${CUR} -> ${EMAILDEST} ${prefwords}"
            fi
        elif [ "${dest}" == "${OTHER_POST_RECEIVE_EMAIL_HOOK}" ]; then
            # It *was* the other Ubuntu location - update it to the one we have now
            ln -sf ${POST_RECEIVE_EMAIL_HOOK} post-receive
            git config --replace-all hooks.mailinglist "${EMAILDEST}"
            git config --replace-all hooks.emailprefix ""
            echo "updated hook to current Ubuntu hook: $gitdir -> ${EMAILDEST}"
        elif [ "${dest}" == "${LEGACY_LINK}" ]; then
            # It was the old link previous versions used - update it
            ln -sf ${POST_RECEIVE_EMAIL_HOOK} post-receive
            git config --replace-all hooks.mailinglist "${EMAILDEST}"
            git config --replace-all hooks.emailprefix ""
            echo "updated legacy link to current Ubuntu hook: $gitdir -> ${EMAILDEST}"
        else
            echo "Error: $hooksdir/post-receive was an unexpected symlink (to ${dest}), don't know how to handle this"
            exit 2
        fi
    elif [ ! -e post-receive ]; then
        # A new repository, with no such file
        ln -s ${POST_RECEIVE_EMAIL_HOOK} post-receive
        git config --replace-all hooks.mailinglist "${EMAILDEST}"
        git config --replace-all hooks.emailprefix ""
        echo "installed hook: $gitdir -> ${EMAILDEST}"
    else
        # exists and isn't a symlink, gah
        echo "Error: $hooksdir/post-receive was an unexpected file, don't know how to handle this"
        exit 2
    fi

    cd ${REPOROOT}
    descf=${gitdir}/description
    if [ ! -f ${descf} ]; then
        # Shouldn't happen, git repos always have descriptions - don't they?
        echo "Warning: ${gitdir}/description does not exist, creating it"
    fi

    # Create a rudimentary auto-description if one hasn't been set yet
    currdesc=`cat ${descf}` || currdesc=""
    if [[ "$currdesc" =~ "Unnamed repo" ]]; then
        printf "%s %s\n" "${BUILDNAME}" "${gitdir}" > ${descf}
    fi
done

cd $OLDPWD
#echo finished
"""

##########################################################

class SshAccess(object):
    """A wrapper for managing ssh and scp access to a repository.
    """

    def __init__(self, user=None, host=None, port=None, path=None):
        """Where we want to access.

        Some combination equivalent to [user@][host][:port][path]
        """
        self.user = user
        self.host = host
        self.port = port
        self.path = path

        s = host
        if user:
            s = '%s@%s'%(user, s)

        # We don't include the port in this because scp and ssh need to
        # be told it in different ways
        self.user_at_host = s

    def scp_remote_cmd(self, local_script, remote_script, dry_run=False):
        """SCP the given script to our location.
        """
        parts = ['scp']
        if self.port:
            parts.append('-P %s'%self.port)
        parts.append(local_script)
        parts.append('%s:%s'%(self.user_at_host, remote_script))
        cmd = ' '.join(parts)
        if dry_run:
            print "Would run: %s"%cmd
        else:
            run0(cmd)

    def ssh_remote_cmd(self, remote_cmd, dirs=None, dry_run=False):
        """SSH to our location, and run the command over the directories.

        * 'remote_cmd' is the words that make up the command (as a list).
        * 'dirs' is the list of directories we want to pass to the command.
          If this is None, or an empty list, then we won't do that...
        """
        parts = ['ssh']
        if self.port:
            parts.append('-p %s'%self.port)
        parts.append(self.user_at_host)
        parts += remote_cmd
        cmd = ' '.join(parts)
        if dry_run:
            print "Would run: %s "%cmd
            if dirs:
                print "and pass it the following directories:"
                print "\n".join(dirs)
        elif dirs:
            print "> %s"%cmd
            p = subprocess.Popen(parts,
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)
            stdoutdata, stderrdata = p.communicate("\n".join(dirs) +'\n')
            if p.returncode:
                print >> sys.stderr, "Error invoking the remote script (rc=%d):"%p.returncode
                print >> sys.stderr, stdoutdata
                raise GiveUp("Error invoking the remote script, rc=%d"%p.returncode)
            print "Script exited successfully, output was:\n%s\n<<<END OUTPUT>>>\n"%stdoutdata
        else:
            run0(cmd)

def parse_repo_url(url):
    """
       TODO: Factor out this parsing into the *Repository classes.
       TODO: ask muddle which VCS we're using, maybe build the string parser into its per-VCS support?
    """
    pgit = re.compile("git\+ssh://([^@]+\@)?([^/:]+)(:\d+)?(/.*)")
    m = pgit.match(url)
    if m is not None:
        user = m.group(1)[:-1]  # lose the trailing '@'
        host = m.group(2)
        port = m.group(3)[1:]   # lose the initial ':'
        path = m.group(4)
        return GitRepository(SshAccess(user, host, port, path))
    raise GiveUp("Sorry, I don't know how to handle this repository: %s"%url)
    # regexp.

##########################################################

def _do_cmdline(args):
    original_dir = os.getcwd()
    dry_run = False

    # TODO: allow switches after args.
    while args:
        word = args[0]
        if word in ('-h', '--help', '-?'):
            print __doc__
            return
        elif word in ('--dry-run', '-n'):
            dry_run = True
        elif word[0] == '-':
            raise GiveUp, "Unexpected command line option %s"%word
        else:
            break
        args = args[1:]

    if len(args) != 1:
        raise GiveUp, "Incorrect non-option argument count (expected 1, the email destination)"

    email_dest = args[0]

    builder = find_and_load(original_dir, muddle_binary=None)
    # Don't bother determining muddle_binary: our invocation of find_and_load
    # doesn't make use of it. (Tibs writes: it's only needed for when
    # running makefiles, for when they use $(MUDDLE).)

    if not builder:
        raise GiveUp("Cannot find a build tree.")

    rootrepo = builder.db.RootRepository_pathfile.get()

    repo = parse_repo_url(rootrepo)

    rules = builder.all_checkout_rules()
    dirs = []
    for r in rules:
        key = r.target
        # Unfortunately, we do not currently support subdomains
        if key.domain:
            continue
        rel_dir = builder.db.get_checkout_location(key)
        if rel_dir.startswith("src/"):  # as it should
            rel_dir = rel_dir[4:]
        dirs.append(rel_dir)
    # in testing, use dirs[0:2] (or something similarly small) in place of dirs.
    repo.run_script(dirs, builder.build_name, email_dest, dry_run)

##########################################################

if __name__ == "__main__":
    try:
        _do_cmdline(sys.argv[1:])
    except GiveUp as f:
        print "%s"%f
        sys.exit(1)
