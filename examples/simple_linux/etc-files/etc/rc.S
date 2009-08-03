#! /bin/sh
#
# A minimal rcS

#### Initialise and mount the root pseudo-FSs ####

mount proc /proc -t proc -o nodev,noexec,nosuid

# Remount / rw. There's no point in all this faffing with
# tmpfs - this is the only RAMdisc we'll ever need (um, we hope).
#
# May want to split off other fs's into tmpfs later for security
# reasons, but we can do that later. Since root is more or less 
# the only useron the system it's not wholly important :-)
mount -o remount,rw /

mount sys /sys -t sysfs -o nodev,noexec,nosuid
#mount /fusectl /sys/fs/fuse/connections -t fusefs 


#### Start udev ####

cp -a -f /lib/udev/devices/* /dev
echo "" >/proc/sys/kernel/hotplug

# Set the hostname
hostname `cat /etc/hostname`

echo Starting udevd .. 
if start-stop-daemon --start --quiet --exec /sbin/udevd -- --daemon; then
    echo Started udevd ..
else
    echo Failed to start udevd
fi

echo Registering hardware drivers ..
/sbin/udevadm trigger
if /sbin/udevadm settle; then
   echo Hardware drivers registered.
else
    echo Failed to register hardware drivers
fi


#### Mount /dev/shm and /dev/pts ####

mount shmfs /dev/shm -t tmpfs -o nosuid,nodev
mount devpts /dev/pts -t devpts

#### Explicitly insmod any drivers you need here ####

#### Any sysctls you want go here ####

#### This is where we would check our filesystems ####
#### if there were any point.                     ####

#### We should initialise the RNG here, but we can't ####
#### because there is nothing to initialise it with  ####

#### Now kick off all the system initialisation functions ####
for rcfile in `ls /etc/rc.d`; do
    /etc/rc.d/$rcfile start
done


# End file.

