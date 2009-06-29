"""
An environment store holds a set of instructions for manipulating
a set of environment variables

Sometimes we need to generate these for C. This is particularly evil
because C neither has good environment variable lookup nor good 
string handling support. 

See the boilerplate in resources/c_env.c for how we handle this. 
It's not pretty .. 

"""

import utils
import copy
import subst

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

    # C
    C = 3

class EnvExpr:
    """
    An environment variable expression. This allows us to symbolically
    represent things like catenating one variable value with another.
    """
    
    # A string
    StringType = "String"
    
    # A variable reference
    RefType = "Ref"

    # A catenation
    CatType = "Cat"

    def __init__(self, type, val = None):
        self.type = type
        self.values = [ ]
        self.append(val)

    def append_str(self, str):
        self.append(EnvExpr(EnvExpr.StringType, str))

    def append_ref(self, ref):
        self.append(EnvExpr(EnvExpr.RefType, ref))

    def append(self, other):
        # None just means 'don't append anything'
        if other is None:
            return

        if ((self.type == EnvExpr.StringType or 
             self.type == EnvExpr.RefType) and 
            type(other) == type(str())):
            self.values.append(other)
        elif (self.type == EnvExpr.CatType and
              (isinstance(other, EnvExpr))):
            self.values.append(other)
        else:
            raise utils.Error("Attempt to append" + 
                              " %s (type %s) to an EnvExpr of type %s"%(other, 
                                                                        type(other), 
                                                                        self.type))

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

    def to_c(self, var, prefix):
        """
        Returns a list of strings you can join together to make C code
        for constructing the value of this expression
        
        @param var  The name of the C variable we're creating.
        @param prefix The name of the prefix to prepend to function calls.
        """

        str_list = [ ]

        if (self.type == EnvExpr.StringType):
            for v in self.values:
                str_list.append(" %s = %s_cat(%s, \"%s\");\n"%(var,
                                                              prefix,
                                                              var,
                                                              utils.c_escape(v)))
        elif (self.type == EnvExpr.RefType):
            for v in self.values:
                str_list.append(
                    " %s = %s_cat(%s, %s_lookup(\"%s\", handle));\n"%(var, 
                                                                     prefix,
                                                                     var, 
                                                                     prefix, 
                                                                     utils.c_escape(v)))
        else:
            for v in self.values:
                str_list.extend(v.to_c(var, prefix))
                        
                                
        return str_list


    def to_value(self, env):
        r_list = [ ]
        if (self.type == EnvExpr.StringType):
            r_list.extend(self.values)
        elif (self.type == EnvExpr.RefType):
            r_list.extend(map(lambda x: env.get(x, ""), self.values))
        else:
            r_list.extend(map(lambda x: x.to_value(env), self.values))

        return "".join(r_list)

    def augment_dependency_set(self, a_set):
        """
        Add the environment variables this expression depends on to 
        a_set
        """
        if (self.type == EnvExpr.RefType):
            for var in self.values:
                a_set.add(var)
        elif (self.type == EnvExpr.CatType):
            for var in self.values:
                var.augment_dependency_set(a_set)
        # Otherwise we just don't care.

    def same_as(self, other):
        """
        Decide if two EnvExprs will produce the same value on output.
        """

        # None and empty are the same for all intents and purposes.
        p = self
        q = other

        if (p is not None) and len(p.values) == 0:
            p = None
        if (q is not None) and len(q.values) == 0:
            q = None

        if (p is None) and (q is None):
            return True
        if (p is None) or (q is None):
            return False
        
        if (p.type != q.type):
            return False
        
        # Values must match. Exactly - I don't want to collapse lists
        #  at this point .. 
        if (len(p.values) != len(q.values)):
            return False

        if (p.type == EnvExpr.RefType or p.type == EnvExpr.StringType):
            for i in range(0, len(p.values)):
                if p.values[i] != q.values[i]:
                    return False
        else:
            for i in range(0, len(p.values)):
                if not p.values[i].same_as(q.values[i]):
                    return False

        # If we get there, they're the same, as far as we can tell.
        return True
            
        
        
       


class EnvBuilder:
    """
    Represents a way of building an environment variable
    value from a series of instructions
    
    prepend_list List of paths to prepend to the value
    retain_old_value  Retain the old value?
    append_list  List of things to append to the old value.;
    env_type     Type of this environment variable
    erased       Have we been erased?
    external     This variable is defined externally.

    All paths are now of EnvExprs.

    """

    def __init__(self, external = False):
        self.prepend_list = [ ]
        self.retain_old_value = True
        self.append_list = [ ]
        self.env_type = EnvType.SimpleValue
        self.erased = False
        self.external = external

    def set_type(self, type):
        self.env_type = type

    def copy(self):
        return copy.deepcopy(self)
        

    def __str__(self):
        return self.get_sh("$VAR", True)

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
            self.ensure_prepended_expr(prep)

        for app in other.append_list:
            self.ensure_appended_expr(app)

    def empty(self):
        """
        Is this environment builder empty? i.e. does it have an empty
        value?
        """
        if (self.erased or self.external):
            return True
        if (len(self.prepend_list) == 0 and
            len(self.append_list) == 0):
            return True
        
        return False

    def erase(self):
        self.prepend_list = [ ]
        self.retain_old_value = True
        self.append_list = [ ]
        self.erased = True
        self.external = False

    def prepend(self, val):
        return self.prepend_expr(EnvExpr(EnvExpr.StringType, val))


    def prepend_expr(self, val):
        """
        Prepend val to this environment value
        """
        self.erased = False
        self.external = False
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
        self.external = False
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
        self.external = False
        for i in range(0, len(self.prepend_list)):
            if val.same_as(self.prepend_list[i]):
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
        self.external = False
        for i in range(0, len(self.append_list)):
            if val.same_as(self.append_list[i]):
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
        self.retain_old_value = False
        self.erased = False
        self.external = False

    def set_external(self, external = True):
        self.external = external
        
    def get(self, inOldValue, language):
        if language == EnvLanguage.Value:
            return self.get_value(inOldValue)
        elif language == EnvLanguage.Sh:
            return self.get_sh(inOldValue, True)
        elif (language == EnvLanguage.C):
            return self.get_c(True)
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
    

    def get_c(self, var, prefix, variable_name):
        """
        Return a string containing C code which leaves the value of this
        builder in 'var'.

        The string does _not_ declare var, - that's the caller's job.

        @param variable_name is the variable name whose value we're processing - it's
         needed so we can refer to its previous value.
        """
        if self.erased:
            return None

        str_array = [ ]
        for i in self.prepend_list:
            str_array.extend(i.to_c(var, prefix))

        if self.retain_old_value and (variable_name is not None):
            str_array.append(" %s = %s_cat(%s, %s_lookup(\"%s\", handle));\n"%(var, 
                                                                             prefix,
                                                                             var,
                                                                             prefix,
                                                                             variable_name))
        for i in self.append_list:
            str_array.extend(i.to_c(var, prefix))

        return "".join(str_array)

        

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


    def dependencies(self):
        """
        Return a set of the environment variables that this value
        depends on 
        """
        if self.external:
            return set()

        result_set = set()
        for p in self.prepend_list:
            p.augment_dependency_set(result_set)

        for p in self.append_list:
            p.augment_dependency_set(result_set)
            
        return result_set


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

    def empty(self, name):
        """
        Return True iff name has a builder with an empty value,
        False otherwise.

        (i.e. if it's likely to actually generate an environment
        variable setting)
        """
        if (name in self.vars):
            b = self.vars[name]
            return b.empty()
        else:
            return True

    
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

    def set_external(self, name):
        b = self.builder_for_name(name)
        b.set_external(name)


    def merge(self, other):
        """
        Merge another environment store into this one. Instructions from
        the new store will override or augment those in self
        """
        for (k,v) in other.vars.items():
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

    def ensure_appended(self, name, value):
        return self.builder_for_name(name).ensure_appended(value)

    def ensure_prepended(self, name, value):
        return self.builder_for_name(name).ensure_prepended(value)

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

    def external(self, name):
        self.builder_for_name(name).set_external(True)


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

    def get_setvars_script(self, builder,  name, lang):
        """
        Write a setvars script in the chosen language
        """
        if (lang == EnvLanguage.Sh):
            return self.get_setvars_sh(name)
        elif (lang == EnvLanguage.Python):
            return self.get_setvars_py(name)
        elif (lang == EnvLanguage.C):
            return self.get_setvars_c(builder, name)
        else:
            raise utils.Error("Can't write a setvars script for language %s"%lang)


    def apply(self, in_env):
        """
        Apply the modifications here to the environment in dict
        """

        sorted_items = self.dependency_sort()
        for (k,v) in sorted_items:
            if (v.external):
                continue

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

        sorted_items = self.dependency_sort()
        for (k,v) in sorted_items:
            if (v.external):
                continue

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

        sorted_items = self.dependency_sort()
        for (k,v) in sorted_items:
            if (v.external):
                continue

            if (v.erased):
                retText.append("unset %s\n"%k)
            else:
                retText.append("export %s="%k)
                retText.append(v.get("$%s"%k, EnvLanguage.Sh))
                retText.append("\n")
            
        retText.append("\n # End file.\n")
        
        return "".join(retText)

    def get_c_subst_var(self, prefix):
        """
        Returns the block of C to use as a substitute for body_impl in 
        resources/c_env.c
        """
        
        sorted_items = self.dependency_sort()
        rlist = [ ]
        doneOne = False
        for (k,v) in sorted_items:
            if (doneOne):
                rlist.append("else ")
            else:
                doneOne = True

            rlist.append("if (!strcmp(\"%s\", name))\n"%utils.c_escape(k) + 
                         "{ \n" + 
                         " char *rv = NULL;\n")
            rlist.extend(v.get_c("rv", prefix, k))
            rlist.append("}\n")
    
        if (doneOne):
            rlist.append("else\n")
        
        rlist.append("return %s_UNKNOWN_ENV_VALUE(handle, name);\n"%(prefix.upper()))
        return "".join(rlist)

    def get_setvars_c(self, builder, prefix):
        dict = { }
        dict["prefix"] = prefix
        dict["ucprefix"] = prefix.upper()
        dict["body_impl"] = self.get_c_subst_var(prefix)
        
        rsrc = builder.resource_body("c_env.c")
        return subst.subst_str(rsrc, None, dict)


    def dependency_sort(self):
        """
        Sort self.vars.items() in as close to dependency order as you
        can.
        """
        
        # deps maps environment variables to a set of the variables they 
        # (directly) depend on.
        deps = { }
        remain = set()

        for (k,v) in self.vars.items():
            deps[k] = v.dependencies()
            remain.add(k)

        done = set()
        out_list = [ ]
        
        while len(remain) > 0:
            # Take out anything we can
            take_out = set()
            new_remain = set()
            did_something = False

            for k in remain:
                can_issue = True

                for cur_dep in deps[k]:
                    if cur_dep not in done:
                        # Curses: a dependency not in done.
                        can_issue = False
                        break

                if (can_issue):
                    out_list.append(k)
                    done.add(k)
                    did_something = True
                else:
                    # Can't issue
                    new_remain.add(k)

            remain = new_remain
            # If we didn't do anything, we've reached the end
            # of the line.
            if (not did_something):
                raise utils.Failure("Cannot produce a consistent environment ordering:\n" + 
                                    "Issued: %s\n"%(" ".join(map(str, out_list))) + 
                                    "Remaain: %s\n"%utils.print_string_set(remain) + 
                                    "Deps: %s\n"%(print_deps(deps)))

        # Form the value list ..
        rv = [ ]
        for k in out_list:
            rv.append((k, self.vars[k]))

        return rv
                                    
            
def print_deps(deps):
    """
    Given a dictionary mapping environment variable names to sets of
    dependencies, return a string representing the map
    """
    result_str = [ ]

    for (k,v) in deps:
        result_str.append("%s = { "%k)
        for dep in v:
            result_str.append(" %s"%dep)
        result_str.append("}\n")

    return "".join(result_str)


def append_expr(var, str):
    """
    Create an environment expression consisting of the given string appended to the
    given variable name
    """
    top = EnvExpr(EnvExpr.CatType)
    top.append_ref(var)
    top.append_str(str)
    return top

def add_install_dir_env(env, var_name):
    """
    Add an install directory, whose base is held in var_name, to PATH,
    LD_LIBRARY_PATH, etc.
    """
    
    env.set_type("LD_LIBRARY_PATH", EnvType.Path)
    env.set_type("PATH", EnvType.Path)
    env.set_type("PKG_CONFIG_PATH", EnvType.Path)
    env.prepend_expr("LD_LIBRARY_PATH", 
                     append_expr(var_name, "/lib"))
    env.prepend_expr("PKG_CONFIG_PATH", 
                    append_expr(var_name, "/lib/pkgconfig"))
    env.prepend_expr("PATH", 
                     append_expr(var_name, "/bin"))


    
# End file.
