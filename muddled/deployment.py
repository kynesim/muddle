"""
Common rules for deployments - basically just the clean rules.
"""

import muddled.depend as depend
import muddled.env_store as env_store
import muddled.utils as utils

from muddled.depend import Action

class CleanDeploymentBuilder(Action):
    def __init__(self):
        pass

    def build_label(self, builder, label):
        if (label.type == utils.LabelType.Deployment and
            (label.tag == utils.LabelTag.Clean or
            label.tag == utils.LabelTag.DistClean)):
            deploy_path = builder.deploy_path(label)
            print "> Remove %s"%deploy_path
            utils.recursively_remove(deploy_path)
            builder.kill_label(label.copy_with_tag(utils.LabelTag.Deployed))
        else:
            raise utils.GiveUp("Attempt to invoke CleanDeploymentBuilder on "
                                "unrecognised label %s"%label)
        # And, um, that's it.


def register_cleanup(builder, deployment):
    """
    Register the rule you need to clean a deployment.

    Cleaning a deployment basically means we remove the directory
    and its deployed tag.
    """

    target_lbl = depend.Label(utils.LabelType.Deployment,
                              deployment,
                              None,
                              utils.LabelTag.Clean)
    rule = depend.Rule(target_lbl, CleanDeploymentBuilder())
    builder.ruleset.add(rule)


def pkg_depends_on_deployment(builder, pkg, roles, deployment, domain=None):
    """
    Make this package depend on the given deployment

    Specifically, given each role 'r' in 'roles', make the label
    "package:<pkg>{<r>}/preconfig" depend on the label
    "deployment:<deployment>/deployed".

    If 'domain' is given, this is (currently) just used for the deploymet
    label.
    """
    deployment_label = depend.Label(utils.LabelType.Deployment,
                                    deployment,
                                    None,
                                    utils.LabelTag.Deployed,
                                    domain=domain)
    for i in roles:
        tgt = depend.Label(utils.LabelType.Package,
                           pkg,
                           i,
                           utils.LabelTag.PreConfig)
        the_rule = depend.Rule(tgt, None)
        the_rule.add(deployment_label)
        builder.ruleset.add(the_rule)


def role_depends_on_deployment(builder, role, deployment, domain=None):
    """
    Make every package in the given role depend on the given deployment
    """

    tgt = depend.Label(utils.LabelType.Package,
                       "*",
                       role,
                       utils.LabelTag.PreConfig)
    the_rule = depend.Rule(tgt, None)
    the_rule.add(depend.Label(utils.LabelType.Deployment,
                       deployment,
                       None,
                       utils.LabelTag.Deployed,
                       domain=domain))
    builder.ruleset.add(the_rule)

def deployment_depends_on_roles(builder, deployment, roles, domain=None):
    """
    Make the deployment of the deployment with the given name
    depend on the installation of every package in the given
    role
    """
    tgt = depend.Label(utils.LabelType.Deployment,
                       deployment,
                       None,
                       utils.LabelTag.Deployed)
    rule = builder.ruleset.rule_for_target(tgt,
                                                      createIfNotPresent = True)
    for r in roles:
        lbl = depend.Label(utils.LabelType.Package,
                           "*",
                           r,
                           utils.LabelTag.PostInstalled,
                           domain=domain)
        rule.add(lbl)

def deployment_depends_on_deployment(builder, what, depends_on, domain=None):
    """
    Inter-deployment dependencies. Aren't you glad we have a
    general purpose dependency solver?
    """
    tgt = depend.Label(utils.LabelType.Deployment,
                       what,
                       None,
                       utils.LabelTag.Deployed)
    rule = builder.ruleset.rule_for_target(tgt,
                                                      createIfNotPresent = True)
    rule.add(depend.Label(utils.LabelType.Deployment,
                          depends_on,
                          None,
                          utils.LabelTag.Deployed,
                          domain=domain))


def inform_deployment_path(builder, name, deployment, roles, domain=None):
    """
    Sets an environment variable to tell the given roles about the
    location of the given deployment.

    Useful when e.g. some tools need to run other tools and therefore
    want to know where they are at build (rather than run)time.
    """

    for role in roles:
        lbl = depend.Label(utils.LabelType.Package,
                           "*",
                           role,
                           "*",
                           domain=domain)
        env = builder.get_environment_for(lbl)
        env.set_type(name, env_store.EnvType.SimpleValue)

        deployment_label = depend.Label(utils.LabelType.Deployment, deployment)
        env.set(name, builder.deploy_path(deployment_label))


def deployment_rule_from_name(builder, name):
    """
    Return the rule for target label "deployment:<name>{}/deployed".

    Raises an exception if there is more than one such rule.
    """
    rules =  builder.ruleset.rules_for_target(
        depend.Label(utils.LabelType.Deployment, name, None,
                     utils.LabelTag.Deployed),
        useTags = True,
        useMatch = False)
    if (len(rules) != 1):
        raise utils.GiveUp("Attempt to retrieve rule for deployment %s:"%name +
                            " returned list had length %d ,not 1.. "%len(rules))

    for r in rules:
        return r

def set_env(builder, deployment, name, value):
    """
    Set NAME=VALUE in the environment for this deployment.
    """
    lbl = depend.Label(utils.LabelType.Deployment,
                       deployment, None,
                       utils.LabelTag.Deployed)
    env = builder.get_environment_for(lbl)
    env.set(name, value)

# End file.
