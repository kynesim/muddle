#!/usr/bin/env python

"""
This is a graph generator for visualising the relationships between
muddle repositories.

Run this script from somewhere within a muddle tree;
provide a list of goal labels on the command-line.

For example:
	visualise-dependencies.py  package:*{linux}/postinstalled
	visualise-dependencies.py  deployment:ramdisk/deployed deployment:sdcard/deployed deployment:system/deployed deployment:tools/deployed

Output is in `dot` format; you probably want to install the `graphviz`
package if you haven't already.
"""

import os,sys,re
try:
    from muddled.utils import GiveUp
except ImportError:
    # try one dir up.
    this_file = os.path.abspath(__file__)
    this_dir = os.path.split(this_file)[0]
    parent_dir = os.path.split(this_dir)[0]
    sys.path.insert(0, parent_dir)
    from muddled.utils import GiveUp
    # This still fails? add the directory containing muddled to your PYTHONPATH

from muddled.cmdline import find_and_load
from muddled.depend import Label

def format_nodename(node):
	""" Sanitises a nodename so it won't choke graphviz.
		Input should be a string or something with a __str__ method
		(e.g. a muddle Label). """
	xnode = str(node)[:]
	xnode = re.sub(r'[\[\]():/{}\-.]', '_', xnode)
	xnode = re.sub(r'\*', '__star__', xnode)
	return xnode


class Node:
	""" A node in the graph is identified by its muddle Label.
		It has a displayname, defaulting to the label string,
		and a dotname (tweaked so it won't choke dot).

		Newly-created Nodes are always added to the global dict.
	"""

	all_nodes = {} # dict: key=rawname val=Node
	@staticmethod 
	def get(name):
		return Node.all_nodes[str(name)]

	def __init__(self, name, isGoal=False, extras=None):
		self.rawname = str(name)
		self.displayname = self.rawname # may be changed later
		self.dotname = format_nodename(self.rawname)
		self.extras = extras
		self.isAptGet = False
		self.auxNames = set()
		self.isGoal = isGoal
		assert self.rawname not in Node.all_nodes
		Node.all_nodes[self.rawname] = self
	def todot(self):
		""" dot-friendly representation """
		if self.extras:
			extras = ', %s'%self.extras
		else:
			extras = ''
		return '%s [label="%s" %s]' % (self.dotname, self.displayname, extras)
	def __str__(self):
		return 'Node <raw=%s label="%s" %s>' %(self.displayname, self.dotname, self.extras)


class Edge:
	""" Representation of an edge.
		Edges are directed with a 'from' and a 'to', and may have
		a label. They are always added to the global dict.

		It is possible that edges will be conflated together by
		a later reduction process.
	"""

	all_edges = {} # dict: key=tuple(From,To) val=Edge
	@staticmethod 
	def get(fro,to):
		return Edge.all_edges[Edge.hashkey_static(fro,to)]

	@staticmethod
	def hashkey_static(fro,to):
		return (fro.rawname, to.rawname)

	def hashkey(self):
		return Edge.hashkey_static(self.nodeFrom, self.nodeTo)

	def __init__(self, nodeFrom, nodeTo, label = None):
		self.nodeFrom = nodeFrom
		self.nodeTo = nodeTo
		self.label = label
		Edge.all_edges[self.hashkey()] = self
	def todot(self, noLabels = False):
		""" dot-friendly representation """
		label = self.label
		if not label or noLabels:
			label = ''
		return '%s -> %s %s'%(self.nodeFrom.dotname, self.nodeTo.dotname, label)
	def __str__(self):
		return 'Edge <%s -> %s, label="%s">' %(self.nodeFrom.displayname, self.nodeTo.displayname, self.label)

def do_deps(gbuilder, goal):
	""" Main dependency walker. Recurses depth-first. """
	# deps := `muddle depend user-short goal` !
	#print 'Would do %s'%goal
	label = Label.from_string(goal)
	rules = gbuilder.invocation.ruleset.rules_for_target(label)

	goalnode = Node.get(goal)
	assert goalnode is not None

	for rule in rules:
		target = rule.target
		builder = None
		if rule.obj:
			builder = rule.obj.__class__.__name__

		# AptGetBuilders aren't very interesting, condense them.
		if builder == 'AptGetBuilder':
			goalnode.displayname = '%s{%s}\\n(AptGetBuilder)' % (rule.obj.name, rule.obj.role)
			goalnode.extras = 'shape=oval'
			goalnode.isAptGet = True
			continue

		rawdeps = []
		for label in rule.deps:
			if not label.system:
				rawdeps.append(label)
		rawdeps.sort()

		for dep in rawdeps:
			newnode = False
			try:
				depnode = Node.get(dep)
			except KeyError:
				depnode = Node(dep)
				newnode = True

			label = None
			if builder:
					label = '[label="%s"]'%builder

			try:
				existEdge = Edge.get(depnode,goalnode)
			except KeyError:
				Edge(depnode, goalnode, label)

			if newnode:
					do_deps(gbuilder, str(dep))

def process(goals):
	if not len(goals):
		raise GiveUp('No goals given - specify one or more labels on the command line')

	if goals[0] in ('-h', '-help', '--help'):
		print __doc__
		sys.exit(0)

	# Do we care about labelling the edges?
	hideEdgeLabels = True
	# Do we care about nodes touching an AptGetBuilder?
	omitAptGetNodes = True

	## ... find a build tree
	original_dir = os.getcwd()
	gbuilder = find_and_load(original_dir, muddle_binary=None)
	# Don't bother determining muddle_binary: our invocation of find_and_load
	# doesn't make use of it. (Tibs writes: it's only needed for when
	# running makefiles, for when they use $(MUDDLE).)

	for g in goals:
		Node(g, isGoal=True, extras="shape=parallelogram")
		# color=green fillcolor=green style=filled...?

	for g in goals:
		do_deps(gbuilder, g)

	# Nodes created by AptGetBuilders aren't very interesting.
	if omitAptGetNodes:
		for k,e in Edge.all_edges.items():
			if e.nodeFrom.isAptGet:
				del Edge.all_edges[k]
		for k,n in Node.all_nodes.items():
			if n.isAptGet:
				del Node.all_nodes[k]

	# If we have A/preconfig -> A/configured -> A/built -> A/installed 
	# [ -> A/preinstalled], we can condense them into one.
	reductio = { 
			'preconfig' : 'configured',
			'configured' : 'built',
			'built' : 'installed',
			'installed' : 'postinstalled',
	}
	while True:
		madeChange = False
		for k,e in Edge.all_edges.items():
			if e.nodeTo.isGoal:
				continue # Don't conflate explicit goal nodes

			nFrom = e.nodeFrom.rawname.rsplit('/',1)
			nTo = e.nodeTo.rawname.rsplit('/',1)
			if not nFrom[0] == nTo[0]:
				continue # labels are not the same, no chance of reduction

			# TODO: This logic is horrible!
			reducable = False
			try:
				if reductio[nFrom[1]] == nTo[1]:
					reducable = True
			except KeyError: pass
			for aux in e.nodeFrom.auxNames:
				try:
					auxFrom = aux.rsplit('/',1)
					assert auxFrom[0] == nFrom[0]
					if reductio[auxFrom[1]] == nTo[1]:
						reducable = True
						break
				except KeyError: pass

			if not reducable: continue

			# Are there any other edges to nodeTo? If so, we can't reduce.
			count = 0
			for ee in Edge.all_edges.values():
				if ee.nodeTo.rawname == e.nodeTo.rawname:
					count=count+1
			if count > 1:
				# NOTE: This code path is untested...
				continue

			# OK, it's safe to conflate the two.
			#print "WOULD REDUCE: %s -> %s" %(e.nodeFrom.rawname,e.nodeTo.rawname)
			oldname = e.nodeFrom.displayname
			if e.nodeTo.displayname.find('+') != -1:
				substr = e.nodeTo.displayname.rsplit('/')[1]
				e.nodeFrom.displayname = "%s+%s" %(e.nodeFrom.displayname, substr)
			else:
				e.nodeFrom.displayname = "%s+%s" %(e.nodeFrom.displayname, nTo[1])
			#print "RENAME: %s => %s"%(oldname, e.nodeFrom.displayname)

			e.nodeFrom.auxNames.add(e.nodeTo.rawname)
			e.nodeFrom.auxNames |= e.nodeTo.auxNames

			# Now kill all nodes B->C, replace with A'->C:
			for kk,ee in Edge.all_edges.items():
				if ee.nodeFrom == e.nodeTo:
					Edge(e.nodeFrom, ee.nodeTo, e.label)
					del Edge.all_edges[kk]
			# Finally, kill off edge A->B and node B themselves:
			del Edge.all_edges[k]
			del Node.all_nodes[e.nodeTo.rawname]

			madeChange = True
			break

		if not madeChange: 
			break
		# else loop forever

	# Now tidy up the conflated display names:
	for n in Node.all_nodes.values():
		if len(n.auxNames)>0:
			tmp = n.displayname.rsplit('/',1)
			n.displayname = '%s/\\n%s'%(tmp[0],tmp[1])

	print 'digraph muddle {'

	print "\n# Nodes"
	print "node [shape=box];"
	for n in Node.all_nodes.values():
		print n.todot()

	print "\n# Edges"
	print "edge [fontsize=9, labelangle=90, decorate=true];"
	for e in Edge.all_edges.values():
		print e.todot(hideEdgeLabels)

	print '}'

if __name__ == '__main__':
	try:
		process(sys.argv[1:])
	except GiveUp as e:
		print >> sys.stderr, e
		sys.exit(1)
