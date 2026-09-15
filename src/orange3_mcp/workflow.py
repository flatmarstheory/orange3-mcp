"""In-memory Orange3 workflow model plus .ows (scheme XML) read/write.

The .ows format implemented here follows Orange3's scheme serialization
(scheme version "2.0"): a <scheme> root with <nodes>, <links>,
<annotations> and <node_properties> (using format="literal", i.e. a
Python literal - safe to parse with ast.literal_eval, no pickling).
Workflows produced here should be opened in Orange Canvas to confirm
widget-specific property defaults look right.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from xml.dom import minidom
from xml.etree import ElementTree as ET

from .widgets import find_widget


class WorkflowError(ValueError):
    pass


@dataclass
class Node:
    id: str
    widget_id: str
    qualified_name: str
    title: str
    x: float
    y: float
    properties: dict = field(default_factory=dict)


@dataclass
class Link:
    id: str
    source_node_id: str
    source_channel: str
    sink_node_id: str
    sink_channel: str
    enabled: bool = True


class Workflow:
    def __init__(self, title: str = "Untitled", description: str = ""):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.description = description
        self.nodes: dict[str, Node] = {}
        self.links: dict[str, Link] = {}
        self.path: str | None = None
        self._node_seq = 0
        self._link_seq = 0

    # -- node/link management ------------------------------------------------

    def add_node(self, widget_identifier: str, title: str | None = None,
                 x: float = 0, y: float = 0, properties: dict | None = None) -> Node:
        spec = find_widget(widget_identifier)
        if spec is not None:
            qualified_name = spec.qualified_name
            default_title = spec.name
        else:
            # allow direct qualified names for widgets not in the catalog
            if "." not in widget_identifier:
                raise WorkflowError(
                    f"Unknown widget '{widget_identifier}'. Use list_widgets to see known "
                    f"widgets, or pass a fully qualified widget class name."
                )
            qualified_name = widget_identifier
            default_title = widget_identifier.rsplit(".", 1)[-1]

        node_id = str(self._node_seq)
        self._node_seq += 1
        node = Node(
            id=node_id,
            widget_id=spec.id if spec else qualified_name,
            qualified_name=qualified_name,
            title=title or default_title,
            x=x,
            y=y,
            properties=dict(properties or {}),
        )
        self.nodes[node_id] = node
        return node

    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            raise WorkflowError(f"No such node id: {node_id}")
        del self.nodes[node_id]
        for link_id in [lid for lid, l in self.links.items()
                        if l.source_node_id == node_id or l.sink_node_id == node_id]:
            del self.links[link_id]

    def connect(self, source_node_id: str, source_channel: str,
                sink_node_id: str, sink_channel: str) -> Link:
        source = self.nodes.get(source_node_id)
        sink = self.nodes.get(sink_node_id)
        if source is None:
            raise WorkflowError(f"No such source node id: {source_node_id}")
        if sink is None:
            raise WorkflowError(f"No such sink node id: {sink_node_id}")

        self._validate_channel(source, "outputs", source_channel)
        self._validate_channel(sink, "inputs", sink_channel)

        link_id = str(self._link_seq)
        self._link_seq += 1
        link = Link(
            id=link_id,
            source_node_id=source_node_id,
            source_channel=source_channel,
            sink_node_id=sink_node_id,
            sink_channel=sink_channel,
        )
        self.links[link_id] = link
        return link

    def _validate_channel(self, node: Node, direction: str, channel: str) -> None:
        spec = find_widget(node.qualified_name)
        if spec is None:
            return  # widget not in catalog; can't validate, allow it
        allowed = spec.outputs if direction == "outputs" else spec.inputs
        if allowed and channel not in allowed:
            raise WorkflowError(
                f"Widget '{spec.name}' has no {direction[:-1]} channel '{channel}'. "
                f"Available: {', '.join(allowed)}"
            )

    def remove_link(self, link_id: str) -> None:
        if link_id not in self.links:
            raise WorkflowError(f"No such link id: {link_id}")
        del self.links[link_id]

    def set_node_properties(self, node_id: str, properties: dict) -> Node:
        node = self.nodes.get(node_id)
        if node is None:
            raise WorkflowError(f"No such node id: {node_id}")
        node.properties.update(properties)
        return node

    def update_node(self, node_id: str, title: str | None = None,
                     x: float | None = None, y: float | None = None) -> Node:
        node = self.nodes.get(node_id)
        if node is None:
            raise WorkflowError(f"No such node id: {node_id}")
        if title is not None:
            node.title = title
        if x is not None:
            node.x = x
        if y is not None:
            node.y = y
        return node

    def describe(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "path": self.path,
            "nodes": [
                {
                    "id": n.id,
                    "widget": n.widget_id,
                    "qualified_name": n.qualified_name,
                    "title": n.title,
                    "position": [n.x, n.y],
                    "properties": n.properties,
                }
                for n in self.nodes.values()
            ],
            "links": [
                {
                    "id": l.id,
                    "source_node_id": l.source_node_id,
                    "source_channel": l.source_channel,
                    "sink_node_id": l.sink_node_id,
                    "sink_channel": l.sink_channel,
                    "enabled": l.enabled,
                }
                for l in self.links.values()
            ],
        }

    # -- .ows (scheme XML) serialization -------------------------------------

    def to_xml(self) -> str:
        scheme = ET.Element("scheme", {
            "version": "2.0",
            "title": self.title,
            "description": self.description,
        })

        nodes_el = ET.SubElement(scheme, "nodes")
        for n in self.nodes.values():
            ET.SubElement(nodes_el, "node", {
                "id": n.id,
                "name": n.title,
                "qualified_name": n.qualified_name,
                "project_name": "Orange3",
                "version": "",
                "title": n.title,
                "position": f"({n.x}, {n.y})",
            })

        links_el = ET.SubElement(scheme, "links")
        for l in self.links.values():
            ET.SubElement(links_el, "link", {
                "id": l.id,
                "source_node_id": l.source_node_id,
                "sink_node_id": l.sink_node_id,
                "source_channel": l.source_channel,
                "sink_channel": l.sink_channel,
                "enabled": "true" if l.enabled else "false",
            })

        ET.SubElement(scheme, "annotations")

        props_el = ET.SubElement(scheme, "node_properties")
        for n in self.nodes.values():
            if not n.properties:
                continue
            prop_el = ET.SubElement(props_el, "properties", {
                "node_id": n.id,
                "format": "literal",
            })
            prop_el.text = repr(n.properties)

        ET.SubElement(scheme, "session_state")

        rough = ET.tostring(scheme, encoding="unicode")
        pretty = minidom.parseString(rough).toprettyxml(indent="  ")
        # drop blank lines minidom likes to insert
        lines = [line for line in pretty.splitlines() if line.strip()]
        return "\n".join(lines) + "\n"

    def save(self, path: str) -> str:
        xml = self.to_xml()
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        self.path = path
        return path

    @classmethod
    def from_xml(cls, xml_text: str, path: str | None = None) -> "Workflow":
        root = ET.fromstring(xml_text)
        wf = cls(
            title=root.get("title", "Untitled"),
            description=root.get("description", ""),
        )
        wf.path = path

        id_map: dict[str, str] = {}
        max_node_id = -1
        nodes_el = root.find("nodes")
        if nodes_el is not None:
            for node_el in nodes_el.findall("node"):
                orig_id = node_el.get("id")
                position = node_el.get("position", "(0, 0)")
                x, y = _parse_position(position)
                node = wf.add_node(
                    widget_identifier=node_el.get("qualified_name"),
                    title=node_el.get("title") or node_el.get("name"),
                    x=x,
                    y=y,
                )
                id_map[orig_id] = node.id
                try:
                    max_node_id = max(max_node_id, int(orig_id))
                except ValueError:
                    pass
        wf._node_seq = max_node_id + 1

        links_el = root.find("links")
        max_link_id = -1
        if links_el is not None:
            for link_el in links_el.findall("link"):
                orig_id = link_el.get("id")
                src = id_map.get(link_el.get("source_node_id"))
                dst = id_map.get(link_el.get("sink_node_id"))
                if src is None or dst is None:
                    continue
                link = wf.connect(
                    source_node_id=src,
                    source_channel=link_el.get("source_channel"),
                    sink_node_id=dst,
                    sink_channel=link_el.get("sink_channel"),
                )
                link.enabled = link_el.get("enabled", "true") == "true"
                try:
                    max_link_id = max(max_link_id, int(orig_id))
                except ValueError:
                    pass
        wf._link_seq = max_link_id + 1

        props_el = root.find("node_properties")
        if props_el is not None:
            import ast
            for prop_el in props_el.findall("properties"):
                orig_node_id = prop_el.get("node_id")
                new_id = id_map.get(orig_node_id)
                if new_id is None or not prop_el.text:
                    continue
                fmt = prop_el.get("format", "literal")
                if fmt == "literal":
                    try:
                        parsed = ast.literal_eval(prop_el.text)
                        if isinstance(parsed, dict):
                            wf.nodes[new_id].properties = parsed
                    except (ValueError, SyntaxError):
                        pass
                # pickle/bytes formats are intentionally not decoded here

        return wf

    @classmethod
    def load(cls, path: str) -> "Workflow":
        with open(path, "r", encoding="utf-8") as f:
            xml_text = f.read()
        return cls.from_xml(xml_text, path=path)

    # -- full-fidelity state (for persisting in-progress sessions) ----------

    def to_state(self) -> dict:
        """Serialize full session state (including id and sequence counters),
        for persisting in-progress workflows across restarts. Distinct from
        the Orange .ows scheme format produced by to_xml()."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "path": self.path,
            "node_seq": self._node_seq,
            "link_seq": self._link_seq,
            "nodes": [
                {
                    "id": n.id,
                    "widget_id": n.widget_id,
                    "qualified_name": n.qualified_name,
                    "title": n.title,
                    "x": n.x,
                    "y": n.y,
                    "properties": n.properties,
                }
                for n in self.nodes.values()
            ],
            "links": [
                {
                    "id": l.id,
                    "source_node_id": l.source_node_id,
                    "source_channel": l.source_channel,
                    "sink_node_id": l.sink_node_id,
                    "sink_channel": l.sink_channel,
                    "enabled": l.enabled,
                }
                for l in self.links.values()
            ],
        }

    @classmethod
    def from_state(cls, data: dict) -> "Workflow":
        wf = cls(title=data.get("title", "Untitled"), description=data.get("description", ""))
        wf.id = data["id"]
        wf.path = data.get("path")
        for n in data.get("nodes", []):
            wf.nodes[n["id"]] = Node(
                id=n["id"],
                widget_id=n["widget_id"],
                qualified_name=n["qualified_name"],
                title=n["title"],
                x=n["x"],
                y=n["y"],
                properties=n.get("properties", {}),
            )
        for l in data.get("links", []):
            wf.links[l["id"]] = Link(
                id=l["id"],
                source_node_id=l["source_node_id"],
                source_channel=l["source_channel"],
                sink_node_id=l["sink_node_id"],
                sink_channel=l["sink_channel"],
                enabled=l.get("enabled", True),
            )
        wf._node_seq = data.get("node_seq", len(wf.nodes))
        wf._link_seq = data.get("link_seq", len(wf.links))
        return wf


def _parse_position(position: str) -> tuple[float, float]:
    try:
        cleaned = position.strip().strip("()")
        x_str, y_str = cleaned.split(",")
        return float(x_str.strip()), float(y_str.strip())
    except (ValueError, AttributeError):
        return 0.0, 0.0
