"""
A RomFS deployment.

This deployment uses genromfs to generate a ROM FS image. It first assembles a
suitable tree in a temporary directory, then runs genromfs to generate the image.

RomFS deployment is modeled after the collect deployment.
"""

import os

import muddled.depend as depend
import muddled.utils as utils
import muddled.filespec as filespec
import muddled.deployment as deployment
import tempfile

from muddled.depend import Action, Label

class RomFSInstructionImplementor(object):
    def prepare(self, builder, instruction, role, path):
        """
        Prepare for rsync
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
        Assembly descriptor constructor
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
            return builder.checkout_path(self.from_label)
        elif (self.from_label.type == utils.LabelType.Package):
            if ((self.from_label.name is None) or
                (self.from_label.name == "*")):
                return builder.role_install_path(self.from_label.role,
                                                            domain = self.from_label.domain)
            else:
                return builder.package_obj_path(self.from_label)
        elif (self.from_label.type == utils.LabelType.Deployment):
            return builder.deploy_path(self.from_label)
        else:
            raise utils.GiveUp("Label %s for romfs action has unknown kind."%(self.from_label))

class RomFSDeploymentBuilder(Action):
    """
    Builds the specified romfs deployment
    """

    def __init__(self, targetName,
                 volumeLabel = None,
                 alignment = None,
                 genRomFS = None):
        self.assemblies = [ ]
        self.target_name = targetName
        self.volume_label = volumeLabel
        self.alignment = alignment
        self.my_tmp = None
        if (genRomFS is None):
            self.genromfs = "genromfs"
        else:
            self.genromfs = genRomFS

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

    def do_genromfs(self, builder, label, my_tmp):
        """
        genromfs everything up into a RomFS image.
        """
        if (self.target_name is None):
            tgt = "rom.romfs"
        else:
            tgt = self.target_name
            
        utils.ensure_dir(builder.deploy_path(label))
        final_tgt = os.path.join(builder.deploy_path(label), 
                                 tgt)
        cmd = "%s -f \"%s\""%(self.genromfs, final_tgt)
        if (self.volume_label is not None):
            cmd = cmd + " -V \"%s\""%self.volume_label
        if (self.alignment is not None):
            cmd = cmd + " -a %d"%(int(self.alignment))
        cmd = cmd + " -d \"%s\""%(my_tmp)
        utils.run_cmd(cmd)
        

    def build_label(self, builder, label):
        """
        Copy everything to a temporary directory and then genromfs it.
        """

        if (self.my_tmp is None):
            self.my_tmp = tempfile.mkdtemp();
            
        print "Deploying to %s .. \n"%self.my_tmp
    
        if (label.tag == utils.LabelTag.Deployed):
            self.apply_instructions(builder, label, True, self.my_tmp)
            self.deploy(builder, label, self.my_tmp)
            self.do_genromfs(builder, label, self.my_tmp)
            utils.recursively_remove(self.my_tmp)
        else:
            raise utils.GiveUp("Attempt to build a deployment with an unexpected tag in label %s"%(label))

    def deploy(self, builder, label, my_tmp):
        for asm in self.assemblies:
            src = os.path.join(asm.get_source_dir(builder), asm.from_rel)
            dst = os.path.join(my_tmp, asm.to_name)
            
            if (not os.path.exists(src)):
                if (asm.fail_on_absent_source):
                    raise utils.GiveUp("Deployment %s: source object %s does not exist"%
                                       (label.name, src))
            else:
                if (asm.using_rsync):
                    # Rsync for great speed!
                    try:
                        os.makedirs(dst)
                    except OSError:
                        pass
                    
                    xdst = dst
                    if (xdst[-1] != '/'):
                        xdst = xdst + '/'
                        
                    utils.run_cmd("rsync -avz \"%s/.\" \"%s\""%(src,xdst))
                elif (asm.recursive):
                    utils.recursively_copy(src, dst, object_exactly = asm.copy_exactly)
                else:
                    utils.copy_file(src, dst, object_exactly = asm.copy_exactly)

    def apply_instructions(self, builder, label, prepare, my_tmp):
        app_dict = get_instruction_dict()

        deploy_path = my_tmp

        for asm in self.assemblies:
            lbl = Label(utils.LabelType.Package, '*', asm.from_label.role,
                        '*', domain = asm.from_label.domain)
            
            if not asm.obeyInstructions:
                continue

            instr_list = builder.load_instructions(lbl)
            for (lbl, fn, instrs) in instr_list:
                print "RomFS: Applying instructions for Role=%s, Label=%s"%(lbl.role, lbl)
                
                for instr in instrs:
                    iname = instr.outer_elem_name()
                    print 'Instruction: ', iname
                    if (iname in app_dict):
                        if prepare:
                            app_dict[iname].prepare(builder, instr, lbl.role, deploy_path)
                        else:
                            app_dict[iname].apply(builder, instr, lbl.role, deploy_path)
                    else:
                        raise utils.GiveUp("RomFS deployments don't know about instruction %s"%iname +
                                           " found in label %s (filename %s)"%(lbl, fn))



def deploy(builder, name, 
           targetName = None,
           volumeLabel = None,
           alignment = None,
           genRomFS = None):
    """
    Create a RomFS deployment builder.

    This adds a new rule linking the label ``deployment:<name>/deployed``
    to the collection deployment builder.

    You can then add assembly descriptors using the other utility functions in
    this module.

    Dependencies get registered when you add an assembly descriptor.

    targetName is the name of the ROM file to generate
    volumeLabel is the volume label
    alignment is the object alignment.
    """
    the_action = RomFSDeploymentBuilder(targetName, volumeLabel, alignment,
                                        genRomFS)
    dep_label = Label(utils.LabelType.Deployment,
                      name, None, utils.LabelTag.Deployed)
    deployment_rule = depend.Rule(dep_label, the_action)

    deployment.register_cleanup(builder, name)
    builder.ruleset.add(deployment_rule)

    iapp_label = Label(utils.LabelType.Deployment, name, None,
                       utils.LabelTag.InstructionsApplied,
                       transient = True)
    iapp_rule = depend.Rule(iapp_label, the_action)
    builder.ruleset.add(iapp_rule)


def copy_from_checkout(builder, name, checkout, rel, dest, 
                       recursive = True,
                       failOnAbsentSource = False,
                       copyExactly = True,
                       domain = None,
                       usingRSync = False):
    rule = deploymnet.deployment_rule_from_name(builder, name)
    dep_label = Label(utils.LabelType.Checkout,
                      checkout, None, utils.LabelTag.CheckedOut, domain=domain)
    asm = AssemblyDescriptor(dep_label, rel, dest, recursive = recursive,
                             failOnAbsentSource = failOnAbsentSource,
                             copyExactly = copyExactly,
                             usingRSync = usingRSync)
    rule.app(dep_label)
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


class RomFSApplyChmod(RomFSInstructionImplementor):
    def prepare(self, builder, instr, role, path):
        return True

    def apply(self, builder, instr, role, path):
        dp = filespec.FSFileSpecDataProvider(path)
        files = dp.abs_match(instr.filespect)
        for f in files:
            utils.run_cmd("chmod %s \"%s\""%(instr.new_mode, f))
        return True

    def needs_privilege(self, builder, instr, role, path):
        return False
    
class RomFSApplyChown(RomFSInstructionImplementor):
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

class RomFSApplyMknod(RomFSInstructionImplementor):
    def prepare(self, builder, instr, role, path):
        return True

    def apply(self, builder, instr, role, path):
        dp = filespec.FSFileSpecDataProvider(path)
        in_dir = os.path.dirname(instr.file_name)
        file_name = os.path.basename(instr.file_name)

        utils.ensure_dir(in_dir)
        if (instr.type == "char"):
            rtype = "c"
        else:
            rtype = "b"

        magic_file = "@%s,%s,%d,%d"%(file_name, rtype, int(instr.major), \
                                         int(instr.minor))
        f = open(os.path.join(in_dir, magic_file), 'w')
        f.close()
        return True


def get_instruction_dict():
    """ 
    Return the instruction dictionary 
    """
    app_dict = { }
    app_dict["chown"] = RomFSApplyChown()
    app_dict["chmod"] = RomFSApplyChmod()
    app_dict["mknod"] = RomFSApplyMknod()
    return app_dict

# End file.
