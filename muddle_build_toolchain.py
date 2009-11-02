#! /usr/bin/env python

""" 
muddle_build_toolchain.py

This script invokes a bunch of commands to build a toolchain from a 
CodeSourcery source package.

It is not formally a part of muddle because you normally want to
build toolchains separately from your build, under controlled 
conditions.

muddle_build_toolchain.py relies on a configuration file, like
those in examples/toolchains .

Usage: muddle_build_toolchain.py [config file] <[stage]>

Patches are from whole package directories so given:

binutils-notworking
binutils-working

do 

diff -urN binutils-notworking binutils-working > my.patch


Switches:

 --help    Print out this help.

"""

import sys
import os
import re
import xml.dom
import xml.dom.minidom
import muddled
import muddled.xmlconfig as xmlconfig

# Should we run just the stage specified, or from the stage 
# specified?
gStageExact = False

class GiveUp(Exception):
    pass


def unpack_bz2(srcdir,filename,tmpdir):
    rv = os.chdir(tmpdir)
    if rv:
        raise GiveUp("Cannot change directory to %s"%tmpdir)

    full_filename = os.path.join(srcdir,filename)
    
    rv = run_command("bzip2 -dc %s | tar  xvf - "%full_filename)
    if rv:
        raise GiveUp("Can't unpack %s - %d"%(filename, rv))

def query_archive(config, pkg):
    return config.query_string("/toolchain/sources/%s/archive"%pkg)

def query_dir(config,pkg):
    return config.query_string("/toolchain/sources/%s/dir"%pkg)
    
def restore_env(saved):
    os.environ = saved

def set_env(k,v):
    os.environ[k] = v

def append_env(k,v):
    if (k in os.environ):
        os.environ[k] = "%s:%s"%(os.environ[k], v)
    else:
        os.environ[k] = v

def prepend_env(k,v):
    if (k in os.environ):
        os.environ[k] = "%s:%s"%(v,os.environ[k])
    else:
        os.environ[k] = v

def run_command(cmd):
    print "%s\n"%cmd
    return os.system(cmd)

def do_configure(actual_dir,opts):
    rv = os.chdir(actual_dir)
    if rv:
        raise GiveUp,"Cannot change dir to %s"%actual_dir

    rv = run_command("./configure %s"%opts)
    if rv:
        raise GiveUp,"Cannot configure - %d"%rv

def do_ext_configure(actual_dir,config_dir,opts):
    rv = os.chdir(actual_dir)
    if rv:
        raise GiveUp,"Cannot change dir to %s"%actual_dir

    rv = run_command("%s/configure %s"%(config_dir,opts))
    if rv:
        raise GiveUp,"Cannot configure - %d"%rv


def do_make(actual_dir, opts, tgt):
    rv = os.chdir(actual_dir)
    if rv:
        raise GiveUp, "Cannot change dir to %s"%actual_dir

    rv = run_command("make %s %s"%(opts, tgt))
    if rv:
        raise GiveUp, "[%s] Cannot make %s - %d"%(actual_dir,tgt,rv)

def build_gnu(base_dir,package_dir,config_options, make_opts):
    actual_dir = os.path.join(base_dir, package_dir)
    do_configure(actual_dir, config_options)
    do_make(actual_dir, make_opts, "all")
    do_make(actual_dir, make_opts, "install")

def run_stage(this_one,specd):
    global gStageExact

    if (gStageExact and this_one == specd):
        print "> Run stage %d (%d) OK. \n"%(this_one, specd)
        return True
    elif ((not gStageExact) and this_one >= specd):
        print "> Run stage %d (%d) OK. \n"%(this_one, specd)
        return True;
    else:
        print "> Run stage %d (%d)  Bad - Don't run.\n"%(this_one, specd)
        return False

def clean_build_dir(root,dir):
    clean_dir(os.path.join(root,dir))

def clean_dir(dname):
    os.system("rm -rf %s"%(dname))

def rename(in_dir, src, dst, force = True):
    if force:
        clean_dir(os.path.join(in_dir, dst))

    print "%s: Renaming %s to %s (force = %s)"%(in_dir, src, dst, force)
    os.rename(os.path.join(in_dir, src), \
                  os.path.join(in_dir, dst))

def patch(config, dst_dir, dst_pkg, patch_dir, patch_name):
    i = 0;
    while True:
        key_name = "/toolchain/sources/%s/patch%d"%(patch_name,i)
        if (config.exists(key_name)):
            patch_name = config.query_string(key_name)
            print "> Patching %s with %s .."%(patch_name, key_name)
            os.chdir(os.path.join(dst_dir, dst_pkg))
            rv = run_command("patch -p1 < %s"%(os.path.join(patch_dir,patch_name)))
            if rv:
                raise GiveUp, "Cannot patch package %s with patch %s"%\
                    (dst_pkg, patch_name)
            i = i + 1
        else:
            break

def copy_dir_into(src_dir,dst_dir):
    rv=os.system("mkdir -p %s"%dst_dir)
    if rv:
        print "Could not create destination directory: got error %s"%rv
    rv=os.system("cp -a %s %s"%(os.path.join(src_dir,"*"), dst_dir))
    if rv:
        print "Could not copy files: got error %s"%rv

def make_writable(dir):
    os.system("chmod -R u+w %s"%dir)

def make_dir(dir):
    os.system("mkdir -p %s"%dir)

def copy_file(src_file, dst_file):
    os.system("cp %s %s"%(src_file,dst_file))

def move_file(src_file,dst_file):
    print "Moving %s -> %s "%(src_file,dst_file)
    os.system("mv %s %s"%(src_file, dst_file))

def do_unlink(src_file):
    print "Unlink %s"%src_file
    os.system("rm -f %s"%src_file)

def build_dir_list(src_dir):
    dir_contents=os.listdir(src_dir)
    dirs=[]
    for name in dir_contents:
        if not os.path.isfile(os.path.join(src_dir,name)):
            dirs.append(name)
    return dirs

def build_file_list(src_dir):
    dir_contents=os.listdir(src_dir)
    files=[]
    for name in dir_contents:
        if os.path.isfile(os.path.join(src_dir,name)):
            files.append(name)
    return files

def do_glibc_build(config, src_dir,install_baremetal,host_tools, \
                       pkgversion, bugurl, \
                       glibc_src_base, glibc_build_base, \
                       variant, cflags, current_stage, specd_start, \
                       doc_dir):
    """Build glibc itself - args are the same as do_glibc_headers    
    doc_dir Documentation dir into which we'll copy the generated docs.
    """

    old_env = os.environ

    # We've already unpacked whatever glibc we were going to use, so
    # just reuse what's already there.csdac
    glibc_src_dir = os.path.join(glibc_src_base, variant)
    glibc_build_dir = os.path.join(glibc_build_base, variant)
    
    target = config.query_string("/toolchain/bare-metal-target")

    if (run_stage(current_stage, specd_start)):
        saved_env = os.environ
        set_env("CC", "%s %s"%(os.path.join(host_tools, "bin", \
                                                "%s-gcc"%target),
                               cflags))
        set_env("CXX", "%s %s"%(os.path.join(host_tools, "bin",
                                             "%s-g++"%target),
                                cflags))
        set_env("CFLAGS", "-g -O2")
        set_env("AR", os.path.join(host_tools, "bin", \
                                       "%s-ar"%target))
        set_env("RANLIB", \
                    os.path.join(host_tools, "bin",\
                                     "%s-ranlib"%target))
        make_dir(glibc_build_dir)
        linux_version = config.query_string("/toolchain/sources/linux/version")
        do_ext_configure(glibc_build_dir, glibc_src_dir, \
                             "--prefix=/usr " + \
                             ("--with-headers=%s "%\
                                  (os.path.join(install_baremetal, "libc", "usr", "include"))) +\
                             "--build=i686-pc-linux-gnu " +\
                             ("--host=%s "%target) +\
                             "--disable-profile " +\
                             "--without-gd " + \
                             "--without-cvs " + \
                             "--enable-add-ons " +\
                             ("--enable-kernel=%s "%linux_version) +\
                             ("--with-pkgversion=%s "%pkgversion) +\
                             ("--with-bugurl=%s "%bugurl))

    if (variant == "default"):
        install_root = os.path.join(install_baremetal, "libc")
    else:
        install_root = os.path.join(install_baremetal, "libc", \
                                        variant)

    current_stage = current_stage + 1
    
    # 068/184 et seq.
    if (run_stage(current_stage, specd_start)):
        do_make(glibc_build_dir, "-j4", "all")
        do_make(glibc_build_dir, "install_root=%s"%(os.path.join(install_baremetal, "libc")),\
                    "install")

    current_stage = current_stage + 1

    if (run_stage(current_stage, specd_start)):
        copy_dir_into(os.path.join(glibc_build_dir, "manual", "libc"), \
                          os.path.join(doc_dir, "html"))
        make_dir(os.path.join(doc_dir, "pdf"))
        copy_file(os.path.join(glibc_build_dir, "manual", "libc.pdf"), \
                      os.path.join(doc_dir, "pdf", "libc.pdf"))
        # Now we want to remove a whole bunchof libraries.
        libc_install_dir = os.path.join(install_baremetal, "libc")
        do_unlink(os.path.join(libc_install_dir, "usr", "libexec", "pt_chown"))
        clean_dir(os.path.join(libc_install_dir, "usr", "lib", "libc_pic"))
        for i in ("libBrokenLocale_pic", "libanl_pic", "libc_pic", "libcidn_pic", \
                      "libcrypt_pic", "libdl_pic", "libm_pic", "libnsl_pic", \
                      "libnss_compat_pic", "libnss_dns_pic", "libnss_files_pic", \
                      "libnss_hesiod_pic", "libnss_nis_pic", "libnss_nisplus_pic", \
                      "libresolv_pic", "librt_pic", "libthread_db_pic", \
                      "libutil_pic"):
            do_unlink(os.path.join(libc_install_dir, "usr", "lib", i + ".a"))
            do_unlink(os.path.join(libc_install_dir, "usr", "lib", i + ".map"))
    
        tgt_bindir = os.path.join(libc_install_dir, "usr", "lib", "bin")
        make_dir(tgt_bindir)

        for i in ("ldconfig", "sln"):
            move_file(os.path.join(libc_install_dir, "sbin", i), \
                          os.path.join(tgt_bindir, i))

        for i in ("catchsegv", "gencat", "getconf", "getent", "iconv", "ldd", \
                      "locale", "localedef", "mtrace", "pcprofiledump", \
                      "rpcgen", "sprof", "tzselect", "xtrace"):
            move_file(os.path.join(libc_install_dir, "usr", "bin", i), \
                          os.path.join(tgt_bindir, i))

        for i in ("iconvconfig", "nscd", "rpcinfo", "zdump", "zic"):
            move_file(os.path.join(libc_install_dir, "usr", "sbin", i), \
                          os.path.join(tgt_bindir, i))
    
    current_stage = current_stage + 1
    return current_stage
        
                         
def do_glibc_headers(config, src_dir, install_baremetal, host_tools, \
                         pkgversion, bugurl, \
                         first_build, header_dir, \
                         variant_dir, cflags, current_stage, specd_start):
    """Builds a glibc and installs headers and crt0 etc.
    
    first_build is where the glibc goes (typically tmp_host_dir/glibc-first)
    header_dir  is where headers will be installed (host_obj/glibc-headers-x)
    variant_dir the variant directory - default/ armv4t etc.
    cflags      the flags passed to gcc when building glibc
    stage       current stage.
    start_stage Stage to start at.

    Returns the next stage.
    
    """

    glibc_first_dir = first_build
    glibc_header_dir = header_dir

    old_env = os.environ
    
    # [054/184]
    # Let's go for glibc0.
    if (run_stage(current_stage, specd_start)):
        make_dir(glibc_first_dir)
        unpack_bz2(src_dir, query_archive(config, "glibc"), glibc_first_dir)
        rename(glibc_first_dir, query_dir(config, "glibc"), variant_dir)
        unpack_bz2(src_dir, query_archive(config, "glibc-ports"), glibc_first_dir)
        rename(glibc_first_dir, query_dir(config, "glibc-ports"), \
                   os.path.join(variant_dir, "ports"), force = True)
        make_writable(glibc_first_dir)

    default_dir = os.path.join(glibc_first_dir, variant_dir)
    glibc_header_default = os.path.join(glibc_header_dir, variant_dir)

    current_stage = current_stage + 1

    if (run_stage(current_stage,specd_start)):
        saved_env = os.environ
        set_env("CC", "%s %s"%(os.path.join(host_tools, "bin", \
                                                "arm-none-linux-gnueabi-gcc"),
                               cflags))
        set_env("CXX", "%s %s"%(os.path.join(host_tools, "bin",
                                             "arm-none-linux-gnueabi-g++"),
                                cflags))
        set_env("CFLAGS", "-g -O2")
        set_env("AR", os.path.join(host_tools, "bin", \
                                       "arm-none-linux-gnueabi-ar"))
        set_env("RANLIB", \
                    os.path.join(host_tools, "bin",\
                                     "arm-none-linux-gnueabi-ranlib"))
        
        make_dir(glibc_header_dir)
        make_dir(glibc_header_default)

        do_ext_configure(glibc_header_default, default_dir,\
                         "--prefix=/usr " + \
                         "--with-headers=%s "%\
                             (os.path.join(install_baremetal, "libc", "usr","include")) +\
                         "--build=i686-pc-linux-gnu "+ \
                         "--host=arm-none-linux-gnueabi "+ \
                         "--disable-profile " + \
                         "--without-gd " + \
                         "--without-cvs " + \
                         "--enable-add-ons " + \
                         "--enable-kernel=2.6.14 " + \
                         "--with-pkgversion=%s "%pkgversion + \
                         "--with-bugurl=%s "%bugurl)
        

    # Work out the install dir .
    if (variant_dir == "default"):
        install_root = os.path.join(install_baremetal, "libc")
    else:
        install_root = os.path.join(install_baremetal, "libc", \
                                        variant_dir)

    current_stage = current_stage + 1
        
    if (run_stage(current_stage, specd_start)):
        do_make(glibc_header_default, \
                    "install_root=%s "%install_root + \
                    "install-bootstrap-headers=yes ",\
                    "install-headers")
        do_make(glibc_header_default, "", "csu/subdir_lib")

        make_dir(os.path.join(install_root, "usr", "lib"))

        for i in ("crt1.o", "crti.o", "crtn.o"):
            copy_file(os.path.join(glibc_header_default, "csu", i), \
                          os.path.join(install_root,"usr",\
                                           "lib",i))

        os.system("%s %s -o %s -nostdlib -nostartfiles -shared -x c /dev/null"%\
                      (os.path.join(host_tools, "bin", \
                                        "arm-none-linux-gnueabi-gcc"), \
                           cflags, \
                           os.path.join(install_root, \
                                            "usr", "lib", \
                                            "libc.so")))
    
    current_stage = current_stage + 1
    os.environ = old_env

    return current_stage

def do_localedef(build_dir, test_dir, src, charset, dest):
    rv=os.chdir(build_dir)
    if rv:
        raise GiveUp, "Cannot change to dir %s"%build_dir

#    rv=run_command("./localedef --quiet -c --little-endian --uint32-align=4 " + \
#                    ("-i glibc/localedata/locales/%s "%src) + \
#                    ("-f glibc/localedata/charmaps/%s "%charset) + \
#                    ("little4/usr/lib/locale/test/%s"%dest))
    rv=run_command("./localedef --quiet -c --little-endian --uint32-align=4 " + \
                    ("-i glibc/localedata/locales/%s "%src) + \
                    ("-f glibc/localedata/charmaps/%s "%charset) + \
                    (test_dir+"/%s"%dest))
    if rv:
        raise GiveUp, "Cannot run command %d"%rv



def main(args):
    global gStageExact

    while args:
        word = args[0]

        if word in ('--help'):
            print __doc__
            return
        elif word == '--exact':
            gStageExact = True
        else:
            break

        args = args[1:]

    if len(args) != 1 and len(args) != 2:
        print __doc__


    config = xmlconfig.Config(args[0])

    src_dir = config.query_string("/toolchain/src-dir")
    dest_dir = config.query_string("/toolchain/dest-dir")
    patch_dir = config.query_string("/toolchain/patch-dir")
    tmp_dir = "/tmp/muddle-toolchain-tmp"
    host_tools = os.path.join(dest_dir, "host-tools")
    support_tools = os.path.join(dest_dir, "support-tools")
    host_obj = os.path.join(tmp_dir, "host-obj")

    tmp_host_dir = os.path.join(tmp_dir, "host")
    
    pkgversion =  config.query_string("/toolchain/version")
    bugurl = config.query_string("/toolchain/bugurl")

    bare_metal_target = config.query_string("/toolchain/bare-metal-target")
    
    # A little lookup table for translating script references to ours:
    #
    # Them -> Us
    #
    # /scratch/julian/lite-respin/linux/install -> host_tools
    # /scratch/julian/lite-respin/linux/obj     -> host_obj
    # /opt/codesourcery -> dest_dir
    # the GMP/MFPR /etc. utility builds -> support_tools
    

    dest_dir_none = os.path.join(dest_dir, 
                                     config.query_string("/toolchain/bare-metal-target"),
                                     "libc")
    


    if len(args) == 2:
        stage = int(args[1])
        print "Running from stage %d"%stage
    else:
        stage = 0



    # Right. This is basically a huge list of commands.
    saved_env = os.environ;

    build_stage = 0

    # Make a scratch dir.
    if (run_stage(build_stage, stage)):
        os.system("rm -rf %s"%tmp_dir)
        os.mkdir(tmp_dir)
        os.mkdir(tmp_host_dir)


    build_stage = build_stage + 1

    # Unpack zlib
    restore_env(saved_env)

    set_env("CC_FOR_BUILD", "gcc")
    set_env("CC", "gcc")
    set_env("AR", "ar rc")
    set_env("RANLIB", "ranlib")    
    append_env("PATH", os.path.join(tmp_host_dir, "bin"))
    append_env("LD_LIBRARY_PATH", os.path.join(tmp_host_dir, "lib"))


    if (run_stage(build_stage, stage)):
        clean_build_dir(tmp_host_dir, query_dir(config, "zlib"))
        unpack_bz2(src_dir, query_archive(config, "zlib"), tmp_host_dir);
        patch(config, tmp_host_dir,query_dir(config, "zlib"), patch_dir, "zlib")
        build_gnu(tmp_host_dir, query_dir(config, "zlib"), "--prefix=%s"%support_tools, "")

    build_stage = build_stage + 1

    # AR now wants to revert to its usual meaning.
    set_env("AR", "ar")
    saved2_env = os.environ
    set_env("CFLAGS", "-g -O2")

    if (run_stage(build_stage,stage)):
        clean_build_dir(tmp_host_dir, query_dir(config, "gmp"))
        unpack_bz2(src_dir, query_archive(config, "gmp"), tmp_host_dir)
        patch(config, tmp_host_dir,query_dir(config, "gmp"), patch_dir, "gmp")
        build_gnu(tmp_host_dir, query_dir(config, "gmp"), \
                      ("--build=i686-pc-linux-gnu "+\
                           "--target=i686-pc-linux-gnu " +\
                           "--prefix=%s " +\
                           "--disable-shared --enable-cxx --host=i686-pc-linux-gnu " +\
                           "--disable-nls")%support_tools, "-j 4")
        do_make(os.path.join(tmp_host_dir, query_dir(config, "gmp")), "", "check")

    build_stage = build_stage + 1
    os.environ = saved2_env
    
    # Task [037/184] et seq.
    if (run_stage(build_stage,stage)):
        clean_build_dir(tmp_host_dir, query_dir(config, "mpfr"))
        unpack_bz2(src_dir, query_archive(config, "mpfr"), tmp_host_dir)
        patch(config, tmp_host_dir,query_dir(config, "mpfr"), patch_dir, "mpfr")
        build_gnu(tmp_host_dir,  query_dir(config, "mpfr"), \
                      ("--build=i686-pc-linux-gnu "+\
                           ("--target=%s "%(bare_metal_target)) + \
                           "--prefix=%s --disable-shared " +\
                           "--host=i686-pc-linux-gnu " +\
                           "--disable-nls --with-gmp=%s")%\
                      (support_tools, support_tools), "")
        

    build_stage = build_stage + 1

    if (run_stage(build_stage, stage)):
        clean_build_dir(tmp_host_dir, query_dir(config, "ppl"))
        unpack_bz2(src_dir, query_archive(config, "ppl"), tmp_host_dir)
        patch(config, tmp_host_dir,query_dir(config, "ppl"), patch_dir, "ppl")
        build_gnu(tmp_host_dir,  query_dir(config, "ppl"), \
                      ("--build=i686-pc-linux-gnu "+\
                           ("--target=%s "%(bare_metal_target)) +\
                           "--prefix=%s --disable-shared " +\
                           "--host=i686-pc-linux-gnu " +\
                           "--disable-nls --with-gmp=%s")%\
                      (support_tools, support_tools), "")
        
        
    #bootstrap_binutils =  "binutils-arm-none-linux-gnueabi-i686-pc-linux-gnu"
    bootstrap_binutils = "binutils-%s-i686-pc-linux-gnu"%(config.query_string("/toolchain/bare-metal-target"))
    sysroot = os.path.join(host_tools, "libc")

    set_env("CC_FOR_BUILD", "gcc")
    set_env("CC", "gcc")
    set_env("AR", "ar")
    set_env("ranlib", "ranlib")
    prepend_env("PATH", os.path.join(host_tools, "bin"))

    binutils_dir = os.path.join(tmp_host_dir, bootstrap_binutils)
    
    doc_target = config.query_string("/toolchain/doc-target")
    doc_dir = os.path.join(host_tools, "share", "doc", doc_target)

    tools_install_options = \
        ("prefix=%s exec_prefix=%s libdir=%s" +\
        " htmldir=%s pdfdir=%s infodir=%s mandir=%s datadir=%s")%\
        (host_tools,\
             host_tools,\
             os.path.join(host_tools,"lib"),\
             os.path.join(host_tools,\
                              "share/doc/%s/html"%(doc_target)),\
             os.path.join(host_tools,\
                              "share/doc/%s/pdf"%(doc_target)),\
             os.path.join(host_tools,\
                              "share/doc/%s/info"%(doc_target)),\
             os.path.join(host_tools,\
                              "share/doc/%s/man"%(doc_target)),\
             os.path.join(host_tools,\
                              "share"))
    
    # Task [041/184] et seq
    if (run_stage(build_stage,stage)):
        clean_build_dir(tmp_host_dir, "binutils-stable")
        clean_build_dir(tmp_host_dir, bootstrap_binutils)
        unpack_bz2(src_dir, query_archive(config, "binutils"), tmp_host_dir)
        rename(tmp_host_dir, query_dir(config, "binutils"), \
                   bootstrap_binutils)
        patch(config, tmp_host_dir, bootstrap_binutils, \
                  patch_dir, "binutils")

        do_configure(binutils_dir, 
                     ("--build=i686-pc-linux-gnu "+\
                           "--target=%s "%(config.query_string("/toolchain/bare-metal-target")) +\
                           "--prefix=%s "%(dest_dir) +\
                           "--host=i686-pc-linux-gnu "+\
                           "--with-pkgversion=\"%s\" "%(pkgversion) +\
                           "--with-bugurl=\"%s\" "%(bugurl) +\
                           "--disable-nls "+\
                           "--with-sysroot=%s "%(sysroot) +\
                           "--enable-poison-system-directories"))
        do_make(binutils_dir, "-j4","all")
        do_make(binutils_dir, tools_install_options, "install")

    build_stage = build_stage + 1

    # Task [045/184]
    if (run_stage(build_stage,stage)):
        # Remove an (old?) verison of libiberty..
        clean_dir(os.path.join(host_tools, "lib"))

        # Replace some directories .. 
        binutils_objdir = os.path.join(host_obj, \
             "host-%s"%(bootstrap_binutils))

        copy_dir_into(os.path.join(binutils_dir,"include"),\
                          os.path.join(binutils_objdir, "usr/include"))
        make_writable(os.path.join(binutils_objdir, "usr/include"))
        make_dir(os.path.join(binutils_objdir, "usr/lib"))
        copy_file(os.path.join(binutils_dir, "libiberty/libiberty.a"),
                  os.path.join(binutils_objdir, "usr/lib"))
        copy_file(os.path.join(binutils_dir, "bfd/.libs/libbfd.a"),
                  os.path.join(binutils_objdir, "usr/lib"))
        copy_file(os.path.join(binutils_dir, "bfd/bfd.h"),
                  os.path.join(binutils_objdir, "usr/include"))
        copy_file(os.path.join(binutils_dir, "bfd/elf-bfd.h"),
                  os.path.join(binutils_objdir, "usr/include"))
        copy_file(os.path.join(binutils_dir, "opcodes/.libs/libopcodes.a"),
                  os.path.join(binutils_objdir, "usr/lib"))
        
    unpacked_gcc = os.path.join(tmp_host_dir, query_dir(config, "gcc"))    
    gcc_final_dir = os.path.join( tmp_host_dir, "gcc-final")
    install_baremetal = os.path.join(host_tools, \
                                       bare_metal_target)
    build_stage = build_stage + 1


    if (config.query_string("/toolchain/with-lib")) == "none":
        # Just build a compiler. Any compiler.
        if (run_stage(build_stage,stage)):
            clean_dir(gcc_final_dir)
            make_dir(gcc_final_dir)
            unpack_bz2(src_dir, query_archive(config, "gcc"), tmp_host_dir)
            patch(config, tmp_host_dir,query_dir(config, "gcc"), patch_dir, "gcc")            
            do_ext_configure(gcc_final_dir, unpacked_gcc, \
                                 "--build=i686-pc-linux-gnu " +\
                                 "--host=i686-pc-linux-gnu " +\
                                 "--target=%s "%(bare_metal_target) + \
                                 "--disable-threads " + \
                                 "--disable-libmudflap " + \
                                 "--disable-libssp " + \
                                 "--disable-libstdcxx-pch " + \
                                 "--disable-libstdcxx " + \
                                 "--with-gnu-as " + \
                                 "--with-gnu-ld " + \
                                 "--enable-languages=c " + \
                                 "--enable-shared " + \
                                 "--enable-symvers=gnu " + \
                                 "--enable-__cxa_atexit " + \
                                 ("--with-pkgversion=\"%s\" "%(pkgversion)) + \
                                 ("--with-bugurl=\"%s\" "%(bugurl)) + \
                                 "--disable-nls " +  \
                                 ("--prefix=%s "%dest_dir) + \
                                 ("--with-gmp=%s " %support_tools) +\
                                 ("--with-mpfr=%s "%support_tools) +\
                                 "--disable-libgomp " + \
                                 "--enable-poison-system-directories " +\
                                 ("--with-build-time-tools=%s"% \
                                      os.path.join(install_baremetal, "bin")))

            #("--with-sysroot=%s "%\
            #                          (os.path.join(dest_dir, bare_metal_target))) +\

            do_make(gcc_final_dir, tools_install_options, "all")
            do_make(gcc_final_dir, tools_install_options, "install")
            # And I think we're done.
        
        print "This is not a glibc build, so we're done."
        sys.exit(0)
                             
                             
                                 
    default_arch = config.query_string("/toolchain/arch")
    default_opts = config.query_string("/toolchain/opts")

    variants = config.query_hashlist("/toolchain/variant", [ "arch", "opts"])
                           
    # Task [046/184]
    linux_srcdir = os.path.join(tmp_host_dir,
                                query_dir(config, "linux"))

    linux_tmp_hdrdir = os.path.join(host_obj, \
                                        "tmp-linux-headers")


    if (run_stage(build_stage,stage)):
        make_dir(os.path.join(install_baremetal,"libc/usr/include"))
        make_dir(os.path.join(install_baremetal,"libc/usr/include/bits"))
        make_dir(os.path.join(install_baremetal,"libc/usr/include/gnu"))
        
        unpack_bz2(src_dir, query_archive(config,"linux"), tmp_host_dir)

        clean_dir(linux_tmp_hdrdir)

        print "In %s"%(linux_srcdir)
        do_make(linux_srcdir, "", \
                    ("ARCH=arm CROSS_COMPILE=%s INSTALL_HDR_PATH=%s "+\
                         "headers_install")%\
                    (os.path.join(host_tools,"bin/%s-"%bare_metal_target),\
                         linux_tmp_hdrdir))
        
        for i in ("linux", "asm", "asm-generic", "mtd", "rdma", \
                      "sound", "video"):
            copy_dir_into(os.path.join(linux_tmp_hdrdir, "include", i),\
                              os.path.join(install_baremetal, "libc", "usr",\
                                               "include", i))
    build_stage = build_stage + 1

    libc_sysroot = os.path.join(install_baremetal, "libc")
    for i in variants:
        make_dir(os.path.join(install_baremetal, "libc", i["arch"]))
        make_dir(os.path.join(install_baremetal, "libc", i["arch"]))

    set_env("AR_FOR_TARGET", "%s-ar"%(bare_metal_target))
    set_env("NM_FOR_TARGET", "%s-nm"%(bare_metal_target))
    set_env("OBJDUMP_FOR_TARGET", "%s-objdump"%(bare_metal_target))
    set_env("STRIP_FOR_TARGET", "%s-strip"%(bare_metal_target))

    gcc_first_dir = os.path.join(tmp_host_dir, "gcc-first")
    unpacked_gcc = os.path.join(tmp_host_dir, query_dir(config, "gcc"))

    # Task [047/184]
    if (run_stage(build_stage,stage)):
        clean_dir(gcc_first_dir)
        make_dir(gcc_first_dir)
        
        unpack_bz2(src_dir, query_archive(config, "gcc"), tmp_host_dir)

        # Make sure we don't use stdlib for the first gcc.
        specs= "%{funwind-tables|fno-unwind-tables|mabi=*|ffreestanding|nostdlib:;:-funwind-tables} %{O2:%{!fno-remove-local-statics: -fremove-local-statics}} %{O*:%{O|O0|O1|O2|Os:;:%{!fno-remove-local-statics: -fremove-local-statics}}}"
        stdcxx="-static-libgcc -Wl,-Bstatic,-lstdc++,-Bdynamic -lm"

        # C++ does not get built for the first gcc, for obvious
        # reasons (we'll try to link against our unwind lib, which uses
        #  glibc, before we're ready)
        do_ext_configure(gcc_first_dir, unpacked_gcc, \
                             ("--build=i686-pc-linux-gnu "+ \
                                  "--host=i686-pc-linux-gnu " +\
                                  ("--target=%s "%(bare_metal_target)) +\
                                  "--enable-threads "+\
                                  "--disable-libmudflap "+\
                                  "--disable-libssp "+\
                                  "--disable-libstdcxx-pch " +\
                                  "--with-gnu-as " +\
                                  "--with-gnu-ld " +\
                                  ("--with-arch=%s "%(default_arch)) + \
                                  "--enable-languages=c,c++ "+\
                                  "--enable-shared "+\
                                  "--disable-lto " +\
                                  "--enable-symvers=gnu "+\
                                  "--enable-__cxa_atexit " +\
                                  ("--with-pkgversion=\"%s\" "%pkgversion) +\
                                  ("--with-bugurl=\"%s\" "%bugurl) +\
                                  "--disable-nls " +\
                                  ("--prefix=%s "%dest_dir) +\
                                  "--disable-shared " +\
                                  "--disable-threads "+\
                                  "--disable-libssp " +\
                                  "--disable-libgomp " +\
                                  "--without-headers " +\
                                  "--with-newlib " +\
                                  "--disable-decimal-float "+\
                                  "--disable-libffi " +\
                                  "--enable-languages=c "+\
                                  ("'--with-specs=%s' "%(specs)) + \
                                  ("'--with-host-libstdcxx=%s' "%(stdcxx)) + \
                                  ("--with-sysroot=%s "%dest_dir_none) +\
                                  ("--with-build-sysroot=%s "%\
                                  (os.path.join(install_baremetal, "libc"))) +\
                                  ("--with-gmp=%s "%support_tools) +\
                                  ("--with-mpfr=%s "%support_tools) +\
                                  ("--with-ppl=%s "%support_tools) +\
                                  "--disable-libgomp "+\
                                  "--enable-poison-system-directories " +\
                                  ("--with-build-time-tools=%s"%\
                                       (os.path.join(install_baremetal, "bin"))))\
                             )
        do_make(gcc_first_dir, \
                    ("LD_FLAGS_FOR_TARGET=--sysroot=%s "%libc_sysroot) +\
                    ("CPPFLAGS_FOR_TARGET=--sysroot=%s "%libc_sysroot) +\
                    ("build_tooldir=%s"%install_baremetal), "all")
        
        do_make(gcc_first_dir, \
                    tools_install_options, "install")

        clean_dir(os.path.join(host_tools, "include"))
        do_unlink(os.path.join(host_tools, "lib/libiberty.a"))
        do_unlink(os.path.join(host_tools, "bin/%s-gccbug"%bare_metal_target))

    build_stage = build_stage + 1

    glibc_first_dir = os.path.join(tmp_host_dir, "glibc-first")
    glibc_header_dir = os.path.join(host_obj, "glibc-headers-x")
    
    # [054/184]
    # We build three glibcs - default/, armv4t/ and thumb2/
    os.environ = saved2_env

    # Next is 057/184
    print "Building glibc0 (ARM) @ stage 8 (specd %d)"%stage
    build_stage = do_glibc_headers(config, \
                                   src_dir, install_baremetal, \
                                       host_tools,\
                                       pkgversion, bugurl, \
                                       glibc_first_dir, \
                                       glibc_header_dir, \
                                       "default", default_opts, build_stage, stage)

    for var in variants:
        arch = var["arch"]
        opts = var["opts"]

        print "Building glibc (%s) @ stage %d"%(arch,build_stage)
        build_stage = do_glibc_headers(config, \
                                           src_dir, install_baremetal, \
                                           host_tools,\
                                           pkgversion, bugurl, \
                                           glibc_first_dir, \
                                           glibc_header_dir, \
                                           arch,  \
                                           opts,\
                                           build_stage, \
                                           stage)
    
    gcc_second_dir = os.path.join(tmp_host_dir, "gcc-second")
    print "Building our second gcc at stage %d, in %s"%(build_stage,gcc_second_dir)

    # [063/184]
    if run_stage(build_stage, stage):
        clean_dir(gcc_second_dir)
        make_dir(gcc_second_dir)
        
        saved_env = os.environ

        set_env("CC_FOR_BUILD", "gcc")
        set_env("CC", "gcc")
        set_env("AR", "ar")
        set_env("RANLIB", "ranlib")    
        append_env("PATH", os.path.join(tmp_host_dir, "bin"))
        append_env("LD_LIBRARY_PATH", os.path.join(tmp_host_dir, "lib"))

        do_ext_configure(gcc_second_dir, unpacked_gcc, \
                             "--build=i686-pc-linux-gnu " +\
                             "--host=i686-pc-linux-gnu " + \
                             "--target=arm-none-linux-gnueabi " +\
                             "--enable-threads "+\
                             "--disable-libmudflap "+\
                             "--disable-libssp "+\
                             "--disable-libstdcxx-pch "+\
                             "--with-gnu-as " +\
                             "--with-gnu-ld " +\
                             "--enable-languages=c,c++ " +\
                             "--enable-shared " +\
                             "--enable-symvers=gnu " +\
                             "--enable-__cxa_atexit " +\
                             "--with-pkgversion=\"%s\" "%pkgversion + \
                             "--with-bugurl=\"%s\" "%bugurl + \
                             "--disable-nls " +\
                             ("--prefix=%s "%dest_dir) +\
                             "--enable-languages=c " +\
                             "--disable-libffi " +\
                             ("--with-sysroot=%s "%\
                              os.path.join(dest_dir, "arm-none-linux-gnueabi", "libc")) +\
                             "--with-build-sysroot=%s "%libc_sysroot +\
                             "--with-gmp=%s "%support_tools +\
                             "--with-mpfr=%s "%support_tools +\
                             "--disable-libgomp " +\
                             "--enable-poison-system-directories " +\
                             ("--with-build-time-tools=%s"% \
                                  os.path.join(install_baremetal, "bin")))
        do_make(gcc_second_dir, 
                ("LDFLAGS_FOR_TARGET=--sysroot=%s "%(os.path.join(install_baremetal, "libc"))) +
                ("CPPFLAGS_FOR_TARGET=--sysroot=%s "%(os.path.join(install_baremetal, "libc"))) + 
                ("build_tooldir=--sysroot=%s"%install_baremetal), "all")
        
        do_make(gcc_second_dir, 
                tools_install_options,
                "install")
        
        clean_dir(os.path.join(host_tools, "include"))
        do_unlink(os.path.join(host_tools, "lib/libiberty.a"))
        do_unlink(os.path.join(host_tools, "bin/%s-gccbug"%bare_metal_target))

        os.environ = saved_env;
        
    glibc_second_src = os.path.join(tmp_host_dir, "glibc-first")
    glibc_second_build = os.path.join(tmp_host_dir, "glibc-second-build")

    build_stage = build_stage + 1

    # [067/184] second stage glibc build.
    print "Second stage glibc @ %d"%build_stage

    build_stage = do_glibc_build(config, src_dir, install_baremetal, \
                               host_tools,\
                               pkgversion, bugurl, \
                               glibc_second_src, \
                               glibc_second_build, \
                               "default", default_opts, build_stage, stage,\
                               doc_dir)

    for i in variants:
        arch = var["arch"]
        opts = var["opts"]
        
        print "Second stage glibc for %s @ %d"%(arch, build_stage)
        build_stage = do_glibc_build(config, src_dir, install_baremetal, \
                                         host_tools,\
                                         pkgversion, bugurl, \
                                         glibc_second_src, \
                                         glibc_second_build, \
                                         arch, opts, build_stage,stage, \
                                         doc_dir)
    
    print "Building locale definitions @ %d"%build_stage

    locale_build_dir = os.path.join(tmp_host_dir, 
                                    query_dir(config, "glibc-localedef"))
    locale_install_dir = os.path.join(locale_build_dir, "install_test_locales")
    locale_little4_dir = os.path.join(locale_install_dir, "little4")
    locale_test_dir = os.path.join(locale_little4_dir, "usr", "lib", "locale", "test")

    if run_stage(build_stage, stage):
        #[076/184]
        clean_dir(locale_build_dir)
        unpack_bz2(src_dir, query_archive(config, "glibc-localedef"), tmp_host_dir)

        saved_env = os.environ

        set_env("CC_FOR_BUILD", "gcc")
        set_env("CC", "gcc")
        set_env("AR", "ar")
        set_env("RANLIB", "ranlib")    
        append_env("PATH", os.path.join(tmp_host_dir, "bin"))
        append_env("LD_LIBRARY_PATH", os.path.join(tmp_host_dir, "lib"))

        
        print "local build dir is %s"%locale_build_dir
        print "glibc_second_src is %s"%(os.path.join(glibc_second_src, "default"))
        do_configure(locale_build_dir, \
                         "--prefix=/usr " +\
                         "--with-glibc=%s"%(os.path.join(glibc_second_src, "default")))
        do_make(locale_build_dir, "-j4", "all")
        #start of #[077/184]
        locale_opts = config.query_string("/toolchain/sources/glibc-localedef/options")
        do_make(locale_build_dir, "install_root=%s "%(locale_little4_dir) + \
                    ("'LOCALEDEF_OPTS=%s'"%locale_opts),
                "install-locales")

        os.environ = saved_env

    build_stage = build_stage + 1
    print "Creating test locales @ %d"%build_stage

    if (run_stage(build_stage, stage)):
        print "default build"

        make_dir(locale_test_dir)
        print "locale test dir is %s"%locale_test_dir
        print "locale build dir is %s"%locale_build_dir
        f = open(os.path.join(locale_test_dir, "README"),"w")
        f.write("The locales in this directory are used by the GLIBC test harness\n")
        f.close()
        set_env("I18NPATH", os.path.join(glibc_second_src, "localedata"))
        set_env("GCONV_PATH", "iconvdata")
#        do_localedef(locale_build_dir, locale_test_dir, "de_DE", "ISO-8859-1", "de_DE.ISO-8859-1")
                     
        for lang in ["de_DE", "en_US", "da_DK", "sv_SE", "fr_FR", "nb_NO", "nn_NO"]:
            do_localedef( locale_build_dir, locale_test_dir, lang, "ISO-8859-1", lang+".ISO-8859-1" )
        for lang in ["de_DE", "en_US", "ja_JP", "tr_TR", "cs_CZ", "fa_IR", "fr_FR"]:
            do_localedef( locale_build_dir, locale_test_dir, lang, "UTF-8", lang+".UTF-8")

        do_localedef( locale_build_dir, locale_test_dir, "hr_HR", "ISO-8859-2", "hr_HR.ISO-8859-2" )
        do_localedef( locale_build_dir, locale_test_dir, "en_US", "ANSI_X3.4-1968", "en_US.ANSI_X3.4-1968" )
        do_localedef( locale_build_dir, locale_test_dir, "ja_JP", "EUC-JP", "ja_JP.EUC-JP" )
        do_localedef( locale_build_dir, locale_test_dir, "ja_JP", "SHIFT_JIS", "ja_JP.SHIFT_JIS" )
        do_localedef( locale_build_dir, locale_test_dir, "vi_VN", "TCVN5712-1", "vi_VN.TCVN5712-1" )
        do_localedef( locale_build_dir, locale_test_dir, "zh_TW", "EUC-TW", "zh_TW.EUC-TW" )
        copy_dir_into( locale_little4_dir, os.path.join( host_tools, "arm-none-linux-gnueabi", "libc") )

    build_stage = build_stage + 1

    if (run_stage(build_stage, stage)):
        #Stage 29: Start of #[078/184]
        #for each directory in locale_little4_dir/usr/lib/locale,
        #create a directory with subdirectory "LC_MESSAGES" in
        #host_tools/arm-none-linux-gnueabi/libc/armv4t/usr/lib/locale
        #and create links from targets to sources for all files

        for var in variants:
            arch = var["arch"]
            opts = var["opts"]
            
            print "Relocating locales for variant %s"%(arch)
            locale_definitions_base_dir=os.path.join(locale_little4_dir,"usr","lib","locale")
            dir_list=build_dir_list(locale_definitions_base_dir)
            test_dir_list=build_dir_list(os.path.join(locale_definitions_base_dir,"test"))

            for name in dir_list:
                if name!="test":
                #create directory
                    locale_definitions_target_dir=os.path.join(host_tools,
                                                               bare_metal_target,"libc",
                                                               arch,"usr","lib","locale",name)
                
                    print locale_definitions_target_dir
                    print os.path.join(locale_definitions_base_dir, name)
                
                    make_dir(locale_definitions_target_dir)
                #get a list of all files in the directory
                    file_list=build_file_list(os.path.join(locale_definitions_base_dir, name))
                    
                #link files
                    for filename in file_list:
                        src_file=os.path.join( locale_definitions_base_dir,name, filename )
                        target_file=os.path.join(locale_definitions_target_dir, filename)
                        try:
                            os.link(src_file, target_file)
                        except:
                        #do_unlink(target_file)
                            os.system("rm -f %s"%target_file)
                            os.link(src_file, target_file)
                    
                #do the same for the subdirectory LC_MESSAGES
                    locale_definitions_target_dir=os.path.join(host_tools,
                                                              bare_metal_target, 
                                                               "libc",arch,
                                                               "usr","lib","locale",
                                                               name,"LC_MESSAGES")
                    make_dir(locale_definitions_target_dir)
                #get a list of all files in the directory
                    file_list=build_file_list(os.path.join(locale_definitions_base_dir, 
                                                           name, "LC_MESSAGES"))
                #link files
                    for filename in file_list:
                        src_file=os.path.join( locale_definitions_base_dir,name, 
                                               "LC_MESSAGES", filename )
                        target_file=os.path.join(locale_definitions_target_dir, filename)
                        try:
                            os.link(src_file, target_file)
                        except:
                        #do_unlink(target_file)
                            os.system("rm -f %s"%target_file)
                            os.link(src_file, target_file)
                else:
                #create test directory
                    locale_definitions_target_dir=os.path.join(host_tools,bare_metal_target,
                                                               "libc",arch,"usr","lib",
                                                               "locale","test")
                    make_dir(locale_definitions_target_dir)
                    for testname in test_dir_list:
                    #create test subdirectories
                        locale_definitions_target_dir=os.path.join(host_tools,
                                                                   bare_metal_target,
                                                                   "libc",arch,
                                                                   "usr","lib","locale",
                                                                   "test",testname)
                        make_dir(locale_definitions_target_dir)
                    
                        print locale_definitions_target_dir
                        print os.path.join(locale_definitions_base_dir, "test", testname)
                    
                    #get directory contents
                        file_list=build_file_list(os.path.join(locale_definitions_base_dir, "test", testname))
                    #link files
                        for filename in file_list:
                            src_file=os.path.join( locale_definitions_base_dir, "test", 
                                                   testname, filename )
                            target_file=os.path.join(locale_definitions_target_dir, filename)
                            try:
                                os.link(src_file, target_file)
                            except:
                                do_unlink(target_file)
                                os.link(src_file, target_file)
                    #do the same for the subdirectory LC_MESSAGES
                        locale_definitions_target_dir=os.path.join(host_tools,
                                                                   bare_metal_target,
                                                                   "libc",arch,
                                                                   "usr","lib","locale",
                                                                   "test",testname,"LC_MESSAGES")
                        make_dir(locale_definitions_target_dir)
                    #get directory contents
                        file_list=build_file_list(os.path.join(locale_definitions_base_dir, 
                                                               "test", testname, "LC_MESSAGES"))
                    #link files
                        for filename in file_list:
                            src_file=os.path.join( locale_definitions_base_dir, "test", testname, "LC_MESSAGES", filename )
                            target_file=os.path.join(locale_definitions_target_dir, filename)
                            try:
                                os.link(src_file, target_file)
                            except:
                                do_unlink(target_file)
                                os.link(src_file, target_file)

    build_stage = build_stage + 1



    if (run_stage(build_stage, stage)):
        #Stage 31
        #[080/184]
        #run configuration for the final gcc build
        clean_dir(gcc_final_dir)
        make_dir(gcc_final_dir)
        #gcc has already been unpacked, so skip straight to the configuration
        do_ext_configure(gcc_final_dir, unpacked_gcc, \
                             "--build=i686-pc-linux-gnu " +\
                             "--host=i686-pc-linux-gnu " + \
                             "--target=arm-none-linux-gnueabi " +\
                             "--enable-threads "+\
                             "--disable-libmudflap "+\
                             "--disable-libssp "+\
                             "--disable-libstdcxx-pch "+\
                             "--with-gnu-as " +\
                             "--with-gnu-ld " +\
                             "--enable-languages=c,c++ " +\
                             "--enable-shared " +\
                             "--enable-symvers=gnu " +\
                             "--enable-__cxa_atexit " +\
                             "--with-pkgversion=\"%s\" "%pkgversion + \
                             "--with-bugurl=\"%s\" "%bugurl + \
                             "--disable-nls " +\
                             ("--prefix=%s "%dest_dir) +\
                             ("--with-sysroot=%s "%\
                              os.path.join(dest_dir, "arm-none-linux-gnueabi", "libc")) +\
                             "--with-build-sysroot=%s "%libc_sysroot +\
                             ("--with-gmp=%s "%support_tools) +\
                             ("--with-mpfr=%s "%support_tools) +\
                             "--disable-libgomp " +\
                             "--enable-poison-system-directories " +\
                             ("--with-build-time-tools=%s"% \
                                  os.path.join(install_baremetal, "bin")))
        #[081/184]: the final gcc build
        do_make(gcc_final_dir, 
                ("LDFLAGS_FOR_TARGET=--sysroot=%s "%(os.path.join(install_baremetal, "libc"))) +
                ("CPPFLAGS_FOR_TARGET=--sysroot=%s "%(os.path.join(install_baremetal, "libc"))) + 
                ("build_tooldir=--sysroot=%s"%install_baremetal), "all")
        
        #[082/184]: install the final gcc build
        do_make(gcc_final_dir, tools_install_options, "install")
        
        #[083/184]: postinstall the final gcc build
        clean_dir(os.path.join(host_tools, "include"))
        do_unlink(os.path.join(host_tools, "lib/libiberty.a"))
        for var in variants:
            arch = var["arch"]
            do_unlink(os.path.join(host_tools, "lib/%s/libiberty.a"%arch))
        do_unlink(os.path.join(host_tools, "bin/%s-gccbug"%bare_metal_target))
        
                                            

    build_stage = build_stage + 1
    
#    if (run_stage(stage, build_stage)):
        #stage 32


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except GiveUp, why:
        print 'Giving up:', why

# End file.

        
