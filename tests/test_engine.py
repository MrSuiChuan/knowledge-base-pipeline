# Copyright 2026 AI实战技能圈
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Unit tests: audit gates, proposal gates, publish guard, rule lifecycle."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_REPO = Path(__file__).resolve().parent.parent
ENGINE = ROOT_REPO / "engine"
sys.path.insert(0, str(ENGINE))

from core import audit, context, gates, proposals, render, skeleton, snapshot, sync  # noqa: E402


class KbBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        context.ensure_app_dir(self.root, mode="mock", domain="user")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _demo_skeleton(self) -> dict:
        return {
            "domain": "user",
            "steps_completed": [1, 2, 3, 4, 5],
            "business_panorama": "注册 → 活跃 → 留存",
            "scope": "用户域",
            "entities": [{"name": "user", "desc": "平台用户"}],
            "processes": [{"name": "活跃", "desc": "当日有行为"}],
            "scenarios": [
                {
                    "name": "活跃统计",
                    "anchor_table": "dwd_user_di",
                    "scope_tables": ["dwd_user_di"],
                    "goal": "UV",
                }
            ],
            "rules": [{"concept": "活跃", "definition": "当日有任意行为即活跃", "scope": "user"}],
            "table_notes": [
                {
                    "table_id": "dwd_user_di",
                    "business_context": "用户域明细",
                    "upstream_calibers": ["概念「活跃」= 当日有任意行为即活跃"],
                    "joins": [],
                    "faq": [{"q": "q", "a": "a"}],
                    "keywords": ["用户"],
                }
            ],
            "goals": [{"goal": "活跃监控", "metrics": ["uv"], "tables": ["dwd_user_di"]}],
            "keywords": {"用户": ["dwd_user_di"]},
        }

    def _generate(self) -> None:
        snapshot.fetch_metadata(self.root, "user")
        skeleton.save(self.root, "user", self._demo_skeleton())
        snap = snapshot.latest_snapshot(self.root)
        notes = {n.get("table_id"): n for n in self._demo_skeleton().get("table_notes") or []}
        context.ensure_dir(context.tables_dir(self.root, "user"))
        for table in snap.get("tables", []):
            context.write_text(
                context.tables_dir(self.root, "user") / f"{table.get('table_id')}.md",
                render.table_doc_markdown(table.get("table_id"), table, notes.get(table.get("table_id")) or {}),
            )
        context.write_text(
            context.domain_dir(self.root, "user") / "navigation.md",
            render.navigation_markdown("user", skeleton.load(self.root, "user")),
        )
        context.write_text(context.repo_dir(self.root) / "README.md", "# Knowledge Base\n\n## domains\n- [user](domains/user/navigation.md)\n")

    def _proposal(self, domain: str = "user", rule_id: str = "DQ-USER-PK") -> dict:
        return {
            "proposal_id": f"{rule_id}-PROP",
            "domain": domain,
            "title": "pk unique",
            "qualification": {
                "owner": "zhangsan",
                "five_gates": {"跨需求成立": True, "长期成立": True, "可量化": True, "确定性匹配": True, "有证据": True},
            },
            "candidate_rule": {
                "id": rule_id,
                "concept": "用户主键唯一",
                "pattern": f"pk_unique(dwd_user_di.user_id)",
                "lineage": [{"table": "dwd_user_di", "column": "user_id"}],
                "tests": {"positive": ["去重==总数"], "negative": ["重复记录"], "ambiguous": ["跨分区重复"]},
                "owner": "zhangsan",
            },
        }


class CliInvocationTests(unittest.TestCase):
    """门控只该认"真的在调用"，不该认"提到了这些词"。

    实测误伤（旧实现对整条命令做子串匹配）：
      * `rg -n "^def verb_" engine/kbp.py` —— 只读检索，路径里含 kbp.py
      * 打印一行 `=== OpenViking ... ===` 当标题 —— 只是提到一个词
    两条都被 setup_guard 拦下过。这里把两种形态都钉住。
    """

    def setUp(self) -> None:
        # 刻意不用 KbBase：它会建 .kb/，而 setup_guard 恰恰只在"没有 .kb"时才拦。
        self._tmp = tempfile.TemporaryDirectory()
        self.empty = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_readonly_mentions_are_not_invocations(self) -> None:
        for command in (
            'rg -n "^def verb_" engine/kbp.py',
            'echo "=== OpenViking 远程集成 ==="',
            'rg -n "kb-publish" skills/',
            "git log --grep=kbp.py",
            "Get-Content engine/kbp.py",
            'python -c "print(open(\'engine/kbp.py\').read())"',
        ):
            decision = gates.decide_cli_command(command, self.empty)
            self.assertFalse(decision.blocked(), (command, decision.gate, decision.reason))

    def test_real_invocations_still_blocked_before_setup(self) -> None:
        for command in (
            "kbp.py publish --domain user --reason x",
            "py -3 .data-dev/engine/kbp.py publish --domain user --reason x",
            "./engine/kbp.py audit --domain user",
            "kb-publish --domain user",
            "FOO=1 sudo kbp.py publish --domain user",
            "echo warmup && kbp.py publish --domain user",
        ):
            decision = gates.decide_cli_command(command, self.empty)
            self.assertEqual(decision.gate, "setup_guard", (command, decision))
            self.assertTrue(decision.blocked(), command)

    def test_setup_via_engine_is_exempt_from_setup_guard(self) -> None:
        # 引擎自己的 setup 动词是"初始化项目"的动作，不该被 setup_guard 拦。
        decision = gates.decide_cli_command("py -3 engine/kbp.py setup --mode mock", self.empty)
        self.assertFalse(decision.blocked(), decision)


class ConsumerContractTests(KbBase):
    """跨插件契约（**生产端**）：发布时写进 data-development-plugin mock 知识库索引的形状。

    消费端的对应断言在 data-development-plugin 的 `tests/test_kb_contract.py` 里。
    两边各自对着同一份 schema 断言——这样两个单仓 CI 都能钉住这条跨仓库的缝，
    不需要同时 checkout 两个仓库。
    """

    def setUp(self) -> None:
        super().setUp()
        self._made: list = []

    def tearDown(self) -> None:
        for path in self._made:
            shutil.rmtree(path, ignore_errors=True)
        super().tearDown()

    def _consumer(self, with_index: bool = True) -> Path:
        consumer = Path(tempfile.mkdtemp(prefix="ddproj-"))
        self._made.append(consumer)
        kb_dir = consumer / ".data-dev" / "mock" / "kb"
        kb_dir.mkdir(parents=True)
        if with_index:
            context.write_json(kb_dir / "index.json", {"documents": []})
        return consumer

    def _documents(self, consumer: Path) -> list:
        return context.load_json(consumer / ".data-dev" / "mock" / "kb" / "index.json")["documents"]

    def _audited(self) -> None:
        """建好知识树并跑一次 publish 模式的严格审计——publish 的前置条件。"""
        self._generate()
        result = audit.run_audit(self.root, "user", mode="publish", level="strict")
        self.assertTrue(result["passed"], result["issues"])

    def test_publish_writes_documents_in_the_agreed_shape(self) -> None:
        self._audited()
        consumer = self._consumer()
        result = sync.publish(self.root, "user", reason="t", consumer_root=consumer)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["consumer_sync"]["ok"], result["consumer_sync"])

        docs = self._documents(consumer)
        self.assertTrue(docs, "发布后消费方索引应当有表文档")
        for doc in docs:
            self.assertGreaterEqual(
                set(doc), {"uri", "domain", "layer", "tables", "abstract"}, doc
            )
            # 数开插件的铁律：知识源必须以 viking://resources/ 开头
            self.assertTrue(doc["uri"].startswith("viking://resources/"), doc["uri"])
            self.assertEqual(doc["domain"], "user", doc)
            self.assertEqual(len(doc["tables"]), 1, doc)
            # layer 由表名首段推导，两个插件都依赖这个约定
            self.assertEqual(doc["layer"], doc["tables"][0].split("_")[0], doc)

    def test_republish_does_not_duplicate_documents(self) -> None:
        self._audited()
        consumer = self._consumer()
        sync.publish(self.root, "user", reason="t1", consumer_root=consumer)
        first = len(self._documents(consumer))
        sync.publish(self.root, "user", reason="t2", consumer_root=consumer)
        self.assertEqual(len(self._documents(consumer)), first, "重复发布不应产生重复条目")

    def test_missing_consumer_index_is_reported_not_swallowed(self) -> None:
        """消费方还没初始化时，同步一行都不会做——这件事必须可见。

        原来 `_update_data_dev_index` 的返回值被 publish 直接丢掉，调用方只看到
        `ok: true`，跨插件同步静默丢失（实测）。
        """
        self._audited()
        consumer = self._consumer(with_index=False)
        result = sync.publish(self.root, "user", reason="t", consumer_root=consumer)
        self.assertTrue(result["ok"], "发布本身成功")   # git + OV 确实成功了
        self.assertIn("consumer_sync", result)
        self.assertFalse(result["consumer_sync"]["ok"])
        self.assertIn("index.json", result["consumer_sync"]["reason"])

    def test_no_consumer_configured_means_no_consumer_sync(self) -> None:
        self._audited()
        result = sync.publish(self.root, "user", reason="t")
        self.assertIsNone(result["consumer_sync"])


class AuditTests(KbBase):
    def test_audit_passes_clean_knowledge(self) -> None:
        self._generate()
        result = audit.run_audit(self.root, "user", mode="publish", level="strict")
        self.assertTrue(result["passed"], result["issues"])
        self.assertEqual(result["generator"], "domain-knowledge-generator")
        self.assertIn("v41_six_layers", result["link_audit"])

    def test_conflict_definition_fails(self) -> None:
        self._generate()
        path = context.tables_dir(self.root, "user") / "dwd_user_di.md"
        text = context.read_text(path) + "\n- 概念「活跃」= 当天点击过按钮才算\n"
        context.write_text(path, text)
        result = audit.run_audit(self.root, "user", mode="publish", level="strict")
        self.assertFalse(result["passed"])
        self.assertTrue(any(i["code"] == "conflict.definition" for i in result["issues"]))

    def test_broken_link_fails(self) -> None:
        self._generate()
        nav = context.read_text(context.domain_dir(self.root, "user") / "navigation.md")
        nav += "\n- 断链场景 [ghost_table](tables/ghost_table.md)\n"
        context.write_text(context.domain_dir(self.root, "user") / "navigation.md", nav)
        result = audit.run_audit(self.root, "user", mode="publish", level="strict")
        self.assertFalse(result["passed"])

    def test_chinese_word_containing_rule_id_is_not_a_reference(self) -> None:
        """「活动规则ID」这类中文词不能被当成规则引用（真实 DDL 注释里到处都是）。"""
        self._generate()
        path = context.tables_dir(self.root, "user") / "dwd_user_di.md"
        context.write_text(path, context.read_text(path) + "\n| activity_rule_id | STRING | 活动规则ID |  |\n")
        result = audit.run_audit(self.root, "user", mode="publish", level="strict")
        self.assertTrue(result["passed"], result["issues"])

    def test_rule_reference_with_separator_must_exist(self) -> None:
        """带分隔符的规则引用仍要能查出来——断链必须红。"""
        self._generate()
        path = context.tables_dir(self.root, "user") / "dwd_user_di.md"
        context.write_text(path, context.read_text(path) + "\n- 规则: DQ-NOT-EXIST\n")
        result = audit.run_audit(self.root, "user", mode="publish", level="strict")
        self.assertFalse(result["passed"])
        self.assertTrue(any(i["code"] == "link.broken" for i in result["issues"]), result["issues"])


class VcsStatusTests(KbBase):
    """KBP-009：版本控制层不可用时，安装期就要说出来，而不是等到发布才炸。"""

    def test_reports_ok_when_git_is_available(self) -> None:
        self.assertEqual(context.vcs_status(self.root), {"ok": True, "enabled": True})

    def test_reports_disabled_when_config_turns_it_off(self) -> None:
        cfg = context.load_config(self.root)
        cfg["git_enabled"] = False
        context.write_json(context.config_path(self.root), cfg)
        status = context.vcs_status(self.root)
        self.assertTrue(status["ok"], status)
        self.assertFalse(status["enabled"], status)

    def test_reports_a_reason_when_git_is_missing(self) -> None:
        """不能真的卸载 git，用 PATH 模拟——vcs_status 走 shutil.which。"""
        import unittest.mock as mock

        with mock.patch.dict(os.environ, {"PATH": ""}):
            status = context.vcs_status(self.root)
        self.assertFalse(status["ok"], status)
        self.assertIn("git", status["reason"])


class PublishGateTests(KbBase):
    def test_publish_without_audit_blocked(self) -> None:
        self._generate()
        decision = gates.decide_cli_command("kbp.py publish --domain user --reason x", self.root)
        self.assertEqual(decision.gate, "kb_publish_guard")
        self.assertTrue(decision.blocked())

    def test_publish_after_audit_allowed(self) -> None:
        self._generate()
        audit.run_audit(self.root, "user", mode="publish", level="strict")
        decision = gates.decide_cli_command("kbp.py publish --domain user --reason x", self.root)
        self.assertFalse(decision.blocked(), decision)
        result = sync.publish(self.root, "user", reason="t")
        self.assertTrue(result["ok"], result)
        self.assertIn("kb-v1", result["version"])
        self.assertTrue(any(u.startswith("viking://resources/") for u in result["uris"]))

    def test_publish_blocked_when_content_changed_after_audit(self) -> None:
        self._generate()
        audit.run_audit(self.root, "user", mode="publish", level="strict")
        context.write_text(context.domain_dir(self.root, "user") / "navigation.md", "# changed\n")
        decision = gates.decide_cli_command("kbp.py publish --domain user --reason x", self.root)
        self.assertTrue(decision.blocked())
        self.assertIn("重跑", decision.reason)

    def test_rules_direct_write_blocked(self) -> None:
        rule_path = context.rules_dir(self.root, "user") / "DQ-X.yaml"
        decision = gates.decide_file_write(str(rule_path), self.root)
        self.assertEqual(decision.gate, "rules_direct_write_guard")
        self.assertTrue(decision.blocked())


class ProposalTests(KbBase):
    def test_proposal_without_id_gets_one_from_the_engine(self) -> None:
        """外部 JSON 不带 proposal_id 时，引擎必须补号，不能写成 None.json。"""
        snapshot.fetch_metadata(self.root, "user")
        proposal = self._proposal()
        proposal.pop("proposal_id")
        result = proposals.apply_proposal(self.root, proposal)
        self.assertTrue(result["ok"], result)
        proposal_id = str(result.get("proposal_id") or "")
        self.assertTrue(proposal_id.startswith("DQ-"), result)
        stored = context.proposals_dir(self.root) / f"{proposal_id}.json"
        self.assertTrue(stored.is_file(), stored)
        self.assertFalse((context.proposals_dir(self.root) / "None.json").exists())

    def test_proposal_missing_tests_blocked(self) -> None:
        snapshot.fetch_metadata(self.root, "user")
        proposal = self._proposal()
        proposal["candidate_rule"]["tests"] = {}
        result = proposals.apply_proposal(self.root, proposal)
        self.assertFalse(result["ok"])
        self.assertTrue(any("单测" in i for i in result["issues"]))

    def test_proposal_missing_lineage_blocked(self) -> None:
        snapshot.fetch_metadata(self.root, "user")
        proposal = self._proposal()
        proposal["candidate_rule"]["lineage"] = [{"table": "dwd_user_di", "column": "not_a_column"}]
        result = proposals.apply_proposal(self.root, proposal)
        self.assertFalse(result["ok"])
        self.assertTrue(any("血缘" in i for i in result["issues"]))

    def test_proposal_duplicate_blocked(self) -> None:
        snapshot.fetch_metadata(self.root, "user")
        first = proposals.apply_proposal(self.root, self._proposal())
        self.assertTrue(first["ok"], first)
        second = proposals.apply_proposal(self.root, self._proposal(rule_id="DQ-USER-PK-2"))
        self.assertFalse(second["ok"])
        self.assertTrue(any("重复" in i for i in second["issues"]))

    def test_proposal_apply_then_approve_lifecycle(self) -> None:
        snapshot.fetch_metadata(self.root, "user")
        result = proposals.apply_proposal(self.root, self._proposal())
        self.assertTrue(result["ok"], result)
        rule_dir = context.rules_dir(self.root, "user")
        rule = render.rule_yaml_parse(context.read_text(rule_dir / "DQ-USER-PK.yaml"))
        self.assertEqual(rule["status"], "APPLIED")
        self.assertEqual(rule["final_status"], "READY_FOR_REVIEW")
        # 非 owner 代签被拦
        wrong = proposals.approve_proposal(self.root, "DQ-USER-PK-PROP", "lisi", "代签")
        self.assertFalse(wrong["ok"])
        ok = proposals.approve_proposal(self.root, "DQ-USER-PK-PROP", "zhangsan", "终签")
        self.assertTrue(ok["ok"], ok)
        rule = render.rule_yaml_parse(context.read_text(rule_dir / "DQ-USER-PK.yaml"))
        self.assertEqual(rule["status"], "active")
        self.assertEqual(rule["final_status"], "APPROVED")


class HardeningTests(KbBase):
    def test_write_verb_and_machine_asset_segment_matching(self) -> None:
        """同段=真写入要拦；跨段（分析脚本）不该误伤。"""
        for cmd in (
            'echo {} > .kb/_state.json',
            'cd x && rm .kb/runtime/executions.json',
        ):
            decision = gates.decide_cli_command(cmd, self.root)
            self.assertTrue(decision.blocked(), (cmd, decision))
        benign = 'py -3 -c "\nimport shutil\nprint(\'inspect .kb/_state.json\')\n"\n'
        decision = gates.decide_cli_command(benign, self.root)
        self.assertFalse(decision.blocked(), decision)

    def test_variable_indirection_and_cd_still_blocked(self) -> None:
        """实测绕过：路径存进变量，或先 cd 进机器资产目录再相对路径写入。"""
        for cmd in (
            "$t = Join-Path $PWD '.kb\\runtime\\x.json'\nSet-Content -Path $t -Value '{}'\n",
            "cd .kb/runtime\nSet-Content x.json -Value '{}'",
        ):
            decision = gates.decide_cli_command(cmd, self.root)
            self.assertTrue(decision.blocked(), (cmd, decision))

    def test_windows_trailing_dot_and_space_variants_blocked(self) -> None:
        """Windows 把 `runtime.` / `_state.json.` 当同一个路径，等价写法必须拦住。"""
        cases = (
            (".kb/runtime./x.json", "runtime_guard"),
            (".kb/runtime /x.json", "runtime_guard"),
            (".kb/_state.json.", "state_write_guard"),
            (".kb/_state.json ", "state_write_guard"),
            (".kb/.KB-AUDIT-1.JSON", "audit_manifest_guard"),
            (".kb/repo/rules./demo.yml", "rules_direct_write_guard"),
        )
        for rel, gate in cases:
            decision = gates.decide_file_write(rel, self.root)
            self.assertTrue(decision.blocked(), (rel, decision))
            self.assertEqual(decision.gate, gate, rel)

    def test_shell_write_variants_blocked(self) -> None:
        """shell 的各种写文件写法都要拦（Set-Content / Out-File / cp / tee / 重定向…）。"""
        for cmd in (
            'echo {} > .kb/_state.json',
            'Set-Content -Path .kb/_state.json -Value "{}"',
            'Get-Content x | Out-File .kb/.kb-audit-1.json',
            'cp evil.json .kb/.kb-manifest.json',
            'echo {} | tee .kb/runtime/x.json',
            'sed -i s/a/b/ .kb/repo/rules/demo.yml',
            'New-Item -ItemType File -Path .kb/repo/rules/hack.yml',
        ):
            decision = gates.decide_cli_command(cmd, self.root)
            self.assertTrue(decision.blocked(), (cmd, decision))

    def test_shape_fallback_for_unknown_or_missing_tool_name(self) -> None:
        for payload in (
            {"tool_input": {"file_path": ".kb/runtime/x.json"}},
            {"tool_name": "SomeNewTool", "tool_input": {"path": ".kb/_state.json"}},
            {"tool_name": "apply_patch", "tool_input": {"input": "*** Add File: .kb/runtime/y.json\n+{}\n*** End Patch"}},
        ):
            decision = gates.decide_pre_tool(payload, self.root)
            self.assertTrue(decision.blocked(), (payload, decision))

    def test_state_and_runtime_writes_blocked(self) -> None:
        state = context.state_path(self.root)
        decision = gates.decide_file_write(str(state), self.root)
        self.assertEqual(decision.gate, "state_write_guard")
        self.assertTrue(decision.blocked())
        runtime = context.runtime_dir(self.root) / "snapshots" / "x.json"
        decision = gates.decide_file_write(str(runtime), self.root)
        self.assertEqual(decision.gate, "runtime_guard")
        self.assertTrue(decision.blocked())

    def test_bash_touch_audit_blocked(self) -> None:
        decision = gates.decide_cli_command(
            f"touch {context.repo_dir(self.root) / '.kb-audit-20260901-000001.json'}", self.root
        )
        self.assertTrue(decision.blocked())
        self.assertIn("guard", decision.gate)

    def test_content_hash_blocks_publish_even_if_state_tampered(self) -> None:
        self._generate()
        audit.run_audit(self.root, "user", mode="publish", level="strict")
        self.assertTrue(audit.audit_fresh_enough(self.root)["ok"])
        path = context.tables_dir(self.root, "user") / "dwd_user_di.md"
        context.write_text(path, context.read_text(path) + "\n- 补充说明：示例\n")
        # attacker also rewrites last_audit content_hash to current tree hash
        state = context.load_state(self.root)
        state["last_audit"]["content_hash"] = audit.content_tree_hash(self.root, "user")
        context.save_state(self.root, state)
        gate = audit.audit_fresh_enough(self.root)
        self.assertFalse(gate["ok"])
        self.assertIn("内容哈希不一致", gate["reason"])

    def test_live_publish_requires_remote_sync(self) -> None:
        self._generate()
        cfg = context.load_config(self.root)
        cfg["mode"] = "live"
        context.write_json(context.config_path(self.root), cfg)
        audit.run_audit(self.root, "user", mode="publish", level="strict")
        result = sync.publish(self.root, "user", reason="t")
        self.assertFalse(result["ok"])
        self.assertEqual(result["gate"], "ov_live_not_configured")

    def test_custom_uri_root_mirrors_prefix(self) -> None:
        self._generate()
        cfg = context.load_config(self.root)
        cfg["uri_root"] = "viking://projects/kb/"
        context.write_json(context.config_path(self.root), cfg)
        uris = sync.sync_to_ov(self.root, "user")
        prefix = "viking://projects/kb/"
        self.assertTrue(all(u.startswith(prefix) for u in uris), uris)
        for uri in uris[:1]:
            rel = uri[len(prefix):]
            self.assertTrue((context.ov_dir(self.root) / rel).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
