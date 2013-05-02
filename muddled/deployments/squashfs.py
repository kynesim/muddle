""" A SquashFS deployment.

This deployment uses mksquashfs to generate a squashfs image.

We are modelled after the RomFS deployment, but are sufficiently different
from it (in e.g. the format of device special pseudofiles) that we don't
use the same code.
"""

import os
import errno

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

class SquashFSApplyMknod(InstructionImplementor):
    def prepare(self, builder, instr, role, path):
        return True

    def apply(self, builder, instr, role, path):
        print "Warning: Attempt to apply a mknod() instruction in a squashfs FS - ignored."
        return True


class SquashFSDeploymentBuilder(CollectDeploymentBuilder):
    """
    Builds the specified squashfs deployment

    * 'targetName' is the name of the target squashfs filesytem file.
    * 'mkSquashFS', if given, is the name of the mksquashfs program
      to use. The default is "mksquashfs".
    """

    def __init__(self, targetName, mkSquashFS=None):
        self.assemblies = []
        self.what = 'SquashFS'
        self.target_name = targetName
        self.my_tmp = None
        if mkSquashFS is None:
            self.mksquashfs = "mksquashfs"
        else:
            self.mksquashfs = mkSquashFS

        self.app_dict = {"chown" : CollectApplyChown(),
                         "chmod" : CollectApplyChmod(),
                         "mknod" : SquashFSApplyMknod(),
                        }

    def do_mksquashfs(self, builder, label, my_tmp):
        """
        mksquashfs everything up into a SquashFS image.
        """
        if (self.target_name is None):
            tgt = "rom.squashfs"
        else:
            tgt = self.target_name

        utils.ensure_dir(builder.deploy_path(label))

        final_tgt = os.path.join(builder.deploy_path(label), tgt)
        # mksquashfs will, by default, append rather than replacing, so..
        try:
            os.remove(final_tgt)
        except OSError as e:
            if e.errno != errno.ENOENT: # Only re-raise if it wasn't file missing
                raise
        cmd = "%s \"%s\" \"%s\" -noappend -all-root -info -comp xz"%(self.mksquashfs, my_tmp, final_tgt)
        utils.run0(cmd)

    def build_label(self, builder, label):
        """
        Copy everything to a temporary directory and then mksquashfs it.
        """

        if self.my_tmp is None:
            self.my_tmp = tempfile.mkdtemp();

        print "Deploying to %s .. \n"%self.my_tmp

        if label.tag == utils.LabelTag.Deployed:
            self.apply_instructions(builder, label, True, self.my_tmp)
            self.deploy(builder, label, self.my_tmp)
            self.do_mksquashfs(builder, label, self.my_tmp)
            utils.recursively_remove(self.my_tmp)
        else:
            raise utils.GiveUp("Attempt to build a deployment with an unexpected tag in label %s"%(label))


def deploy(builder, name, targetName = None, mkSquashFS = None):
    """
    Create a SquashFS deployment builder.

    This adds a new rule linking the label ``deployment:<name>/deployed``
    to the collection deployment builder.

    You can then add assembly descriptors using the other utility functions in
    this module.

    Dependencies get registered when you add an assembly descriptor.

    targetName is the name of the ROM file to generate
    volumeLabel is the volume label
    alignment is the object alignment.
    """
    the_action = SquashFSDeploymentBuilder(targetName, mkSquashFS)
    _inside_of_deploy(builder, name, the_action)

# End file.
