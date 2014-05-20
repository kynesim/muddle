#! /usr/bin/env python
"""Test the "Choice" class from utils.py, and some basics of its use in aptget
"""

import os
import sys
import traceback
import unittest

from support_for_tests import *
from muddled.utils import GiveUp, Choice, normalise_dir
from muddled.withdir import Directory, NewDirectory, TransientDirectory

class TestChoice(unittest.TestCase):

    what_to_match = 'ubuntu 12.10'

    def test_match_single_string(self):
        choice = Choice('fred')
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, 'fred')

    def test_match_single_string_in_array(self):
        choice = Choice(['fred'])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, 'fred')

    def test_match_first_item_in_sequence(self):
        choice = Choice([('ubuntu 12.10','first')])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, 'first')

    def test_match_second_item_in_sequence(self):
        choice = Choice([('ubuntu 12.11','first'), ('ubuntu 12.10', 'second')])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, 'second')

    def test_match_first_item_in_sequence_with_default(self):
        choice = Choice([('ubuntu 12.10','first')])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, 'first')

    def test_match_second_item_in_sequence_with_default(self):
        choice = Choice([('ubuntu 12.11','first'), ('ubuntu 12.10', 'second')])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, 'second')

    def test_None_can_be_default(self):
        choice = Choice([('no match','first'), None])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, None)

    def test_None_alone_in_sequence_is_allowed(self):
        choice = Choice([None])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, None)

    def test_choice_cannot_be_None(self):
        with self.assertRaises(GiveUp) as cm:
            choice = Choice(None)

    def test_match_default_in_sequence_with_default(self):
        choice = Choice([('no match','first'), 'fred'])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, 'fred')

    def test_match_first_in_wildcarding(self):
        choice = Choice([('ubuntu 12.*','star'), ('ubuntu 12.10','fred')])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, 'star')

    def test_match_second_in_wildcarding(self):
        choice = Choice([('ubuntu 12.11','fred'), ('ubuntu 12.*','star')])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, 'star')

    def test_match_second_in_more_wildcarding(self):
        choice = Choice([('ubuntu 12.2?','fred'), ('ubuntu 12.1?','query')])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, 'query')

    def test_two_strings(self):
        with self.assertRaises(GiveUp) as cm:
            choice = Choice(['fred', 'fred'])

    def test_middle_string(self):
        with self.assertRaises(GiveUp) as cm:
            choice = Choice([('ubuntu 12.10','fred'), 'fred', ('ubuntu 12.*','star')])

    def test_no_match(self):
        choice = Choice([('redhat 7.0','fred'), ('SuSe 2012','star')])
        with self.assertRaises(ValueError) as cm:
            match = choice.choose(self.what_to_match)
        self.assertEqual(str(cm.exception), 'Nothing matched')

    def test_no_match_with_default(self):
        choice = Choice([('redhat 7.0','fred'), ('SuSe 2012','star'), 'match'])
        match = choice.choose(self.what_to_match)
        self.assertEqual(match, 'match')


BUILD_DESC = """\
import muddled.pkgs.aptget as aptget
from muddled.utils import Choice

def describe_to(builder):
    aptget.simple(builder, "Fred", "Fred", %s)
"""


def main(args):

    keep = False
    if args:
        if len(args) == 1 and args[0] == '-keep':
            keep = True
        else:
            print __doc__
            raise GiveUp('Unexpected arguments %s'%' '.join(args))

    print 'Testing utils.decide'

    suite = unittest.TestLoader().loadTestsFromTestCase(TestChoice)
    results = unittest.TextTestRunner().run(suite)

    if not results.wasSuccessful():
        return False

    # Working in a local transient directory seems to work OK
    # although if it's anyone other than me they might prefer
    # somewhere in $TMPDIR...
    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    def test_aptget(choice, exc_str=None):
        with Directory(os.path.join('src', 'builds')) as srcdir:
            if os.path.exists('01.py'):
                os.remove('01.py')
            if os.path.exists('01.pyc'):
                os.remove('01.pyc')
            touch('01.py', BUILD_DESC%choice)
            rc, text = captured_muddle2(['query', 'checkouts'])
            print text.strip()
            if rc == 0:
                if text.strip() != 'builds':
                    raise GiveUp('Build broken in unexpected manner')
                if exc_str:
                    raise GiveUp('Expected GiveUp with %r'%exc_str)
                print 'OK'
            else:
                if exc_str:
                    if exc_str not in text:
                        raise GiveUp('Got unexpected failure\n'
                                     'Expected %r'%exc_str)
                else:
                    raise GiveUp('Got unexpected failure')
                print 'Which is what we wanted, so OK'

    with TransientDirectory(root_dir, keep_on_error=True, keep_anyway=keep) as root_d:
        banner('CONSTRUCT BUILD DESCRIPTION')
        muddle(['bootstrap', 'git+file:///something', 'DECIDE'])
        # A simple string
        test_aptget('"fromble-v1"')
        # A string in an array, as we always supported
        test_aptget('["fromble-v1"]')
        # or even two such
        test_aptget('["fromble-v1", "fromble-v2"]')
        # A single choice
        test_aptget('Choice("fromble-v1")')
        test_aptget('Choice([("ubuntu 12.10", "choice1"), ("ubuntu 12.9", "choice3"), "choice2"])')
        test_aptget('Choice([("ubuntu 12.10", "choice1"), ("ubuntu 12.9", "choice3"), None])')
        # Choices in an array
        test_aptget('[Choice("fromble-v1")]')
        test_aptget('['
                    'Choice("fromble-v1"),'
                    'Choice([("ubuntu 12.10", "choice1"), ("ubuntu 12.9", "choice3"), "choice2"]),'
                    ']')
        # Strings and choices
        test_aptget('["fromble-v1", Choice("fromble-v1")]')
        test_aptget('["fromble1", Choice([("ubuntu 12.10", "choice1"), ("ubuntu 12.9", "choice3"), "choice2"])]')
        # Broken choices
        test_aptget('Choice([("ubuntu 12.10", "choice1"), "choice2", ("ubuntu 12.9", "choice3")])',
                    'Only the last item in a choice sequence may be a string')
        test_aptget('["fromble1", Choice([("ubuntu 12.10", "choice1"), "choice2", ("ubuntu 12.9", "choice3")])]',
                    'Only the last item in a choice sequence may be a string')
        # The example from the aptget.simple docstring
        test_aptget("""[
               "gcc-multilib",
               "g++-multilib",
               "lib32ncurses5-dev",
               "lib32z1-dev",
               "bison",
               "flex",
               "gperf",
               "libx11-dev",
               # On Ubuntu 11 or 12, choose icedtea-7, otherwise icedtea-6
               Choice([ ("ubuntu 1[12].*", "icedtea-7-jre"),
                        ("ubuntu *", "icedtea-6-jre") ]),
               # On Ubuntu 10 or later, use libgtiff5
               # On Ubuntu 3 through 9, use libgtiff4
               # Otherwise, just don't try to use libgtiff (and note we didn't
               # remember to think about a prospective Ubuntu 20...)
               Choice([ ("ubuntu 1?.*", "libgtiff5"),
                        ("ubuntu 12.[3456789]", "libgtiff4"),
                        None ])
               ], os_version='ubuntu 12.10'""")
        # What redhat?
        test_aptget("""[
               "gcc-multilib",
               # On Ubuntu 11 or 12, choose icedtea-7, otherwise icedtea-6
               Choice([ ("ubuntu 1[12].*", "icedtea-7-jre"),
                        ("ubuntu *", "icedtea-6-jre") ]),
               ], os_version='redhat 7.0'""",
               "and OS 'redhat 7.0', cannot find a match")

    return True


if __name__ == '__main__':
    args = sys.argv[1:]
    try:
        ok = main(args)
    except Exception as e:
        print
        traceback.print_exc()
        ok = False

    if ok:
        print '\nGREEN light\n'
    else:
        print '\nRED light\n'
        sys.exit(1)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
