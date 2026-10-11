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
"""开源标准的机器检查：把 tools/validate_oss.py 挂进用例，本地跑测试就等于跑验收。

为什么要有这一层：标准文件与许可头如果只靠人工记得，下一次改动就会悄悄退回去
（本仓库已经吃过同类教训——生成物漂移与清单不同步都是"没人看见"才存在的）。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_REPO = Path(__file__).resolve().parent.parent


def load_validate_oss():
    spec = importlib.util.spec_from_file_location("validate_oss", ROOT_REPO / "tools" / "validate_oss.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("validate_oss", module)
    spec.loader.exec_module(module)
    return module


class OssReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.oss = load_validate_oss()

    def test_repository_passes_every_oss_check(self) -> None:
        failures = {title: errors for title, fn in self.oss.CHECKS if (errors := fn())}
        self.assertEqual({}, failures, f"开源标准自检未通过：{failures}")

    def test_missing_required_file_is_reported(self) -> None:
        """反例：把 GOVERNANCE.md 挪走，检查必须报出来（否则它就是摆设）。"""
        target = ROOT_REPO / "GOVERNANCE.md"
        backup = target.read_bytes()
        try:
            target.unlink()
            errors = self.oss.check_required_paths()
        finally:
            target.write_bytes(backup)
        self.assertTrue(any("GOVERNANCE.md" in err for err in errors), errors)

    def test_personal_path_is_reported(self) -> None:
        """反例：文档里混进本机绝对路径，必须被拦（真跑时抓到过一次）。"""
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "note.md"
            # 路径拆开拼，免得这个"反例样本"自己被自检脚本当成真的个人路径。
            probe.write_text("bin: " + "/home/" + "someuser/oss/kafka/bin\n", encoding="utf-8")
            original_root, original_exempt = self.oss.ROOT, set(self.oss.PERSONAL_EXEMPT)
            try:
                self.oss.ROOT = Path(tmp)
                self.oss.PERSONAL_EXEMPT = set()
                errors = self.oss.check_personal_traces()
            finally:
                self.oss.ROOT, self.oss.PERSONAL_EXEMPT = original_root, original_exempt
        self.assertTrue(any("本机绝对路径" in err for err in errors), errors)

    def test_license_headers_are_checked_for_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "engine").mkdir()
            (root / "engine" / "fresh.py").write_text("print('no header')\n", encoding="utf-8")
            original = self.oss.ROOT
            try:
                self.oss.ROOT = root
                errors = self.oss.check_license_headers()
            finally:
                self.oss.ROOT = original
        self.assertEqual(["engine/fresh.py 缺 Apache-2.0 许可头"], errors)


if __name__ == "__main__":
    unittest.main()
