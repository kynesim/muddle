"""
File deployment. This deployment just copies files into a 
role subdirectory in the /deployed directory, applying 
appropriate instructions.
"""

import os

import muddled.pkg as pkg
import muddled.env_store
import muddled.depend as depend
import muddled.utils as utils
import muddled.filespec as filespec
import muddled.deployment as deployment

from muddled.depend import Action

class FileInstructionImplementor:
    def apply(self, builder, instruction, role, path):
        pass

    def needs_privilege(self, builder, instr, role, path):
        pass


class FileDeploymentBuilder(Action):
    """
    Builds the specified file deployment
    """
    
    def __init__(self, roles, target_dir):
        """
        role is actually a list of (role, domain) pairs.
        """
        self.target_dir = target_dir
        self.roles = roles

        # Just in case we ever need it...
        self._unswept = True

    def _change_domain(self, new_domain):
        """
        Change the domain names in our "roles" list.

        This used when we become part of a sub-domain, to process all
        of the (role, domain) tuples in our "roles" list.
        """
        if self._unswept:
            roles = []
            for role, domain in self.roles:
                if domain:
                    domain = '%s(%s)'%(new_domain, domain)
                else:
                    domain = new_domain
                roles.append( (role, domain) )
            self.roles = roles
            self._unswept = False

    def _mark_unswept(self):
        self._unswept = True

    def attach_env(self, builder):
        """
        Attaches an environment containing:
        
          MUDDLE_TARGET_LOCATION - the location in the target filesystem where
          this deployment will end up.

        to every package label in this role.
        """
        
        for role, domain in self.roles:
            lbl = depend.Label(utils.LabelType.Package,
                               "*",
                               role,
                               "*", 
                               domain = domain)
            env = builder.invocation.get_environment_for(lbl)
        
            env.set_type("MUDDLE_TARGET_LOCATION", muddled.env_store.EnvType.SimpleValue)
            env.set("MUDDLE_TARGET_LOCATION", self.target_dir)

    def build_label(self, builder, label):
        """
        Performs the actual build.

        We actually do need to copy all files from install/ (where unprivileged
        processes can modify them) to deploy/ (where they can't).

        Then we apply instructions to deploy.
        """


        if (label.tag == utils.LabelTag.Deployed):
            # We want to deploy 
            self.deploy(builder, label)
        elif (label.tag == utils.LabelTag.InstructionsApplied):
            self.apply_instructions(builder, label)
        else:
            raise utils.GiveUp("Attempt to build a deployment with an unexpected tag in label %s"%(label))

    def deploy(self, builder, label):
        deploy_dir = builder.invocation.deploy_path(label.name, domain = label.domain)
        # First off, delete the target directory
        
        utils.recursively_remove(deploy_dir)
        utils.ensure_dir(deploy_dir)

        for role, domain in self.roles:
            if domain:
                print "> %s: Deploying role %s in domain %s .. "%(label.name, role, domain)
            else:
                print "> %s: Deploying role %s .. "%(label.name, role)
            install_dir = builder.invocation.role_install_path(role, domain = domain)
            utils.recursively_copy(install_dir, deploy_dir, object_exactly=True)
        

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
        for role, domain in self.roles:
            lbl = depend.Label(utils.LabelType.Package,
                               "*",
                               role,
                               "*",
                               domain = domain)

            install_dir = builder.invocation.role_install_path(role, domain = label.domain)
        
            instr_list = builder.load_instructions(lbl)

            app_dict = get_instruction_dict()

            for (lbl, fn, instr_file) in instr_list:
                # Obey this instruction?
                for instr in instr_file:
                    iname = instr.outer_elem_name()
                    if (iname in app_dict):
                        if (app_dict[iname].needs_privilege(builder, instr, role, install_dir)):
                            need_root = True
                    # Deliberately do not break - we want to check everything for
                    # validity before acquiring privilege.
                    else:
                        raise utils.GiveUp("File deployments don't know about " + 
                                            "instruction %s"%iname + 
                                            " found in label %s (filename %s)"%(lbl, fn))


        print "Rerunning muddle to apply instructions .. "
        
        permissions_label = depend.Label(utils.LabelType.Deployment,
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

    def apply_instructions(self, builder, label):
        app_dict = get_instruction_dict()

        for role, domain in self.roles:
            lbl = depend.Label(utils.LabelType.Package,
                               "*",
                               role,
                               "*", 
                               domain = domain)

            deploy_dir = builder.invocation.deploy_path(label.name, domain = label.domain)
        
            instr_list = builder.load_instructions(lbl)
            for (lbl, fn, instrs) in instr_list:
                print "File deployment: Applying instructions for role %s, label %s .. "%(role, lbl)
                for instr in instrs:
                    # Obey this instruction.
                    iname = instr.outer_elem_name()
                    print 'Instruction:', iname
                    if (iname in app_dict):
                        app_dict[iname].apply(builder, instr, role, deploy_dir)
                    else:
                        raise utils.GiveUp("File deployments don't know about instruction %s"%iname + 
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

        # NB: take care to apply a chown command to the file named,
        # even if it is a symbolic link (the default is --reference,
        # which would only apply the chown to the file the symbolic
        # link references)
        
        #print "path = %s"%path
        dp = filespec.FSFileSpecDataProvider(path)
        files = dp.abs_match(instr.filespec)
        if (instr.new_user is None):
            cmd = "chgrp %s"%(instr.new_group)
        elif (instr.new_group is None):
            cmd = "chown --no-dereference %s"%(instr.new_user)
        else:
            cmd = "chown --no-dereference %s:%s"%(instr.new_user, instr.new_group)

        for f in files:
            utils.run_cmd("%s \"%s\""%(cmd, f))
            
    def needs_privilege(self, builder, instr, role, path):
        # Yep
        return True



class FIApplyMknod(FileInstructionImplementor):
    def apply(self, builder, instr, role, path):

        if (instr.type == "char"):
            mknod_type = "c"
        else:
            mknod_type = "b"

        abs_file = os.path.join(path, instr.file_name)
        utils.run_cmd("mknod %s %s %s %s"%(
                abs_file,
                mknod_type, 
                instr.major,
                instr.minor))
        utils.run_cmd("chown %s:%s %s"%(
                instr.uid,
                instr.gid,
                abs_file))
        utils.run_cmd("chmod %s %s"%(instr.mode, abs_file))

    def needs_privilege(self, builder, instr, role, path):
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
    app_dict["mknod"] = FIApplyMknod()
    return app_dict


# Legacy function to register a deployment without domains.
def deploy(builder, target_dir, name, roles):
    """
    Register a file deployment.

    This is a convenience wrapper around deploy_with_domains().

    'roles' is a sequence of role names. The deployment will take the roles
    specified, and build them into a deployment at deploy/[name].  

    More specifically, a rule will be created for label:

      "deployment:<name>/deployed"
      
    which depends on "package:\*{<role}/postinstalled" (in the builder's default
    domain) for each <role> in 'roles'.

    In other words, the deployment called 'name' will depend on the given roles
    (in the default domain) having been "finished" (postinstalled).

    An "instructions applied" label "deployment:<name>/instructionsapplied"
    will also be created.

    The deployment should eventually be located at 'target_dir'.
    """
    new_roles = [ ]
    for r in roles:
        new_roles.append( (r, builder.default_domain) )

    return deploy_with_domains(builder, target_dir, name, new_roles)


# A function which registers the standard dependencies for a file deployment.
def deploy_with_domains(builder, target_dir, name, role_domains):
    """
    Register a file deployment.

    'role_domains' is a sequence of (role, domain) pairs. The deployment will
    take the roles and domains specified, and build them into a deployment at
    deploy/[name].  

    More specifically, a rule will be created for label:

      "deployment:<name>/deployed"
      
    which depends on "package:(<domain>)*{<role}/postinstalled" for each
    (<role>, <domain>) pair in 'role_domains'.

    In other words, the deployment called 'name' will depend on the given roles
    in the appropriate domains having been "finished" (postinstalled).

    An "instructions applied" label "deployment:<name>/instructionsapplied"
    will also be created.

    The deployment should eventually be located at 'target_dir'.
    """

    the_action = FileDeploymentBuilder(role_domains, target_dir)

    dep_label = depend.Label(utils.LabelType.Deployment, name, None, 
                             utils.LabelTag.Deployed)

    iapp_label = depend.Label(utils.LabelType.Deployment, name, None,
                              utils.LabelTag.InstructionsApplied,
                              transient = True)

    # We depend on every postinstall for every package in the roles

    deployment_rule = depend.Rule(dep_label, the_action)

    for role, domain in role_domains:
        role_label = depend.Label(utils.LabelType.Package, "*", role,
                                  utils.LabelTag.PostInstalled,
                                  domain = domain)
        deployment_rule.add(role_label)

    # The instructionsapplied label is standalone .. 
    app_rule = depend.Rule(iapp_label, the_action)
    
    # Now add 'em ..
    builder.invocation.ruleset.add(deployment_rule)
    builder.invocation.ruleset.add(app_rule)

    # .. and deal with cleanup, which is entirely generic
    deployment.register_cleanup(builder, name)

    # .. and set the environment
    the_action.attach_env(builder)

    # .. and that's all.



# End file

       
        

        



