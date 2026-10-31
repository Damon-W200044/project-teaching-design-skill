#!/usr/bin/env python3
"""Audit shared design data. Structural checks are not semantic or visual QA."""
import argparse
import json
from collections import Counter
from pathlib import Path

CONTAINS = {"各类包含", "条件包含", "步骤包含", "内容包含", "常见问题包含", "原因包含", "关键点包含", "科目包含", "形式包含", "要求包含"}
RELATIONS = CONTAINS | {"组成", "构成", "组成/构成", "组成／构成", "是一种", "具有属性", "具有特征", "定义", "并列", "是前提", "支持"}


def audit(data, expected_class=None, expected_home=None, core=None, home_ratio=2):
    errors, warnings = [], []
    nodes, resources = data.get("nodes", {}), data.get("resources", {})
    totals = {"课上": 0, "课下": 0}
    task_count = 0
    acts = data.get("activities", [])
    goal_ids = [a.get("goal") for a in acts]
    if data.get("project_goals") != goal_ids or len(set(goal_ids)) != len(acts) or None in goal_ids:
        errors.append("总目标须与各活动唯一最高阶目标一一对应，不额外列项目根节点")
    for nid, n in nodes.items():
        if n.get("type") not in {"DK", "PK", "FC", "CS"}:
            errors.append(f"节点{nid}知识类型无效")
        if not n.get("label"):
            errors.append(f"节点{nid}缺名称")
        if n.get("level") not in {None, "", "记忆", "理解", "运用"}:
            errors.append(f"节点{nid}学习水平无效")
    for a in data.get("activities", []):
        aid, place = a.get("id", "?"), a.get("place")
        gid = a.get("goal")
        if gid == aid and not a.get("framework_goal_explicitly_confirmed"):
            errors.append(f"活动{aid}直接把方法框架作为目标，须核对具体知识和成果依据")
        if gid not in data.get("membership", {}).get(aid, []):
            errors.append(f"活动{aid}目标不在该活动知识组块中")
        if not a.get("goal_evidence"):
            errors.append(f"活动{aid}目标缺学习成果依据")
        if place not in totals:
            errors.append(f"活动{aid}地点须为课上或课下")
        minutes = a.get("minutes", 0)
        if not isinstance(minutes, (int, float)) or minutes <= 0:
            errors.append(f"活动{aid}时长无效")
            minutes = 0
        if place in totals:
            totals[place] += minutes
        tasks = a.get("tasks", [])
        if not tasks:
            errors.append(f"活动{aid}没有任务")
        if sum(t.get("mins", 0) for t in tasks) != minutes:
            errors.append(f"活动{aid}任务时长之和不等于活动时长")
        for j, t in enumerate(tasks, 1):
            task_count += 1
            prefix = f"活动{aid}任务{j}"
            if t.get("place", place) != place:
                errors.append(f"{prefix}地点与所属活动不一致；请拆分活动或按地点分别汇总")
            if t.get("mins", 0) <= 0:
                errors.append(f"{prefix}时长无效")
            if len(t.get("interaction_phase_labels", [])) != len(t.get("interaction", [])):
                errors.append(f"{prefix}缺编号行动环节名称")
            if not t.get("question") or not t.get("expected_answer"):
                errors.append(f"{prefix}缺具体提问或预期回答")
            if t.get("question_phase", 0) not in range(1, len(t.get("interaction", [])) + 1):
                errors.append(f"{prefix}问答未计入已有环节")
            if sum(s[0] for s in t.get("interaction", [])) != t.get("mins"):
                errors.append(f"{prefix}交互分段不等于任务时长")
            if "小组讨论" in t.get("method", ""):
                text = "".join(str(s[1]) for s in t.get("interaction", []))
                if "讨论" not in text or not any(w in text for w in ["汇报", "报告"]):
                    errors.append(f"{prefix}选了小组讨论但交互缺讨论或结果汇报")
            for field in ("desc", "method", "outcome", "criteria"):
                if not t.get(field):
                    errors.append(f"{prefix}缺{field}")
            if place == "课上" and "自主学习" in t.get("method", ""):
                errors.append(f"{prefix}自主学习应放课下")
            for nid in t.get("ids", []):
                if nid not in nodes:
                    errors.append(f"{prefix}引用未知节点{nid}")
            if not t.get("ids"):
                errors.append(f"{prefix}未对应知识点")
            for rid in t.get("res", []):
                if rid not in resources:
                    errors.append(f"{prefix}引用未知资源{rid}")
        for rid in a.get("res", []):
            if rid not in resources:
                errors.append(f"活动{aid}引用未知资源{rid}")
    if home_ratio is not None and home_ratio > 0 and totals["课下"] != totals["课上"] * home_ratio:
        errors.append(f"课上/课下不满足1:{home_ratio}；用户明确另定时才调整比例参数")
    for place, target in (("课上", expected_class), ("课下", expected_home)):
        if target is not None and totals[place] != target:
            errors.append(f"{place}合计{totals[place]}不等于要求{target}")
    diagrams = data.get("diagrams", [])
    overall_edges = {tuple(e) for e in diagrams[0].get("edges", [])} if diagrams else set()
    for i, d in enumerate(diagrams):
        name = d.get("name", str(i))
        if i > 0:
            missing = {tuple(e) for e in d.get("edges", [])} - overall_edges
            if missing:
                errors.append(f"图{name}关系未与总图同步：{sorted(missing)}")
        ids = d.get("ids", [])
        used = set(ids)
        if len(ids) != len(used):
            errors.append(f"图{name}节点ID重复")
        for nid in used - set(nodes):
            errors.append(f"图{name}未知节点{nid}")
        degree, contains = Counter(), Counter()
        adjacency = {n: set() for n in used}
        seen = set()
        for e in d.get("edges", []):
            if len(e) != 3:
                errors.append(f"图{name}边必须为[source,target,relation]")
                continue
            src, dst, relation = e
            if relation == "支持" and src in data.get("membership", {}).get(dst, [])[1:]:
                errors.append(f"图{name}内部知识{src}反向支持{dst}；应检查框架到细目的内容包含关系")
            if relation not in RELATIONS:
                errors.append(f"图{name}未知关系{relation}")
            if src not in used or dst not in used:
                errors.append(f"图{name}连线端点不在本图")
                continue
            if src == dst:
                errors.append(f"图{name}存在自连")
            if tuple(e) in seen:
                errors.append(f"图{name}存在重复边")
            seen.add(tuple(e))
            degree.update((src, dst))
            adjacency[src].add(dst)
            adjacency[dst].add(src)
            if relation in CONTAINS:
                contains[(src, relation)] += 1
        for nid in used:
            if len(used) > 1 and not degree[nid]:
                errors.append(f"图{name}孤立节点{nid}")
        if used:
            todo, reached = [next(iter(used))], set()
            while todo:
                n = todo.pop()
                if n not in reached:
                    reached.add(n)
                    todo.extend(adjacency[n] - reached)
            if reached != used:
                errors.append(f"图{name}存在不连通的知识组块")
        for (src, relation), count in contains.items():
            if count < 2:
                warnings.append(f"图{name}的{src}/{relation}仅1子内容，请人工检查")
        pos, width, height = d.get("pos", {}), d.get("W"), d.get("H")
        if width and height:
            for nid in used:
                if nid not in pos:
                    warnings.append(f"图{name}缺{nid}坐标，跳过几何检查")
                    continue
                x, y, w, h = pos[nid]
                if x - w/2 < 0 or y - h/2 < 0 or x + w/2 > width or y + h/2 > height:
                    errors.append(f"图{name}节点{nid}超出画布")
        if i == 0 and core:
            if core not in pos or not width or not height:
                errors.append("总图缺中心节点坐标或画布尺寸")
            else:
                x, y, _, _ = pos[core]
                if abs(x - width/2) > 0.01*width or abs(y - height/2) > 0.01*height:
                    errors.append("总图核心没有处在画布中心")
    ideology = data.get("ideology_ids", [])
    if not ideology or not diagrams or not set(ideology).issubset(diagrams[0].get("ids", [])):
        errors.append("素质目标的思政点未显式纳入总图")
    if diagrams:
        mapping = data.get("ideology_activity_map", {})
        for i, act in enumerate(acts, 1):
            cid = mapping.get(act["id"])
            if not cid or i >= len(diagrams) or cid not in diagrams[i].get("ids", []):
                errors.append(f"活动{act['id']}的思政要求未在活动图定位")
        for cid in ideology:
            if not any(cid in e[:2] for e in diagrams[0].get("edges", [])):
                errors.append(f"思政节点{cid}在总图未建立关系")
    if not any(n.get("col") == "green" for n in nodes.values()):
        errors.append("未列绿色先决知识")
    return {"passed": not errors, "totals": totals, "activities": len(data.get("activities", [])), "tasks": task_count, "diagrams": len(diagrams), "errors": errors, "warnings": warnings}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data", type=Path)
    p.add_argument("--class-minutes", type=float)
    p.add_argument("--home-minutes", type=float)
    p.add_argument("--core")
    p.add_argument("--home-ratio", type=float, default=2, help="默认1:2，仅用户明确另定时修改；0表示另有约定")
    a = p.parse_args()
    result = audit(json.loads(a.data.read_text(encoding="utf-8")), a.class_minutes, a.home_minutes, a.core, a.home_ratio)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
