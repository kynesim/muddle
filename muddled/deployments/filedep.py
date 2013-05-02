"""
File deployment. This deployment just copies files into a
role subdirectory in the /deployed directory, applying
appropriate instructions.
"""

import os

import muddled.env_store
import muddled.depend as depend
import muddled.utils as utils
import muddled.filespec as filespec
import muddled.deployment as deployment

from muddled.depend import Action
from muddled.deployments.collect import InstructionImplementor, \
        CollectApplyChown, CollectApplyChmod

class FIApplyChmod(CollectApplyChmod):

    # XXX Why is this different than for collect?
    def needs_privilege(self, builder, instr, role, path):
        return False

class FIApplyMknod(InstructionImplementor):
    def prepare(self, builder, instr, role, path):
        return False

    def apply(self, builder, instr, role, path):

        if (instr.type == "char"):
            mknod_type = "c"
        else:
            mknod_type = "b"

        abs_file = os.path.join(path, instr.file_name)
        utils.run0("mknod %s %s %s %s"%(abs_file, mknod_type,
                                        instr.major, instr.minor))
        utils.run0("chown %s:%s %s"%(instr.uid, instr.gid, abs_file))
        utils.run0("chmod %s %s"%(instr.mode, abs_file))

    def needs_privilege(self, builder, instr, role, path):
        return True

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

        self.app_dict = {"chown" : CollectApplyChown(),
                         "chmod" : FIApplyChmod(),
                         "mknod" : FIApplyMknod(),
                        }

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
            lbl = depend.Label(utils.LabelType.Package, "*", role, "*", domain=domain)
            env = builder.get_environment_for(lbl)
            env.set_type("MUDDLE_TARGET_LOCATION", muddled.env_store.EnvType.SimpleValue)
            env.set("MUDDLE_TARGET_LOCATION", self.target_dir)

    def build_label(self, builder, label):
        """
        Performs the actual build.

        We actually do need to copy all files from install/ (where unprivileged
        processes can modify them) to deploy/ (where they can't).

        Then we apply instructions to deploy.
        """

        if label.tag == utils.LabelTag.Deployed:
            self.deploy(builder, label)
        elif label.tag == utils.LabelTag.InstructionsApplied:
            self.apply_instructions(builder, label)
        else:
            raise utils.GiveUp("Attempt to build a deployment with an unexpected tag in label %s"%(label))

    def deploy(self, builder, label):
        deploy_dir = builder.deploy_path(label)
        # First off, delete the target directory
        utils.recursively_remove(deploy_dir)
        utils.ensure_dir(deploy_dir)

        for role, domain in self.roles:
            if domain:
                print "> %s: Deploying role %s in domain %s .. "%(label.name, role, domain)
            else:
                print "> %s: Deploying role %s .. "%(label.name, role)
            install_dir = builder.role_install_path(role, domain = domain)
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
        need_root_for = set()
        for role, domain in self.roles:
            lbl = depend.Label(utils.LabelType.Package, "*", role, "*", domain=domain)
            install_dir = builder.role_install_path(role, domain = label.domain)
            instr_list = builder.load_instructions(lbl)
            for (lbl, fn, instr_file) in instr_list:
                # Obey this instruction?
                for instr in instr_file:
                    iname = instr.outer_elem_name()
                    if iname in self.app_dict:
                        if self.app_dict[iname].needs_privilege(builder, instr, role, install_dir):
                            need_root_for.add(iname)
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

        if need_root_for:
            print "I need root to do %s - sorry! - running sudo .."%(', '.join(sorted(need_root_for)))
            utils.run0("sudo %s buildlabel '%s'"%(builder.muddle_binary,
                                                  permissions_label))
        else:
            utils.run0("%s buildlabel '%s'"%(builder.muddle_binary,
                                             permissions_label))

    def apply_instructions(self, builder, label):

        for role, domain in self.roles:
            lbl = depend.Label(utils.LabelType.Package, "*", role, "*", domain=domain)
            deploy_dir = builder.deploy_path(label)
            instr_list = builder.load_instructions(lbl)
            for (lbl, fn, instrs) in instr_list:
                print "File deployment: Applying instructions for role %s, label %s .. "%(role, lbl)
                for instr in instrs:
                    # Obey this instruction.
                    iname = instr.outer_elem_name()
                    print 'Instruction:', iname
                    if iname in self.app_dict:
                        self.app_dict[iname].apply(builder, instr, role, deploy_dir)
                    else:
                        raise utils.GiveUp("File deployments don't know about instruction %s"%iname +
                                            " found in label %s (filename %s)"%(lbl, fn))


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
    builder.ruleset.add(deployment_rule)
    builder.ruleset.add(app_rule)

    # .. and deal with cleanup, which is entirely generic
    deployment.register_cleanup(builder, name)

    # .. and set the environment
    the_action.attach_env(builder)

    # .. and that's all.

# End file
