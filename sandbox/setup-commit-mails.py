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

NYI: support for domains
NYI: set up a notify on the top-level versions directory if it is held in
     revision control
"""

import os
import sys
import traceback
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

from muddled.utils import run_cmd,get_cmd_data
from muddled.cmdline import find_and_load

##########################################################

def maybe_run(cmd, dryRun):
    if dryRun:
        print "WOULD RUN: %s"%cmd
    else:
        run_cmd(cmd)

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
            if dry_run is True:
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
            self.ssh_acccess.ssh_remote_cmd(remote_cmd, dirs, dry_run)

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
    echo "Wrong number of arguments (expected 3)"
    exit 5
fi

REPOROOT=$1
BUILDNAME=$2
EMAILDEST=$3

OLDPWD=`pwd`

# Known locations for the post-receive hook:
PRH_SRC=/usr/share/doc/git-core/contrib/hooks/post-receive-email
PRH_DEST=/usr/local/lib/git-post-receive-email

if [ ! -x ${PRH_DEST} ]; then
    if [ ! -f ${PRH_SRC} ]; then
        echo "Error: Cannot locate post-receive-email hook on this system"
        # non-debian/ubuntu machines may need some logic above to iterate over possible values of PRH_SRC.
        exit 5
    fi

    # Try to set it up, if we can write to /usr/local/lib
    cp -f ${PRH_SRC} ${PRH_DEST} || true
    chmod a+x ${PRH_DEST} || true
    if [ ! -x ${PRH_DEST} ]; then
        echo "Error: Could not set up post-receive-email hook"
        echo -e "As root, please run: \n  cp ${PRH_SRC} ${PRH_DEST}\n  chmod a+x ${PRH_DEST}"
        exit 4
    fi
    POSTRECEIVE=${PRH_DEST}
else
    POSTRECEIVE=${PRH_DEST}
fi

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
    if [ ! -e post-receive ]; then
        ln -s ${POSTRECEIVE} post-receive
        git config --replace-all hooks.mailinglist "${EMAILDEST}"
        git config --replace-all hooks.emailprefix ""
        echo "installed hook for $gitdir -> ${EMAILDEST}"
    elif [ -L post-receive ]; then
        # it's a symlink: have we been here before?
        dest=`readlink post-receive`
        if [ "${dest}" == "${POSTRECEIVE}" ]; then
            CUR=`git config hooks.mailinglist`
            PREF=`git config hooks.emailprefix`
            if [ "${CUR}" != "${EMAILDEST}" ]; then
                if [ ! -z "${PREF}" ]; then
                    prefwords=" (and emailprefix: ${CUR} -> \"\")"
                fi
                echo "${gitdir}: ${CUR} -> ${EMAILDEST} ${prefwords}"
                git config --replace-all hooks.mailinglist "${EMAILDEST}"
                git config --replace-all hooks.emailprefix ""
            fi
        else
            echo "Error: $hooksdir/post-receive was an unexpected symlink (to ${dest}), don't know how to handle this"
            exit 2
        fi
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
        if port:
            s = '%s:%s'%(s, port)

    def scp_remote_cmd(self, local_script, remote_script, try_run=False):
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
            run_cmd(cmd)

    def ssh_remote_cmd(self, remote_cmd, dirs=None, dry_run=False):
        """SSH to our location, and run the command over the directories.

        * 'remote_cmd' is the words that make up the command (as a list).
        * 'dirs' is the list of directories we want to pass to the command.
          If this is None, or an empty list, then we won't do that...
        """
        parts = ['ssh']
        if self.port:
            parts.append('%s:%s'%(self.user_at_host, self.port))
        else:
            parts.append(self.user_at_host)
        parts.append(remote_cmd)
        cmd = ' '.join(parts)
        if dry_run:
            print "Would run: %s "%cmd
            if dirs:
                print "and pass it the following directories:"
                print "  \n".join(dirs)
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
            run_cmd(cmd)

def parse_repo_url(url):
    """
       TODO: Factor out this parsing into the *Repository classes.
       TODO: ask muddle which VCS we're using, maybe build the string parser into its per-VCS support?
    """
    pgit = re.compile("git\+ssh://([^@]+\@)?([^/:]+)(:\d+)?(/.*)")
    m = pgit.match(url)
    if m is not None:
        userAt = m.group(1)
        host = m.group(2)
        colonPort = m.group(3)
        path = m.group(4)
        return GitRepository(SshAccess(userAt, host, colonPort, path))
    raise GiveUp("Sorry, I don't know how to handle this repository: %s"%url)
    # regexp.

##########################################################

def _do_cmdline(args):
    original_dir = os.getcwd()
    original_env = os.environ.copy()
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

    rootrepo = builder.invocation.db.repo.get()

    repo = parse_repo_url(rootrepo)

    rules = builder.invocation.all_checkout_rules()
    dirs = []
    for r in rules:
        key = builder.invocation.db.normalise_checkout_label(r.target)
        rel_dir = builder.invocation.db.checkout_locations.get(key, r.target.name)
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
