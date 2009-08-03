# Makefile for init-files
#

all:
	@echo Nothing to do

config:
	@echo Nothing to do

DIRS_TO_BUILD=dev proc sys lib/udev/devices lib/udev/devices/net lib/udev/devices/pts \
	lib/udev/devices/shm

install:
	$(MUDDLE_INSTRUCT) instructions.xml
	if [ ! -d $(MUDDLE_INSTALL)/etc ]; then mkdir $(MUDDLE_INSTALL)/etc; fi
	if [ ! -d $(MUDDLE_INSTALL)/etc/init.d ]; then mkdir $(MUDDLE_INSTALL)/etc/init.d; fi
	# We need to exclude .svn files from the copy. Ugh.
	$(MUDDLE) copywithout etc/ $(MUDDLE_INSTALL)/etc .svn
	-rm -rf  $(MUDDLE_INSTALL)/lib/udev/devices/*
	for i in $(DIRS_TO_BUILD); do \
		if [ ! -d $(MUDDLE_INSTALL)/$$i ]; then mkdir -p $(MUDDLE_INSTALL)/$$i; fi;\
	done
	ln -fs /proc/kcore $(MUDDLE_INSTALL)/lib/udev/devices/core 
	ln -fs /proc/self/fd $(MUDDLE_INSTALL)/lib/udev/devices/fd
	ln -fs /sbin/MAKEDEV $(MUDDLE_INSTALL)/lib/udev/devices/MAKEDEV
	ln -fs /sbin/sndstat $(MUDDLE_INSTALL)/lib/udev/devices/sndstat
	ln -fs /proc/self/fd/2 $(MUDDLE_INSTALL)/lib/udev/devices/stderr
	ln -fs /proc/self/fd/0 $(MUDDLE_INSTALL)/lib/udev/devices/stdin
	ln -fs /proc/self/fd/1 $(MUDDLE_INSTALL)/lib/udev/devices/stdout

	# Oh, you _guys_ .. 
	for i in /var/run /tmp /var/log; do \
	  if [ ! -d "$(MUDDLE_INSTALL)$$i" ]; then \
	   mkdir -p "$(MUDDLE_INSTALL)$$i";  \
	 fi\
       done

install-udev-lib:
	# Nothing to do


clean:
	@echo Nothing to do

distclean:
	@echo Nothing to do.


# End file.
