#! /usr/bin/python
# 

"""
Given two stamp files, work out what has changed between them.

For each checkout, we produce a directory containing:

 - A git log between the two revisions
 - A list of patches, one patch file per commit.

We then produce a single summary file containing all git log
entries for every repository.

Syntax: interpatch.py [options] <tree> <from_stamp> <to_stamp> <result_dir>

Options:

 --allow-failure         Allow git to fail and insert [FAILURES] into the result.

"""

import traceback
import sys
import re
import os
import subprocess
import time
import ConfigParser
import datetime
import getpass

g_allow_failure = False
g_nr_failures = 0

class Error(Exception):
    """
    Oh no!
    """
    pass

def debug(s):
    print(s)
    pass

def run_or_die(what, inputData = None, outputFile = None, allowedToFail = False,
               allowedRc = 0):
    cmd = " ".join(what)
    print "> %s"%(cmd)
    p = subprocess.Popen(cmd, shell = True, stderr=subprocess.PIPE, 
                         stdout=subprocess.PIPE, stdin = subprocess.PIPE)
    (output,error) = p.communicate(inputData)

    if (outputFile is not None):
        f = open(outputFile, "w")
        f.write(output)
        f.close()

    rc = p.wait()
    if (rc != allowedRc and (not allowedToFail)):
        raise Error("Can't run %s - %s"%(cmd, rc))
    #print output
    #print error
    return (rc, output)


class Log:
    """
    Deals with writing log files
    """
    def __init__(self, file_name):
        self.f = open(file_name, 'w')
        self.p = ConfigParser.RawConfigParser()
        if g_allow_failure:
            self.p.add_section("FAILURES")

    def close(self):
        self.p.write(self.f)
        self.f.close()

    def start(self,ip):
        self.p.add_section("START")
        now = datetime.datetime.now()
        self.p.set("START", "stamp_from", ip.sfrom.fn)
        self.p.set("START", "stamp_to", ip.sto.fn)
        self.p.set("START", "user", getpass.getuser())
        self.p.set("START", "host", (os.uname())[1])
        self.p.set("START", "on", now.isoformat())
                     

class Stamp:
    def __init__(self, fn):
        self.fn = fn
        self.p = ConfigParser.RawConfigParser()
        self.p.read(fn)
        self.checkouts = { }
        self.check_version()
        self.read_base_data()
        self.read_checkouts()


    def check_version(self):
        self.vsn = int(self.p.get('STAMP', 'version'))
        debug ("Stamp %s has version %d"%(self.fn, self.vsn))
        if not (self.vsn == 2):
            raise Error("Invalid version stamp %d for %s"%(self.vsn, self.fn))

    def read_base_data(self):
        """
        Read out the [root] label and get the repository info
        """
        self.repo = self.p.get('ROOT','repository')

    def read_checkouts(self):
        """
        Populates self.repos, which is a list of dictionaries:
        name => name
        repo => repository
        rev => revision
        """
        sections = self.p.sections()
        for section in sections:
            scomponents = section.split(" ")
            if (len(scomponents) > 0 and scomponents[0] == "CHECKOUT"):
                checkout = scomponents[1]
                debug("Reading data for checkout %s .. "%(checkout))
                repo = None
                if (self.p.has_option(section, "repo_from_url_string")):
                    repo = self.p.get(section, "repo_from_url_string")
                    if (repo == "None"): 
                        repo = None

                if repo is None:
                    repo_name = self.p.get(section, "repo_name")
                    if (self.p.has_option(section, "repo_prefix")):
                        repo_dir = self.p.get(section, "repo_prefix")
                        repo_ext = os.path.join(repo_dir, repo_name)
                    else:
                        repo_dir = None
                        repo_ext = repo_name
                    repo_base = self.p.get(section, "repo_base_url")
                    repo = os.path.join(repo_base, repo_ext)

                co = None
                co_name = self.p.get(section, "co_leaf")
                if (self.p.has_option(section, "co_dir")):
                    co_dir = self.p.get(section, "co_dir")
                    co= os.path.join(co_dir, co_name)
                else:
                    co = co_name

                if (self.p.get(section, "repo_vcs") != "git"):
                    raise Error("Interpatch will only work with git repositories; sorry.\n")
                rev = self.p.get(section, "repo_revision")

                cdict = { }
                cdict["name"] = checkout
                cdict["repo"] = repo
                cdict["rev"] = rev
                cdict["co"] = co
                if checkout in self.checkouts:
                    raise Error("Duplicate checkout name %s in %s"%(checkout, self.fn))
                self.checkouts[checkout] = cdict
                debug("   repo = %s"%repo)
                debug("   rev = %s"%rev)


    def missing_repo_report(self, a_log, section_name, other):
        """
        Find the repositories which are in this, but not in other
        """
        missing = []
        a_log.p.add_section(section_name)
        print "Running missing repo report.."
        for in_self in self.checkouts:
            print " checking %s\n"%in_self
            if (not (in_self in other.checkouts)):
                a_log.p.set(section_name, in_self, self.checkouts[in_self]["repo"])
                missing.append(in_self)
                
        return missing

class Commit:
    def __init__(self, cid, hdrs, log):
        self.cid = cid
        self.hdrs = hdrs
        self.log = log
        self.prune_log()

    def prune_log(self):
        new_log = [ ]
        # Remove all the blank lines at the start and end.
        started = False
        last_line = 0
        for l in self.log:
            if (len(l) > 0):
                started = True
                last_line = len(new_log)
                
            if started:
                new_log.append(l)
        self.log = new_log[0:last_line+1]

    def __str__(self):
        return "Commit[id=%s hdrs=%s log=%s]"%(self.cid,self.hdrs,self.log)

    def do_log(self, log, nr, sect):
        log.p.set(sect, "commit-%d"%nr, self.cid)
        for hdr in self.hdrs:
            log.p.set(sect,"commit-%d-%s"%(nr,hdr), self.hdrs[hdr])
        i = 0
        for lne in self.log:
            log.p.set(sect, "commit-%d-log%d"%(nr,i), lne)
            i = i +1
        

class Repo:
    def __init__(self, repo):
        self.repo = repo

    def get_path(self):
        if (os.path.isdir(os.path.join(self.repo, ".git"))):
            p = os.path.join(self.repo, ".git")
        else:
            p = self.repo 
        return p


    def do_diff(self, id1, id2,log):
        """
        Do a git log id1 .. id2, 
        """
        global g_nr_failures
        global g_allow_failure
        debug("Processing diffs for %s: %s .. %s "%(self.repo, id1, id2))
        sha_id1 = id1 # self.r.ref(id1)
        sha_id2 = id2 # self.r.ref(id2)
        # is self.repo a bare repository?
         
        cmd = ["git", "--git-dir=%s"%(self.get_path()), "log", "%s..%s"%(id1,id2)];

        (rc,changes) = run_or_die(cmd,
                                  allowedToFail = g_allow_failure)
        if (rc != 0):
            # git failed.
            log.p.set("FAILURES", "%d-cmd"%g_nr_failures, " ".join(cmd))
            log.p.set("FAILURES", "%d-result"%g_nr_failures, changes)
            log.p.set("FAILURES", "%d-rc"%g_nr_failures, rc)
            g_nr_failures = g_nr_failures + 1
            return [ ]

        # Now we have to iterate through the changes, producing a dictionary for each one.
        #print "Matching .. in %s"%changes
        hex_pattern = re.compile(r'([0-9a-fA-F]+)$')
        header_pattern = re.compile(r'([^:]+):\s*(.*)$')
        commit_id = None
        commits = [ ]
        log_message = [ ]

        lines = changes.split('\n')
        for l in lines:
            if (l.find('commit ') == 0):
                # This is a new commit id. commit the old one .. 
                if (commit_id is not None):
                    commits.append(Commit(commit_id, headers, log_message))
                # then ..
                m =  hex_pattern.search(l)
                if (m is None):
                    raise Error("Could not parse git commit line: '%s'"%l)
                commit_id = m.group(1)
                headers = { }
                log_message = [ ]
            else:
                # Is it a header line?
                h = header_pattern.search(l)
                if (h is None):
                    # Cannot be a header, must be text.
                    log_message.append(l.strip())
                else:
                    headers[h.group(1)] = h.group(2)

        if commit_id is not None:
            commits.append(Commit(commit_id, headers, log_message))

        return commits

    def log_commits(self, commits, log, sect):
        log.p.add_section(sect)
        nr = 0
        for commit in commits:
            commit.do_log(log, nr, sect)
            nr = nr + 1
    
    def dump_diffs(self, commits, where):
        """
        Dump the diffs for a set of commits into a directory somewhere
        """
        i = 0
        for c in commits:
            run_or_die(["git", "--git-dir=%s"%(self.get_path()), "show", "%s"%(c.cid) ],
                       outputFile = os.path.join(where, "%d-%s.diff"%(i,c.cid)))
            i= i + 1
        

    

class InterPatch:


    def __init__(self, tree, from_fn, to_fn):
        self.tree = tree
        self.sfrom = Stamp(from_fn)
        self.sto = Stamp(to_fn)

    def do_missing(self, log):
        # Things missing from To means removed.
        self.checkouts_added = self.sfrom.missing_repo_report(log, 'Checkouts-Removed', self.sto)
        # Things missing from From means added.
        self.checkouts_removed = self.sto.missing_repo_report(log, 'Checkouts-Added', self.sfrom)

    def do_repo_diff(self, log, out_dir):
        for in_from in self.sfrom.checkouts:
            if (in_from in self.sto.checkouts):
                co_from = self.sfrom.checkouts[in_from]
                co_to = self.sto.checkouts[in_from]
                if (co_from["co"] != co_to["co"]):
                    raise Error("Interpatch does not yet support moving checkouts")
                a_repo = Repo(os.path.join(self.tree, 'src', co_from["co"]))
                sect = "Checkout %s"%in_from
                commits = a_repo.do_diff(co_from["rev"], co_to["rev"], log)
                a_repo.log_commits(commits, log, sect)
                long_dir = os.path.join(out_dir, co_from["co"]);
                try:
                    os.makedirs(long_dir)
                except OSError,e:
                    pass
                a_repo.dump_diffs(commits, long_dir)

                

def go(args):
    global g_allow_failure

    while args:
        word = args[0]
        if word in ('-h','-?','--help'):
            print __doc__
            return
        elif word in ('--allow-failure'):
            g_allow_failure = True
        else:
            break
        args = args[1:]

    if (len(args) != 4):
        print __doc__
        return

    (tree, from_stamp,to_stamp, result_dir) = args;
    print "Interpatch on %s from %s to %s  => %s \n"%(tree, from_stamp,to_stamp,result_dir)
    ip = InterPatch(tree,from_stamp, to_stamp)
    try:
        os.mkdir(result_dir)
    except OSError,e:
        pass
    log_file_name = os.path.join(result_dir, "log.txt")
    the_log = Log(log_file_name)
    try:
        the_log.start(ip)

        ip.do_missing(the_log)
        ip.do_repo_diff(the_log, result_dir)

    finally:
        the_log.close()
        

            


if __name__ == "__main__":
    try:
        go(sys.argv[1:])
    except Error, e:
        print "%s"%e
        traceback.print_exc()
        sys.exit(1)


# End file.

