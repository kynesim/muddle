#!/usr/bin/env python

import os, sys

listName = []
listLine = []
listCharacters = []
listTodo = []
listSingleLine = []
thing2 = []
thing3 = []
commentList = []
johnsLine = []
johnsList = []
fileList = []
a = -1
fileTypes = [".c", ".h", ".cpp"]  # If other file types must be added then add them here

# The first version of this was run via a shell script using xargs to pass
# file argument to us. This limits what we can return as an exit code - the
# xargs man page says:
#
#    xargs exits with the following status:
#    0 if it succeeds
#    123 if any invocation of the command exited with status 1-125
#    124 if the command exited with status 255
#    125 if the command is killed by a signal
#    126 if the command cannot be run
#    127 if the command is not found
#    1 if some other error occurred.
#
# but in fact exiting with 255 also outputs an error message, which it
# doesn't seem possible to suppress.
#
# Unfortunately, GNU xargs appears to return:
#
#    126 -> 126
#    127 -> 127
#    128..254 -> 123
#
# and there's no way to get 1. So that's not really enough to let us know
# what happened.
#
# The solution is to allow this program to read filenames separated by
# '\0' bytes (as produced by "git diff -z") directly from stdin.

# The following is taken from http://bugs.python.org/issue1152248#msg109117,
# which is a (long) discussion on making it easy to do this in Python
def fileLineIter(inputFile,
                 inputNewline="\n",
                 outputNewline=None,
                 readSize=8192):
   """Like the normal file iter but you can set what string indicates newline.

   The newline string can be arbitrarily long; it need not be restricted to a
   single character. You can also set the read size and control whether or not
   the newline string is left on the end of the iterated lines.  Setting
   newline to '\0' is particularly good for use with an input file created with
   something like "os.popen('find -print0')".
   """
   if outputNewline is None: outputNewline = inputNewline
   partialLine = ''
   while True:
       charsJustRead = inputFile.read(readSize)
       if not charsJustRead: break
       partialLine += charsJustRead
       lines = partialLine.split(inputNewline)
       partialLine = lines.pop()
       for line in lines: yield line + outputNewline
   if partialLine: yield partialLine

def checkIsFile():
    if args.git:
        # We expect to have been given specific files relative to the
        # current directory
        filenames = []
        for name in fileLineIter(sys.stdin, '\0'):
            if name[-1] == '\0':
                filenames.append(name[:-1])
            else:
                filenames.append(name)
        print 'XXX', filenames
        findLineNumbers('.', filenames)
        return output()
    else:
        for root, dirs, files in os.walk(os.path.join(".")):
            fileList = []
            for lump in args.f:
                if "/" in lump:
                    slash = lump.rfind("/")
                    lump = lump[slash+1:]
                if lump in dirs:
                    startup(os.path.join(root, lump))
                    commentFind(os.path.join(root, lump))
                if lump in files:
                    fileList.append(lump)
                    commentFind2(root, files, -1)
            if fileList != []:
                findLineNumbers(root, fileList)
        return output()


def startup(directory):
    for root, dirs, files in os.walk(directory):
        findLineNumbers(root, files)


def findLineNumbers(root, files):
    global listName, listLine, listCharacters, listTodo, listSingleLine, johnsLine
    for x in range(0, len(files)):
        if files[x][files[x].find("."):] not in fileTypes:
            pass
        else:
            try:
                thing = open(os.path.join(root, files[x]), "r")
                line = thing.readline()
            except IOError as e:
                print "Error: %s" % e
                line = ""
            z = 1
            characters = 0
            while True:
                if line == "":
                    break
                if "//==" in line:
                    johnsLine.append([line, os.path.join(root, files[x]), z])
                if "@todo" in line.lower() or "TODO" in line:
                    listLine.append(z)
                    listName.append(os.path.join(root, files[x]))
                    y = characters + line.lower().find("todo")
                    listCharacters.append(y)
                    if "#" in line:
                        listSingleLine.append(characters + line.find("#"))
                    elif "//" in line:
                        listSingleLine.append(characters + line.find("//"))
                    else:
                        listSingleLine.append(0)
                characters += len(line)
                z += 1
                line = thing.readline()
            try:
                thing.close()
            except UnboundLocalError:
                pass
    context()


def context():
    """Part of the process of finding todos - specifically finding the comment it is in
    """

    global listTodo, johnsLine
    for x in range(0, len(johnsLine)):
        split = johnsLine[x][0].split()
        y = 0
        for item in split:
            if "//==" in item:
                number = y
            if "//==" not in item:
                y += 1
        thing4 = ''.join([item for item in split[:number]])
        thing5 = ''.join([item for item in split[number+1:]])
        if thing4 != thing5:
            johnsList.append([johnsLine[x][1], johnsLine[x][2]])
    johnsLine = []
    for x in range(0, len(listCharacters)):
        text = open(listName[x], "r")
        string = text.read()
        text.close()

        if int(listSingleLine[x]) == 0:
            begin = string.rfind("/*", 0, listCharacters[x])
            finnish = string.find("*/", listCharacters[x])
            listTodo.append(string[begin:finnish + 2])
        elif int(listSingleLine[x]) > 0:
            finnish = string.find("\n", listSingleLine[x])
            thing = string[listSingleLine[x]:finnish + 1]
            listTodo.append(thing)
        else:
            listTodo.append("Was not within a comment")


def commentFind(thing):
    a = -1
    for root, dirs, files in os.walk(thing):
        commentFind2(root, files, a)


def commentFind2(root, files, a):
    thing2.append([])
    for x in range(0, len(files)):
        thing2.append([])
        if files[x][files[x].find("."):] not in fileTypes:
            pass
        else:
            a += 1
            string1 = open(os.path.join(root, files[x]), "r")
            string = string1.read()
            string1.close()

            pos = ""
            place = -1

            while "-1" not in str(pos):
                pos = string.lower().find("/*", place+1)
                place = pos
                if len(string) > pos > -1:
                    thing2[a].append([place, os.path.join(root, files[x]), "start"])

            pos = ""
            place = -1

            while "-1" not in str(pos):
                pos = string.lower().find("*/", place+1)
                place = pos
                thing2[a].append([place, os.path.join(root, files[x]), "end"])
    commentFind3(thing2)


def commentFind3(thing2):
    global commentList
    for lump in thing2:
        thing3.append(sorted(lump))

    for lump in range(0, len(thing3)):
        for x in range(0, len(thing3[lump])):
            try:
                if thing3[lump][x][2] == "start":
                    if thing3[lump][x+1][2] != "end":
                        commentList.append([thing3[lump][x][0], thing3[lump][x][1]])
            except IndexError:
                commentList.append([thing3[lump][x][0], thing3[lump][x][1]])

    for x in range(0, len(commentList)):
        one = open(commentList[x][1], "r")
        two = one.read()
        one.close()

        pos = 0
        z = 0
        while "-1" not in str(pos):
            pos = two.lower().find("\n", pos+1, int(commentList[x][0])+1)
            if pos > -1:
                z += 1       # Accounts for the fact that the \n is after the final character on the last line
        commentList[x].append(z+1)
        # This function can have an issue with comments opening before any other text is typed.
        # It will show up one line too soon


def output():
    if johnsList != []:
        for x in range(0, len(johnsList)):
            print "The two sides of //== don't match on line", johnsList[x][1], "in file ", johnsList[x][0], "\n"
    if listTodo != []:
        for x in range(0, len(listLine)):
            print "There is a 'todo' at line", listLine[x], "in the file", listName[x] + ":"
            print listTodo[x], "\n"
    if commentList != []:
        for x in range(0, len(commentList)):
            print "There is an un-finished comment on line "+str(commentList[x][2])+" in file "+str(commentList[x][1])
    if commentList != []:
        return 2
    if johnsList != []:
        return 4
    if listTodo != []:
        return 8

notInUse = '''\
def function(directory, x="all"):  # Allows you to specify directory and choose what you want said directory checked for
    if x == "all" or x == "comment":  # Checks for Comments that haven't been closed
        commentFind(directory)
    if x == "all" or x == "todo":     # Checks for todos within the directrory
        findLineNumbers(directory)
    output() '''

#######################################################################################################

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("f", help="The files/directorys to be searched",  # Specify the directory from the cmd.
                    type=str, nargs='*')
parser.add_argument("--git", help="Set if the files are specified by the ToDoFinder git pre-commit hook", nargs='?', const=True, default=False)
parser.add_argument("--xxx", help="The type of thing to search for",   # Specify what you are searching for from
                    choices=["all", "comment", "todo"], default="all")  # within the cmd.

args = parser.parse_args()


if __name__ == "__main__":
    sys.exit(checkIsFile())
