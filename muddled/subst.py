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

def query_string_value(xml_doc, k):
    """
    Given a string-valued query, work out what the result was
    """
    v = None
    result_node = None

    if (k[0] == '/'):
        # An XML query
        if xml_doc is not None:
            result_node = query_result(split_query(k), xml_doc)
        if (result_node is not None):
            v = get_text_in_xml_node(result_node)
    else:
        # An environment variable
        v = env[k]
    return v

def subst_str(in_str, xml_doc, env):
    """
    Substitute ``${...}`` in in_str with the appropriate objects - if XML
    doesn't match, try an environment variable.

    Unescape ``$${...}`` in case someone actually wanted `${...}`` in the
    output.
    
    Functions can be called with:
    ${fn:NAME(ARGS) REST}

    name can be: eq(query,value) - in which case REST is substituted.
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

                if (fn_name == "eq" and len(proc_params) == 2):
                    result = query_string_value(xml_doc, proc_params[0])
                    if (result.strip() == proc_params[1]):
                        v = rest
                    else:
                        v = ""
                elif (fn_name == "val" and len(proc_params) == 1):
                    v = query_string_value(xml_doc, proc_params[0])

            else:
                v = query_string_value(xml_doc, k)
    
            if (v is None):
                interm[base_idx+2] = ""
            else:
                interm[base_idx+2] = v

        interm[base_idx+1] = ""
        

    return "".join(interm)

def subst_file(in_file, out_file, xml_doc, env):
    
    f_in = open(in_file, "r")
    f_out = open(out_file, "w")
    
    while True:
        in_line = f_in.readline()
        if (in_line == ""):
            break
        
        out_line = subst_str(in_line, xml_doc, env)
        f_out.write(out_line)


    

# End File.

    
