# Define our paths if no one has done it for us.
BASE_DIR ?= .
SRCDIR ?= $(BASE_DIR)/src
INCDIR ?= $(BASE_DIR)/include

BUILD_DIR ?= $(BASE_DIR)/build
BINDIR ?= $(BUILD_DIR)/bin
OBJDIR ?= $(BUILD_DIR)/obj
LIBDIR ?= $(BUILD_DIR)/lib
TSTDIR ?= $(OBJDIR)/tests
UTILDIR ?= $(BUILD_DIR)/utils

INSTALL_DIR ?= $(BASE_DIR)/install
INST_BINDIR ?= $(INSTALL_DIR)/bin
INST_LIBDIR ?= $(INSTALL_DIR)/lib
INST_INCDIR ?= $(INSTALL_DIR)/include

.PHONY: all progs libs test util clean distclean config install
.SUFFIXES:

all: progs libs util

$(BUILD_DIR) $(BINDIR) $(OBJDIR) $(LIBDIR) $(TSTDIR) $(INST_BINDIR) $(INST_LIBDIR) $(UTILDIR):
	$(AT)$(MKDIR_P) $@

config: $(BINDIR) $(OBJDIR) $(LIBDIR) $(TSTDIR) $(UTILDIR)

install: progs libs $(INST_BINDIR) $(INST_LIBDIR)
	$(foreach PROG, $(PROGS), $(call install-prog,$(PROG)))
	$(foreach LIB, $(LDLIBS), $(call install-ldlib,$(LIB)))
	$(foreach LIB, $(ARLIBS), $(call install-arlib,$(LIB)))

progs: $(PROGS:%=$(BINDIR)/%)

libs: $(LDLIBS:%=$(LIBDIR)/lib%.so) $(ARLIBS:%=$(LIBDIR)/lib%.a)

tests: $(TESTS:%=$(TSTDIR)/%_test)

util: $(UTILS:%=$(UTILDIR)/%)

test: $(TESTS:%=$(TSTDIR)/%_test)
	$(foreach TEST, $^, $(call execute-test,$(TEST)))

clean:
	rm -rf $(OBJDIR)

distclean:
	rm -rf $(BUILD_DIR)

# Note that we use *FLAGS in their "proper" places, that is:
# CPPFLAGS - whenever we compile or link C & C++ files.
# CXXFLAGS - whenever we compile C++ files.
# CFLAGS   - whenever we compile C files.
# LDFLAGS  - whenever we link anything.
CPPFLAGS += -g -fPIC -I$(INCDIR) $(EXTRA_CPPFLAGS)
CXXFLAGS += $(EXTRA_CXXFLAGS)
CFLAGS += $(EXTRA_CFLAGS)
LDFLAGS += $(EXTRA_LDFLAGS)

# Used to set LD_LIBRARY_PATH for running tests.
space:=$(empty) $(empty)
TEST_LDPATH := $(subst $(space),:,$(TEST_LDPATH_DIRS))

# Verbosity toggling
# By default we don't print the command being executed, we instead print short,
# readable messages. Setting V=1 kills the messages and shows the actual
# commands instead.
V ?= 0
ifeq ("$(V)", "0")
AT := @
ECHO := @echo
else
AT :=
ECHO := @true
endif

MKDIR_P := mkdir -p
CP_A := cp -a

# NOTE: If you're going to put recipe instructions in a define and call them
# in a loop, they will be smushed into a single shell invocation.
# So you need semicolons after each, and nothing that might expand to '@'.

# Run a test.
# Note that this will abort on the first test to exit with a non-zero status.
define execute-test
echo "Running test $(1)... ";
LD_LIBRARY_PATH=$(LD_LIBRARY_PATH):$(TEST_LDPATH):$(LIBDIR) $(1);
endef

# Install a program
define install-prog
echo "Installing $(1)... ";
install -m 0755 $(BINDIR)/$(1) $(INST_BINDIR)/$(1);
endef

# Install a dynamic library and its header files.
# Note that a library's header files are defined as being anything in
# $(INCDIR)/LIBRARY_NAME, if you want private header files, put them somewhere
# else.
define install-ldlib
echo "Installing lib$(1).so... ";
install -m 0644 $(LIBDIR)/lib$(1).so $(INST_LIBDIR)/;
$(MKDIR_P) $(INST_INCDIR)/$(1);
-$(CP_A) $(INCDIR)/$(1)/* $(INST_INCDIR)/$(1);
endef

# Install a static library and its header files.
define install-arlib
echo "Installing lib$(1).a... ";
install -m 0644 $(LIBDIR)/lib$(1).a $(INST_LIBDIR)/;
$(MKDIR_P) $(INST_INCDIR)/$(1);
-$(CP_A) $(INCDIR)/$(1)/* $(INST_INCDIR)/$(1);
endef

# Below is defined a set of macros that are used to build programs, static &
# dynamic libaries, and tests.
#
# The general idea is that every template calls BASE_template, which:
#   * takes an argument "foo", for which there should be a corresponding list
#     of source files named "foo_SOURCES"
#   * builds the lists of object files ("foo_OBJS") and dependency files
#     ("foo_DEPS") from the source list
#   * includes any of the dependency files that exist
#
# They then build their targets and depend on their object files, which the
# dependency files ensure depends on all their included headers. This means
# that everything should always be rebuilt correctly.

define BASE_template
$(1)_OBJS := $$($(1)_SOURCES:%=$$(OBJDIR)/%.o)
$(1)_DEPS := $$($(1)_OBJS:.o=.d)

-include $$($(1)_DEPS)
endef

define TEST_template
$$(eval $$(call BASE_template,$(1)))

$(1)_TEST_OBJS := $$($(1)_TEST:%=$$(OBJDIR)/%.o)
$(1)_TEST_DEPS := $$($(1)_TEST_OBJS:.o=.d)
$(1)_TEST_NAME := $(1)
$(1)_TEST_NAME := $$($(1)_TEST_NAME:%=$(TSTDIR)/%_test)
TEST_NAMES += $$($(1)_TEST_NAME)

-include $$($(1)_TEST_DEPS)

$$($(1)_TEST_NAME): $$($(1)_OBJS) $$($(1)_TEST_OBJS) | $(TSTDIR)
	$$(ECHO) "Creating test $$(@F)..."
	$$(AT)$$(CXX) -o $$@ $$^ -L$(LIBDIR) $$(LDFLAGS) $$($(1)_LDFLAGS) $$($(1)_TEST_LDFLAGS)
endef
$(foreach TEST, $(TESTS), $(eval $(call TEST_template,$(TEST))))

UTIL_LDFLAG_LIBS := -L$(LIBDIR) $(LDLIBS:%=-l%)
UTIL_LIBS := $(LDLIBS:%=$(LIBDIR)/lib%.so)

define UTIL_template
$$(eval $$(call BASE_template,$(1)))
$(1)_UTIL_OBJS := $$($(1)_SOURCES:%=$(OBJDIR)/utils/%.o) $$($(1)_EXTRA_OBJS:%=$(OBJDIR)/%)
$(1)_UTIL_DEPS := $$($(1)_UTIL_OBJS:.o=.d)
$(1)_UTIL_NAME := $(1)
$(1)_UTIL_NAME := $$($(1)_UTIL_NAME:%=$(UTILDIR)/%)
UTIL_NAMES += $$($(1)_UTIL_NAME)

-include $$($(1)_UTIL_DEPS)

$$($(1)_UTIL_NAME):  $$($(1)_UTIL_OBJS) | $(UTIL_LIBS) $(UTILDIR)
	$$(ECHO) "Creating utility $$(@F)..."
	$$(AT)$$(CXX) -o $$@ $$^ $$(LDFLAGS) $$($(1)_LDFLAGS) $$($(1)_UTIL_LDFLAGS) $$(UTIL_LDFLAG_LIBS) $$($(1)_LIBS)
endef
$(foreach UTIL, $(UTILS), $(eval $(call UTIL_template,$(UTIL))))

define PROG_template
$$(eval $$(call BASE_template,$(1)))

$(1)_MAIN_OBJ := $$($(1)_MAIN:%=$$(OBJDIR)/%.o)
$(1)_MAIN_DEP := $$($(1)_MAIN_OBJ:.o=.d)

-include $$($(1)_MAIN_DEP)

$$(BINDIR)/$(1): $$($(1)_OBJS) $$($(1)_MAIN_OBJ) | $(UTIL_LIBS) $(BINDIR)
	$$(ECHO) "Creating program $$(@F)..."
	$$(AT)$$(CXX) -o $$@ $$^ -L$(LIBDIR) $$(LDFLAGS) $$($(1)_LDFLAGS) $$($(1)_LIBS)
endef
$(foreach PROG, $(PROGS), $(eval $(call PROG_template,$(PROG))))

# @TODO soname
define LD_template
$$(eval $$(call BASE_template,$(1)))

$$(LIBDIR)/lib$(1).so: $$($(1)_OBJS) | $(LIBDIR)
	$$(ECHO) "Creating shared library $$(@F)..."
	$$(AT)$$(CC) -shared -o $$@ $$^ $$(LDFLAGS) $$($(1)_LDFLAGS)
endef
$(foreach LIB, $(LDLIBS), $(eval $(call LD_template,$(LIB))))

define AR_template
$$(eval $$(call BASE_template,$(1)))

$$(LIBDIR)/lib$(1).a: $$($(1)_OBJS) | $(LIBDIR)
	$$(ECHO) "Creating static library $$(@F)..."
	$$(AT)$$(AR) rc $$@ $$?
endef
$(foreach LIB, $(ARLIBS), $(eval $(call AR_template,$(LIB))))

# Here we make use of the -MMD flag (common to gcc & clang), which builds a
# foo.d file for every foo.o file, which contains a make rule that lists all of
# a source file's includes as a dependency for the .o file.
#
# These .d files are then included by BASE_template & friends.

$(OBJDIR)/%.cpp.o: $(SRCDIR)/%.cpp | $(OBJDIR)
	$(ECHO) "Compiling $<..."
	$(AT)test -d $(@D) || mkdir -pm 775 $(@D)
	$(AT)$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -c -o $@ $<

$(OBJDIR)/%.c.o: $(SRCDIR)/%.c | $(OBJDIR)
	$(ECHO) "Compiling $<..."
	$(AT)test -d $(@D) || mkdir -pm 775 $(@D)
	$(AT)$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -c -o $@ $<
