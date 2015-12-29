EXTRA_CPPFLAGS += $(MUDDLE_INCLUDE_DIRS:%=-I%)
EXTRA_LDFLAGS += $(MUDDLE_LIB_DIRS:%=-L%)
# Put these directories in the LD_LIBRARY_PATH when running tests.
TEST_LDPATH_DIRS += $(MUDDLE_LIB_DIRS)

BUILD_DIR ?= $(MUDDLE_OBJ)
OBJDIR ?= $(MUDDLE_OBJ_OBJ)
INSTALL_DIR ?= $(MUDDLE_INSTALL)
INST_INCDIR ?= $(MUDDLE_OBJ)/include

BASE_DIR ?= $(MUDDLE_SRC)

THIS_FILE := $(abspath $(lastword $(MAKEFILE_LIST)))
include $(dir $(THIS_FILE))/rules.mk
