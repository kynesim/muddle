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


import muddled
import muddled.pkg as pkg
import muddled.env_store
import muddled.depend as depend
import muddled.utils as utils
import muddled.deployment as deployment
import muddled.cpiofile as cpiofile
import types
import os

class CpioInstructionImplementor:
    def apply(self, builder, instruction, role, path):
        pass

class CpioDeploymentBuilder(pkg.Action):
    """
    Builds the specified CPIO deployment.
    """
    
    def __init__(self, target_file, target_base, 
                 compressionMethod = None, 
                 pruneFunc = None):
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

            lbl = depend.Label(utils.LabelType.Package,
                               "*",
                               l.role,
                               "*", 
                               domain = l.domain)
            env = builder.invocation.get_environment_for(lbl)
        
            env.set_type("MUDDLE_TARGET_LOCATION", muddled.env_store.EnvType.SimpleValue)
            env.set("MUDDLE_TARGET_LOCATION", target_loc)
    


    def build_label(self,builder, label):
        """
        Actually cpio everything up, following instructions appropriately.
        """
        
        if (label.tag == utils.LabelTag.Deployed):
            # Collect all the relevant files ..
            deploy_dir = builder.invocation.deploy_path(label.name, 
                                                        domain = label.domain)
            deploy_file = os.path.join(deploy_dir,
                                       self.target_file)

            utils.ensure_dir(os.path.dirname(deploy_file))

            
            the_hierarchy = cpiofile.Hierarchy({ }, { })
            


            for (l,bt) in self.target_base:
                if (type ( bt ) == types.TupleType ):
                    real_source_path = os.path.join(builder.invocation.role_install_path(l.role,
                                                                                         l.domain),
                                                    bt[0])
                    base = bt[1]
                else:
                    base = bt
                    real_source_path = os.path.join(builder.invocation.role_install_path(l.role,
                                                                                         l.domain))


                print "Collecting %s  for deployment to %s .. "%(l,base)
                if (len(base) > 0 and base[0] != '/'):
                    base = "/%s"%(base)

                m = cpiofile.hierarchy_from_fs(real_source_path,
                                               base)
                the_hierarchy.merge(m)

            # Normalise the hierarchy .. 
            the_hierarchy.normalise()
            print "h = %s"%the_hierarchy

            if (self.prune_function is not None):
                self.prune_function(the_hierarchy)

            app_dict = get_instruction_dict()


            # Apply instructions .. 
            for (src,bt) in self.target_base:
                if (type (bt) == types.TupleType ):
                    base = bt[1]
                else:
                    base = bt

                print "base = %s"%(base)
                lbl = depend.Label(utils.LabelType.Package, "*", src.role, "*",
                                   domain = src.domain)
                print "Scanning instructions for role %s, domain %s .. "%(src.role, src.domain)
                instr_list = builder.load_instructions(lbl)
                for (lbl, fn, instrs) in instr_list:
                    print "CPIO deployment: Applying instructions for role %s, label %s .. "%(src.role, lbl)
                    for instr in instrs:
                        iname = instr.outer_elem_name()
                        print 'Instruction:', iname
                        if (iname in app_dict):
                            app_dict[iname].apply(builder, instr, lbl.role,
                                                  base,
                                                  the_hierarchy)
                        else:
                            raise utils.GiveUp("CPIO deployments don't know about "
                                                "the instruction %s (lbl %s, file %s"%(iname, lbl, fn))
            # .. and write the file.
            print "> Writing %s .. "%deploy_file
            the_hierarchy.render(deploy_file, True)
            
            if (self.compression_method is not None):
                if (self.compression_method == "gzip"):
                    utils.run_cmd("gzip -f %s"%deploy_file)
                elif (self.compression_method == "bzip2"):
                    utils.run_cmd("bzip2 -f %s"%deploy_file)
                else:
                    raise utils.GiveUp("Invalid compression method %s"%self.compression_method + 
                                        "specified for cpio deployment. Pick gzip or bzip2.")

        else:
            raise utils.GiveUp("Attempt to build a cpio deployment with unknown label %s"%(lbl))

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

        print "target_base = %s for role %s"%(target_base, role)
        real_path = utils.rel_join(target_base, instr.file_name)
        
        cpio_file.key_name = real_path
        print "put_target_file %s"%real_path
        hierarchy.put_target_file(real_path, cpio_file)
        

def get_instruction_dict():
    """
    Return a dictionary mapping the names of instructions to the
    classes that implement them.
    """
    app_dict = { }
    app_dict["chown"] = CIApplyChown()
    app_dict["chmod"] = CIApplyChmod()
    app_dict["mknod"] = CIApplyMknod()
    return app_dict

def deploy_labels(builder, target_file, target_base, name,  
           compressionMethod = None, 
           pruneFunc = None, target_labels_order = None):
    """
    Set up a cpio deployment

    @todo  This is (probably) fatally broken - we won't deploy packages
             correctly at all, but I have no time to fix it properly - 
             rrw 2010-01-27


    * target_file - Where, relative to the deployment directory, should the
      build cpio file end up? Note that compression will add a suitable '.gz'
      or '.bz2' suffix.
    * target_base - Where should we expect to unpack the CPIO file to - this
      is a dictionary mapping labels to target locations. If the target location
      is a tuple (s,d), it maps a source to a destination. 
    * compressionMethod - The compression method to use, if any - gzip -> gzip,
      bzip2 -> bzip2.
    * pruneFunc - If not None, this a function to be called like
      pruneFunc(Hierarchy) to prune the hierarchy prior to packing. Usually
      something like deb.deb_prune, it's intended to remove spurious stuff like
      manpages from initrds and the like.
    * target_labels_order - Order in which labels should be merged. Labels not
       mentioned get merged in any old order.
    """

    out_target_base = [ ]
    strike_out = { }
    if (target_labels_order is not None):
        for t in target_labels_order:
            if (t in strike_out):
                raise utils.MuddleBug("Duplicate label %s in attempt to order cpio deployment"%t)
                                  
            if (t in target_base):
                out_target_base.append( (t, target_base[t]) )
                strike_out[t] = target_base[t]
    
    # Now add everything not specified in the target_order
    for (k,v) in target_base.items():
        if (k not in strike_out):
            # Wasn't in the order - append it.
            out_target_base.append( (k,v) )
            


    the_action = CpioDeploymentBuilder(target_file, 
                                           out_target_base, compressionMethod, 
                                           pruneFunc = pruneFunc)
    
    dep_label = depend.Label(utils.LabelType.Deployment,
                             name, None,
                             utils.LabelTag.Deployed,
                             domain = builder.default_domain)

    deployment_rule = depend.Rule(dep_label, the_action)

    # Now do the dependency thing .. 
    for ( ltuple, base )  in out_target_base:
        if (type ( ltuple ) == types.TupleType ):
            real_lbl = ltuple[0]
        else:
            real_lbl = ltuple

        role_label = depend.Label(utils.LabelType.Package,
                                  "*",
                                  real_lbl.role,
                                  utils.LabelTag.PostInstalled,
                                  domain = real_lbl.domain)
        deployment_rule.add(role_label)
                

    #print "Add to deployment %s .. "%(deployment_rule)
    builder.invocation.ruleset.add(deployment_rule)

    the_action.attach_env(builder)
    
    # Cleanup is generic
    deployment.register_cleanup(builder, name)

    return the_action



def deploy(builder, target_file, target_base, name, target_roles_order,
           compressionMethod = None,
           pruneFunc = None):
    """
    Legacy entry point for cpio: target_order is a list of roles in order they are to be copied,
    target_base the list of role -> path mappings
    
    If target_order's target is a pair (src, dst) only that (src,dst) will be copied, so
    ( "foo", ("/a/b", "/c/d") )

    Copies install/foo/a/b to deploy/XXX/c/d .
    
    """
    proper_target_base = { }
    for (r,base) in target_base.items():
        lbl = depend.Label(utils.LabelType.Package,
                           "*",
                           r, 
                           "*",
                           domain = builder.default_domain)
        proper_target_base[lbl] = base
        

    label_order = [ ]
    for r in target_roles_order:
        lbl = depend.Label(utils.LabelType.Package,
                           "*",
                           r, 
                           "*",
                           domain = builder.default_domain)
        label_order.append(lbl)

    return deploy_labels(builder, target_file, proper_target_base, name,
                         compressionMethod, pruneFunc, label_order)


class CpioWrapper:
    def __init__(self, builder, action, label):
        self.action = action
        self.label = label
        self.builder = builder


    def copy_from_role(self, from_role, from_fragment, to_fragment):
        """
        Copy the relative path from_fragment in from_role to to_fragment in the CPIO
        deployment given by 'action'
        """
        
        role_label = depend.Label(utils.LabelType.Package,
                                  "*",
                                  from_role,
                                  utils.LabelTag.PostInstalled,
                                  domain = self.builder.default_domain)
        r = self.builder.invocation.ruleset.rule_for_target(self.label, createIfNotPresent = False)
        if (r is None):
            raise utils.GiveUp("Cannot copy from a deployment (%s) "%self.label +
                               " which has not yet been created.")
        
        r.add(role_label)
        self.action.target_base.append( ( role_label, ( from_fragment, to_fragment ) ) )
        
    def done(self):
        """
        Call this once you've added all the roles you want; it attaches
        the deployment environment to them and generally finishes up
        """
        self.action.attach_env(self.builder)



def create(builder, target_file, name, compressionMethod = None, 
           pruneFunc = None):
    """
    Create a CPIO deployment with the given name and return it.
    """
    
    the_action = CpioDeploymentBuilder(target_file,
                                           [ ],
                                           compressionMethod,
                                           pruneFunc)
    
    dep_label = depend.Label(utils.LabelType.Deployment, name, None,
                             utils.LabelTag.Deployed,
                             domain = builder.default_domain)

    deployment_rule = depend.Rule(dep_label, the_action)

    builder.invocation.ruleset.add(deployment_rule)
    deployment.register_cleanup(builder, name)

    return CpioWrapper(builder, the_action, dep_label)



           

# End file.


        
