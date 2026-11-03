"""Integration test against the real backend schema.

Set ``COLOSTRUCT_REPO_ROOT`` to the Colostruct checkout, or run the tests from
that checkout so the repository root is discovered automatically.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests import resolve_repo_root

DEV_ROOT = Path(__file__).resolve().parents[1]

CHILD_CODE = r"""
from core.llm.result import AGroupResult, PassAResult, Diagnostics
from core.pathology_schema import ColoStructExtraction

extraction = ColoStructExtraction(fields={}, override_logs=[], has_block=False)
result = AGroupResult(
    extraction=extraction,
    pass_a_result=PassAResult(),
    diagnostics=Diagnostics(),
)
assert isinstance(result.extraction, ColoStructExtraction)
assert result.schema_version == "a_group_result/v1"
print("INTEGRATION_OK")
"""


class RealBackendSchemaIntegrationTests(unittest.TestCase):
    def test_real_schema_accepts_agroupresult(self):
        repo_path = resolve_repo_root()

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([str(DEV_ROOT), str(repo_path)])
        completed = subprocess.run(
            [sys.executable, "-c", CHILD_CODE],
            capture_output=True,
            text=True,
            env=env,
        )
        if completed.returncode != 0:
            stderr = completed.stderr or ""
            if "ModuleNotFoundError" in stderr or "ImportError" in stderr:
                self.skipTest("backend dependency unavailable: " + stderr.strip().splitlines()[-1])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("INTEGRATION_OK", completed.stdout)


if __name__ == "__main__":
    unittest.main()
