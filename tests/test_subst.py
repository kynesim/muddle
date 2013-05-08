#! /usr/bin/env python
"""Test the muddle subst mechanism.

./test_subst.py [-keep]

With -keep, do not delete the 'transient' directory used for the tests.

Written so I could figure out the details of how it works - it seemed sensible
to enshrine that as yet another test...

I've incorporated what used to be the input/xml/output files in the
"tests/parsers" directory - having them here ensures they will get run.
These may be argued to show the original scope intended for the mechanism.

Note that this is *not* an exhaustive exploration of the way that "muddle
subst" works, it does not attempt to explore the odd corners of its
implementation. What you get is what you get.
"""

import os
import sys
import traceback

from subprocess import CalledProcessError

from support_for_tests import *
try:
    import muddled.cmdline
except ImportError:
    # Try one level up
    sys.path.insert(0, get_parent_dir(__file__))
    import muddled.cmdline

from muddled.utils import GiveUp, normalise_dir
from muddled.withdir import Directory, NewDirectory, TransientDirectory

# -----------------------------------------------------------------------------
SIMPLE_IN_1 = """\
A simple test: can we read a perfectly ordinary document?

Hello, World!
"""

SIMPLE_XML_1 = """\
<?xml version="1.0" ?>

<top>
  <my-name-is>Fred</my-name-is>
</top>
"""

SIMPLE_OUT_1 = """\
A simple test: can we read a perfectly ordinary document?

Hello, World!
"""

# -----------------------------------------------------------------------------
SIMPLE_IN_2 = """\
Can we read a simple directive?

Hello, I am ${/top/my-name-is}  .
"""

SIMPLE_XML_2 = """\
<?xml version="1.0" ?>

<top>
  <my-name-is>Fred</my-name-is>
</top>
"""

SIMPLE_OUT_2 = """\
Can we read a simple directive?

Hello, I am Fred  .
"""

# -----------------------------------------------------------------------------
SIMPLE_IN_3 = """\
How about a function?

Hello, I am ${fn:val("/top/my-name-is")} .
"""

SIMPLE_XML_3 = """\
<?xml version="1.0" ?>

<top>
  <my-name-is>Jim</my-name-is>
</top>
"""

SIMPLE_OUT_3 = """\
How about a function?

Hello, I am Jim .
"""

# -----------------------------------------------------------------------------
SIMPLE_IN_4 = """\
Multiple parameters?

Hello, I am ${fn:echo("a","b",c,d,"e,f")}.
"""

SIMPLE_XML_4 = """\
<?xml version="1.0" ?>

<top>
  <my-name-is>Sheila</my-name-is>
</top>
"""

# ???
SIMPLE_OUT_4 = """\
Multiple parameters?

Hello, I am abcde,f.
"""

# -----------------------------------------------------------------------------
SIMPLE_IN_5 = """\
How about some escaping?

$${I wonder if this works?}
And this should be literal: $$
How about $${ ?
And really adventurously: ${fn:echo("a\\"b", c\\,d)}
"""

SIMPLE_XML_5 = """\
<?xml version="1.0" ?>

<top>
  <my-name-is>And</my-name-is>
</top>
"""

# Mind the trailing space after the final ':'
SIMPLE_OUT_5 = """\
How about some escaping?

${I wonder if this works?}
And this should be literal: $$
How about ${ ?
And really adventurously: a"bc,d
"""

# -----------------------------------------------------------------------------
SIMPLE_IN_6 = """\
Let's see if embedded evaluation (and some odd spacing) works...

Hello, ${${/top/pronoun-name}}
${  "${/top/animal-name}"  }
"""

SIMPLE_XML_6 = """\
<?xml version="1.0" ?>

<top>
  <data>
    <pronoun>her</pronoun>
    <animal>dog</animal>
  </data>
  <pronoun-name>/top/data/pronoun</pronoun-name>
  <animal-name>/top/data/animal</animal-name>
</top>
"""

SIMPLE_OUT_6 = """\
Let's see if embedded evaluation (and some odd spacing) works...

Hello, her
dog
"""

# -----------------------------------------------------------------------------
SIMPLE_IN_7 = """\
How about ifeq?

Fish ${fn:ifeq("/top/fish", "soup")

Fish = Soup
And Fish = ${/top/fish}
}

Soup ${fn:ifeq("/top/fish", "fish")

Fish = Fish
}
"""

SIMPLE_XML_7 = """\
<?xml version="1.0" ?>

<top>
  <fish>soup</fish>
</top>

"""

# Mind the trailing spaces after the standalone 'Fish' and 'Soup'
SIMPLE_OUT_7 = """\
How about ifeq?

Fish 

Fish = Soup
And Fish = soup


Soup 
"""

# -----------------------------------------------------------------------------
SIMPLE_IN_8 = """\
ifneq?

Fish ${fn:ifneq("/top/fish","soup")

Fish is not soup!
}

Soup: ${fn:ifneq("/tmp/fish","fish")
Fish is not fish!
}
"""

SIMPLE_XML_8 = """\
<?xml version="1.0" ?>

<top>
  <fish>soup</fish>
</top>

"""

# Mind the trailing spaces after the standalone 'Fish' and 'Soup:'
SIMPLE_OUT_8 = """\
ifneq?

Fish 

Soup: 
Fish is not fish!

"""

# -----------------------------------------------------------------------------
VALUES_XML = """\
<?xml version="1.0" ?>
<!-- XML only allows a single root element --> 
<data>
    <version>Kynesim version 99</version>
    <values>
        <value1>This is value 1</value1>
        <value2>This is value 2</value2>
    </values>
    <a>3</a>
    <b>3</b>
    <c>4</c>
    <d>5</d>
</data>
"""

# -----------------------------------------------------------------------------
# "${fred" should end with "}", not "]"
BROKEN_1_IN = """\
Here is some text. It's really just padding.
However, ${VERSION} ${fred]
and some other text.
"""

# "${values..." should be "${/values..." if it is XML, and otherwise
# there is no environment variable called "values/value2"
BROKEN_2_IN = """\
$${values/value2} gives ${values/value2}
"""

# There is no "/values/value2" in the XML file
BROKEN_3_IN = """\
$${fn:val(/values/value2)} gives ${fn:val(/values/value2)}
"""

# There is no values called "{version" (and it doesn't notice the extra "}")
BROKEN_4_IN = """\
$${{version}} gives ${{version}}
"""

# There is a missing closing ")" on the "ifeq" function call
BROKEN_5_IN = """\
This test is also broken: ${fn:ifeq(a,b,c}
"""

# There is no value "version" in the XML file or the environment
# (it is "/data/version")
BROKEN_6_IN = """\
This value is not defined: ${version}
"""

# -----------------------------------------------------------------------------
TEXT_IN = """\
01: This is test ${/data/version}
02:
03: However, ${VERSION}
04:
05: * ${/data/values/value1}
06: * ${/data/values/value2} (${"/data/values/value2"})
07:
08: Here is ${AN_ENVIRONMENT_VALUE}, and again: ${"AN_ENVIRONMENT_VALUE"}
09:
10: This is $${NOT SUBSTITUTED}
11:
12: $${fn:val(/data/values/value2)} gives ${fn:val(/data/values/value2)}
13: $${fn:val(/data/values/value2)} gives ${fn:val(/data/values/value2)}
14:
15: ${/data/a}. ${/data/b}, ${/data/c}, ${/data/d}
16:
17: ${fn:ifeq(/data/a,${/data/b})/data/c} -- should be /data/c
18: ${fn:ifeq(/data/b,${/data/c})/data/d} -- should be empty
19: ${fn:ifneq(/data/a,${/data/b})/data/c} -- should be empty
20: ${fn:ifneq(/data/b,${/data/c})/data/d} -- should be /data/d
21:
22: ${fn:ifeq(/data/a,${/data/b})${/data/c}} -- should be 4
23: ${fn:ifeq(/data/b,${/data/c})${/data/d}} -- should be empty
24: ${fn:ifneq(/data/a,${/data/b})${/data/c}} -- should be empty
25: ${fn:ifneq(/data/b,${/data/c})${/data/d}} -- should be 5
26:
27: ${fn:echo(data/version, a,b, AN_ENVIRONMENT_VALUE,"some text")}
28: ${fn:echo(data/version, ${/data/a},${/data/b}, AN_ENVIRONMENT_VALUE, "some text")}
"""

TEXT_OUT = """\
01: This is test Kynesim version 99
02:
03: However, 123456
04:
05: * This is value 1
06: * This is value 2 (This is value 2)
07:
08: Here is Fred, and again: Fred
09:
10: This is ${NOT SUBSTITUTED}
11:
12: ${fn:val(/data/values/value2)} gives This is value 2
13: ${fn:val(/data/values/value2)} gives This is value 2
14:
15: 3. 3, 4, 5
16:
17: /data/c -- should be /data/c
18:  -- should be empty
19:  -- should be empty
20: /data/d -- should be /data/d
21:
22: 4 -- should be 4
23:  -- should be empty
24:  -- should be empty
25: 5 -- should be 5
26:
27: data/versionabAN_ENVIRONMENT_VALUEsome text
28: data/version33AN_ENVIRONMENT_VALUEsome text
"""

# -----------------------------------------------------------------------------
def broken_muddle(cmd_list, error=None, endswith=None):
    try:
        text = captured_muddle(cmd_list)
        raise GiveUp('Command unexpectedly worked, returned %r'%text)
    except CalledProcessError as e:
        stripped = e.output.strip()
        if error:
            check_text(stripped, error)
        else:
            if not stripped.endswith(endswith):
                raise GiveUp('Wrong error for "muddle %s"\n'
                             'Got:\n'
                             '  %s\n'
                             'Expected it to end:\n  %s'%(' '.join(cmd_list),
                                 '\n  '.join(stripped.splitlines()),
                                 '\n  '.join(endswith.splitlines())))
        print 'Successfully failed'
        print

def test_muddle_subst(d):

    banner('Simple tests, all should pass', 2)

    simple = {1: (SIMPLE_IN_1, SIMPLE_XML_1, SIMPLE_OUT_1),
              2: (SIMPLE_IN_2, SIMPLE_XML_2, SIMPLE_OUT_2),
              3: (SIMPLE_IN_3, SIMPLE_XML_3, SIMPLE_OUT_3),
              4: (SIMPLE_IN_4, SIMPLE_XML_4, SIMPLE_OUT_4),
              5: (SIMPLE_IN_5, SIMPLE_XML_5, SIMPLE_OUT_5),
              6: (SIMPLE_IN_6, SIMPLE_XML_6, SIMPLE_OUT_6),
              7: (SIMPLE_IN_7, SIMPLE_XML_7, SIMPLE_OUT_7),
              8: (SIMPLE_IN_8, SIMPLE_XML_8, SIMPLE_OUT_8),
              }

    for item in sorted(simple.keys()):
        input, xml, output = simple[item]
        in_name = 'simple.%d.in'%item
        xml_name = 'simple.%d.xml'%item
        out_name = 'simple.%d.out'%item
        touch(in_name, input)
        touch(xml_name, xml)
        muddle(['subst', in_name, xml_name, out_name])
        text = open(out_name).read()
        lines = text.splitlines()
        check_text_lines_v_lines(lines, output.splitlines())

    touch('values.xml', VALUES_XML)
    touch('broken1.txt.in', BROKEN_1_IN)
    touch('broken2.txt.in', BROKEN_2_IN)
    touch('broken3.txt.in', BROKEN_3_IN)
    touch('broken4.txt.in', BROKEN_4_IN)
    touch('broken5.txt.in', BROKEN_5_IN)
    touch('broken6.txt.in', BROKEN_6_IN)
    touch('values.txt.in', TEXT_IN)

    banner('Broken tests, all should fail', 2)

    os.environ['AN_ENVIRONMENT_VALUE'] = 'Fred'
    os.environ['VERSION'] = '123456'

    broken_muddle(['subst', 'broken1.txt.in', 'broken1.txt'],
            endswith="The text that was not ended is 'fred]\\nand some other text.\\n'\n"
                     "\n"
                     "Syntax Error: Input text ends whilst waiting for end char (':', '}')\n"
                     "Whilst processing broken1.txt.in")

    broken_muddle(['subst', 'broken2.txt.in', 'values.xml', 'broken2.txt'],
            error="Environment variable 'values/value2' not defined.\n"
                  "Whilst processing broken2.txt.in with XML file values.xml")

    broken_muddle(['subst', 'broken3.txt.in', 'values.xml', 'broken3.txt'],
            error="Attempt to substitute key '/values/value2' which does not exist.\n"
                  "Whilst processing broken3.txt.in with XML file values.xml")

    broken_muddle(['subst', 'broken4.txt.in', 'values.xml', 'broken4.txt'],
            error="Environment variable '{version' not defined.\n"
                  "Whilst processing broken4.txt.in with XML file values.xml")

    broken_muddle(['subst', 'broken5.txt.in', 'values.xml', 'broken5.txt'],
            endswith="The text that was not ended is 'c}\\n'\n"
                     "\n"
                     "Syntax Error: Input text ends whilst waiting for end char (')', ',')\n"
                     "Whilst processing broken5.txt.in with XML file values.xml")

    broken_muddle(['subst', 'broken6.txt.in', 'values.xml', 'broken6.txt'],
            error="Environment variable 'version' not defined.\n"
                  "Whilst processing broken6.txt.in with XML file values.xml")

    banner('General test, which should pass', 2)

    muddle(['subst', 'values.txt.in', 'values.xml', 'values.txt'])
    text = open('values.txt').read()
    lines = text.splitlines()
    check_text_lines_v_lines(lines, TEXT_OUT.splitlines())


def main(args):

    keep = False
    if args:
        if len(args) == 1 and args[0] == '-keep':
            keep = True
        else:
            print __doc__
            return

    root_dir = normalise_dir(os.path.join(os.getcwd(), 'transient'))

    with TransientDirectory(root_dir, keep_on_error=True, keep_anyway=keep) as root_d:

        banner('TESTING MUDDLE SUBST')

        test_muddle_subst(root_d)


if __name__ == '__main__':
    args = sys.argv[1:]
    try:
        main(args)
        print '\nGREEN light\n'
    except Exception as e:
        print
        traceback.print_exc()
        print '\nRED light\n'
        sys.exit(1)

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
