"""
A utility module which allows you to read XML files and
then query them as XPath-like paths. 

Call readXml() to read an XML file and return an xmlConfig
object which you can then pass queries like:

/elem1/elem2/elem3

This is essentially a (restricted) XPath query with an
implicit ::text() appended.

This file is hereby placed in the public domain - 
 Richard Watts, <rrw@kynesim.co.uk> 2009-10-23.

(as this is about the third time I have had to write
 it and I am getting quite bored .. )
"""

import xml.dom
import xml.dom.minidom

class ConfigError(Exception): 
    pass

class Config:
    """
    Represents a configuration file
    """

    def __init__(self, in_file):
        """
        Parse an XML config file into a local representation
        """
        self.doc = xml.dom.minidom.parse(in_file)

    def text(self, node):
        """
        Collect all the text in an XML node
        """
        if (node is None): 
            return None

        elems = []
        for n in node.childNodes:
            if n.nodeType == node.TEXT_NODE:
                elems.append(n.data)

        # Strip any trailing CRs
        result = "".join(elems)
        if (len(result) > 0 and result[-1] == '\n'):
            result = result[:-1]
        
        return result

    def query(self, keys):
        """
        Perform a query on this list of keys and return 
        the node which matches (and which you can then
        call text() on)
        """
        result = self.doc
        
        for i in keys:
            next = None
            
            for j in result.childNodes:
                if (j.nodeType == j.ELEMENT_NODE) and (j.nodeName == i):
                    next = j
                    break
            
            # End of the line :-(
            if (next is None):
                return None
            else:
                result = next

        return result

    def split_key(self, instring):
        """
        Take a series of components and split them by '/'.
        """
        s = instring.split('/')
        if (s[0] == ''):
            # Absolute path - zap the initial empty string
            s = s[1:]

        return s

    def exists(self, key):
        """
        Given a key, decide if its value exists in the
        configuration file.
        """
        node = self.query(self.split_key(key))
        if (node is None):
            return False
        else:
            return True


    def query_string(self, key):
        """
        Given an XPath-like expression /a/b/c , return the text
        in the final node. If the node doesn't exist, throw.
        """
        val =  self.text(self.query(self.split_key(key)))
        if (val is None):
            raise ConfigError("Key %s doesn't exist"%(key))
        return val

    def query_int(self,key):
        """
        Given an XPath-like expression a/b/c.., return the
        text in the final node interpreted as an integer.
        
        If the node doesn't exist, throw.
        """
        return int(self.query_string(key))

    def query_bool(self,key):
        """
        Given an XPath-like expression, return a boolean
        value based on a text value of 'true' (True) 
        or anything else (False)

        If the node doesn't exist, throw.
        """
        txt = self.query_string(key)
        if (txt is None):
            raise ConfigError("Key %s doesn't exist"%(key))
        elif (txt == "true"):
            return True
        else:
            return False

    def query_list(self, key):
        """
        Given an XPath-like expression, return a list containing
        the text from all values key0..keyN that actually
        exist
        """
        i = 0
        result = [ ]
        while True:
            effective_key = "%s%d"%(key,i)
            if (self.exists(effective_key)):
                result.append(self.query_string(effective_key))
                i = i + 1
            else:
                break
            
        return result

    def query_hashlist(self, key, subkeys):
        """
        Given an XPath-like expression and a list of subkeys,
        take the list denoted by key and return a list of hashes
        pointing the subkeys at their values.
        """
        i = 0
        result = [ ]
        while True:
            effective_key = "%s%d"%(key,i)
            if (self.exists(effective_key)):
                # Build a dictionary
                dict = { }
                for k in subkeys:
                    inner_e = "%s/%s"%(effective_key, k)
                    if (self.exists(inner_e)):
                        dict[k] = self.query_string(inner_e)
                result.append(dict)
                i = i + 1
            else:
                break

        return result
        


# End file.

        
    
                
    

       
  
