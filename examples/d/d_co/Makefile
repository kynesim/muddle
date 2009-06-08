# Makefile for c_co
#

INSTALL=install

all:
	$(CC) -o $(MUDDLE_OBJ)/hello_world hello_world.c

install:
	$(INSTALL) -D -m 0755 $(MUDDLE_OBJ)/hello_world $(MUDDLE_INSTALL)/bin/hello_world
	$(MUDDLE_INSTRUCT) postbuild_instructions.xml

config:
	@echo Nothing to do

clean:
	rm -f $(MUDDLE_OBJ)/hello_world
	$(MUDDLE_UNINSTRUCT) 

distclean: clean
	@echo Distclean is just a clean

# End file
