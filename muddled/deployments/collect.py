"""
Collect deployment.

Principally depending on other deployments, this 
deployment is used to collect elements built by
other parts of the system into a directory -
usually to be processed by some external tool.
"""

import muddled
import muddled.pkg as pkg
import muddled.env_store
import muddled.depend as depend
import muddled.utils as utils
import muddled.filespec as filespec
import muddled.deployment as deployment
import muddled.cpiofile as cpiofile
import os

class AssemblyDescriptor:
    def __init__(self, from_label, from_rel, to_name, recursive = True, 
                 failOnAbsentSource = False, 
                 copyExactly = True):
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
        self.fail_on_absent_source = failOnAbsentSource
        self.copy_exactly = copyExactly

        
    def get_source_dir(self, builder):
        if (self.from_label.tag_kind == utils.LabelKind.Checkout):
            return builder.invocation.checkout_path(self.from_label.name)
        elif (self.from_label.tag_kind == utils.LabelKind.Package):
            if ((self.from_label.name is None) or 
                self.from_label.name == "*"):
                return builder.invocation.role_install_path(self.from_label.role)
            else:
                return builder.invocation.package_obj_path(self.from_label.name, 
                                                           self.from_label.role)
        elif (self.from_label.tag_kind == utils.LabelKind.Deployment):
            return builder.invocation.deploy_path(self.from_label.name)
        else:
            raise utils.Failure("Label %s for collection dependable has unknown kind."%(self.from_label))

class CollectDeploymentBuilder(pkg.Dependable):
    """
    Builds the specified collect deployment.
    """

    def __init__(self, builder):
        self.builder = builder
        self.assemblies = [ ]

    def add_assembly(self, assembly_descriptor):
        self.assemblies.append(assembly_descriptor)

    def build_label(self, label):
        """
        Actually do the copies ..
        """

        utils.ensure_dir(self.builder.invocation.deploy_path(label.name))

        if (label.tag == utils.Tags.Deployed):
            for asm in self.assemblies:
                src = os.path.join(asm.get_source_dir(self.builder), asm.from_rel)
                dst = os.path.join(self.builder.invocation.deploy_path(label.name), 
                                   asm.to_name)

                if (not os.path.exists(src)):
                    if (asm.fail_on_absent_source):
                        raise utils.Failure("Deployment %s: source object %s does not exist."%(label.name, src))
                    # Else no one cares :-)
                else:
                    if (asm.recursive):
                        utils.recursively_copy(src, dst, object_exactly = asm.copy_exactly)
                    else:
                        utils.copy_file(src, dst, object_exactly = asm.copy_exactly)
        else:
            pass


def deploy(builder, name):
    """
    Create a collection deployment builder.

    This adds a new rule linking the label "deployment:<name>/deployed"
    to the collection deployment builder.

    You can then add assembly descriptors using the other utility functions in
    this module.

    Dependencies get registered when you add an assembly descriptor.
    """
    the_dependable = CollectDeploymentBuilder(builder)

    dep_label = depend.Label(utils.LabelKind.Deployment, 
                             name, None,
                             utils.Tags.Deployed)

    deployment_rule = depend.Rule(dep_label, the_dependable)

    # We need to clean it as well, annoyingly .. 
    deployment.register_cleanup(builder, name)

    builder.invocation.ruleset.add(deployment_rule)

def copy_from_checkout(builder, name, checkout, rel, dest, 
                       recursive = True, 
                       failOnAbsentSource = False, 
                       copyExactly = True):
    rule = deployment.deployment_rule_from_name(builder, name)
    
    dep_label = depend.Label(utils.LabelKind.Checkout, 
                             checkout, 
                             None,
                             utils.Tags.CheckedOut)

    asm = AssemblyDescriptor(dep_label, rel, dest, recursive = recursive,
                             failOnAbsentSource = failOnAbsentSource, 
                             copyExactly = copyExactly)
    rule.add(dep_label)
    rule.obj.add_assembly(asm)

def copy_from_package_obj(builder, name, pkg_name, pkg_role, rel,dest,
                          recursive = True,
                          failOnAbsentSource = False,
                          copyExactly = True):
    rule = deployment.deployment_rule_from_name(builder, name)
    
    dep_label = depend.Label(utils.LabelKind.Package,
                             pkg_name, pkg_role,
                             utils.Tags.Built)
    asm = AssemblyDescriptor(dep_label, rel, dest, recursive = recursive,
                             failOnAbsentSource = failOnAbsentSource, 
                             copyExactly = copyExactly)
    rule.add(dep_label)
    rule.obj.add_assembly(asm)

def copy_from_role_install(builder, name, role, rel, dest,
                           recursive = True,
                           failOnAbsentSource = False,
                           copyExactly = True):
    """
    Add a rule to copy from the given role's install to the named deployment.

    'name' is the name of the collecting deployment, as created by::

        deploy(builder,name)

    The new rule will be added to label "deployment:<name>/deployed", where
    <name> is the 'name' given.

    'role' is the role to copy from. Copying will be based from 'rel' within
    the role's ``install``, to 'dest' within the deployment.

    An AssemblyDescriptor will be created to copy from 'rel' in the install
    directory of the label "package:*{<role>}/postinstalled", to 'dest' within
    the deployment directory of 'name'

    So, for instance::

        copy_from_role_install(builder,'fred','data','public','data/public',
                               True, False, True)

    might copy from (recursively) from::

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
    """
    rule = deployment.deployment_rule_from_name(builder, name)
    dep_label = depend.Label(utils.LabelKind.Package,
                             "*",
                             role,
                             utils.Tags.PostInstalled)
    asm = AssemblyDescriptor(dep_label, rel, dest, recursive = recursive,
                             failOnAbsentSource = failOnAbsentSource, 
                             copyExactly = copyExactly)
    rule.add(dep_label)
    rule.obj.add_assembly(asm)

def copy_from_deployment(builder, name, dep_name, rel, dest,
                         recursive = True,
                         failOnAbsentSource = False,
                         copyExactly = True):
    rule = deployment.deployment_rule_from_name(builder,name)
    dep_label = depend.Label(utils.LabelKind.Deployment,
                             dep_name, 
                             None, 
                             utils.Tags.Deployed)
    asm = AssemblyDescriptor(dep_label, rel, dest, recursive = recursive,
                             failOnAbsentSource = failOnAbsentSource, 
                             copyExactly = copyExactly)
    rule.add(dep_label)
    rule.obj.add_assembly(asm)


# End file.
                             



    
                        


            


