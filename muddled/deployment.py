"""
Common rules for deployments - basically just the clean rules.
"""

import depend
import os
import mechanics
import utils
import pkg
import env_store

class CleanDeploymentBuilder(pkg.Dependable):
    def __init__(self):
        pass
        
    def build_label(self, builder, label):
        if (label.type == utils.LabelKind.Deployment and 
            (label.tag == utils.Tags.Clean or 
            label.tag == utils.Tags.DistClean)):
            deploy_path = builder.invocation.deploy_path(label.name, domain= label.domain)
            print "> Remove %s"%deploy_path
            utils.recursively_remove(deploy_path)
        else:
            raise utils.Failure("Attempt to invoke CleanDeploymentBuilder on "
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
                              "*",
                              utils.Tags.Clean)
    rule = depend.Rule(target_lbl, CleanDeploymentBuilder())
    builder.invocation.ruleset.add(rule)


def pkg_depends_on_deployment(builder, pkg, roles, deployment, domain=None):
    """
    Make this package depend on the given deployment
    """
    for i in roles:
        tgt = depend.Label(utils.LabelKind.Package, 
                           pkg, 
                           i,
                           utils.Tags.PreConfig)
        the_rule = depend.Rule(tgt, None)
        the_rule.add(depend.Label(utils.LabelKind.Deployment,
                                  deployment,
                                  None,
                                  utils.Tags.Deployed,
                                  domain=domain))
        builder.invocation.ruleset.add(the_rule)
                

def role_depends_on_deployment(builder, role, deployment, domain=None):
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
                       utils.Tags.Deployed,
                       domain=domain))
    builder.invocation.ruleset.add(the_rule)

def deployment_depends_on_roles(builder, deployment, roles, domain=None):
    """
    Make the deployment of the deployment with the given name
    depend on the installation of every package in the given
    role
    """
    tgt = depend.Label(utils.LabelKind.Deployment, 
                       deployment,
                       None,
                       utils.Tags.Deployed)
    rule = builder.invocation.ruleset.rule_for_target(tgt, 
                                                      createIfNotPresent = True)
    for r in roles:
        lbl = depend.Label(utils.LabelKind.Package,
                           "*",
                           r,
                           utils.Tags.PostInstalled,
                           domain=domain)
        rule.add(lbl)

def deployment_depends_on_deployment(builder, what, depends_on, domain=None):
    """
    Inter-deployment dependencies. Aren't you glad we have a
    general purpose dependency solver?
    """
    tgt = depend.Label(utils.LabelKind.Deployment,
                       what,
                       None,
                       utils.Tags.Deployed)
    rule = builder.invocation.ruleset.rule_for_target(tgt, 
                                                      createIfNotPresent = True)
    rule.add(depend.Label(utils.LabelKind.Deployment, 
                          depends_on,
                          None,
                          utils.Tags.Deployed,
                          domain=domain))
    

def inform_deployment_path(builder, name, deployment, roles, domain=None):
    """
    Sets an environment variable to tell the given roles about the
    location of the given deployment.

    Useful when e.g. some tools need to run other tools and therefore
    want to know where they are at build (rather than run)time.
    """
    
    for role in roles:
        lbl = depend.Label(utils.LabelKind.Package,
                           "*",
                           role,
                           "*",
                           domain=domain)
        env = builder.invocation.get_environment_for(lbl)
        env.set_type(name,env_store.EnvType.SimpleValue)
        env.set(name, builder.invocation.deploy_path(deployment))
    

def deployment_rule_from_name(builder, name):
    rules =  builder.invocation.ruleset.rules_for_target(
        depend.Label(utils.LabelKind.Deployment, name, None, 
                     utils.Tags.Deployed), 
        useTags = True, 
        useMatch = False)
    if (len(rules) != 1):
        raise utils.Failure("Attempt to retrieve rule for deployment %s:"%name + 
                            " returned list had length %d ,not 1.. "%len(rules))

    for r in rules:
        return r
    
def set_env(builder, deployment, name, value):
    """
    Set NAME=VALUE in the environment for this deployment.
    """
    lbl = depend.Label(utils.LabelKind.Deployment, 
                       deployment, None,
                       utils.Tags.Deployed)
    env = builder.invocation.get_environment_for(lbl)
    env.set(name, value)

# End file.
