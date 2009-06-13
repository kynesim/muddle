#! /bin/sh
#
# Shell general init script. Can't use python here as the
# target may not have it.

TARGET_INSTALL_LOCATION=${MUDDLE_TARGET_LOCATION}
BUILD_NAME=${MUDDLE_ROLE}

PATH=$TARGET_INSTALL_LOCATION/bin:$PATH
LD_LIBRARY_PATH=$TARGET_INSTALL_LOCATION/lib:$LD_LIBRARY_PATH
INITRD_PATH=$TARGET_INSTALL_LOCATION/etc/init.d

export PATH
export LD_LIBRARY_PATH
export INITRD_PATH
export TARGET_INSTALL_LOCATION

if [ -e $TARGET_INSTALL_LOCATION/bin/setvars ]; then
     . $TARGET_INSTALL_LOCATION/bin/setvars
fi

case "$1" in
    start) 
	VERB="Starting"
	;;
    end)
	VERB="Stopping"
	;;
    restart)
	VERB="Restarting"
	;;
    *)
	VERB=$1
esac

if [ -e $TARGET_INSTALL_LOCATION/bin/setvars ]; then
    . $TARGET_INSTALL_LOCATION/bin/setvars
fi

echo "$VERB $BUILD_NAME .. "
if [ ! -d $INITRD_PATH ]; then
    echo "No $INITRD_PATH - cannot find initialisation scripts"
    exit 1
fi

exitcode=0

for i in `cd $INITRD_PATH; ls`; do
    echo "  $VERB $i ... "
    $INITRD_PATH/$i $1
    rc=$?
    if [ $rc -ne 0 ]; then
	echo "   ... [ Failed ]"
	exitcode=1
    else
	echo "   ... [ OK ]"
    fi
    
done

exit $RC
