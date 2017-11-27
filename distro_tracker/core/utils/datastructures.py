# Copyright 2013 The Distro Tracker Developers
# See the COPYRIGHT file at the top-level directory of this distribution and
# at https://deb.li/DTAuthors
#
# This file is part of Distro Tracker. It is subject to the license terms
# in the LICENSE file found in the top-level directory of this
# distribution and at https://deb.li/DTLicense. No part of Distro Tracker,
# including this file, may be copied, modified, propagated, or distributed
# except according to the terms contained in the LICENSE file.
"""Utility data structures for Distro Tracker."""
from collections import deque
from copy import deepcopy


class InvalidDAGException(Exception):
    pass


class DAG(object):
    """
    A class representing a Directed Acyclic Graph.

    Allows clients to build up a DAG where the nodes of the graph are any type
    of object which can be placed in a dictionary.
    """
    class Node(object):
        def __init__(self, id, original):
            self.id = id

            self.original = original

        def __hash__(self):
            return self.id.__hash__()

        def __eq__(self, other):
            return self.id == other.id

    def __init__(self):
        """
        Instantiates an empty DAG.
        """
        #: Maps original node objects to their internal representation
        self.nodes_map = {}
        #: Represents the graph structure of the DAG as an adjacency list
        self.graph = {}
        #: Holds the in-degree of each node to allow constant-time lookups
        #: instead of iterating through all nodes in the graph.
        self.in_degree = {}
        #: Represents the last id given to an inserted node.
        self._last_id = 0

    def _next_id(self):
        """
        A private helper method which returns the next ID which can be given to
        a node being inserted in the DAG.
        """
        # NOTE: Not thread safe.
        self._last_id += 1
        return self._last_id

    @property
    def all_nodes(self):
        """
        Returns a list of all nodes in the DAG.
        """
        return list(self.nodes_map.keys())

    def add_node(self, node):
        """
        Adds a new node to the graph.
        """
        dag_node = DAG.Node(self._next_id(), node)
        self.nodes_map[node] = dag_node
        self.in_degree[dag_node.id] = 0
        self.graph[dag_node.id] = []

    def replace_node(self, original_node, replacement_node):
        """
        Replaces a node already present in the graph ``original_node`` by a new
        object.
        The internal representation of the DAG remains the same, except the new
        object now takes the place of the original one.
        """
        node = self.nodes_map[original_node]
        del self.nodes_map[original_node]
        node.original = replacement_node
        self.nodes_map[replacement_node] = node

    def remove_node(self, node):
        """
        Removes a given node from the graph.

        The ``node`` parameter can be either the internal Node type or the
        node as the client sees them.
        """
        if not isinstance(node, DAG.Node):
            # Try to map it to a DAG Node
            node = self.nodes_map[node]

        node_to_remove = node

        # Update the in degrees of its dependents
        for node in self.graph[node_to_remove.id]:
            self.in_degree[node] -= 1
        # Finally remove it:
        # From node mappings
        del self.nodes_map[node_to_remove.original]
        # From the graph
        for dependent_nodes in self.graph.values():
            if node_to_remove.id in dependent_nodes:
                dependent_nodes.remove(node_to_remove.id)
        del self.graph[node_to_remove.id]
        # And the in-degree counter
        del self.in_degree[node_to_remove.id]

    def add_edge(self, node1, node2):
        """
        Adds an edge between two nodes.

        :raises InvalidDAGException: If the edge would introduce a cycle in the
            graph structure.
        """
        # Check for a cycle
        if node1 in self.nodes_reachable_from(node2):
            raise InvalidDAGException(
                "Cannot add edge since it would create a cycle in the graph.")

        # When everything is ok, create the new link
        node1 = self.nodes_map[node1]
        node2 = self.nodes_map[node2]

        # If an edge already exists, adding it again does nothing
        if node2.id not in self.graph[node1.id]:
            self.graph[node1.id].append(node2.id)
            self.in_degree[node2.id] += 1

    def _get_node_with_no_dependencies(self):
        """
        Returns an internal node which has no dependencies, i.e. that has an
        in-degree of 0.
        If there are multiple such nodes, it is not defined which one of them
        them is returned.
        """
        for node in self.nodes_map.values():
            if self.in_degree[node.id] == 0:
                return node
        # If no node with a zero in-degree can be found, the graph is not a DAG
        # NOTE: If edges are always added using the `add_edge` method, this
        #       will never happen since the cycle would be caught at that point
        raise InvalidDAGException("The graph contains a cycle.")

    def dependent_nodes(self, node):
        """
        Returns all nodes which are directly dependent on the given node, i.e.
        returns a set of all nodes N where there exists an edge(node, N) in the
        DAG.
        """
        node = self.nodes_map[node]
        id_to_node_map = {
            node.id: node
            for node in self.nodes_map.values()
        }
        return [
            id_to_node_map[dependent_node_id].original
            for dependent_node_id in self.graph[node.id]
        ]

    def topsort_nodes(self):
        """
        Generator which returns DAG nodes in toplogical sort order.
        """
        # Save the original nodes structure
        original_nodes_map = deepcopy(self.nodes_map)
        original_in_degree = deepcopy(self.in_degree)
        original_graph = deepcopy(self.graph)
        while len(self.nodes_map):
            # Find a node with a 0 in degree
            node = self._get_node_with_no_dependencies()
            # We yield instances of the original node added to the graph, not
            # DAG.Node as that is what clients expect.
            yield node.original
            # Remove this node from the graph and update the in-degrees
            self.remove_node(node)
        # Restore the original nodes structure so that a top sort is not a
        # destructive operation
        self.nodes_map = original_nodes_map
        self.in_degree = original_in_degree
        self.graph = original_graph

    def nodes_reachable_from(self, node):
        """
        Returns a set of all nodes reachable from the given node.
        """
        node = self.nodes_map[node]

        # Implemented in terms of a BFS to avoid recursion
        queue = deque([node])
        reachable_nodes = []
        visited = set()
        visited.add(node.id)

        id_to_node_map = {
            node.id: node
            for node in self.nodes_map.values()
        }

        while len(queue):
            current_node = queue.popleft()
            for successor_id in self.graph[current_node.id]:
                if successor_id not in visited:
                    visited.add(successor_id)
                    successor = id_to_node_map[successor_id]
                    queue.append(successor)
                    reachable_nodes.append(successor.original)

        return set(reachable_nodes)
