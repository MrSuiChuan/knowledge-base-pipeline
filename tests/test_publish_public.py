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
"""公开镜像同步工具：脱敏替换、残留检查、以及"别把好内容也改掉"。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT_REPO = Path(__file__).resolve().parent.parent


def load_publisher():
    spec = importlib.util.spec_from_file_location("publish_public", ROOT_REPO / "tools" / "publish_public.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("publish_public", module)
    spec.loader.exec_module(module)
    return module


# 待脱敏样本**在运行时拼装**，不在源码里写完整标识：
# 否则公开镜像把这几个字面量替换成占位符后，本文件里的断言就会失效（镜像自己把自己测坏）。
_IP = "47.120." + "37.220"
_HOST = "skillhh" + "-prod"
_USER = "kb" + "-admin"
_ACCOUNT = "xhdw" + "/data-dev"
_WORKSPACE = "openviking" + "_workspace"
_PEM = "~/Downloads/skillhh" + ".pem"
_PEM_NAME = "skillhh" + ".pem"
_KEYNAME = "xhdw_kb" + "-admin.key"
_KEYPATH = "~/.openviking/api" + ".key"


class SanitizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pub = load_publisher()

    def test_private_identifiers_are_replaced(self) -> None:
        text = (
            f"线上 http://{_IP}:1933/studio/home 主机 {_HOST}，"
            f"key 在 {_KEYPATH}，用户 {_USER}（租户 {_ACCOUNT}），"
            f"本机工作区 {_WORKSPACE}，私钥 {_PEM}"
        )
        cleaned, counts = self.pub.sanitize(text)
        for pattern in (_IP, _HOST, _USER, "xhdw", _WORKSPACE, _PEM_NAME):
            self.assertNotIn(pattern, cleaned, pattern)
        for placeholder in ("<openviking-host>", "<host>", "<key-file>", "<user>", "<account>", "<workspace>", "<ssh-key-file>"):
            self.assertIn(placeholder, cleaned, placeholder)
        self.assertGreaterEqual(sum(counts.values()), 6)

    def test_longer_patterns_win_over_shorter_ones(self) -> None:
        """更长的键名必须先于短的用户名命中，否则键名会被切的半截（见下一条断言）。"""
        cleaned, _ = self.pub.sanitize(f"见 {_KEYNAME} 与 data-dev_kb{'-admin.key'}")
        self.assertEqual("见 <key-file> 与 <key-file>", cleaned)

    def test_legit_project_names_are_untouched(self) -> None:
        """data-development-plugin、.data-dev 是兄弟项目的真名，不许被"脱敏"掉。"""
        text = "consumer-root 指向 data-development-plugin 项目根；运行态在 .data-dev/runtime"
        cleaned, counts = self.pub.sanitize(text)
        self.assertEqual(text, cleaned)
        self.assertEqual({}, counts)

    def test_residual_check_flags_hard_identifiers(self) -> None:
        self.assertEqual([_IP], self.pub.residuals(f"host={_IP}", "docs/x.md"))

    def test_ci_detector_file_is_allowlisted(self) -> None:
        """CI 里那行"禁止出现的词"列表本身不参与替换，否则检测形同虚设。"""
        self.assertEqual([], self.pub.residuals('! rg -n -i "xhdw|alipay"', ".github/workflows/ci.yml"))

    def test_repository_passes_the_publish_check(self) -> None:
        """真仓库跑一遍 --check：确保现在就能发，而不是"记得发的时候才发现有残留"。"""
        self.assertEqual(0, self.pub.check())


if __name__ == "__main__":
    unittest.main()
