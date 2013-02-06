#! /usr/bin/env python

import os
import sys
import imp
from importlib import import_module

def report():

	# Import everything we can find
	all_modules = {}
	for dirpath, dirnames, filenames in os.walk('muddled'):
		for filename in filenames:
			name, ext = os.path.splitext(filename)
			if ext == '.py':
				# We assert that the __init__.py files in muddle do not
				# contain anything we need to report.
				if name == '__init__':
					continue
				filepath = os.path.join(dirpath, filename)
				print 'XXX', dirpath, dirpath.split(os.sep)
				parts = dirpath.split(os.sep)
				module_name = '.'.join(parts) + '.' + name

				print '---', module_name
				with open(filepath) as fd:
					module = imp.load_module(module_name, fd, filepath, ('.py', 'r', imp.PY_SOURCE))
				all_modules[module_name] = module

				print module_name, module
				#import_module(module_name)
				#print module_name, ':', dir(module_name)



	#import_module('muddled')
	#print dir('muddled')


if __name__ == '__main__':
	report()

# vim: set tabstop=8 softtabstop=4 shiftwidth=4 expandtab:
