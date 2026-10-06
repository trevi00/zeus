from codex_harness.adapters.knowledge import extract_python


def test_import_and_call_topology_survives_line_movements_and_property_variants(tmp_path):
    (tmp_path / "helper.py").write_text("def helper():\n    return 1\n")
    source = "import helper\n\ndef local():\n    return 1\n\ndef use():\n    return local()\n"
    source += "\nclass A:\n    @property\n    def value(self):\n        return 1\n"
    source += "    @value.setter\n    def value(self, value):\n        pass\n"
    path = tmp_path / "main.py"
    path.write_text(source)
    before = extract_python(str(tmp_path))
    assert len({node["id"] for node in before["nodes"]}) == len(before["nodes"])
    assert any(edge[2] == "imports" for edge in before["edges"])
    assert any(edge[2] == "may_call" for edge in before["edges"])
    path.write_text("\n\n" + source)
    after = extract_python(str(tmp_path))
    assert {node["id"] for node in before["nodes"]} == {node["id"] for node in after["nodes"]}
