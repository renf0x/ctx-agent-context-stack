import tempfile
import unittest
from pathlib import Path
from unittest import mock

import install


class InstallerTests(unittest.TestCase):
    def test_installs_all_adapters_without_overwriting_existing_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "AGENTS.md").write_text("# Existing\n", encoding="utf-8")
            with mock.patch("install.run", return_value=0):
                result = install.main([str(project), "--agents", "all"])
            self.assertEqual(result, 0)
            self.assertTrue((project / "ctx.py").is_file())
            self.assertTrue((project / "rlm.py").is_file())
            self.assertTrue((project / "AGENT_CONTEXT.md").is_file())
            self.assertEqual(
                (project / "AGENT_CONTEXT.md").read_text(encoding="utf-8"),
                install.read_template("AGENT_CONTEXT.md"),
            )
            agents = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("# Existing", agents)
            self.assertIn(install.read_template("adapters/AGENTS.md").strip(), agents)
            self.assertEqual(agents.count(install.MANAGED_START), 1)
            self.assertTrue((project / "CLAUDE.md").is_file())
            self.assertEqual(
                (project / "CLAUDE.md").read_text(encoding="utf-8"),
                install.read_template("adapters/CLAUDE.md").rstrip() + "\n",
            )

    def test_repeated_install_does_not_duplicate_managed_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            with mock.patch("install.run", return_value=0):
                self.assertEqual(install.main([str(project)]), 0)
                self.assertEqual(install.main([str(project)]), 0)
            agents = (project / "AGENTS.md").read_text(encoding="utf-8")
            claude = (project / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertEqual(agents.count(install.MANAGED_START), 1)
            self.assertEqual(claude.count(install.MANAGED_START), 1)

    def test_real_install_creates_valid_generic_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            result = install.main([
                str(project),
                "--agents",
                "generic",
                "--no-codegraph",
            ])
            self.assertEqual(result, 0)
            self.assertTrue((project / "memory" / "MEMORY.md").is_file())
            self.assertNotIn(
                "COURSE_OVERVIEW",
                (project / "memory" / "MEMORY.md").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
