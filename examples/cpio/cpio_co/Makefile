# Makefile for cpio_co
#
# Just dumps some compiled C into the right place.

INSTALL=install

all:
	$(CC) -o $(MUDDLE_OBJ)/hello_world hello_world.c

install:
	if [ ! -d $(MUDDLE_INSTALL)/bin ]; then mkdir $(MUDDLE_INSTALL)/bin; fi
	$(INSTALL) -m 0755 $(MUDDLE_OBJ)/hello_world $(MUDDLE_INSTALL)/bin/hello_world
	$(INSTALL) -m 0644 hello_world.c $(MUDDLE_INSTALL)/hello_world.c

config:
	@echo Nothing to do

clean:
	rm -f $(MUDDLE_OBJ)/hello_world

distclean: clean
	@echo Distclean is just a clean

# end file.
