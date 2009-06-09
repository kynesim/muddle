"""
Common rules for deployments - basically just the clean
rules.
"""

import depend
import os
import mechanics
import utils
import pkg

class CleanDeploymentBuilder(pkg.Dependable):
    def __init__(self, builder):
        self.builder = builder
        
    def build_label(self, label):
        if (label.tag_kind == utils.LabelKind.Deployment and 
            (label.tag == utils.Tags.Clean or 
            label.tag == utils.Tags.DistClean)):
            utils.recursively_remove(self.builder.invocation.deploy_path(label.name))
        else:
            raise utils.Failure("Attempt to invoke CleanDeploymentBuilder on " + 
                                "unrecognised label %s"%label)
        # And, um, that's it.
        

def register_cleanup(builder, deployment):
    """
    Register the labels you need to clean a deployment.
    
    Cleaning a deployment basically means we remove the directory
    and its deployed tag. 
    """
    
    target_lbl = depend.Label(utils.LabelKind.Deployment, 
                              deployment, 
                              None,
                              utils.Tags.Clean)
    rule = depend.Rule(target_lbl, CleanDeploymentBuilder(builder))
    builder.invocation.ruleset.add(rule)


def role_depends_on_deployment(builder, role, deployment):
    """
    Make every package in the given role depend on the given deployment
    """
    
    tgt = depend.Label(utils.LabelKind.Package, 
                       "*",
                       role, 
                       utils.Tags.PreConfig)
    the_rule = depend.Rule(tgt, None)
    the_rule.add(depend.Label(utils.LabelKind.Deployment,
                       deployment,
                       None,
                       utils.Tags.Deployed))
    builder.invocation.ruleset.add(the_rule)

# End file.
