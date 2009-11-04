A very simple example of how to build a Linux for the Beagleboard.

Attempts to make a build using head-of-tree OMAP Linux and Busybox.

Slightly old-fashioned in how it does it (my style for the 01.py has changed
slightly), but should do what it aims.

Use by the normal incantations::

  muddle init svn+http://muddle.googlecode.com/svn/trunk/muddle/examples/simple.beagle builds/01.py
  muddle

Using the results
-----------------
You need a flash card with two partitions. The first should be FAT32, and 50MB
is plenty. The second should be EXT3, and I call it Linux.

Copy the contents of the fat32 directory into the FAT32 partition.

Copy (nb: ``sudo cp -a`` is your friend) the contents of the rootfs directory
into the Linux partition.

Old boot instructions
---------------------
I've been booting following the instructions at http://free-electrons.com/blog/android-beagle/

For instance::

    setenv bootargs console=ttyS2,115200n8 noinitrd root=/dev/mmcblk0p2 video=omapfb.mode=dvi:1280x720MR-24@50 init=/init rootfstype=ext3 rw rootdelay=1 nohz=off androidboot.console=ttyS2

(you may or may not want to "saveenv") and theni (assuming the flash card is
inserted)::

    mmc init
    fatload mmc 0 0x80000000 uImage
    bootm 0x80000000

Newer boot instructions
-----------------------
These have primarily been used for a different setup, but will probably work
with this one.

Start up the beagleboard and set things::

  setenv bootcmd 'mmc init; fatload mmc 0:1 0x80300000 uImage; bootm 0x80300000'
  setenv bootargs 'console=ttyS2,115200n8 root=/dev/mmcblk0p2 rootwait rootfstype=ext3 rw'
  saveenv
  boot

(note the ``mmc init`` instead of ``mmcinit``. On my Beagleboard, if I break
into the U-Boot prompt when the flash card is *not* in, I get an older version
of U-Boot (or a different one, at least) for which the command is ``mmcinit``.
If I boot with the flash card *in*, I get the ``mcc init`` form...)

