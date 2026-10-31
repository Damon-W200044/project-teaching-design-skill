#!/usr/bin/env python3
"""Compare DOCX table merges/grids against the authoritative template profile."""
import argparse
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{" + NS["w"] + "}"


def signatures(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    result = []
    for t in root.findall("w:body/w:tbl", NS):
        grid = [c.get(W + "w") for c in t.findall("w:tblGrid/w:gridCol", NS)]
        rows = []
        for r in t.findall("w:tr", NS):
            cells = []
            for c in r.findall("w:tc", NS):
                span = c.find("w:tcPr/w:gridSpan", NS)
                merge = c.find("w:tcPr/w:vMerge", NS)
                cells.append((span.get(W + "val", "1") if span is not None else "1", merge.get(W + "val", "continue") if merge is not None else None))
            rows.append(cells)
        result.append({"grid": grid, "rows": rows})
    return result


def expected_table(source, rule, count):
    t = source[rule["template_table"]]
    start, stop = rule["repeat_rows"]
    return {"grid": t["grid"], "rows": t["rows"][:rule["prefix_rows"]] + t["rows"][start:stop]*count}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("template", type=Path)
    p.add_argument("docx", type=Path)
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--task-counts", type=int, nargs="+", required=True)
    a = p.parse_args()
    profile = json.loads(a.profile.read_text())
    src, actual = signatures(a.template), signatures(a.docx)
    expected = [expected_table(src, profile["overview"], len(a.task_counts))]
    expected.extend(expected_table(src, profile["activity"], n) for n in a.task_counts)
    if profile.get("final_footer_signature") and len(expected) > 1:
        expected[-1]["rows"].append([tuple(x) for x in profile["final_footer_signature"]])
    errors = []
    if len(actual) != len(expected):
        errors.append(f"表格数量：实际{len(actual)}，预计{len(expected)}")
    for i, (x, y) in enumerate(zip(actual, expected)):
        if x["grid"] != y["grid"]:
            errors.append(f"表{i}网格列宽变化")
        if len(x["rows"]) != len(y["rows"]):
            errors.append(f"表{i}行数：实际{len(x['rows'])}，预计{len(y['rows'])}")
        for j, (row_x, row_y) in enumerate(zip(x["rows"], y["rows"])):
            if row_x != row_y:
                errors.append(f"表{i}行{j}gridSpan/vMerge与模板不一致")
    print(json.dumps({"passed": not errors, "tables": len(actual), "rows": [len(t["rows"]) for t in actual], "errors": errors, "note": "只检查表格结构，不替代内容及渲染检查"}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
