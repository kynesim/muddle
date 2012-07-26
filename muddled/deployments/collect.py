"""
Collect deployment.

Principally depending on other deployments, this
deployment is used to collect elements built by
other parts of the system into a directory -
usually to be processed by some external tool.
"""

import os

import muddled.depend as depend
import muddled.utils as utils
import muddled.filespec as filespec
import muddled.deployment as deployment

from muddled.depend import Action, Label

class CollectInstructionImplementor(object):
    def prepare(self, builder, instruction, role, path):
        """
        Prepares for rsync. This means fixing up the destination file
        (e.g. removing it if it may have changed uid by a previous deploy)
        so we will be able to rsync it.
        """
        pass
    def apply(self, builder, instruction, role, path):
        pass
    def needs_privilege(self, builder, instr, role, path):
        pass

class AssemblyDescriptor(object):
    def __init__(self, from_label, from_rel, to_name, recursive = True,
                 failOnAbsentSource = False,
                 copyExactly = True,
                 usingRSync = False,
                 obeyInstructions = True):
        """
        Construct an assembly descriptor.

        We copy from the directory from_rel in from_label
        (package, deployment, checkout) to the name to_name under
        the deployment.

        Give a package of '*' to copy from the install directory
        for a given role.

        If recursive is True, we'll copy recursively.

        * failOnAbsentSource - If True, we'll fail if the source doesn't exist.
        * copyExactly        - If True, keeps links. If false, copies the file
          they point to.
        """
        self.from_label = from_label
        self.from_rel = from_rel
        self.to_name = to_name
        self.recursive = recursive
        self.using_rsync = usingRSync
        self.fail_on_absent_source = failOnAbsentSource
        self.copy_exactly = copyExactly
        self.obeyInstructions = obeyInstructions


    def get_source_dir(self, builder):
        if (self.from_label.type == utils.LabelType.Checkout):
            return builder.invocation.checkout_path(self.from_label)
        elif (self.from_label.type == utils.LabelType.Package):
            if ((self.from_label.name is None) or
                self.from_label.name == "*"):
                return builder.invocation.role_install_path(self.from_label.role,
                                                            domain=self.from_label.domain)
            else:
                return builder.invocation.package_obj_path(self.from_label)
        elif (self.from_label.type == utils.LabelType.Deployment):
            return builder.invocation.deploy_path(self.from_label)
        else:
            raise utils.GiveUp("Label %s for collection action has unknown kind."%(self.from_label))

class CollectDeploymentBuilder(Action):
    """
    Builds the specified collect deployment.
    """

    def __init__(self):
        self.assemblies = [ ]

    def add_assembly(self, assembly_descriptor):
        self.assemblies.append(assembly_descriptor)

    def _inner_labels(self):
        """
        Return any "inner" labels, so their domains may be altered.
        """
        labels = []
        for assembly in self.assemblies:
            labels.append(assembly.from_label)
        return labels

    def build_label(self, builder, label):
        """
        Actually do the copies ..
        """

        utils.ensure_dir(builder.invocation.deploy_path(label))

        if (label.tag == utils.LabelTag.Deployed):
            self.apply_instructions(builder, label, True)
            self.deploy(builder, label)
        elif (label.tag == utils.LabelTag.InstructionsApplied):
            self.apply_instructions(builder, label, False)
        else:
            raise utils.GiveUp("Attempt to build a deployment with an unexpected tag in label %s"%(label))

    def deploy(self, builder, label):
        for asm in self.assemblies:
            src = os.path.join(asm.get_source_dir(builder), asm.from_rel)
            dst = os.path.join(builder.invocation.deploy_path(label),
                               asm.to_name)

            if (not os.path.exists(src)):
                if (asm.fail_on_absent_source):
                    raise utils.GiveUp("Deployment %s: source object %s does not exist."%(label.name, src))
                # Else no one cares :-)
            else:
                if (asm.using_rsync):
                    # Use rsync for speed
                    try:
                        os.makedirs(dst)
                    except OSError:
                        pass

                    xdst = dst
                    if xdst[-1] != "/":
                        xdst = xdst + "/"

                    utils.run_cmd("rsync -avz \"%s/.\" \"%s\""%(src,xdst))
                elif (asm.recursive):
                    utils.recursively_copy(src, dst, object_exactly = asm.copy_exactly)
                else:
                    utils.copy_file(src, dst, object_exactly = asm.copy_exactly)

        # Sort out and run the instructions. This may need root.
        need_root = False
        for asm in self.assemblies:
            # there's a from label - does it have instructions?

            # If we're not supposed to obey them anyway, give up.
            if not asm.obeyInstructions:
                continue

            lbl = Label(utils.LabelType.Package, '*', asm.from_label.role,
                        '*', domain=asm.from_label.domain)
            install_dir = builder.invocation.role_install_path(lbl.role, label.domain)
            instr_list = builder.load_instructions(lbl)
            app_dict = get_instruction_dict()

            for (lbl, fn, instr_file) in instr_list:
                # Obey this instruction?
                for instr in instr_file:
                    iname = instr.outer_elem_name()
                    if (iname in app_dict):
                        if (app_dict[iname].needs_privilege(builder, instr, lbl.role, install_dir)):
                            need_root = True
                    # Deliberately do not break - we want to check everything for
                    # validity before acquiring privilege.
                    else:
                        raise utils.GiveUp("Collect deployments don't know about " +
                                            "instruction %s"%iname +
                                            " found in label %s (filename %s)"%(lbl, fn))


        print "Rerunning muddle to apply instructions .. "

        permissions_label = Label(utils.LabelType.Deployment,
                                  label.name, None, # XXX label.role,
                                  utils.LabelTag.InstructionsApplied,
                                  domain = label.domain)

        if need_root:
            print "I need root to do this - sorry! - running sudo .."
            utils.run_cmd("sudo %s buildlabel '%s'"%(builder.muddle_binary,
                                                     permissions_label))
        else:
            utils.run_cmd("%s buildlabel '%s'"%(builder.muddle_binary,
                                                permissions_label))

    def apply_instructions(self, builder, label, prepare):
        app_dict = get_instruction_dict()

        for asm in self.assemblies:
            lbl = Label(utils.LabelType.Package, '*', asm.from_label.role,
                        '*', domain = asm.from_label.domain)

            if not asm.obeyInstructions:
                continue

            deploy_dir = builder.invocation.deploy_path(label)

            instr_list = builder.load_instructions(lbl)
            for (lbl, fn, instrs) in instr_list:
                print "Collect deployment: Applying instructions for role %s, label %s .. "%(lbl.role, lbl)
                for instr in instrs:
                    # Obey this instruction.
                    iname = instr.outer_elem_name()
                    print 'Instruction:', iname
                    if (iname in app_dict):
                        if prepare:
                            app_dict[iname].prepare(builder, instr, lbl.role, deploy_dir)
                        else:
                            app_dict[iname].apply(builder, instr, lbl.role, deploy_dir)
                    else:
                        raise utils.GiveUp("Collect deployments don't know about instruction %s"%iname +
                                            " found in label %s (filename %s)"%(lbl, fn))


def deploy(builder, name):
    """
    Create a collection deployment builder.

    This adds a new rule linking the label ``deployment:<name>/deployed``
    to the collection deployment builder.

    You can then add assembly descriptors using the other utility functions in
    this module.

    Dependencies get registered when you add an assembly descriptor.
    """
    the_action = CollectDeploymentBuilder()

    dep_label = Label(utils.LabelType.Deployment,
                      name, None, utils.LabelTag.Deployed)

    deployment_rule = depend.Rule(dep_label, the_action)

    # We need to clean it as well, annoyingly ..
    deployment.register_cleanup(builder, name)

    builder.invocation.ruleset.add(deployment_rule)

    # InstructionsApplied is a standalone rule, invoked by the deployment
    iapp_label = Label(utils.LabelType.Deployment, name, None,
                       utils.LabelTag.InstructionsApplied,
                       transient = True)
    iapp_rule = depend.Rule(iapp_label, the_action)
    builder.invocation.ruleset.add(iapp_rule)


def copy_from_checkout(builder, name, checkout, rel, dest,
                       recursive = True,
                       failOnAbsentSource = False,
                       copyExactly = True,
                       domain = None,
                       usingRSync = False):
    rule = deployment.deployment_rule_from_name(builder, name)

    dep_label = Label(utils.LabelType.Checkout,
                      checkout, None, utils.LabelTag.CheckedOut, domain=domain)

    asm = AssemblyDescriptor(dep_label, rel, dest, recursive = recursive,
                             failOnAbsentSource = failOnAbsentSource,
                             copyExactly = copyExactly,
                             usingRSync = usingRSync)
    rule.add(dep_label)
    rule.action.add_assembly(asm)

def copy_from_package_obj(builder, name, pkg_name, pkg_role, rel,dest,
                          recursive = True,
                          failOnAbsentSource = False,
                          copyExactly = True,
                          domain = None,
                          usingRSync = False):
    """
      - If 'usingRSync' is true, copy with rsync - substantially faster than
           cp, if you have rsync. Not very functional if you don't :-)
    """

    rule = deployment.deployment_rule_from_name(builder, name)

    dep_label = Label(utils.LabelType.Package,
                      pkg_name, pkg_role, utils.LabelTag.Built, domain=domain)
    asm = AssemblyDescriptor(dep_label, rel, dest, recursive = recursive,
                             failOnAbsentSource = failOnAbsentSource,
                             copyExactly = copyExactly,
                             usingRSync = usingRSync)
    rule.add(dep_label)
    rule.action.add_assembly(asm)

def copy_from_role_install(builder, name, role, rel, dest,
                           recursive = True,
                           failOnAbsentSource = False,
                           copyExactly = True,
                           domain = None,
                           usingRSync = False,
                           obeyInstructions = True):
    """
    Add a requirement to copy from the given role's install to the named deployment.

    'name' is the name of the collecting deployment, as created by::

        deploy(builder, name)

    which is remembered as a rule whose target is ``deployment:<name>/deployed``,
    where <name> is the 'name' given.

    'role' is the role to copy from. Copying will be based from 'rel' within
    the role's ``install``, to 'dest' within the deployment.

    The label ``package:(<domain>)*{<role>}/postinstalled`` will be added as a
    dependency of the collecting deployment rule.

    An AssemblyDescriptor will be created to copy from 'rel' in the install
    directory of the label ``package:*{<role>}/postinstalled``, to 'dest'
    within the deployment directory of 'name', and added to the rule's actions.

    So, for instance::

        copy_from_role_install(builder,'fred','data','public','data/public',
                               True, False, True)

    might copy (recursively) from::

        install/data/public

    to::

        deploy/fred/data/public

    'rel' may be the empty string ('') to copy all files in the install
    directory.

    - If 'recursive' is true, then copying is recursive, otherwise it is not.
    - If 'failOnAbsentSource' is true, then copying will fail if the source
      does not exist.
    - If 'copyExactly' is true, then symbolic links will be copied as such,
      otherwise the linked file will be copied.
    - If 'usingRSync' is true, copy with rsync - substantially faster than
         cp, if you have rsync. Not very functional if you don't :-)
    - If 'obeyInstructions' is False, don't obey any applicable instructions.
    """
    rule = deployment.deployment_rule_from_name(builder, name)
    dep_label = Label(utils.LabelType.Package,
                      "*", role, utils.LabelTag.PostInstalled, domain=domain)
    asm = AssemblyDescriptor(dep_label, rel, dest, recursive = recursive,
                             failOnAbsentSource = failOnAbsentSource,
                             copyExactly = copyExactly,
                             usingRSync = usingRSync,
                             obeyInstructions = obeyInstructions)
    rule.add(dep_label)
    rule.action.add_assembly(asm)

def copy_from_deployment(builder, name, dep_name, rel, dest,
                         recursive = True,
                         failOnAbsentSource = False,
                         copyExactly = True,
                         domain = None,
                         usingRSync = False):
    """
    usingRSync - set to True to copy with rsync - substantially faster than
                 cp
    """
    rule = deployment.deployment_rule_from_name(builder,name)
    dep_label = Label(utils.LabelType.Deployment,
                      dep_name, None, utils.LabelTag.Deployed, domain=domain)
    asm = AssemblyDescriptor(dep_label, rel, dest, recursive = recursive,
                             failOnAbsentSource = failOnAbsentSource,
                             copyExactly = copyExactly,
                             usingRSync = usingRSync)
    rule.add(dep_label)
    rule.action.add_assembly(asm)

# And the instruction implementations:
class CollectApplyChmod(CollectInstructionImplementor):
    def prepare(self, builder, instr, role, path):
        return True

    def apply(self, builder, instr, role, path):

        dp = filespec.FSFileSpecDataProvider(path)

        files = dp.abs_match(instr.filespec)
        # @todo We _really_ need to use xargs here ..
        for f in files:
            utils.run_cmd("chmod %s \"%s\""%(instr.new_mode, f))
        return True

    def needs_privilege(self, builder, instr, role, path):
        # You don't, in general, need root to change permissions.
        # Except, you do in order to chmod setuid after a chown ...
        return True

class CollectApplyChown(CollectInstructionImplementor):
    def prepare(self, builder, instr, role, path):
        return self._prep_or_apply(builder, instr, role, path, True)

    def apply(self, builder, instr, role, path):
        return self._prep_or_apply(builder, instr, role, path, False)

    def _prep_or_apply(self, builder, instr, role, path, is_prepare):

        # NB: take care to apply a chown command to the file named,
        # even if it is a symbolic link (the default is --reference,
        # which would only apply the chown to the file the symbolic
        # link references)

        dp = filespec.FSFileSpecDataProvider(path)
        files = dp.abs_match(instr.filespec)
        if (instr.new_user is None):
            cmd = "chgrp %s"%(instr.new_group)
        elif (instr.new_group is None):
            cmd = "chown --no-dereference %s"%(instr.new_user)
        else:
            cmd = "chown --no-dereference %s:%s"%(instr.new_user, instr.new_group)

        for f in files:
            if is_prepare:
                # @TODO: This doesn't handle directories that have been
                # chowned and will collapse in a soggy heap. If support for
                # those is required, need to either:
                #   sudo rm -rf dir
                #   sudo chown -R <nonprivuser> dir
                #   or just run the whole rsync under sudo.
                utils.run_cmd("rm -f \"%s\""%f)
            else:
                utils.run_cmd("%s \"%s\""%(cmd, f))

    def needs_privilege(self, builder, instr, role, path):
        return True


def get_instruction_dict():
    """
    Return a dictionary mapping the names of instructions to the
    classes that implement them.
    """
    app_dict = { }
    app_dict["chown"] = CollectApplyChown()
    app_dict["chmod"] = CollectApplyChmod()
    return app_dict

# End file.
