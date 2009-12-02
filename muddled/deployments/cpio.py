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
import muddled.filespec as filespec
import muddled.deployment as deployment
import muddled.cpiofile as cpiofile
import os

class CpioInstructionImplementor:
    def apply(self, builder, instruction, role, path):
        pass

class CpioDeploymentBuilder(pkg.Dependable):
    """
    Builds the specified CPIO deployment.
    """
    
    def __init__(self, target_file, target_base, 
                 compressionMethod = None, 
                 pruneFunc = None):
        """
        target_base is a dictionary mapping roles to their root addresses
        in the heirarchy.
        """
        self.target_file = target_file
        self.target_base = target_base
        self.compression_method = compressionMethod
        self.prune_function = pruneFunc

    def attach_env(self, builder):
        """
        Attaches an environment containing:
        
          MUDDLE_TARGET_LOCATION - the location in the target filesystem where
          this deployment will end up.

        to every package label in this role.
        """
        
        for (l,b) in self.target_base.items():
            lbl = depend.Label(utils.LabelKind.Package,
                               "*",
                               l.role,
                               "*", 
                               domain = l.domain)
            env = builder.invocation.get_environment_for(lbl)
        
            env.set_type("MUDDLE_TARGET_LOCATION", muddled.env_store.EnvType.SimpleValue)
            env.set("MUDDLE_TARGET_LOCATION", b)
    


    def build_label(self,builder, label):
        """
        Actually cpio everything up, following instructions appropriately.
        """
        
        if (label.tag == utils.Tags.Deployed):
            # Collect all the relevant files ..
            deploy_dir = builder.invocation.deploy_path(label.name, 
                                                        domain = label.domain)
            deploy_file = os.path.join(deploy_dir,
                                       self.target_file)

            utils.ensure_dir(os.path.dirname(deploy_file))

            
            the_heirarchy = cpiofile.Heirarchy({ }, { })
            for (l,base) in self.target_base.items():
                m = cpiofile.heirarchy_from_fs(builder.invocation.role_install_path
                                               (l.role, 
                                                domain = l.domain), 
                                               base)
                the_heirarchy.merge(m)

            # Normalise the heirarchy .. 
            the_heirarchy.normalise()
            #print "h = %s"%the_heirarchy

            if (self.prune_function is not None):
                self.prune_function(the_heirarchy)

            app_dict = get_instruction_dict()


            # Apply instructions .. 
            for (src,base) in self.target_base.items():
                lbl = depend.Label(utils.LabelKind.Package, "*", src.role, "*", 
                                   domain = src.domain)
                print "Scanning instructions for role %s, domain %s .. "%(src.role, src.domain)
                instr_list = builder.load_instructions(lbl)
                for (lbl, fn, instrs) in instr_list:
                    print "Applying instructions for role %s, label %s .. "%(src.role, lbl)
                    for instr in instrs:
                        iname = instr.outer_elem_name()
                        if (iname in app_dict):
                            app_dict[iname].apply(builder, instr, lbl.role,
                                                  base,
                                                  the_heirarchy)
                        else:
                            raise utils.Failure("CPIO deployments don't know about "
                                                "the instruction %s (lbl %s, file %s"%(iname, lbl, fn))
            # .. and write the file.
            print "> Writing %s .. "%deploy_file
            the_heirarchy.render(deploy_file, True)
            
            if (self.compression_method is not None):
                if (self.compression_method == "gzip"):
                    utils.run_cmd("gzip -f %s"%deploy_file)
                elif (self.compression_method == "bzip2"):
                    utils.run_cmd("bzip2 -f %s"%deploy_file)
                else:
                    raise utils.Failure("Invalid compression method %s"%self.compression_method + 
                                        "specified for cpio deployment. Pick gzip or bzip2.")

        else:
            raise utils.Failure("Attempt to build a cpio deployment with unknown label %s"%(lbl))

class CIApplyChmod(CpioInstructionImplementor):
    def apply(self, builder, instr, role, target_base, heirarchy):
        dp = cpiofile.CpioFileDataProvider(heirarchy)

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
    def apply(self, builder, instr, role, target_base, heirarchy):
        dp = cpiofile.CpioFileDataProvider(heirarchy)
        files = dp.abs_match(instr.filespec, vroot = target_base)

        uid = utils.parse_uid(builder, instr.new_user)
        gid = utils.parse_gid(builder, instr.new_group)

        for f in files:
            if (instr.new_user is not None):
                f.uid = uid
            if (instr.new_group is not None):
                f.gid = gid

class CIApplyMknod(CpioInstructionImplementor):
    def apply(self, builder, instr, role, target_base, heirarchy):
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
        heirarchy.put_target_file(real_path, cpio_file)
        

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
           pruneFunc = None):
    """
    Set up a cpio deployment

    * target_file - Where, relative to the deployment directory, should the
      build cpio file end up? Note that compression will add a suitable '.gz'
      or '.bz2' suffix.
    * target_bases - Where should we expect to unpack the CPIO file to - this
      is a dictionary mapping labels to target locations.
    * compressionMethod - The compression method to use, if any - gzip -> gzip,
      bzip2 -> bzip2.
    * pruneFunc - If not None, this a function to be called like
      pruneFunc(Heirarchy) to prune the heirarchy prior to packing. Usually
      something like deb.deb_prune, it's intended to remove spurious stuff like
      manpages from initrds and the like.
    * roles - The roles to place in the deployed archive; note that roles are
      merged into the archive in the order specified here, so files in later
      roles will override those in earlier roles.
    """

    the_dependable = CpioDeploymentBuilder(target_file, 
                                           target_base, compressionMethod, 
                                           pruneFunc = pruneFunc)
    
    dep_label = depend.Label(utils.LabelKind.Deployment,
                             name, None,
                             utils.Tags.Deployed, 
                             domain = builder.default_domain)

    deployment_rule = depend.Rule(dep_label, the_dependable)
    for lbl in target_base.keys():
        role_label = depend.Label(utils.LabelKind.Package,
                                  "*",
                                  lbl.role,
                                  utils.Tags.PostInstalled,
                                  domain = lbl.domain)
        deployment_rule.add(role_label)

    builder.invocation.ruleset.add(deployment_rule)

    the_dependable.attach_env(builder)
    
    # Cleanup is generic
    deployment.register_cleanup(builder, name)




def deploy(builder, target_file, target_base, name, roles,
           compressionMethod = None,
           pruneFunc = None):
    """
    Legacy entry point for cpio: roles is a list of roles, target_base
    the list of role -> path mappings
    """

    proper_target_base = { }
    for (r,base) in target_base.items():
        lbl = depend.Label(utils.LabelKind.Package,
                           "*",
                           r, 
                           "*",
                           domain = builder.default_domain)
        proper_target_base[lbl] = base

    return deploy_labels(builder, target_file, proper_target_base, name,
                         compressionMethod, pruneFunc)
           

# End file.


        
