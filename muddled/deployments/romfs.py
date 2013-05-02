"""
A RomFS deployment.

This deployment uses genromfs to generate a ROM FS image. It first assembles a
suitable tree in a temporary directory, then runs genromfs to generate the image.

RomFS deployment is modeled after the collect deployment.
"""

import os

import muddled.depend as depend
import muddled.utils as utils
import muddled.filespec as filespec
import muddled.deployment as deployment
import tempfile

from muddled.depend import Action, Label
from muddled.deployments.collect import InstructionImplementor, \
        AssemblyDescriptor, CollectDeploymentBuilder, \
        CollectApplyChown, CollectApplyChmod, _inside_of_deploy

# And, so that the user of this module can use them
from muddled.deployments.collect import copy_from_checkout, \
                                        copy_from_package_obj, \
                                        copy_from_role_install, \
                                        copy_from_deployment

class RomFSApplyChmod(CollectApplyChmod):

    # XXX Why is this different than for collect?
    def needs_privilege(self, builder, instr, role, path):
        return False

class RomFSApplyMknod(InstructionImplementor):

    def prepare(self, builder, instr, role, path):
        return True

    def apply(self, builder, instr, role, path):
        dp = filespec.FSFileSpecDataProvider(path)
        in_dir = os.path.dirname(instr.file_name)
        file_name = os.path.basename(instr.file_name)

        utils.ensure_dir(in_dir)
        if instr.type == "char":
            rtype = "c"
        else:
            rtype = "b"

        magic_file = "@%s,%s,%d,%d"%(file_name, rtype, int(instr.major),
                                     int(instr.minor))
        f = open(os.path.join(in_dir, magic_file), 'w')
        f.close()
        return True


class RomFSDeploymentBuilder(CollectDeploymentBuilder):
    """
    Builds the specified romfs deployment

    * 'targetName' is the name of the target squashfs filesytem file.
    * 'volumeLabel' is the volume label to use.
    * 'alignment' is the byte alignment to use for regular files
    * 'genRomFS', if given, is the name of the genromfs program to use. The
      default is "genromfs".
    """

    def __init__(self, targetName, volumeLabel=None, alignment=None, genRomFS=None):
        self.assemblies = []
        self.what = 'RomFS'
        self.target_name = targetName
        self.volume_label = volumeLabel
        self.alignment = alignment
        self.my_tmp = None
        if genRomFS is None:
            self.genromfs = "genromfs"
        else:
            self.genromfs = genRomFS

        self.app_dict = {"chown" : CollectApplyChown(),
                         "chmod" : RomFSApplyChmod(),
                         "mknod" : RomFSApplyMknod(),
                        }

    def do_genromfs(self, builder, label, my_tmp):
        """
        genromfs everything up into a RomFS image.
        """
        if self.target_name is None:
            tgt = "rom.romfs"
        else:
            tgt = self.target_name

        utils.ensure_dir(builder.deploy_path(label))
        final_tgt = os.path.join(builder.deploy_path(label), tgt)
        cmd = "%s -f \"%s\""%(self.genromfs, final_tgt)
        if (self.volume_label is not None):
            cmd = cmd + " -V \"%s\""%self.volume_label
        if (self.alignment is not None):
            cmd = cmd + " -a %d"%(int(self.alignment))
        cmd = cmd + " -d \"%s\""%(my_tmp)
        utils.run0(cmd)

    def build_label(self, builder, label):
        """
        Copy everything to a temporary directory and then genromfs it.
        """

        if self.my_tmp is None:
            self.my_tmp = tempfile.mkdtemp();

        print "Deploying to %s .. \n"%self.my_tmp

        if label.tag == utils.LabelTag.Deployed:
            self.apply_instructions(builder, label, True, self.my_tmp)
            self.deploy(builder, label, self.my_tmp)
            self.do_genromfs(builder, label, self.my_tmp)
            utils.recursively_remove(self.my_tmp)
        else:
            raise utils.GiveUp("Attempt to build a deployment with an unexpected tag in label %s"%(label))


def deploy(builder, name, targetName=None, volumeLabel=None,
           alignment=None, genRomFS=None):
    """
    Create a RomFS deployment builder.

    This adds a new rule linking the label ``deployment:<name>/deployed``
    to the collection deployment builder.

    You can then add assembly descriptors using the other utility functions in
    this module.

    Dependencies get registered when you add an assembly descriptor.

    * targetName is the name of the ROM file to generate
    * volumeLabel is the volume label
    * alignment is the object alignment.
    """
    the_action = RomFSDeploymentBuilder(targetName, volumeLabel, alignment,
                                        genRomFS)
    _inside_of_deploy(builder, name, the_action)

# End file.
