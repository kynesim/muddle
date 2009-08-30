"""
Write a setvars script:

    $(MUDDLE_TARGET_LOCATION)/bin/setvars

containing PATH and LD_LIBRARY_PATH modifications
for MUDDLE_TARGET_LOCATION, plus any environment
variables set by the environment associated with this
package, which you can get using the get_env_store()
function here
"""

import muddled
import muddled.pkg as pkg
import muddled.env_store
import muddled.depend as depend
import muddled.utils as utils
import os
import muddled.subst as subst

