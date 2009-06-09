Welcome to Muddle 
-----------------

Muddle is a package-level build system. It aims to do for software and
firmware distributions what Make does for individual software
packages.

Muddle's design philosophy is the same as UNIX's: mechanism, not
policy. As a result you'll discover that muddle will let you do nearly
anything you like. You'll also discover that doing anything you like
sometimes doesn't make you popular among your peers.


Labels
------

(Nearly) everything in muddle is described by a label. 
A label is structured as:

<type>:<name>-<role>/<tag>[<flags>]

Any component of a label may be wildcarded with '*' and
a role (only!) may be omitted. All components are made
up of the characters [A-Z0-9a-z*_] only. names beginning
with an underscore are reserved by muddle.

Muddle does not constrain the values of labels - you may 
use any string for any component. However, certain labels
are special:

<type>: is typically

  checkout          Describes a unit of source control
  package           Describes a unit of software build
  deploy            Describes a unit of software installation


<tag>:  is typically

  checked_out       The state of a copy having been taken from
                      revision control
  pulled            Changes have been taking from revision control
                      but not yet applied to the local copy
  up_to_date        All changes in revision control for this 
                      branch have been applied.
  changes_committed Local changes committed, but not yet written
                      back to version control
  changes_pushed    Local changes have bene pushed back to revision
                      control

  preconfig         Preconfiguration checks have been made on a package
  configured        A package has been configured
  built             A package has been built
  installed         A package has been installed
  postinstalled     A package has been postinstalled

  deployed          A deployment has been created


Muddle's central algorithms revolve around describing the relationships
between components by linking labels in rules. Rules are similar to
make rules:


target: dependencies
   <command>


Except that the target and dependency lists contain (possibly wildcarded)
labels rather than simple strings.


Muddle's view of the build process
----------------------------------

Muddle believes that a build process consists of the following
steps:

 1. Check a number of checkouts out of source control
    (stored in $MUDDLE_ROOT/src)

 2. Build a set of packages from them. Each package may be built
   in a number of roles - intended for different use cases, so
   you may have a libc/arm and a libc/x86, for example.
   (packages are built in $MUDDLE_ROOT/obj/<pkg>/</role>)

 3. Install each role into a different installation directory.
   (packages are installed into $MUDDLE_ROOT/install/<role>)

 4. Build these role installations into a series of objects
   suitable for installation on some target machine
   (deployments are installed into $MUDDLE_ROOT/deploy)

There is often a 1-1 association between checkouts and packages, roles
and deployments, but muddle does not enforce this - and in fact, many
to many associations between these objects can be used to implement
common workflows - picking different elements of a single role to
populate 'lite' and 'full' versions of firmware, or using the same
checkout to build different architectures, for example.


Build Descriptions and the muddle database
------------------------------------------

To build your system, Muddle needs a machine-readable description
of it and it needs some filespace in which to build. You provide
filespace by initialising a muddle build tree in some convenient
filesystem location. You provide the description of what to build
with a build description.

A build description is a perfectly normal piece of python containing
a subroutine:

def describe_to(builder)

 Which is called to load information about your software into an
object called a 'builder' (see muddled/mechanics.py) which can
then build your software.

 Several examples are provided in the examples/ directory and 
utility APIs are provided to build packages controlled by make, 
to ensure that the host has certain Debian packages installed, 
to build a target filesystem with the right file permissions, etc.

 The build description is stored in a checkout in revision control 
along with everything else in your system - muddle will 
automatically check it out when needed. 

 Apart from some bootstrapping rules, the build description 
checkout is a perfectly normal checkout and you can manipulate
it with the same tools you would any other checkout. 

 It is strongly advised that you call your build description checkout
'builds'. Again, muddle will not enforce this - it's just good
practice.

 Note that your build descriptions are perfectly sensible python
programs in their own right and are welcome to do almost anything
they like - specifically, you are encouraged to use inheritance and
imports to place the common parts of your build descriptions in a
single file. This can greatly aid configuration management.

 Muddle will track your build using a database stored in a
'.muddle' directory. The structure of this database is well-known
and you are actively encouraged to edit it by hand to resolve
any problems you might have:

 .muddle/
 .muddle/Description       Path from the src directory to the build description
                             file for this build.
 .muddle/RootRepository    URL for the root of the repository from which to 
                             fetch checkouts (you can override this in your
                             build description if you want to - it's just
                             a useful default)
 .muddle/tags/..           If a label is asserted, there will be a file
                              corresponding to it here. You can touch these
                              files to synthetically assert labels or 
                              remove them to retract them.
 .muddle/instructions/<pkg>/</role>
                           Instruction files - these hold pending install
                            directions for the deploy step to use.
 
Multiple Files and Inheritance in Build Descriptions
----------------------------------------------------

Muddle automatically adds the build description's checkout directory to
sys.path before it imports your build description. This allows you to
treat the build description directory as a python package from which
you can import additional build description helper files at will - e.g.

in builds/foo.py

import bar


def describe_to(builder):
    bar.do_common_setup() 
    ...



Environment variables, sudo and instructions
---------------------------------------------

 In order to successfully build your package, your makefile (or whatever)
is going to need to know a few things. Among them are commonly:

 Where should I install my object files/binaries?
 Where will those directories be on the target system?
 How do I set permissions/change ownerships of my created directories?

 Some of these can be answered by setting environment variables. Muddle
sets a number of variables itself:

 MUDDLE_ROOT        The directory with the .muddle directory in it.
 MUDDLE_LABEL 
  MUDDLE_KIND
  MUDDLE_NAME
  MUDDLE_ROLE
  MUDDLE_TAG        The label we're currently building, and its components.
 MUDDLE_INSTALL     Where do we install package files to?
                       (typically under $MUDDLE_ROOT/install)
 MUDDLE_DEPLOY_FROM Where do we deploy from (typically $MUDDLE_ROOT/install/<role>)
 MUDDLE_DEPLOY_TO   Where do we deploy to? (typically $MUDDLE_ROOT/deploy/<deployment>)
 MUDDLE             How to call muddle itself
 MUDDLE_INSTRUCT
 MUDDLE_UNINSTRUCT  Used by the instruction system - see below.

 And the facility to associate environments with a (possibly wildcarded) label.
This allows you to associate any extra environment variables you want from
your build description to various labels - all packages, for example, or all
roles.

 Take a look at muddled/env_store.py and muddled/mechanism.py for details.

 This doesn't tell you where your package will end up on the target system.
It doesn't tell you because it doesn't know. You'll typically be required to
give this information when you ask muddle to create a deployment, and most
deployments define:

 MUDDLE_TARGET_LOCATION

 To tell you where the deployment will end up.
 
 Even so, there are things that can't be done by your makefile.

 Creation of initrds with proper filesystems and changes of ownership, for
example, cannot (in general) be done by makefiles or package builds of other
kinds because they are running as a mortal user and those operations
require root privilege. 

 Traditionally, build systems have got around this by sudo ing at random
times and expecting you to either have passwordless sudo access (a security
risk) or type in your password at irregular interfaces (which is just
annoying).

 Muddle uses things called instructions.

 The idea of instructions is that during your makefile, you run a command
like:

 $(MUDDLE_INSTRUCT) instr-file.xml

 Where instr-file.xml contains a series of instructions about what to do 
after deployment, potentially as root. There are examples in examples/c and
examples/d (and see muddled/filespec.py for a detailed description of what
you can do with filespecs).

 $(MUDDLE_INSTRUCT) causes muddle to take the specified XML, check its 
syntax, and stash a copy of the commands contained therein in .muddle/instructions
(see, that's what it's for .. :-)).

 When the deployment has copied all its files to deploy/ , it looks for 
stored instructions from the packages and roles that it incorporated and 
obeys them (it can also register some of its own, of course).

 If root privilege is required to complete the deployment, having assembled
the instructions it needs to run, the deployment can ask for your password
just once and leave you alone the rest of the time. This means you can 
have passworded sudo access and leave your machine happily building whilst
you go for coffee without coming back to discover that your machine's
been sitting there for 15 minutes waiting for you to type your password.

 For completeness, if you're cleaning your package you should probably not
leave these cached instructions lying about:

 $(MUDDLE_UNINSTRUCT) 

 Will do the right thing.

Version control
---------------

 Muddle is version-control agnostic.

 muddle vcs

 Will tell you which version control systems your copy of muddle currently 
supports. Feel free to add your favourites!

 Every VCS is slightly different so muddle's one-model-fits-all approach
is sometimes a little awkward. Sorry about that - improvements gratefully
recieved - but it does basically work, and it's a lot better than having to
bolt your VCS on over the top (or, worse, switch VCS!)

 As usual, muddle itself doesn't restrict you here: your project
needn't use the same repository, or indeed the same VCS for all its
checkouts. However, most do and to help with this muddle has the idea
of a root repository stored in the .muddle/RootRepository file. This
is typically initialised to the repository you got your build
description from and it's strongly advised that you leave it there.

 Muddle describes repositories with three elements:

 repository URL
 relative path (rest)
 revision

 The repository URL is always of the form:

 [vcs]+[scheme]://[host]/[file]

 And the precise meaning is delegated to the VCS plugin involved
(see muddled/vcs/*):

  file+file:///<path>       - Copy files from the given path
                              (useful for building the examples)
  bzr+[URL]                 - The bazaar repository at [URL]
  git+[URL]                 - The git repository at [URL]
  svn+[URL]                 - The Subversion repository at [URL]
  cvs+pserver://[host]/[path] - The CVS repository at host and path.

 The relative path is generally tacked onto the end of the URL for
 retrieval purposes - so each checkout for bazaar, for example, is
 a separate bazaar repository - however, for CVS it is the CVS
 module name - and if you want to use perforce you'll probably want
 to use it this way there too.

 The revision specifies which revision or branch we should check out -
 with git it's the branch, with bazaar it could be a tag, with CVS it's
 the (probably sticky?) tag. The special value 'HEAD' means the current
 head.
 
 By default, you'd specify a checkout with:

 muddled.checkouts.simple.relative(builder, co_name)

 Which just checks out HEAD of repository = RootRepository, relative path = 
co_name , but you can specify your own repositories, revisions, etc. to 
construct more complex arrangements of checkouts.

 A word of caution here: it's possible to get really quite tangled in
complex repository layouts and this can make configuration management
a nightmare. Muddle is happy to let you shoot yourself in this
particular foot, but you might prefer not to.

The build process
-----------------

 A quick start :-). To build, say, example D, assuming you've checked
muddle out in $MUDDLE_DIR and added that directory to your path:

$ cd /somewhere/convenient
$ muddle init file+file:///$MUDDLE_DIR/examples/d builds/01.py

 - this initialises a muddle build tree with 

 file+file:///$MUDDLE_DIR/examples/d 

 as its repository and a build description of 'builds/01.py'. 
 
 The astute will notice that you haven't told muddle which actual
repository the build description is in - you've only told it where
the repository root is and where the build description _file_ is. 

 Muddle guesses (and at this point it's a very good idea not to 
try and contradict it - sorry!) that 'builds/01.py' means
'repository file+file:///$MUDDLE_DIR/examples/d/builds, file 01.py'.

 Note that muddle init checks out the build description for the sake
of politeness - it doesn't really need to, but it feels it probably
ought to for the sake of form.

$ muddle

 This is a bit of a cheat. When run with no arguments, muddle attempts
to 'do what you mean' (see 'DWIM' below). In this case, you're in
the build root and the build description has said:

 builder.by_default_deploy("example_d")

 - which says 'when someone runs muddle, and you can't think of something
better to do, try to deploy the deployment example_d'.

 As a result, muddle will:

 * Fetch d_co (the single checkout in this build)
 * Build the d_pkg package that depends on it and install it in role x86.
 * Deploy example_d, which depends on the x86 role which d_pkg is in.

 You'll need to type your password since it wants to chown the resulting
hello_world executable to root:root, and you should end up with:

rrw@minervois:~/tmp/m4$ ls -lR deploy/
deploy/:
total 4
drwxr-xr-x 3 rrw rrw 4096 2009-06-05 19:15 example_d

deploy/example_d:
total 4
drwxr-xr-x 2 rrw rrw 4096 2009-06-05 19:15 bin

deploy/example_d/bin:
total 4
-rwxr-xr-x 1 root root 888 2009-06-05 19:15 hello_world

 .. which shows the built, deployed hello_world binary with the right
ownership and permissions. If you're feeling adventurous, you can even
run it:

rrw@minervois:~/tmp/m4$ ./deploy/example_d/bin/hello_world
Hello, muddle test D world!
rrw@minervois:~/tmp/m4$

 Amazing, huh? :-)

Available Muddle Commands
-------------------------

 The list of available muddle commands, together with documentation,
can be got from:

$ muddle help

 - it's best to read the documentation from there, rather than anything here.

 A rebuild occurs when you pretend that an object has been updated and then
try to remake everything that depends on it.

 A build does not imply a deployment! (this helps to avoid endless prompts
to enter your password).

DWIM
----

 When you invoke muddle with no arguments, it will try to guess what you meant.
To help it, the build description gives it:

 * A list of default roles.
 * A default label.

 The rules it uses are these:

If you invoke muddle from a checkout
------------------------------------

 Rebuild all the packages that depend on this checkout, in all the default roles.

If you invoke muddle from a package build directory
---------------------------------------------------

 Rebuild this package and role.


If you invoke muddle from a package install directory
-----------------------------------------------------

 Build every package in this role.
 

If you invoke muddle from a deployment directory
------------------------------------------------

 Deploy this deployment


If you invoke muddle from the root
----------------------------------

 Build the default label, if there is one.


If you don't give an action command like build, rebuild, etc., an
argument, muddle will apply these rules to guess what it should be
building, rebuilding, etc.

The choice of verb above is a carefully tuned compromise between 
forcing long build times on (not-so-)innocents who typed muddle whilst
in the wrong directory and failing to rebuild packages that might have
been changed in an over-optimistic attempt to trim the amount of
work we need to do.

They will probably need further tuning, and feedback is actively 
solicited on them. If you feel really deeply about it, you could even
(shock! horror!) submit a patch.

Licencing
---------

 muddle is licenced under the MPL 1.1 .

Any other queries?
-----------------

 Richard Watts, <rrw@kynesim.co.uk> is the man to call. Enjoy!



End File
--------
