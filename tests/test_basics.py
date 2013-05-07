#! /usr/bin/env python
"""
Tests the rest of muddled.
"""

import os
import sys
import subprocess
import traceback

from support_for_tests import get_parent_dir

try:
    import muddled.cmdline
except ImportError:
    # Try one level up
    sys.path.insert(0, get_parent_dir(__file__))
    import muddled.cmdline

import muddled.depend as depend
import muddled.utils as utils
import muddled.version_control as version_control
import muddled.env_store as env_store
import muddled.mechanics as mechanics
import muddled.filespec as filespec
import muddled.pkg as pkg
import muddled.subst as subst
import muddled.cpiofile as cpiofile

from muddled.depend import Label

def cpio_unit_test():
    """
    A brief test of the cpio module. Uses ``<tempname>/test.cpio``.
    """

    tmpd = os.tempnam()
    os.mkdir(tmpd)
    tmpf = os.path.join(tmpd, 'test.cpio')

    f1 = cpiofile.file_from_fs(__file__)  # A file we're fairly sure exists
    f1.rename("foo")
    f2 = cpiofile.file_for_dir("bar")
    f3 = cpiofile.File()
    f3.rename("bar/baz")
    f3.set_contents("Hello, World!\n")

    arc = cpiofile.Archive()
    arc.add_files([f1])
    arc.render(tmpf, True)
    # Now just make sure that cpio can read the data

    out = subprocess.check_output("cpio -i --to-stdout <'%s'"%tmpf, shell=True)

    text = open(__file__).read()
    assert out[:len(text)] == text
    # Ignoring any extra lines about number of blocks...

def env_store_unit_test():
    """
    Test some bits of the environment store mechanism.
    """

    ee = env_store.EnvExpr(env_store.EnvExpr.StringType, "a")
    ee.append(r"\b")
    ee.append("'c")

    assert ee.to_sh(True) == r"a\\b\'c"
    assert ee.to_sh(False) == r"a\b'c"

    ee = env_store.EnvExpr(env_store.EnvExpr.RefType, "a")
    assert ee.to_sh(True) == '$a'

    # Now try something a bit more complex ..
    ee = env_store.EnvExpr(env_store.EnvExpr.CatType)
    ee.append_str("Fish")
    ee.append_ref("Soup")
    ee.append_str("Wombat")

    assert ee.to_sh(True) == 'Fish$SoupWombat'

    assert ee.to_value(env = { "Soup" : "X"}) == "FishXWombat"

    lst = ee.to_py(env_var = "env")

    assert len(lst) == 3

    assert lst[0] == '"Fish"'
    assert lst[1] == 'env["Soup"]'
    assert lst[2] == '"Wombat"'



def subst_unit_test():
    """
    Substitution unit test.
    """

    test_env = { "FISH" : "soup", "WOMBAT" : "herring" }
    result = subst.subst_str("${WOMBAT} is ${FISH}", None, test_env)
    assert result == "herring is soup"

    return 0

def filespec_unit_test():
    """
    Filespec unit tests.
    """

    lsp = filespec.ListFileSpecDataProvider(["/a/b", "/a/c", "/a/b/c", "/a/b/cee", "/d", "/d/bcee" ])

    l_full = lsp.list_files_under("/a", True)
    assert len(l_full) == 4

    l_part = lsp.list_files_under("/a", False)
    assert len(l_part) == 2

    # Right ..
    fs1 = filespec.FileSpec("/a", ".*", False, False)
    results = fs1.match(lsp)
    assert len(results) == 2
    assert "/a/b" in results
    assert "/a/c" in results

    fs1 = filespec.FileSpec("/a", "b", allUnder = False, allRegex = False)
    results = fs1.match(lsp)
    assert len(results) == 1
    assert "/a/b" in results

    fs1 = filespec.FileSpec("/a", "b", allUnder = True, allRegex = False)
    results = fs1.match(lsp)
    assert len(results) == 3
    assert "/a/b/c" in results
    assert "/a/b/cee" in results
    assert "/a/b" in results

    fs1 = filespec.FileSpec("/", "(.*)b(.*)", allUnder = True, allRegex = True)
    results = fs1.match(lsp)
    assert len(results) == 4
    assert "/d/bcee" in results
    assert "/a/b/c" in results
    assert "/a/b/cee" in results
    assert "/a/b" in results


def depend_unit_test():
    """
    Some fairly simple tests for the dependency solver.
    """

    l1 = Label(utils.LabelType.Checkout, "co_1", "role_1", utils.LabelTag.CheckedOut)
    l2 = Label(utils.LabelType.Checkout, "co_1", "role_1", utils.LabelTag.Pulled)
    l3 = Label(utils.LabelType.Package, "pkg_1", "role_1", utils.LabelTag.PreConfig)
    l4 = Label(utils.LabelType.Deployment, "dep_1", "role_2", utils.LabelTag.Built)

    # Check label_from_string ..
    lx = Label.from_string("foo:bar{baz}/wombat[T]")
    lx_a = Label("foo", "bar", "baz", "wombat")
    assert lx == lx_a
    assert lx.transient
    assert not lx.system

    lx = Label.from_string("foo:bar/wombat[T]")
    lx_a = Label("foo", "bar", None, "wombat")
    assert lx == lx_a
    assert lx.transient
    assert not lx.system

    lx = Label.from_string("*:bar/wombat")
    assert (lx is not None)
    lx_a = Label("*", "bar", None, "wombat")
    assert lx == lx_a
    assert not lx.transient
    assert not lx.system


    lx = Label.from_string("*:wombat/*")
    assert lx is not None
    lx_a = Label("*", "wombat", None, "*")
    assert lx == lx_a
    assert not lx.transient
    assert not lx.system

    lx = Label.from_string(l1.__str__())
    assert lx is not None
    assert lx == l1

    lx = Label.from_string(l2.__str__())
    assert lx is not None
    assert lx == l2

    lx = Label.from_string(l3.__str__())
    assert lx is not None
    assert lx == l3

    lx = Label.from_string(l4.__str__())
    assert lx is not None
    assert lx == l4

    # Let's check that label matching works the way we think it does ..
    la1 = Label(type='*', name=l1.name, domain=l1.domain, role=l1.role, tag=l1.tag)

    la2 = Label(type=l1.type, name='*', domain=l1.domain, role=l1.role, tag=l1.tag)

    la3 = Label(type=l1.type, name='*', domain=l1.domain, role='*', tag=l1.tag)

    la4 = l1.copy_with_tag('*')

    assert l1.match(l1) == 0
    assert l2.match(l1) is None
    assert la1.match(l1) == -1
    assert l1.match(la1) == -1
    assert (l2.match(la4)) == -1
    assert l1.match(la3) == -2

    r1 = depend.Rule(l1, pkg.NoAction())

    r2 = depend.Rule(l2, pkg.NoAction())
    r2.add(l1)

    r3 = depend.Rule(l3, pkg.NoAction())
    r4 = depend.Rule(l4, pkg.NoAction())

    r3.add(l2)
    r4.add(l3); r4.add(l2)

    rs = depend.RuleSet()
    rs.add(r1)
    rs.add(r2)
    rs.add(r3)
    rs.add(r4)
    assert str(rs).strip() == """\
-----
checkout:co_1{role_1}/checked_out <-NoAction-- [ ]
checkout:co_1{role_1}/pulled <-NoAction-- [ checkout:co_1{role_1}/checked_out ]
deployment:dep_1{role_2}/built <-NoAction-- [ checkout:co_1{role_1}/pulled, package:pkg_1{role_1}/preconfig ]
package:pkg_1{role_1}/preconfig <-NoAction-- [ checkout:co_1{role_1}/pulled ]
-----"""

    r3_required_for = depend.needed_to_build(rs, l3)
    assert depend.rule_list_to_string(r3_required_for) == "[ checkout:co_1{role_1}/checked_out <-NoAction-- [ ], checkout:co_1{role_1}/pulled <-NoAction-- [ checkout:co_1{role_1}/checked_out ], package:pkg_1{role_1}/preconfig <-NoAction-- [ checkout:co_1{role_1}/pulled ],  ]"

    r2_required_by = depend.required_by(rs, l2)
    assert depend.rule_list_to_string(r2_required_by) == "[ checkout:co_1{role_1}/pulled, deployment:dep_1{role_2}/built, package:pkg_1{role_1}/preconfig,  ]"

def utils_unit_test():
    """
    Unit testing on various utility code.
    """

    s = utils.c_escape("Hello World!")
    assert s == "Hello World!"

    s = utils.c_escape("Test \" \\ One")

    assert s == "Test \\\" \\\\ One"

    s = utils.pad_to("0123456789", 11)
    assert s == "0123456789 "

    s = utils.pad_to("0123456789", 8)
    assert s == "0123456789"

    s = utils.pad_to("0", 10, "z")
    assert s == "0zzzzzzzzz"

    s = utils.split_path_left("a/b/c")

    assert s == ("a", "b/c")

    s = utils.split_path_left("/a/b/c")
    assert s == ("", "a/b/c")

    s = utils.replace_root_name("/a", "/b", "/a/c")
    assert s == "/b/c"

    s = utils.replace_root_name("/a", "/b", "/d/e")
    assert s == "/d/e"


def vcs_unit_test():
    """
    Perform VCS unit tests.
    """
    repo = "http://www.google.com/"
    (x,y) = utils.split_vcs_url(repo)

    assert utils.split_vcs_url(repo) == (None, None)

    repo = "cVs+pserver://Foo.example.com/usr/cvs/foo"
    (vcs,url) = utils.split_vcs_url(repo)
    assert vcs == "cvs"
    assert url == "pserver://Foo.example.com/usr/cvs/foo"

def label_domain_sort():
    """Test sorting labels with domain names in them.
    """

    # Yes, apparently these are all legitimate label names
    # The domain names are the same as those used in the docstring for
    # utils.sort_domains()
    labels = [
            Label.from_string('checkout:(a)fred/*'),
            Label.from_string('checkout:(+(1))fred/*'),
            Label.from_string('checkout:(-(2))fred/*'),
            Label.from_string('checkout:(a(b(c2)))fred/*'),
            Label.from_string('checkout:(a(b(c1)))fred/*'),
            Label.from_string('checkout:(+(1(+2(+4(+4)))))fred/*'),
            Label.from_string('checkout:(b(b))fred/*'),
            Label.from_string('checkout:(b)fred/*'),
            Label.from_string('checkout:(b(a))fred/*'),
            Label.from_string('checkout:(a(a))fred/*'),
            Label.from_string('checkout:(+(1(+2)))fred/*'),
            Label.from_string('checkout:(+(1(+2(+4))))fred/*'),
            Label.from_string('checkout:(+(1(+3)))fred/*'),
            ]

    sorted_labels = sorted(labels)

    string_labels = map(str, labels)
    string_labels.sort()

    # Our properly sorted labels have changed order from that given
    assert sorted_labels != labels

    # It's not the same order as we'd get by sorting the labels as strings
    assert map(str, sorted_labels) != string_labels

    # It is this order...
    assert depend.label_list_to_string(sorted_labels) == (
            "checkout:(+(1))fred/*"
            " checkout:(+(1(+2)))fred/*"
            " checkout:(+(1(+2(+4))))fred/*"
            " checkout:(+(1(+2(+4(+4)))))fred/*"
            " checkout:(+(1(+3)))fred/*"
            " checkout:(-(2))fred/*"
            " checkout:(a)fred/*"
            " checkout:(a(a))fred/*"
            " checkout:(a(b(c1)))fred/*"
            " checkout:(a(b(c2)))fred/*"
            " checkout:(b)fred/*"
            " checkout:(b(a))fred/*"
            " checkout:(b(b))fred/*")

    # A specific test, which we originally got wrong
    labels = [
              Label.from_string('checkout:(sub1)builds/checked_out'),
              Label.from_string('checkout:(sub1(sub4))builds/checked_out'),
              Label.from_string('checkout:(sub1(sub5))builds/checked_out'),
              Label.from_string('checkout:(sub2)builds/checked_out'),
              Label.from_string('checkout:(sub1(sub4))co0/checked_out'),
              Label.from_string('checkout:(sub1(sub5))co0/checked_out'),
              Label.from_string('checkout:(sub2(sub3))builds/checked_out'),
              Label.from_string('checkout:(sub2(sub3))co0/checked_out'),
             ]

    sorted_labels = sorted(labels)

    string_labels = map(str, labels)
    string_labels.sort()

    # Our properly sorted labels have changed order from that given
    assert sorted_labels != labels

    # It's not the same order as we'd get by sorting the labels as strings
    assert map(str, sorted_labels) != string_labels

    #print 'xxx'
    #for label in sorted_labels:
    #    print '  ', str(label)
    #print 'xxx'

    # It is this order...
    assert depend.label_list_to_string(sorted_labels) == (
              "checkout:(sub1)builds/checked_out"
              " checkout:(sub1(sub4))builds/checked_out"
              " checkout:(sub1(sub4))co0/checked_out"
              " checkout:(sub1(sub5))builds/checked_out"
              " checkout:(sub1(sub5))co0/checked_out"
              " checkout:(sub2)builds/checked_out"
              " checkout:(sub2(sub3))builds/checked_out"
              " checkout:(sub2(sub3))co0/checked_out")

    # Another originally erroneous case

    l1 = Label.from_string("checkout:(subdomain2(subdomain3))main_co/checked_out")
    l2 = Label.from_string("checkout:first_co/checked_out")
    print
    print 'xx', l1
    print 'xx', l2
    print 'xx l2 < l1', l2 < l1
    assert l2 < l1

    labels = [
              Label.from_string("checkout:main_co/checked_out"),
              Label.from_string("checkout:(subdomain1)first_co/checked_out"),
              Label.from_string("checkout:(subdomain1)main_co/checked_out"),
              Label.from_string("checkout:(subdomain1)second_co/checked_out"),
              Label.from_string("checkout:(subdomain1(subdomain3))first_co/checked_out"),
              Label.from_string("checkout:(subdomain1(subdomain3))main_co/checked_out"),
              Label.from_string("checkout:(subdomain1(subdomain3))second_co/checked_out"),
              Label.from_string("checkout:(subdomain2)first_co/checked_out"),
              Label.from_string("checkout:(subdomain2)main_co/checked_out"),
              Label.from_string("checkout:(subdomain2(subdomain3))main_co/checked_out"),
              Label.from_string("checkout:first_co/checked_out"),
              Label.from_string("checkout:second_co/checked_out"),
              Label.from_string("checkout:(subdomain2)second_co/checked_out"),
              Label.from_string("checkout:(subdomain2(subdomain3))first_co/checked_out"),
              Label.from_string("checkout:(subdomain2(subdomain3))second_co/checked_out"),
              Label.from_string("checkout:(subdomain2(subdomain4))first_co/checked_out"),
              Label.from_string("checkout:(subdomain2(subdomain4))main_co/checked_out"),
              Label.from_string("checkout:(subdomain2(subdomain4))second_co/checked_out"),
             ]

    sorted_labels = sorted(labels)

    string_labels = map(str, labels)
    string_labels.sort()

    # Our properly sorted labels have changed order from that given
    assert sorted_labels != labels

    # It's not the same order as we'd get by sorting the labels as strings
    assert map(str, sorted_labels) != string_labels

    # It is this order...
    assert depend.label_list_to_string(sorted_labels) == (
             "checkout:first_co/checked_out"
             " checkout:main_co/checked_out"
             " checkout:second_co/checked_out"
             " checkout:(subdomain1)first_co/checked_out"
             " checkout:(subdomain1)main_co/checked_out"
             " checkout:(subdomain1)second_co/checked_out"
             " checkout:(subdomain1(subdomain3))first_co/checked_out"
             " checkout:(subdomain1(subdomain3))main_co/checked_out"
             " checkout:(subdomain1(subdomain3))second_co/checked_out"
             " checkout:(subdomain2)first_co/checked_out"
             " checkout:(subdomain2)main_co/checked_out"
             " checkout:(subdomain2)second_co/checked_out"
             " checkout:(subdomain2(subdomain3))first_co/checked_out"
             " checkout:(subdomain2(subdomain3))main_co/checked_out"
             " checkout:(subdomain2(subdomain3))second_co/checked_out"
             " checkout:(subdomain2(subdomain4))first_co/checked_out"
             " checkout:(subdomain2(subdomain4))main_co/checked_out"
             " checkout:(subdomain2(subdomain4))second_co/checked_out"
            )

def run_tests():
    print "> cpio"
    cpio_unit_test()
    print "> Utils"
    utils_unit_test()
    print "> env"
    env_store_unit_test()
    print "> subst"
    subst_unit_test()
    print "> filespec"
    filespec_unit_test()
    print "> VCS"
    vcs_unit_test()
    print "> Depends"
    depend_unit_test()
    print "> Label domain sort"
    label_domain_sort()

if __name__ == '__main__':
    try:
        run_tests()
        print '\nGREEN light\n'
    except Exception as e:
        print
        traceback.print_exc()
        print '\nRED light\n'
        sys.exit(1)
