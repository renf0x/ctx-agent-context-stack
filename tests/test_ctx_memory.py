import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ctx
import rlm


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def init_memory(self):
        args = argparse.Namespace(path=str(self.root), with_codegraph=False)
        self.assertEqual(ctx.cmd_memory_init(args), 0)

    def test_init_is_idempotent_and_preserves_content(self):
        self.init_memory()
        rules = self.root / "memory" / "project-rules.md"
        self.assertTrue((self.root / "memory" / ".gitignore").is_file())
        self.assertIn("node_modules/", (self.root / ".gitignore").read_text(encoding="utf-8"))
        rules.write_text("custom rules\n", encoding="utf-8")
        self.init_memory()
        self.assertEqual(rules.read_text(encoding="utf-8"), "custom rules\n")
        self.assertTrue((self.root / "memory" / "templates" / "bug.md").is_file())

    def test_check_detects_missing_broken_link_and_large_index(self):
        self.init_memory()
        (self.root / "memory" / "architecture.md").unlink()
        index = self.root / "memory" / "MEMORY.md"
        index.write_text("# Index\n\n[[missing-note]]\n" + "line\n" * 121, encoding="utf-8")
        issues = ctx.memory_check(self.root)
        codes = {issue["code"] for issue in issues}
        self.assertIn("missing", codes)
        self.assertIn("broken-link", codes)
        self.assertIn("index-too-long", codes)

    def test_rules_change_requires_approval(self):
        self.init_memory()
        rules = self.root / "memory" / "project-rules.md"
        rules.write_text(rules.read_text(encoding="utf-8") + "\nnew rule\n", encoding="utf-8")
        self.assertIn("rules-changed", {i["code"] for i in ctx.memory_check(self.root)})
        args = argparse.Namespace(path=str(self.root), user_approved=True)
        self.assertEqual(ctx.cmd_memory_rules_approve(args), 0)
        self.assertNotIn("rules-changed", {i["code"] for i in ctx.memory_check(self.root)})

    def test_rotate_moves_only_closed_entries(self):
        self.init_memory()
        journal = self.root / "memory" / "bugs.md"
        closed = "## BUG-20260615-001\n\n- Status: closed\n\n" + ("fixed\n" * 5000)
        opened = "## BUG-20260615-002\n\n- Status: open\n\nKeep this active.\n"
        journal.write_text("# Bug Log\n\n" + closed + "\n" + opened, encoding="utf-8")
        args = argparse.Namespace(path=str(self.root))
        self.assertEqual(ctx.cmd_memory_rotate(args), 0)
        active = journal.read_text(encoding="utf-8")
        self.assertNotIn("BUG-20260615-001", active)
        self.assertIn("BUG-20260615-002", active)
        archives = list((self.root / "memory" / "archive" / "bugs").glob("*.md"))
        self.assertEqual(len(archives), 1)
        self.assertIn("BUG-20260615-001", archives[0].read_text(encoding="utf-8"))

    @mock.patch("ctx._run_codegraph")
    def test_context_uses_limited_memory_and_codegraph(self, run_codegraph):
        self.init_memory()
        (self.root / ".codegraph").mkdir()
        run_codegraph.side_effect = [
            mock.Mock(returncode=0, stdout="", stderr=""),
            mock.Mock(returncode=0, stdout="graph result", stderr=""),
        ]
        text = ctx._memory_context(self.root, "change progress", 30, 6)
        self.assertIn("memory/MEMORY.md", text)
        self.assertIn("handoff.md", text)
        self.assertIn("memory/project-rules.md", text)
        self.assertIn("graph result", text)
        self.assertNotIn("archive", text)

    @mock.patch("ctx._find_obsidian", return_value=None)
    def test_open_does_not_install_without_explicit_flag(self, find_obsidian):
        self.init_memory()
        args = argparse.Namespace(path=str(self.root), install_obsidian=False)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ctx.cmd_memory_open(args), 1)
        find_obsidian.assert_called_once()

    @mock.patch("ctx.subprocess.Popen")
    @mock.patch("ctx._restart_obsidian_if_running")
    @mock.patch("ctx._register_obsidian_vault",
                return_value=("0123456789abcdef", True))
    @mock.patch("ctx._find_obsidian", return_value="C:/Program Files/Obsidian/Obsidian.exe")
    def test_open_launches_existing_obsidian(
        self, find_obsidian, register, restart, popen
    ):
        self.init_memory()
        args = argparse.Namespace(path=str(self.root), install_obsidian=False)
        self.assertEqual(ctx.cmd_memory_open(args), 0)
        register.assert_called_once_with(self.root / "memory")
        restart.assert_called_once_with()
        command = popen.call_args.args[0]
        self.assertEqual(command[0], "C:/Program Files/Obsidian/Obsidian.exe")
        self.assertEqual(command[1], "obsidian://open?vault=memory")

    @mock.patch("ctx.cmd_rlm", return_value=0)
    def test_query_routes_memory_scope_to_rlm(self, cmd_rlm):
        self.init_memory()
        args = argparse.Namespace(
            path=str(self.root),
            scope="memory",
            question="what changed",
            mode="mapreduce",
            provider="fake",
            model=None,
            sub_model=None,
            chunk_tokens=4000,
            max_depth=1,
            json=False,
        )
        self.assertEqual(ctx.cmd_memory_query(args), 0)
        forwarded = cmd_rlm.call_args.args[0]
        self.assertEqual(Path(forwarded.file), self.root / "memory")
        self.assertEqual(forwarded.query, "what changed")

    @mock.patch("ctx.subprocess.Popen")
    @mock.patch("ctx.subprocess.run")
    @mock.patch("ctx.shutil.which")
    @mock.patch("ctx._register_obsidian_vault",
                return_value=("0123456789abcdef", False))
    @mock.patch("ctx._find_obsidian")
    def test_open_installs_only_with_explicit_flag(
        self, find_obsidian, register, which, run, popen
    ):
        self.init_memory()
        find_obsidian.side_effect = [None, "C:/Obsidian.exe"]
        which.return_value = "C:/Windows/winget.exe"
        run.return_value = mock.Mock(returncode=0)
        args = argparse.Namespace(path=str(self.root), install_obsidian=True)
        self.assertEqual(ctx.cmd_memory_open(args), 0)
        run.assert_called_once()
        self.assertIn("Obsidian.Obsidian", run.call_args.args[0])
        popen.assert_called_once()

    @mock.patch("ctx.subprocess.Popen")
    @mock.patch("ctx._install_obsidian_from_official_release", return_value=0)
    @mock.patch("ctx.shutil.which", return_value=None)
    @mock.patch("ctx._register_obsidian_vault",
                return_value=("0123456789abcdef", False))
    @mock.patch("ctx._find_obsidian")
    def test_open_falls_back_to_official_release_without_winget(
        self, find_obsidian, register, which, install_release, popen
    ):
        self.init_memory()
        find_obsidian.side_effect = [None, "C:/Obsidian.exe"]
        args = argparse.Namespace(path=str(self.root), install_obsidian=True)
        self.assertEqual(ctx.cmd_memory_open(args), 0)
        install_release.assert_called_once_with()
        popen.assert_called_once()

    @mock.patch.dict(os.environ, {"APPDATA": ""}, clear=False)
    def test_register_vault_preserves_existing_entries(self):
        appdata = self.root / "appdata"
        with mock.patch.dict(os.environ, {"APPDATA": str(appdata)}, clear=False):
            config = appdata / "obsidian" / "obsidian.json"
            config.parent.mkdir(parents=True)
            config.write_text(
                '{"vaults":{"existing":{"path":"C:/notes","ts":1}}}',
                encoding="utf-8",
            )
            memory = self.root / "memory"
            memory.mkdir()
            vault_id, created = ctx._register_obsidian_vault(memory)
            data = __import__("json").loads(config.read_text(encoding="utf-8"))
            self.assertIn("existing", data["vaults"])
            self.assertEqual(len(vault_id), 16)
            self.assertTrue(created)
            self.assertTrue(any(
                value["path"] == str(memory.resolve())
                for value in data["vaults"].values()
            ))

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("rlm.shutil.which", return_value=None)
    @mock.patch("rlm.gemini_creds_path")
    @mock.patch("rlm.codex_auth_path")
    def test_provider_prefers_codex_oauth_credentials(
        self, codex_auth_path, gemini_creds_path, which
    ):
        codex_auth_path.return_value = mock.Mock(is_file=lambda: True)
        gemini_creds_path.return_value = mock.Mock(is_file=lambda: False)
        self.assertEqual(rlm.pick_provider("auto"), "openai-oauth")

    @mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-key"}, clear=True)
    @mock.patch("rlm.shutil.which", return_value=None)
    @mock.patch("rlm.gemini_creds_path")
    @mock.patch("rlm.codex_auth_path")
    def test_provider_auto_detects_openrouter(
        self, codex_auth_path, gemini_creds_path, which
    ):
        codex_auth_path.return_value = mock.Mock(is_file=lambda: False)
        gemini_creds_path.return_value = mock.Mock(is_file=lambda: False)
        self.assertEqual(rlm.pick_provider("auto"), "openrouter")

    @mock.patch.dict(os.environ, {
        "OPENROUTER_API_KEY": "or-key",
        "OPENROUTER_APP_TITLE": "ctx-test",
    }, clear=True)
    @mock.patch("rlm._http_json")
    def test_openrouter_provider_sends_selected_model(self, http_json):
        http_json.return_value = {
            "choices": [{"message": {"content": "answer"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        }

        provider = rlm.resolve_provider(
            "openrouter",
            model="deepseek/deepseek-chat-v3.1",
            sub_model="deepseek/deepseek-chat-v3.1",
        )
        self.assertEqual(provider.root("question"), "answer")

        url, payload, headers = http_json.call_args.args
        self.assertEqual(url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(payload["model"], "deepseek/deepseek-chat-v3.1")
        self.assertEqual(payload["messages"][0]["content"], "question")
        self.assertEqual(headers["Authorization"], "Bearer or-key")
        self.assertEqual(headers["X-Title"], "ctx-test")

    @mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-key"}, clear=True)
    @mock.patch("rlm._http_json")
    def test_openrouter_sub_model_defaults_to_selected_model(self, http_json):
        http_json.return_value = {"choices": [{"message": {"content": "answer"}}]}

        provider = rlm.resolve_provider(
            "openrouter",
            model="deepseek/deepseek-chat-v3.1",
            sub_model=None,
        )
        self.assertEqual(provider.sub("chunk"), "answer")

        payload = http_json.call_args.args[1]
        self.assertEqual(payload["model"], "deepseek/deepseek-chat-v3.1")

    def test_rawcount_counts_directory_without_ledger(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "app.ts").write_text("export const app = 1;\n", encoding="utf-8")
        (self.root / ".env").write_text("SECRET=value\n", encoding="utf-8")
        args = argparse.Namespace(path=str(self.root), include_secrets=False, json=False)

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(ctx.cmd_rawcount(args), 0)

        output = stdout.getvalue()
        self.assertIn("# raw context:", output)
        self.assertIn("files: 1", output)
        self.assertIn("secret-looking files skipped: 1", output)
        self.assertFalse((self.root / ".ctx" / "ledger.jsonl").exists())


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._cwd = os.getcwd()
        os.chdir(self.root)  # ledger is written to a cwd-relative .ctx

    def tearDown(self):
        os.chdir(self._cwd)
        self.temp.cleanup()

    def ledger_records(self):
        path = self.root / ".ctx" / "ledger.jsonl"
        if not path.is_file():
            return []
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]

    def test_read_logs_uncompressed_pull(self):
        (self.root / "f.txt").write_text("hello world\n", encoding="utf-8")
        args = argparse.Namespace(file="f.txt")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ctx.cmd_read(args), 0)
        self.assertIn("hello world", out.getvalue())
        recs = self.ledger_records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["op"], "read")
        # a raw read has no saving: it is the honest denominator
        self.assertEqual(recs[0]["raw_tokens"], recs[0]["kept_tokens"])
        self.assertEqual(recs[0]["saved_tokens"], 0)

    def test_map_logs_recon_record(self):
        (self.root / "a.py").write_text("def a():\n    pass\n", encoding="utf-8")
        args = argparse.Namespace(path=".", top=40, all=False, warn=4000)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ctx.cmd_map(args), 0)
        ops = [r["op"] for r in self.ledger_records()]
        self.assertIn("map", ops)

    def test_ledger_log_keeps_extra_fields_and_drops_none(self):
        ctx.ledger_log("rlm", 100, 10, "q", provider="fake", model=None, calls=3)
        rec = self.ledger_records()[0]
        self.assertEqual(rec["provider"], "fake")
        self.assertEqual(rec["calls"], 3)
        self.assertNotIn("model", rec)  # None extras are dropped
        self.assertEqual(rec["v"], 2)

    def test_hook_logs_direct_pull_from_stdin(self):
        payload = {
            "session_id": "abc",
            "tool_name": "Read",
            "tool_response": {"file": {"content": "x " * 500}},
        }
        args = argparse.Namespace(min_tokens=10)
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))):
            self.assertEqual(ctx.cmd_hook(args), 0)
        recs = self.ledger_records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["op"], "direct")
        self.assertEqual(recs[0]["raw_tokens"], recs[0]["kept_tokens"])
        self.assertEqual(recs[0]["session"], "abc")

    def test_hook_is_silent_on_garbage_and_below_threshold(self):
        with mock.patch("sys.stdin", io.StringIO("not json")):
            self.assertEqual(ctx.cmd_hook(argparse.Namespace(min_tokens=10)), 0)
        tiny = {"tool_name": "Read", "tool_response": "hi"}
        with mock.patch("sys.stdin", io.StringIO(json.dumps(tiny))):
            self.assertEqual(ctx.cmd_hook(argparse.Namespace(min_tokens=200)), 0)
        self.assertEqual(self.ledger_records(), [])  # nothing logged either way

    def test_hook_skips_ctx_selfcall_to_avoid_double_count(self):
        # `ctx digest` run via Bash already self-logs; the hook must not also
        # count its output as a raw "direct" pull.
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "ctx digest big.py"},
            "tool_response": {"stdout": "signature " * 200},
        }
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))):
            self.assertEqual(ctx.cmd_hook(argparse.Namespace(min_tokens=10)), 0)
        self.assertEqual(self.ledger_records(), [])  # nothing logged
        # a non-ctx Bash command IS counted
        payload["tool_input"]["command"] = "cat big.py"
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))):
            self.assertEqual(ctx.cmd_hook(argparse.Namespace(min_tokens=10)), 0)
        self.assertEqual([r["op"] for r in self.ledger_records()], ["direct"])

    def test_report_splits_content_flow_from_recon_and_dedups(self):
        ctx.ledger_log("read", 100, 100, "f.txt")          # raw pull
        ctx.ledger_log("digest", 100, 20, "f.py")           # compressed pull
        ctx.ledger_log("map", 50000, 80, "/repo")           # recon, must not inflate %
        ctx.ledger_log("rlm", 4000, 40, "mapreduce:q", provider="gemini", calls=5)
        ctx.ledger_log("direct", 30, 30, "Read", tool_id="T9")
        ctx.ledger_log("direct", 30, 30, "Read", tool_id="T9")  # duplicate, must drop
        args = argparse.Namespace(price=5.0, reset=False, settle=0)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ctx.cmd_report(args), 0)
        text = out.getvalue()
        self.assertIn("CONTENT FLOW", text)
        self.assertIn("RECONNAISSANCE", text)               # map reported separately
        self.assertIn("tracked file-content coverage", text)
        # content saved = (100+100+4000+30) - (100+20+40+30) = 4040 of 4230 -> 95.5%
        self.assertIn("95.5%", text)
        self.assertIn("de-duplicated 1", text)              # the repeated T9 dropped
        self.assertIn("gemini", text)                       # provider breakdown present


if __name__ == "__main__":
    unittest.main()
