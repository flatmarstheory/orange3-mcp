"""Regression tests: every tool invocation can run in a fresh process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET
from concurrent.futures import ThreadPoolExecutor


ROOT = Path(__file__).resolve().parents[1]
CALL = """
import json, sys
from orange3_mcp import server
request = json.load(sys.stdin)
result = getattr(server, request['tool'])(**request['args'])
print(json.dumps(result))
"""


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = dict(os.environ, ORANGE3_MCP_DATA_DIR=self.temp.name,
                        PYTHONPATH=str(ROOT / "src"))

    def call(self, tool, **args):
        result = subprocess.run(
            [sys.executable, "-c", CALL],
            input=json.dumps({"tool": tool, "args": args}),
            text=True, capture_output=True, env=self.env, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_workflow_survives_fresh_processes(self):
        wf = self.call("create_workflow", title="Iris")['id']
        self.assertEqual(self.call("list_workflows")[0]['id'], wf)
        file = self.call("add_node", workflow_id=wf, widget="file")['node_id']
        table = self.call("add_node", workflow_id=wf, widget="Data Table")['node_id']
        link = self.call("connect_nodes", workflow_id=wf,
                         source_node_id=file, source_channel="Data",
                         sink_node_id=table, sink_channel="Data")['link_id']
        self.call("set_node_properties", workflow_id=wf, node_id=file,
                  properties={"example": [1, "iris", True]})
        state = self.call("describe_workflow", workflow_id=wf)
        self.assertEqual(state['nodes'][0]['properties']['example'], [1, "iris", True])
        self.assertEqual(state['links'][0]['id'], link)
        output = str(Path(self.temp.name) / "iris.ows")
        self.call("save_workflow", workflow_id=wf, path=output)
        self.assertEqual(self.call("describe_workflow", workflow_id=wf)['path'], output)
        loaded = self.call("load_workflow", path=output)
        self.assertEqual(len(loaded['nodes']), 2)
        self.call("remove_link", workflow_id=wf, link_id=link)
        self.call("remove_node", workflow_id=wf, node_id=table)
        replacement = self.call("add_node", workflow_id=wf, widget="Data Table")
        self.assertNotEqual(replacement['node_id'], table)
        self.assertEqual(self.call("describe_workflow", workflow_id=wf)['links'], [])

    def test_concurrent_processes_do_not_lose_edits(self):
        wf = self.call("create_workflow")['id']
        with ThreadPoolExecutor(max_workers=4) as pool:
            nodes = list(pool.map(lambda _: self.call(
                "add_node", workflow_id=wf, widget="file"), range(8)))
        self.assertEqual(len({node['node_id'] for node in nodes}), 8)
        self.assertEqual(len(self.call("describe_workflow", workflow_id=wf)['nodes']), 8)

    def test_export_delivers_file_content_without_container_access(self):
        wf = self.call("create_workflow", title="Iris & <flowers> — α")['id']
        self.call("add_node", workflow_id=wf, widget="file")
        exported = self.call("export_workflow", workflow_id=wf)
        self.assertEqual(exported['filename'], f"workflow-{wf}.ows")
        self.assertEqual(exported['encoding'], 'utf-8')
        root = ET.fromstring(exported['content'])
        self.assertEqual(root.attrib['title'], "Iris & <flowers> — α")
        self.assertEqual(len(root.findall('nodes/node')), 1)
        self.assertIsNone(self.call("describe_workflow", workflow_id=wf)['path'])
        output = Path(self.temp.name) / 'iris.ows'
        saved = self.call("save_workflow", workflow_id=wf, path=str(output))
        self.assertEqual(saved['content'], output.read_text(encoding='utf-8'))
        self.assertEqual(saved['filename'], 'iris.ows')
        output.unlink()  # Simulate losing the container-local exported file.
        recovered = self.call("export_workflow", workflow_id=wf)
        self.assertEqual(recovered['content'], saved['content'])

    def test_corrupt_state_is_not_overwritten(self):
        self.call("create_workflow")
        path = Path(self.temp.name) / "state" / "mcp_workflows.json"
        for corrupt in ('{broken', '[]'):
            path.write_text(corrupt, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-c", CALL], text=True, capture_output=True,
                input=json.dumps({'tool': 'create_workflow', 'args': {}}),
                env=self.env, timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Could not read workflow state", result.stderr)
            self.assertEqual(path.read_text(encoding="utf-8"), corrupt)


if __name__ == "__main__":
    unittest.main()
