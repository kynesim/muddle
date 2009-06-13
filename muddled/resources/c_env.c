/* Muddle boilerplate for accessing environments from C
 *
 */

#include <stdlib.h>
#include <stdio.h>
#include <string.h>

#ifndef ${prefix}_UNKNOWN_ENV

/* Given a handle and a string containing the name of an environment variable,
 *  return a malloc()'d buffer containing the value of the variable
 *
 *  strdup(getenv(x)) is a good definition here if you want to access
 *  the external environment.
 */
#define ${ucprefix}_UNKNOWN_ENV_VALUE(handle, x) (NULL)
#endif

char *${prefix}_cat(char *a, char *b)
{
  if (!a) 
    {
      return b;
    }
  else if (!b)
    {
      return a;
    }
  else
    {
      size_t len_a = strlen(a);
      size_t len_b = strlen(b);
      size_t overall_len = len_a + len_b + 1;
      char *rv;

      rv = malloc(overall_len * sizeof(char));
      if (!rv) { return NULL; }
      memcpy(rv, a, len_a);
      memcpy(&rv[len_a], b, len_b);
      rv[len_a+len_b] = '\0';
      
      return rv;
    }
}

char *${prefix}_lookup(const char *name, void *handle)
{
  ${body_impl}
}

/* End file */

