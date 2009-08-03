kernel_config is your kernel configuration file.
You should un-bzip2 a set of kernel sources into linux-2.6.30/ in this
  directory.
If makeInstall is True in the build description, we'll run
 'make install' from this directory to do any depmod'ing or 
 module copying that we need to.
