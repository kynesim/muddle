"""
cpio deployment.

Most commonly used to create Linux ramdisks, this
deployment creates a CPIO archive from the relevant
install directory and applies the relevant instructions.

Because python has no native CPIO support, we need to
do this by creating a tar archive and then invoking
cpio in copy-through mode to convert the archive to
cpio. Ugh.
"""

import types
import os

import muddled
import muddled.env_store
import muddled.depend as depend
import muddled.utils as utils
import muddled.deployment as deployment
import muddled.cpiofile as cpiofile

from muddled.depend import Action
from muddled.utils import GiveUp, LabelType, LabelTag

class CpioInstructionImplementor(object):

    def apply(self, builder, instruction, role, path):
        pass

class CpioDeploymentBuilder(Action):
    """
    Builds the specified CPIO deployment.
    """

    def __init__(self, target_file, target_base, compressionMethod=None, pruneFunc=None):
        """
        * 'target_file' is the CPIO file to construct.
        * 'target_base' is an array of pairs mapping labels to target locations, or
          (label, src) -> location
        * 'compressionMethod' is the compression method to use, if any - gzip -> gzip,
          bzip2 -> bzip2.
        * if 'pruneFunc' is not None, it is a function to be called like
          pruneFunc(Hierarchy) to prune the hierarchy prior to packing. Usually
          something like deb.deb_prune, it's intended to remove spurious stuff like
          manpages from initrds and the like.
        """
        self.target_file = target_file
        self.target_base = target_base
        self.compression_method = compressionMethod
        self.prune_function = pruneFunc

    def __str__(self):
        result = "cpioDeploymentBuilder{"
        result = result + "target_file=%s"%self.target_file
        result = result + ",target_base="
        for (l,tgt) in self.target_base:
            result = result + "(%s,%s) "%(l,tgt)
        result = result + ",compression=%s"%self.compression_method
        result = result + ",prune=%s}"%self.prune_function
        return result


    def _inner_labels(self):
        """
        Return a list of all of the Labels we "hide" inside ourselves.

        This is intended for use in moving the Rule containing us into a new
        domain, so that it can add our "inner" labels to its list of labels
        to change the domain of.

        We do it this way in case the labels are used for other purposes - it
        is important that the labels get "moved" in one sweep, so that they
        don't accidentally get moved more than once.
        """
        labels = []
        for i in self.target_base:
            labels.append(i[0])

        return labels

    def attach_env(self, builder):
        """
        Attaches an environment containing:

          MUDDLE_TARGET_LOCATION - the location in the target filesystem where
          this deployment will end up.

        to every package label in this role.
        """

        for (l,bl) in self.target_base:
            if (type ( bl ) == types.TupleType ):
                target_loc = bl[1]
            else:
                target_loc = bl

            lbl = depend.Label(LabelType.Package, "*", l.role, "*",
                               domain = l.domain)
            env = builder.get_environment_for(lbl)

            env.set_type("MUDDLE_TARGET_LOCATION", muddled.env_store.EnvType.SimpleValue)
            env.set("MUDDLE_TARGET_LOCATION", target_loc)



    def build_label(self,builder, label):
        """
        Actually cpio everything up, following instructions appropriately.
        """

        if label.type not in (LabelType.Deployment, LabelType.Package):
            raise GiveUp("Attempt to build a CPIO deployment with a label"
                         " of type %s"%(label.type))

        if label.type == LabelType.Deployment and label.tag != LabelTag.Deployed:
            raise GiveUp("Attempt to build a CPIO deployment with a"
                         " deployment label of type %s"%(label.tag))
        elif label.type == LabelType.Package and label.tag != LabelTag.PostInstalled:
            raise GiveUp("Attempt to build a CPIO deployment with a"
                         " package label of type %s"%(label.tag))

        # Collect all the relevant files ..
        if label.type == LabelType.Deployment:
            deploy_dir = builder.deploy_path(label)
        else:
            # XXX Would it be better to use package_obj_path(label) ???
            deploy_dir = builder.package_install_path(label)

        deploy_file = os.path.join(deploy_dir, self.target_file)
        utils.ensure_dir(os.path.dirname(deploy_file))

        the_hierarchy = cpiofile.Hierarchy({ }, { })

        for l ,bt in self.target_base:
            if type( bt ) == types.TupleType:
                real_source_path = os.path.join(builder.role_install_path(l.role, l.domain),
                                                bt[0])
                # This is bt[1] - the actual destination. base is computed differently
                # (bt[2]) for applying instructions.
                base = bt[1]
            else:
                base = bt
                real_source_path = os.path.join(builder.role_install_path(l.role, l.domain))

            print "Collecting %s  for deployment to %s .. "%(l,base)
            if (len(base) > 0 and base[0] != '/'):
                base = "/%s"%(base)

            m = cpiofile.hierarchy_from_fs(real_source_path, base)
            the_hierarchy.merge(m)

        # Normalise the hierarchy ..
        the_hierarchy.normalise()
        print "Filesystem hierarchy is:\n%s"%the_hierarchy.as_str(builder.db.root_path)

        if self.prune_function:
            self.prune_function(the_hierarchy)

        app_dict = _get_instruction_dict()

        # Apply instructions. We actually need an intermediate list here,
        # because you might have the same role with several different
        # sources and possibly different bases.
        to_apply = {}
        for src, bt in self.target_base:
            if type(bt) == types.TupleType:
                base = bt[2]
            else:
                base = bt
            to_apply[ (src, base) ] = (src, bt)

        # Now they are unique .. 
        for src, bt in to_apply.values():
            if type(bt) == types.TupleType:
                base = bt[2]
            else:
                base = bt

            print "base = %s"%(base)
            lbl = depend.Label(LabelType.Package, "*", src.role, "*",
                               domain = src.domain)
            print "Scanning instructions for role %s, domain %s .. "%(src.role, src.domain)
            instr_list = builder.load_instructions(lbl)
            for lbl, fn, instrs in instr_list:
                print "CPIO deployment: Applying instructions for role %s, label %s .. "%(src.role, lbl)
                for instr in instrs:
                    iname = instr.outer_elem_name()
                    #print 'Instruction:', iname
                    if iname in app_dict:
                        print 'Instruction:', str(instr)
                        app_dict[iname].apply(builder, instr, lbl.role, base,
                                              the_hierarchy)
                    else:
                        print 'Instruction:', iname
                        raise GiveUp("CPIO deployments don't know about "
                                     "the instruction %s (lbl %s, file %s)"%(iname, lbl, fn))
        # .. and write the file.
        print "> Writing %s .. "%deploy_file
        the_hierarchy.render(deploy_file, True)

        if (self.compression_method is not None):
            if (self.compression_method == "gzip"):
                utils.run0(["gzip", "-f", deploy_file])
            elif (self.compression_method == "bzip2"):
                utils.run0(["bzip2", "-f", deploy_file])
            else:
                raise GiveUp("Invalid compression method %s"%self.compression_method +
                             "specified for cpio deployment. Pick gzip or bzip2.")


class CIApplyChmod(CpioInstructionImplementor):

    def apply(self, builder, instr, role, target_base, hierarchy):
        dp = cpiofile.CpioFileDataProvider(hierarchy)

        (clrb, bits) = utils.parse_mode(instr.new_mode)



        files = dp.abs_match(instr.filespec,
                             vroot = target_base)


        for f in files:
            # For now ..
            #print "Change mode of f %s -> %s"%(f.name, instr.new_mode)
            #print "mode = %o clrb = %o bits = %o\n"%(f.mode, clrb, bits)
            #print "Change mode of %s"%(f.name)
            f.mode = f.mode & ~clrb
            f.mode = f.mode | bits

class CIApplyChown(CpioInstructionImplementor):

    def apply(self, builder, instr, role, target_base, hierarchy):
        dp = cpiofile.CpioFileDataProvider(hierarchy)
        files = dp.abs_match(instr.filespec, vroot = target_base)

        uid = utils.parse_uid(builder, instr.new_user)
        gid = utils.parse_gid(builder, instr.new_group)

        for f in files:
            if (instr.new_user is not None):
                f.uid = uid
            if (instr.new_group is not None):
                f.gid = gid

class CIApplyMknod(CpioInstructionImplementor):

    def apply(self, builder, instr, role, target_base, hierarchy):
        # Find or create the relevant file
        cpio_file = cpiofile.File()

        (clrb, setb) = utils.parse_mode(instr.mode)
        cpio_file.mode = setb
        cpio_file.uid = utils.parse_uid(builder, instr.uid)
        cpio_file.gid = utils.parse_gid(builder, instr.gid)
        if (instr.type == "char"):
            cpio_file.mode = cpio_file.mode | cpiofile.File.S_CHAR
        else:
            cpio_file.mode = cpio_file.mode | cpiofile.File.S_BLK

        cpio_file.rdev = os.makedev(int(instr.major), int(instr.minor))
        # Zero-length file - it's a device node.
        cpio_file.name = None
        cpio_file.data = None

        #print "target_base = %s for role %s"%(target_base, role)
        real_path = utils.rel_join(target_base, instr.file_name)

        cpio_file.key_name = real_path
        #print "put_target_file %s"%real_path
        print 'Adding device node %s'%real_path
        hierarchy.put_target_file(real_path, cpio_file)


def _get_instruction_dict():
    """
    Return a dictionary mapping the names of instructions to the
    classes that implement them.
    """
    app_dict = { }
    app_dict["chown"] = CIApplyChown()
    app_dict["chmod"] = CIApplyChmod()
    app_dict["mknod"] = CIApplyMknod()
    return app_dict


class CpioWrapper(object):
    def __init__(self, builder, action, label):
        self.action = action
        self.label = label
        self.builder = builder

    def copy_from_role(self, from_role, from_fragment, to_fragment, with_base=None):
        """
        Copy the relative path from_fragment in from_role to to_fragment in the CPIO
        package or deployment given by 'action'

        Use 'with_base' to change the base offset we apply when executing instructions;
        this is useful when using repeated copy_from_role() invocations to copy
        a subset of one role to a package/deployment.
        """

        if self.label.type == LabelType.Package and from_role == self.label.role:
            raise GiveUp("Cannot deploy from the same role (%s) as that of the"
                         " target CPIO deployment package label (%s), as it"
                         " would give a circular dependency in the rules"%(from_role, self.label))
            # Why not? Because we use package:*{<from_role>} in our rule for what
            # self.label depends on, and if that can be the same role as self.label,
            # then we will immediately get a circular dependency.
            # We *could* add every package label in <from_role> explicitly to
            # the rules, but then we'd require the user to have already specified
            # them all before calling us, and that's not good either.

        if with_base is None:
            with_base = to_fragment

        role_label = depend.Label(LabelType.Package,
                                  "*",
                                  from_role,
                                  LabelTag.PostInstalled,
                                  domain = self.builder.default_domain)
        r = self.builder.ruleset.rule_for_target(self.label, createIfNotPresent = False)
        if (r is None):
            raise GiveUp("Cannot copy from a package/deployment (%s) "%self.label +
                         " which has not yet been created.")

        r.add(role_label)
        self.action.target_base.append( ( role_label, ( from_fragment, to_fragment, with_base ) ) )

    def done(self):
        """
        Call this once you've added all the roles you want; it attaches
        the deployment environment to them and generally finishes up
        """
        self.action.attach_env(self.builder)


def create(builder, target_file, name, compressionMethod = None,
           pruneFunc = None):
    """
    Create a CPIO deployment and return it.

    * 'builder' is the muddle builder that is driving us

    * 'target_file' is the name of the CPIO file we want to create.
      Note that this may include a sub-path (for instance, "fred/file.cpio"
      or even "/fred/file.cpio").

    * 'name' is either:

        1. The name of the deployment that will contain this CPIO file
           (in the builder's default domain), or
        2. A deployment or package label, ditto

    * 'comporessionMethod' is the compression method to use:

        * None means no compression
        * 'gzip' means gzip
        * 'bzip2' means bzip2

    * if 'pruneFunc' is not None, it is a function to be called like
      pruneFunc(Hierarchy) to prune the hierarchy prior to packing. Usually
      something like deb.deb_prune, it's intended to remove spurious stuff like
      manpages from initrds and the like.

    Normal usage is thus something like::

        fw = cpio.create(builder, 'firmware.cpio', deployment)
        fw.copy_from_role(role1, '', '/')
        fw.copy_from_role(role2, 'bin', '/bin')
        fw.done()

    or::

        fw = cpio.create(builder, 'firmware.cpio', package('firmware', role))
        fw.copy_from_role(role, '', '/')
        fw.done()

    """

    if isinstance(name, basestring):
        label = depend.Label(LabelType.Deployment, name, None,
                             LabelTag.Deployed,
                             domain = builder.default_domain)
    elif isinstance(name, depend.Label):
        label = name
        if label.type not in (LabelType.Deployment, LabelType.Package):
            raise GiveUp("Third argument to muddled.deployments.cpio.create()"
                         " should be a string or a deployment/package label,"
                         " not a %s label"%label.type)

        if label.type == LabelType.Deployment and label.tag != LabelTag.Deployed:
            label = label.copy_with_tag(LabelTag.Deployed)
        elif label.type == LabelType.Package and label.tag != LabelTag.PostInstalled:
            label = label.copy_with_tag(LabelTag.PostInstalled)

    else:
        raise GiveUp("Third argument to muddled.deployments.cpio.create()"
                     " should be a string or a package/deployment label,"
                     " not %s"%type(name))

    the_action = CpioDeploymentBuilder(target_file, [], compressionMethod, pruneFunc)

    the_rule = depend.Rule(label, the_action)

    builder.ruleset.add(the_rule)

    if label.type == LabelType.Deployment:
        deployment.register_cleanup(builder, name)

    return CpioWrapper(builder, the_action, label)

