"""
File deployment. This deployment just copies files into a 
role subdirectory in the /deployed directory, applying 
appropriate instructions.
"""

import muddled
import muddled.pkg as pkg
import muddled.env_store
import muddled.depend as depend
import muddled.utils as utils
import muddled.filespec as filespec
import muddled.deployment as deployment

class FileInstructionImplementor:
    def apply(self, builder, instruction, role, path):
        pass

    def needs_privilege(self, builder, instr, role, path):
        pass


class FileDeploymentBuilder(pkg.Dependable):
    """
    Builds the specified file deployment
    """
    
    def __init__(self, roles, builder, target_dir):
        self.builder = builder
        self.target_dir = target_dir
        self.roles = roles

    def attach_env(self):
        """
        Attaches an environment containing:
        
        MUDDLE_TARGET_LOCATION   the location in the target filesystem where 
                                  this deployment will end up.

        To every package label in this role.
        """
        
        for role in self.roles:
            lbl = depend.Label(utils.LabelKind.Package,
                               "*",
                               role,
                               "*")
            env = self.builder.invocation.get_environment_for(lbl)
        
            env.set_type("MUDDLE_TARGET_LOCATION", muddled.env_store.EnvType.SimpleValue)
            env.set("MUDDLE_TARGET_LOCATION", self.target_dir)

    def build_label(self, label):
        """
        Performs the actual build.

        We actually do need to copy all files from install/ (where unprivileged
        processes can modify them) to deploy/ (where they can't).

        Then we apply instructions to deploy.
        """

        if (label.tag == utils.Tags.Deployed):
            # We want to deploy 
            self.deploy(label)
        elif (label.tag == utils.Tags.InstructionsApplied):
            self.apply_instructions(label)
        else:
            raise utils.Failure("Attempt to build a deployment with an unknown in label %s"%(label))

    def deploy(self, label):
        deploy_dir = self.builder.invocation.deploy_path(label.name)
        # First off, delete the target directory
        
        utils.recursively_remove(deploy_dir)
        utils.ensure_dir(deploy_dir)

        for role in self.roles:
            print "> Installing role %s .. "%(role)
            install_dir = self.builder.invocation.role_install_path(role)
            utils.recursively_copy(install_dir, deploy_dir)
        

        # This is somewhat tricky as it potentially requires privilege elevation.
        # Privilege elevation is done by hooking back into ourselves via a 
        # build command to a label we registered earlier.
        #
        # Note that you cannot split instruction application - once the first
        # privilege-requiring instruction is executed, all further instructions
        # may require privilege even if they didn't before (e.g. a chmod after
        # chown)

        # First off, do we need to at all?
        need_root = False
        for role in self.roles:
            lbl = depend.Label(utils.LabelKind.Package, 
                               "*",
                               role,
                               "*")

            install_dir = self.builder.invocation.role_install_path(role)
        
            instr_list = self.builder.load_instructions(lbl)

            app_dict = get_instruction_dict()

            for (lbl, fn, instr_file) in instr_list:
                # Obey this instruction?
                for instr in instr_file:
                    iname = instr.outer_elem_name()
                    if (iname in app_dict):
                        if (app_dict[iname].needs_privilege(self.builder, instr, role, install_dir)):
                            need_root = True
                    # Deliberately do not break - we want to check everything for
                    # validity before acquiring privilege.
                    else:
                        raise utils.Failure("File deployments don't know about " + 
                                            "instruction %s"%iname + 
                                            " found in label %s (filename %s)"%(lbl, fn))


        print "Rerunning muddle to apply instructions .. "
        
        permissions_label = depend.Label(utils.LabelKind.Deployment,
                                         label.name, label.role,
                                         utils.Tags.InstructionsApplied)

        if need_root:
            print "I need root to do this - sorry! - running sudo .."
            utils.run_cmd("sudo %s buildlabel %s"%(self.builder.muddle_binary, 
                                              permissions_label))
        else:
            utils.run_cmd("%s buildlabel %s"%(self.builder.muddle_binary, 
                                         permissions_label))

    def apply_instructions(self, label):
        app_dict = get_instruction_dict()

        for role in self.roles:
            lbl = depend.Label(utils.LabelKind.Package, 
                               "*",
                               role,
                               "*")

            deploy_dir = self.builder.invocation.deploy_path(label.name)
        
            instr_list = self.builder.load_instructions(lbl)
            for (lbl, fn, instrs) in instr_list:
                print "Applying instructions for role %s, label %s .. "%(role, lbl)
                for instr in instrs:
                    # Obey this instruction.
                    iname = instr.outer_elem_name()
                    if (iname in app_dict):
                        app_dict[iname].apply(self.builder, instr, role, deploy_dir)
                    else:
                        raise utils.Failure("File deployments don't know about instruction %s"%iname + 
                                            " found in label %s (filename %s)"%(lbl, fn))
        

# Application routines.
class FIApplyChmod(FileInstructionImplementor):
    def apply(self, builder, instr, role, path):

        dp = filespec.FSFileSpecDataProvider(path)

        files = dp.abs_match(instr.filespec)
        # @todo We _really_ need to use xargs here ..
        for f in files:
            utils.run_cmd("chmod %s \"%s\""%(instr.new_mode, f))

    def needs_privilege(self, builder, instr, role, path):
        # You don't, in general, need root to change permissions
        return False

class FIApplyChown(FileInstructionImplementor):
    def apply(self, builder, instr, role, path):
        
        #print "path = %s"%path
        dp = filespec.FSFileSpecDataProvider(path)
        files = dp.abs_match(instr.filespec)
        if (instr.new_user is None):
            cmd = "chgrp %s"%(instr.new_group)
        elif (instr.new_group is None):
            cmd = "chown %s"%(instr.new_user)
        else:
            cmd = "chown %s:%s"%(instr.new_user, instr.new_group)

        for f in files:
            utils.run_cmd("%s \"%s\""%(cmd, f))
            
    def needs_privilege(self, builder, instr, role, path):
        # Yep
        return True

# Register the relevant instruction providers.
def get_instruction_dict():
    """
    Return a dictionary mapping the names of instructions to the 
    classes that implement them.
    """
    app_dict = { }
    app_dict["chown"] = FIApplyChown()
    app_dict["chmod"] = FIApplyChmod()
    return app_dict


# A function which registers the standard dependencies for a file deployment.
def deploy(builder, target_dir, name, roles):
    """
    Register a file deployment.

    The deployment will take the roles specified in the role list, and
    build them into a deployment at deploy/[name]

    The deployment should eventually be located at target_dir
    """

    the_dependable = FileDeploymentBuilder(roles, builder, 
                                           target_dir)

    dep_label = depend.Label(utils.LabelKind.Deployment,
                             name, 
                             None, 
                             utils.Tags.Deployed)
    
    iapp_label = depend.Label(utils.LabelKind.Deployment,
                              name,
                              None,
                              utils.Tags.InstructionsApplied,
                              transient = True)
    
    # We depend on every postinstall for every package in the roles

    deployment_rule = depend.Rule(dep_label, the_dependable)

    for role in roles:
        role_label = depend.Label(utils.LabelKind.Package, 
                                  "*",
                                  role, 
                                  utils.Tags.PostInstalled)
        deployment_rule.add(role_label)

    # The instructionsapplied label is standalone .. 
    app_rule = depend.Rule(iapp_label, the_dependable)
    
    # Now add 'em ..
    builder.invocation.ruleset.add(deployment_rule)
    builder.invocation.ruleset.add(app_rule)

    # .. and deal with cleanup, which is entirely generic
    deployment.register_cleanup(builder, name)

    # .. and set the environment
    the_dependable.attach_env()

    # .. and that's all.



# End file

       
        

        



