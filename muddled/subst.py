"""
Substitutes a file with query parameters. These can come from environment
variables or from an (optional) XML file.

Queries are a bit like XPath::

    /elem/elem ...

An implicit ``::text()`` is appended so you get all the text in the specified
element.
"""

import muddled
import muddled.utils as utils
import xml.dom
import xml.dom.minidom
import os
import re

g_trace_parser = False

def get_text_in_xml_node(node):
    """
    Given an XML node, collect all the text in it.
    """
    elems = [ ]
    for n in node.childNodes:
        if (n.nodeType == n.TEXT_NODE):
            elems.append(n.data)

    result = "".join(elems)
    # Strip trailing '\n's
    if (result[:-1] == '\n'):
        result = result[:-1]

    return result

def query_result(keys, doc_node):
    """
    Given a list of keys and a document node, return the XML node
    which matches the query, or None if there isn't one.
    """
    result = doc_node

    for i in keys:
        next_result = None

        for j in result.childNodes:
            if (j.nodeType == j.ELEMENT_NODE and \
                    (j.nodeName == i)):
                next_result = j
                break

        if (next_result is None):
            return None
        else:
            result = next_result

    return result

def split_query(query):
    """
    Split a query into a series of keys suitable to be passed to query_result().
    """
    
    result = query.split("/")
    if (result[0] == ''):
        # Absolute path - lop off the initial empty string
        result = result[1:]

    return result

def query_string_value(xml_doc, env, k):
    """
    Given a string-valued query, work out what the result was
    """
    v = None
    result_node = None

    if (len(k) == 0):
        return ""

    if (k[0] == '/'):
        # An XML query
        if xml_doc is not None:
            result_node = query_result(split_query(k), xml_doc)
        if (result_node is not None):
            v = get_text_in_xml_node(result_node)
    else:
        # An environment variable
        if (k in env):
            v = env[k]
        else:
            raise utils.Failure("Environment variable '%s' not defined."%k)

    return v

class PushbackInputStream:
    """
    A pushback input stream based on a string. Used in our recursive descent
    parser
    """
    
    def __init__(self, str):
        self.input = str;
        self.idx = 0
        self.pushback_char = -1
        self.line = 1
        self.char = 1

    def next(self):
        res = -1
        if (self.pushback_char != -1):
            c = self.pushback_char
            self.pushback_char = -1
            res = c
        elif (self.idx >= len(self.input)):
            res = -1
        else:
            i = self.idx
            self.idx = self.idx + 1
            res = self.input[i]

        if (res == '\n'):
            self.char = 1; self.line = self.line + 1
        elif (res != -1):
            self.char = self.char + 1
            
        if (g_trace_parser):
            if res < 0:
                print "next(%d,%d) = -1"%(self.line,self.char)
            else:
                print "next(%d,%d) = %c "%(self.line,self.char,res)

        return res

    def push_back(self,c):
        self.pushback_char = c

    def peek(self):
        if (self.pushback_char != -1):
            return self.pushback_char
        elif (self.idx >= len(self.input)):
            return -1
        else:
            return self.input[self.idx]

    def report(self):
        return "line %d, char %d"%(self.line, self.char)

        
class TreeNode:
    """
    A TreeNode contains itself, followed by all its children, so this is
    essentially a left tree.
    """

    StringType = "string"
    InstructionType = "instruction"
    ContainerType = "container"


    def __init__(self,in_type):
        self.type = in_type
        self.children = [ ]
        self.string = ""
        # The default function is to evaluate something.
        self.instr_type = "val"
        self.function = ""


    def set_string(self, inStr):
        self.type = TreeNode.StringType
        self.string = inStr

    def append_child(self, n):
        self.children.append(n)

    def set_val(self, v):
        """
        v is the value which should be evaluated to get the
        value to evaluate.
        """
        self.instr_type = "val"
        self.function = ""
        self.expr = v
    
    def set_fn(self, fn_name, params, rest):
        """
        fn_name is the name of the function
        params and rest are lists of nodes
        """
        self.instr_type = "fn"
        self.function = fn_name
        self.params = params
        self.append_child(rest)

    def __str__(self):
        buf = [ ]
        if (self.type == TreeNode.StringType):
            buf.append("{ String: '%s' "%(self.string))
        elif (self.type == TreeNode.InstructionType):
            if (self.instr_type == "val"):
                buf.append("{ ValInstr: !%s!  "%(self.expr))
            elif (self.instr_type == "fn"):
                param_str = [ "[ " ]
                for p in self.params:
                    param_str.append("%s "%p)
                param_str.append(" ]")
                

                buf.append("{ FnInstr: %s Params: [ %s ] "%(self.function, 
                                                            "".join(param_str)))
            else:
                buf.append("{ UnknownInstr type = %s "%(self.instr_type))
        elif (self.type == TreeNode.ContainerType):
            buf.append("{ Container ")
        buf.append("\n")
        for c in self.children:
            buf.append(" - %s \n"%c)
        buf.append("}\n")
        return "".join(buf)

    def append_children(self, xml_doc, env, output_list):
        for c in self.children:
            c.eval(xml_doc, env, output_list)

    def eval(self, xml_doc, env, output_list):
        """
        Evaluate this node with respect to xml_doc, env and place your
        output in output_list - a list of strings.
        """
        if (self.type == TreeNode.StringType):
            # Easy enough .. 
            output_list.append(self.string)
            for c in self.children:
                c.eval(xml_doc, env, output_list)
        elif (self.type == TreeNode.ContainerType):
            for c in self.children:
                c.eval(xml_doc, env, output_list)
        elif (self.type == TreeNode.InstructionType):
            # Evaluate some sort of function.
            if (g_trace_parser):
                print "Eval instr: %s"%(self.instr_type)
            
            if (self.instr_type == "val"):
                self.val(xml_doc, env, output_list)
            elif (self.instr_type == "fn"):
                if (self.function == "val"):
                    self.fnval(xml_doc, env, output_list)
                elif (self.function == "ifeq"):
                    self.ifeq(xml_doc, env, output_list)
                elif (self.function == "echo"):
                    self.echo(xml_doc, env, output_list)
            else:
                # Evaluates to nothing.
                pass
    
    def eval_str(self, xml_doc, env):
        """
        Evaluate this node and return the result as a string
        """
        output_list = [ ]
        self.eval(xml_doc, env, output_list)
        return "".join(output_list)

    def val(self, xml_doc, env, output_list):
        key_name = self.expr.eval_str(xml_doc, env)
        key_name = key_name.strip()


        if (key_name is None):
            res =  ""
        else:
            res = query_string_value(xml_doc, env, key_name)

        if (g_trace_parser):
            print "node.val(%s -> %s) = %s"%(self.expr, key_name, res)

        output_list.append(res)


    def fnval(self, xml_doc, env, output_list):
        if (len(self.params) != 1):
            raise utils.Failure("val() must have exactly one parameter")

        key_name = self.params[0].eval_str(xml_doc, env)
        key_name = key_name.strip()


        if (key_name is None):
            res =  ""
        else:
            res = query_string_value(xml_doc, env, key_name)

        if (g_trace_parser):
            print "node.fnval(%s -> %s) = %s"%(self.params[0], key_name, res)

        output_list.append(res)

    def ifeq(self, xml_doc, env, output_list):
        # Must have two parameters ..
        if (len(self.params) != 2):
            raise utils.Failure("ifeq() must have two parameters")

        key = self.params[0].eval_str(xml_doc, env)
        key = key.strip()
        value = self.params[1].eval_str(xml_doc, env)

        key_value = query_string_value(xml_doc, env, key)
        if (key_value is not None):
            key_value = key_value.strip()

        if (key_value == value):
            self.append_children(xml_doc, env, output_list)

    def echo(self, xml_doc, env, output_list):
        # Just echo your parameters.
        for p in self.params:
             p.eval(xml_doc, env, output_list)



def parse_document(input_stream, node, end_chars):
    """
    Parse a document into a tree node.
    Ends with end_char (which may be -1)
    
    Leaves the input stream positioned at end_char.
    """
    
    # States:
    #
    #   0 - Parsing text.
    #   1 - Got '$'.
    #   2 - Got '$$'
    #   3 - Got '\'
    state = 0
    cur_str = [ ]

    while True:
        c = input_stream.next()
        

        if (g_trace_parser):
            print "parse_document(): c = %s cur_str = [ %s ] state = %d"%(c,",".join(cur_str), state)

        ends_now = (c < 0)
        if ((not ends_now) and  state == 0 and end_chars is not None):
            ends_now = (c in end_chars)

        if ((end_chars is not None) and (c < 0)):
            raise utils.Failure("Stream ends whilst waiting for end chars: Syntax error")

        if (ends_now):
            cur_node = TreeNode(TreeNode.StringType)
            cur_node.set_string("".join(cur_str))
            node.append_child(cur_node)
            # Push back .. 
            input_stream.push_back(c)
            cur_str = [ ]
            if (g_trace_parser):
                print "parse_document(): terminating character %s detected. Ending."%(c)
            return
        
        if (state == 0):
            if (c == '$'):
                state = 1
            elif (c== '\\'):
                # Literal.
                state = 3
            else:
                cur_str.append(c)
        elif (state == 1):
            if (c == '$'):
                # Got '$$' 
                state = 2
            elif (c == '{'):
                # Start of an instruction.
                cur_node = TreeNode(TreeNode.StringType)
                cur_node.set_string("".join(cur_str))
                cur_str = [ ]
                node.append_child(cur_node)
                parse_instruction(input_stream, node)
                # Eat the trailing character
                input_stream.next()
                # .. and back to the start.
                state = 0
            else:
                cur_str.append('$')
                cur_str.append(c)
                state = 0
        elif (state == 2):
            if (c == '{'):
                # Ah. Literal ${
                cur_str.append('$')
                cur_str.append('{')
            else:
                # Literal $$<c>
                cur_str.append('$')
                cur_str.append('$')
                cur_str.append(c)
            state = 0
        elif (state == 3):
            # Unescape
            cur_str.append(c)
            state = 0


def skip_whitespace(in_stream):
    """
    Skip some whitespace
    """
    while True:
        c = in_stream.peek()
        if (c == ' ' or c=='\r' or c=='\t' or c=='\n'):
            in_stream.next()
        else:
            return

def flatten_literal_node(in_node):
    """
    Flatten a literal node into a string. Raise Failure if we, um, fail.
    """
    lst = [ ]

    if (in_node.type == TreeNode.StringType):
        lst.append(in_node.string)
    elif (in_node.type == TreeNode.ContainerType):
        pass
    else:
        # Annoyingly, we can't report here yet.
        raise utils.Failure("Non literal where literal expected.")

    for i in in_node.children:
        lst.append(flatten_literal_node(i))

    if (g_trace_parser):
        print "Flatten: %s  Gives '%s'\n"%(in_node, "".join(lst))
        
    return "".join(lst)

def parse_literal(input_stream, echars):
    """
    Given a set of end chars, parse a literal.
    """
    dummy = TreeNode(TreeNode.ContainerType)
    parse_document(input_stream, dummy, echars)
    return flatten_literal_node(dummy)
    
            
def parse_param(input_stream, node, echars):
    """
    Parse a parameter: may be quoted (in which case ends at ") else ends at echars
    """
    skip_whitespace(input_stream)
    
    if (input_stream.peek() == '\"'):
        input_stream.next(); # Skip the quote.
        e2chars = set([ '"' ])
        parse_document(input_stream, node, e2chars)
        # Skip the '"'
        input_stream.next()
        skip_whitespace(input_stream)
        c = input_stream.peek()
        if (c in echars):
            # Fine.
            return
        else:
            raise utils.Failure("Quoted parameter ends with invalid character %c - %s"%(c,
                                                                                        input_stream.report()))
    else:
        parse_document(input_stream, node, echars)

def parse_instruction(input_stream, node):
                     
    """
    An instruction ends at }, and contains:
    
    fn:<name>(<args>, .. ) rest}

    or 

    <stuff>}
    """

    if (g_trace_parser):
        print "parse_instruction() begins: "

    skip_whitespace(input_stream)

    # This is an instruction node, so .. 
    if (input_stream.peek() == '"'):
        if (g_trace_parser):
            print "parse_instruction(): quoted literal detected"

        # Consume that last peek'd character...
        input_stream.next()
        skip_whitespace(input_stream)
        # Quoted string. So we know .. 
        result = TreeNode(TreeNode.InstructionType)
        container = TreeNode(TreeNode.ContainerType)
        echars = set([ '"' ])
        old_report = input_stream.report() # In case we need it later..
        parse_document(input_stream, container, echars)
        if (input_stream.next() != '"'):
            raise utils.Failure("Literal instruction @ %s never ends"%(old_report))

        skip_whitespace(input_stream)
        c = input_stream.next();
        if (c != '}'):
            # Rats
            raise utils.Failure("Syntax Error - no end to literal instruction @ %s"%
                                (input_stream.report()))
        # Otherwise ..
        result.set_val(container)
        node.append_child(result)
        if (g_trace_parser):
            print "parse_instruction(): ends"

        return

    # Otherwise .. 
    dummy = TreeNode(TreeNode.ContainerType)
    result = TreeNode(TreeNode.InstructionType)

    echars = set([ ':', '}' ])
    parse_document(input_stream, dummy, echars)
    c = input_stream.next()
    if (c == ':'):
        # Must have been a literal.
        str = flatten_literal_node(dummy)

        # A directive of some kind.
        if (str == "fn"):
            # Gotcha! Function must also be a literal.
            echars = set([ '(', '}' ])
            fn_name = parse_literal(input_stream, echars)
            params = [ ]
            rest = TreeNode(TreeNode.ContainerType)
            c2 = input_stream.next()
            if (c2 == '('):
                # We have parameters!
                while True:
                    echars = set([ ',', ')' ] )
                    param_node = TreeNode(TreeNode.ContainerType)
                    parse_param(input_stream, param_node, echars)
                    params.append(param_node)
                    c = input_stream.next()
                    if (c != ','):
                        break
            # End of params.
            echars = set(['}'])
            parse_document(input_stream, rest, echars)
            result.set_fn(fn_name, params, rest)
        else:
            raise utils.Failure("Invalid designator in value: %s at %s"%(str, input_stream.report()))
    else:
        # This was the end of the directive.
        result.set_val(dummy)
        # .. BUT! We haven't pushed '}' back so ..
        input_stream.push_back(c)

                        
    # In many ways, it is worth adding our result to the parse tree.
    if (g_trace_parser):
        print "parse_instruction(): ends (2)"
    node.append_child(result)



                 
def subst_str(in_str, xml_doc, env):
    """
    Substitute ``${...}`` in in_str with the appropriate objects - if XML
    doesn't match, try an environment variable.

    Unescape ``$${...}`` in case someone actually wanted `${...}`` in the
    output.
    
    Functions can be called with:
    ${fn:NAME(ARGS) REST}

    name can be: ifeq(query,value) - in which case REST is substituted.
                 val(query)  - just looks up query.

    """

    top_node = TreeNode(TreeNode.ContainerType)
    stream = PushbackInputStream(in_str)
    parse_document(stream, top_node, None)

    output_list = []
    top_node.eval(xml_doc, env, output_list)
    
    return "".join(output_list)



def subst_str_old(in_str, xml_doc, env):
    """
    Substitute ``${...}`` in in_str with the appropriate objects - if XML
    doesn't match, try an environment variable.

    Unescape ``$${...}`` in case someone actually wanted `${...}`` in the
    output.
    
    Functions can be called with:
    ${fn:NAME(ARGS) REST}

    name can be: ifeq(query,value) - in which case REST is substituted.
                 val(query)  - just looks up query.

    """
    
    the_re = re.compile(r"(\$)?\$\{([^\}]+)\}")
    fn_re = re.compile(r'fn:([^()]+)\(([^\)]+)\)(.*)$')

    out_str = in_str
    interm = the_re.split(in_str)

    for i in range(0, len(interm)/3):
        base_idx = 3*i
        
        k = interm[base_idx+2]
        

        if (interm[base_idx+1] == '$'):
            interm[base_idx + 2] = "${%s}"%k
        else:
            # Let's see if this is a function?
            m = fn_re.match(k)
            if (m is not None):
                # It's a function
                g = m.groups()
                fn_name = g[0]
                param_str = g[1]
                rest = g[2]

                params = param_str.split(",")
                proc_params = []
                for p in params:
                    trimmed = p.strip()
                    if (trimmed[0] == "\""):
                        trimmed = trimmed[1:-1]
                    proc_params.append(trimmed)

                if (fn_name == "ifeq" and len(proc_params) == 2):
                    result = query_string_value(xml_doc, env, proc_params[0])
                    #print "rest=%s"%rest
                    #print "groups = %s"%(" ".join(m.groups()))
                    if (proc_params[1] is not None and
                        result is not None):
                        if (result.strip() == proc_params[1]):
                            v = rest
                        else:
                            v = ""
                    else:
                        v = ""
                elif (fn_name == "val" and len(proc_params) == 1):
                    v = query_string_value(xml_doc, env, proc_params[0])

            else:
                v = query_string_value(xml_doc, env,k)
    
            if (v is None):
                interm[base_idx+2] = ""
            else:
                interm[base_idx+2] = v

        interm[base_idx+1] = ""
        

    return "".join(interm)

def subst_file(in_file, out_file, xml_doc, env):
    
    f_in = open(in_file, "r")
    f_out = open(out_file, "w")
    
    contents = f_in.read()
    out = subst_str(contents, xml_doc, env)
    f_out.write(out)
    
#    lines = ""
#    while True:
#        in_line = f_in.readline()
#        if (in_line == ""):
#            break
#        
#        out_line = subst_str(in_line, xml_doc, env)
#        f_out.write(out_line)


    

# End File.

    
