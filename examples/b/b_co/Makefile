# Makefile for b_co
#
# Common variables for muddle makefiles
#
# MUDDLE_OBJ  - Build object files here
# MUDDLE_INSTALL - Install files to here.

INSTALL=install

all:
	$(CC) -o $(MUDDLE_OBJ)/hello_world hello_world.c

install:
	$(INSTALL) -m 0755 $(MUDDLE_OBJ)/hello_world $(MUDDLE_INSTALL)/hello_world

config:
	@echo Nothing to do

clean:
	rm -f $(MUDDLE_OBJ)/hello_world

distclean: clean
	@echo Distclean is just a clean


# End file.

