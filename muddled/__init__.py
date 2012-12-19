"""
Muddle - A VCS-agnostic package build and configuration management system
"""

# We import the vcs module here so that *its* __init__ can load each
# individual VCS, and they can register the VCS with version_control.py
import muddled.vcs
