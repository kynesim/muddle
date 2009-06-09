"""
An environment store holds a set of instructions for manipulating
a set of environment variables
"""

import utils
import copy

class EnvType:
    """
    Types of environment variable

    SimpleValue         is just a value (the default)
    Path                colon-separated path
    """
    
    SimpleValue = 0
    Path = 1


class EnvMode:
    """
    Ways of manipulating environment variables
    """

    # Append to the variable
    Append = 0

    # Replace the variable
    Replace = 1

    # Prepend to the variable
    Prepend = 2

class EnvLanguage:
    """
    Languages in which we can generate setenv files
    """

    # Sh
    Sh = 0

    # Python
    Python = 1

    # The actual value for this variable
    Value = 2


class EnvExpr:
    """
    An environment variable expression. This allows us to symbolically
    represent things like catenating one variable value with another.
    """
    
    # A string
    StringType = 0
    
    # A variable reference
    RefType = 1

    # A catenation
    CatType = 2

    def __init__(self, type, val = None):
        self.type = type
        if (val is None):
            self.values = [ ]
        else:
            self.values = [ val ]

    def append_str(self, str):
        self.append(EnvExpr(EnvExpr.StringType, str))

    def append_ref(self, ref):
        self.append(EnvExpr(EnvExpr.RefType, ref))

    def append(self, other):
        self.values.append(other)

    def to_sh(self, doQuote):
        if (self.type == EnvExpr.StringType):
            return "".join(map(lambda x: utils.maybe_shell_quote(x, doQuote), self.values))
        elif (self.type == EnvExpr.RefType):
            return "".join(map(lambda x: utils.maybe_shell_quote("$%s"%x, doQuote), self.values))
        else:
            return "".join(map(lambda x: x.to_sh(doQuote), self.values))

    def to_py(self, env_var):
        """
        Return a list of expressions you can put into a 
        literal python list after "".join() to write the
        correct value for this variable
        """
        r_list = [ ]
        if (self.type == EnvExpr.StringType):
            r_list.extend(map(lambda x: "\"%s\""%(x), self.values))
        elif (self.type == EnvExpr.RefType):
            r_list.extend(map(lambda x: "%s[\"%s\"]"%(env_var,x), self.values))
        else:
            for i in self.values:
                r_list.extend(i.to_py(env_var))

        return r_list


    def to_value(self, env):
        r_list = [ ]
        if (self.type == EnvExpr.StringType):
            r_list.extend(self.values)
        elif (self.type == EnvExpr.RefType):
            r_list.extend(map(lambda x: env.get(x, ""), self.values))
        else:
            r_list.extend(map(lambda x: x.to_value(env), self.values))

        return "".join(r_list)
        

class EnvBuilder:
    """
    Represents a way of building an environment variable
    value from a series of instructions
    
    prepend_list List of paths to prepend to the value
    retain_old_value  Retain the old value?
    append_list  List of things to append to the old value.;
    env_type     Type of this environment variable
    erased       Have we been erased?

    All paths are now of EnvExprs.

    """

    def __init__(self):
        self.prepend_list = [ ]
        self.retain_old_value = True
        self.append_list = [ ]
        self.env_type = EnvType.SimpleValue
        self.erased = False

    def set_type(self, type):
        self.env_type = type

    def copy(self):
        return copy.deepcopy(self)
        

    def merge(self, other):
        """
        Merge another environment builder with this one.
        """
        if other.erased:
            self.erase()
            return

        self.env_type = other.env_type
        self.retain_old_value = other.retain_old_value

        for prep in other.prepend_list:
            self.prepend(prep)

        for app in other.append_list:
            self.append(app)


    def erase(self):
        self.prepend_list = [ ]
        self.retain_old_value = True
        self.append_list = [ ]
        self.erased = True


    def prepend(self, val):
        return self.prepend_expr(EnvExpr(EnvExpr.StringType, val))


    def prepend_expr(self, val):
        """
        Prepend val to this environment value
        """
        self.erased = False
        if (self.env_type == EnvType.SimpleValue):
            self.prepend_list.insert(0, val)
        else:
            self.ensure_prepended_expr(val)


    def append(self, val):
        return self.append_expr(EnvExpr(EnvExpr.StringType, val))

    def append_expr(self,val):
        """
        Append val to this environment value
        """
        self.erased = False
        if (self.env_type == EnvType.SimpleValue):
            self.append_list.append(val)
        else:
            self.ensure_appended_expr(val)

    def ensure_prepended(self, val):
        return self.ensure_prepended_expr(EnvExpr(EnvExpr.StringType, val))

    def ensure_prepended_expr(self, val):
        """
        Make sure val is part of the value or prepend it.
        What you usually want for paths

        @return True if we added the value, False if it was
           already there.
        """
        self.erased = False
        for i in range(0, len(self.prepend_list)):
            if val == self.prepend_list[i]:
                del self.prepend_list[i:i+1]
                break

        # Wasn't there .. (or isn't now, anyway)
        self.prepend_list.insert(0, val)
        return True

    def ensure_appended(self, val):
        return self.ensure_appended_expr(EnvExpr(EnvExpr.StringType, val))

    def ensure_appended_expr(self, val):
        """
        Make sure val is appended to the value or append it.
        
        @return True if we added the value, False if it was
          already there
          """
        self.erased = False
        for i in range(0, len(self.append_list)):
            if val == self.append_list[i]:
                del self.append_list[i:i+1]
                break
        
        # Wasn't there.. (or isn't now, anyway)
        self.append_list.append(val)
        return True

    def set(self, val):
        return self.set_expr(EnvExpr(EnvExpr.StringType, val))

    def set_expr(self, val):
        """
        Set val to this environment value
        """
        self.prepend_list = [ val ]
        self.append_list = [ ]
        self.retain_old_value = False#
        self.erased = False

        
    def get(self, inOldValue, language):
        if language == EnvLanguage.Value:
            return self.get_value(inOldValue)
        elif language == EnvLanguage.Sh:
            return self.get_sh(inOldValue, True)
        else:
            return self.get_py(inOldValue)


    def get_value(self, inOldValue, env = { }):

        if self.erased:
            return None

        val_array = [ ]
        atLeastOne = False

        val_array.extend(map(lambda x: x.to_value(env), self.prepend_list))
        if (inOldValue is not None) and self.retain_old_value: 
            val_array.append(inOldValue)
        val_array.extend(map(lambda x: x.to_value(env), self.append_list))

        return ":".join(val_array)
    

    def get_py(self, inOldValue, env_name = "os.environ"):
        """
        Like get, but in python syntax

        @param[in] inOldValue A python expression which gives the old value.
        """

        if self.erased:
            return None

        newValue = [ ]
        atLeastOne = False

        newValue.append("\":\".join([ ")

        for i in self.prepend_list:
            if atLeastOne:
                newValue.append(", ")
            newValue.append(",".join(i.to_py(env_name)))
            atLeastOne = True

        if self.retain_old_value and (not (inOldValue is None)):
            if atLeastOne:
                newValue.append(", ")
            newValue.append(inOldValue)
            atLeastOne = True

        for i in self.append_list:
            if atLeastOne:
                newValue.append(", ")
            newValue.append(",".join(i.to_py(env_name)))
            atLeastOne = True

        return "".join(newValue)


    def get_sh(self, inOldValue, doQuote):
        """
        The old value of this variable was inOldValue;
        what is its new value?
        
        @param[in] doQuote if doQuote is true, we'll use
          shell quoting. We never quote inOldValue since 
          it's probably $PATH or something else that shouldn't
          be quoted.
        """

        if self.erased:
            return None

        newValue = [ ]
        atLeastOne = False
        for i in self.prepend_list:
            if atLeastOne:
                newValue.append(":")
            newValue.append(i.to_sh(doQuote))
            atLeastOne = True

        if self.retain_old_value and (not (inOldValue is None)):
            if atLeastOne:
                newValue.append(":")
            newValue.append(inOldValue)

        for i in self.append_list:
            if atLeastOne:
                newValue.append(":")
            newValue.append(i.to_sh(doQuote))
            atLeastOne = True

        return "".join(newValue)


class Store:
    """
    Maintains a store of environment variables and allows us to apply them
    to any given environment dictionary
    """
    
    def __init__(self):
        self.vars = { }

    def copy(self):
        # We need to do quite a deep copy here ..
        new_store = Store()

        for (k,v) in self.vars.items():
            new_store.vars[k] = v.copy()
            
        return new_store

    def builder_for_name(self, name):
        """
        Return a builder for the given variable, inventing one if
        there isn't already one
        """
        if (name in self.vars):
            return self.vars[name]
        else:
            builder = EnvBuilder()
            self.vars[name] = builder
            return builder

    def set_type(self, name, type):
        b = self.builder_for_name(name)
        b.set_type(type)


    def merge(self, other):
        """
        Merge another environment store into this one. Instructions from
        the new store will override or augment those in self
        """
        for (k,v) in other.vars:
            self.builder_for_name(k).merge(v)


    def append_expr(self, name, expr):
        """
        Append an EnvExpr to a variable
        """
        self.builder_for_name(name).append_expr(expr)

    def prepend_expr(self, name, expr):
        """
        Prepend an EnvExpr to a variable
        """
        self.builder_for_name(name).prepend_expr(expr)

    def set_expr(self, name, expr):
        """
        Set a variable to an EnvExpr
        """
        self.builder_for_name(name).set_expr(expr)

    def append(self, name, value):
        """
        Append a value to a variable
        """
        self.builder_for_name(name).append(value)

    def prepend(self, name, value):
        """
        Prepend a value to a variable
        """
        self.builder_for_name(name).prepend(value)

    def set(self, name, value):
        """
        Set a value for a name
        """
        self.builder_for_name(name).set(value)


    def erase(self, name):
        """
        Explicitly erase a variable
        """
        self.builder_for_name(name).erase()
        

    def op(self, name, mode, value):
        """
        Perform mode (an EnvMode) on name with value
        """
    
        var = self.builder_for_name(name)

        if mode == EnvMode.Append:
            var.append(value)
        elif mode == EnvMode.Replace:
            var.set(value)
        elif mode == EnvMode.Prepend:
            var.prepend(value)

    def get_setvars_script(self, name, lang):
        """
        Write a setvars script in the chosen language
        """
        if (lang == EnvLanguage.Sh):
            return self.get_setvars_sh(name)
        elif (lang == EnvLanguage.Python):
            return self.get_setvars_py(name)
        else:
            raise utils.Error("Can't write a setvars script for language %s"%lang)


    def apply(self, in_env):
        """
        Apply the modifications here to the environment in dict
        """
        for (k,v) in self.vars.items():
            if (v.erased):
                if (k in in_env):
                    del in_env[k]
            else:
                old_value = in_env.get(k, None)
                in_env[k] = v.get_value(old_value)

            
    def get_setvars_py(self, name):
        """
        Write some statements that will set the relevant environment
        variables in python
        
        @return a string containing the relevant python
        """
            
        retHdr =  "# setenv code for %s\n"%name +  \
            "# %s\n"%(utils.iso_time());

        retText = [ retHdr ]

        retText.append("\n")

        for (k,v) in self.vars.items():
            if (v.erased):
                retText.append("if (\"%s\" in os.environ):\n"%k +
                               "  del os.environ[\"%s\"]\n"%k)
            else:
                retText.append("os.environ[\"%s\"]="%k)
                retText.append(v.get("os.environ[%s]"%k, EnvLanuage.Python))
                retText.append("\n")
            
        retText.append("\n # End code\n")
        
        return "".join(retText)


    def get_setvars_sh(self, name):
        """
        Write a setvars script

        Returns a string containing the script.
        """
        retHdr = "# setenv script for %s\n"%name + \
            "# %s\n"%(utils.iso_time());

        retText = [ retHdr ]

        retText.append("\n")

        for (k,v) in self.vars.items():
            if (v.erased):
                retText.append("unset %s\n"%k)
            else:
                retText.append("export %s="%k)
                retText.append(v.get("$%s"%k, EnvLanguage.Sh))
                retText.append("\n")
            
        retText.append("\n # End file.\n")
        
        return "".join(retText)

def append_expr(var, str):
    """
    Create an environment expression consisting of the given string appended to the
    given variable name
    """
    top = EnvExpr(EnvExpr.CatType)
    top.append_ref(var)
    top.append_str(str)
    return top
                   


    
# End file.
