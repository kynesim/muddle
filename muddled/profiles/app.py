"""
The application profile. 

An application profile ties together a role with a group of environment
variables and a tarfile deployment.

You add an application profile to your project by invoking 
app = app.AppProfile(builder, role, target_path, deployment)
builder.assume_profile(app)

"""

import muddled
import muddled.pkgs

class AppProfile(Profile):
    """
    AppProfile embodies an application profile for a given role.

    The role installation directory is <root>/install/<role>.

    We define:

    MUDDLE_RUN_FROM   The root of where this code will be run from.

    in addition to the usual basic environment provided by muddle.
    """
    
    def __init__(self, role, target_path, deployment):
        Profile.__init__(self, "AppProfile", role)
        self.target_path = target_path
        self.deployment = deployment
        self.matching_label = Label(utils.LabelKind.Deployment,
                                    "*",
                                    role,
                                    "*")
                                    

    def use(self, builder):
        pass

    def assume(self, builder):
        # Add an environment that applies our target path.
        store = builder.invocation.get_environment_for(self.matching_label)
        store.set("MUDDLE_RUN_FROM", self.target_path)

# End file.


        
        
    
