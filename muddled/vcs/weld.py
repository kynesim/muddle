"""
Muddle support for weld

A weld is expressed in muddle as a VCS which does nothing. 

The effect is that one can write a build description within a weld and
 then use muddle to build the weld once the weld is checked out with
 git; this follows the weld idiom that one should use git commands
 to manipulate a weld.
"""

import os
import muddled.utils as utils
from muddled.version_control import register_vcs, VersionControlSystem

class Weld(VersionControlSystem):
    """
    Provides version control operations for a weld -
    this is basically a no-op, and it turns out that that is
    what the base class provides, so .. 
    """
    
    def __init__(self):
        pass
    

register_vcs("weld", Weld(), __doc__)

# End file.
