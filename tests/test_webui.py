"""웹 UI(webui/kdump-webui.py)와 LLM 모듈(webui/kdump_llm.py) 단위 테스트.

    python -m unittest discover -s tests -v

네트워크와 SSH 없이 돌아갑니다. sh·setsid·base64가 필요한 테스트는 없으면 건너뜁니다(Windows 등).
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, "webui")
sys.path.insert(0, WEBUI)

import kdump_llm  # noqa: E402

_spec = importlib.util.spec_from_file_location("kdump_webui", os.path.join(WEBUI, "kdump-webui.py"))
webui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(webui)

HAS_SH = shutil.which("sh") is not None and os.name == "posix"


class MaskTextTest(unittest.TestCase):
    def test_masks_host_ip_mac_email(self):
        text = ("NODENAME: kdump-ubuntu.example.com\n"
                "connected to 10.1.2.3 from aa:bb:cc:dd:ee:ff by admin@example.com\n"
                "host kdump-ubuntu dm /dev/mapper/kdump--ubuntu-root\n"
                "RELEASE: 5.14.0-687.10.1.el9_8.0.1.x86_64\n")
        out = kdump_llm.mask_text(text)
        for secret in ("kdump-ubuntu", "kdump--ubuntu", "10.1.2.3", "aa:bb:cc:dd:ee:ff", "admin@example.com"):
            self.assertNotIn(secret, out)
        self.assertIn("<HOSTNAME>", out)
        self.assertIn("/dev/mapper/<HOSTNAME>-root", out)
        self.assertIn("<IPV4>", out)
        self.assertIn("<MAC>", out)
        self.assertIn("<EMAIL>", out)
        # 커널 버전 같은 점 구분 숫자는 IP로 보지 않습니다.
        self.assertIn("5.14.0-687.10.1.el9_8.0.1.x86_64", out)

    def test_short_hostname_not_overmasked(self):
        out = kdump_llm.mask_text("NODENAME: db\nthe db01 table\n")
        self.assertIn("db01", out)  # 3글자 미만 이름은 마스킹하지 않음


class FitTest(unittest.TestCase):
    def report(self):
        parts = ["kdump summary report\nvmcore: /var/crash/x/vmcore\n"]
        for title, lines in (("crash> sys", 20), ("crash> bt", 50), ("crash> log", 4000), ("crash> ps", 3000)):
            parts.append("\n===== %s =====\n" % title + "".join("%s line %d\n" % (title, i) for i in range(lines)))
        return "".join(parts)

    def test_short_text_unchanged(self):
        text = self.report()
        self.assertEqual(kdump_llm.fit(text, len(text) + 10), text)

    def test_fits_limit_and_keeps_small_sections(self):
        text = self.report()
        limit = 20000
        out = kdump_llm.fit(text, limit)
        self.assertLess(len(out), limit + 500)  # 잘린 표시 문구만큼은 넘을 수 있음
        self.assertTrue(out.startswith("kdump summary report"))
        self.assertIn("crash> sys line 19", out)   # 짧은 섹션은 그대로
        self.assertIn("crash> log line 3999", out)  # log는 뒤쪽을 남김
        for title in ("crash> sys", "crash> bt", "crash> log", "crash> ps"):
            self.assertIn("===== %s =====" % title, out)


class SettingsTest(unittest.TestCase):
    def test_update_source_defaults(self):
        self.assertEqual(webui.update_source({}), ("621dev/kdump-analyzer", "release", "main"))

    def test_update_source_invalid_channel_falls_back(self):
        repo, channel, branch = webui.update_source({"update_channel": "nightly", "update_branch": "dev"})
        self.assertEqual((channel, branch), ("release", "dev"))

    def test_crash_timeout_clamped(self):
        self.assertEqual(webui.crash_timeout_seconds({}), 30 * 60)
        self.assertEqual(webui.crash_timeout_seconds({"crash_timeout": 0}), 30 * 60)  # 0은 기본값
        self.assertEqual(webui.crash_timeout_seconds({"crash_timeout": 99999}), 1440 * 60)
        self.assertEqual(webui.crash_timeout_seconds({"crash_timeout": "abc"}), 30 * 60)

    def test_human_duration(self):
        self.assertEqual(webui.human_duration(7200), "2시간")
        self.assertEqual(webui.human_duration(1800), "30분")
        self.assertEqual(webui.human_duration(90), "90초")

    def test_repo_and_branch_patterns(self):
        self.assertTrue(webui.REPO_RE.match("621dev/kdump-analyzer"))
        self.assertFalse(webui.REPO_RE.match("../etc/passwd"))
        self.assertFalse(webui.REPO_RE.match("a/b; rm -rf /"))
        self.assertTrue(webui.BRANCH_RE.match("v1.18.2"))
        self.assertFalse(webui.BRANCH_RE.match("main; reboot"))

    def test_ssh_target_rejects_option_injection(self):
        self.assertTrue(webui.valid_ssh_target("tester@172.17.180.124"))
        self.assertTrue(webui.valid_ssh_target("db01"))
        for bad in ("", "-oProxyCommand=calc", "-p22", "user@host extra", "user@host\n"):
            self.assertFalse(webui.valid_ssh_target(bad), repr(bad))
        with self.assertRaises(webui.ApiError):
            webui.ssh_args({"name": "x", "target": "-oProxyCommand=calc", "port": 22})
        args = webui.ssh_args({"name": "x", "target": "tester@host", "port": 2222, "key_file": "k"})
        self.assertEqual(args[-1], "tester@host")
        self.assertIn("2222", args)

    def test_default_install_path_follows_repo_name(self):
        self.assertEqual(webui.DEFAULT_SERVER["tool"], "/opt/kdump-analyzer/bin/analyze-kdump")
        self.assertEqual(webui.vmlinux_base({"tool": ""}), "/opt/kdump-analyzer/vmlinux")
        self.assertEqual(webui.vmlinux_base({"tool": "/srv/x/bin/analyze-kdump"}), "/srv/x/vmlinux")
        # 원격 스크립트에는 예전 설치 위치 보정이 앞에 붙습니다.
        for name in ("REMOTE_CHECK", "REMOTE_PREPARE", "REMOTE_INSTALL"):
            self.assertTrue(getattr(webui, name).startswith(webui.INSTALL_FALLBACK_SH), name)

    @unittest.skipUnless(HAS_SH, "sh가 필요합니다")
    def test_install_fallback_keeps_other_paths(self):
        # 새 기본 위치가 아닌 경로나 다른 인자는 그대로 넘깁니다(이 테스트 환경에는 /opt 설치가 없다고 가정하지 않음).
        script = webui.with_install_fallback('printf "%s|" "$@"', 2)
        out = subprocess.run(["sh", "-c", script, "sh", "a b", "/srv/x/vmlinux", "c"],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(out, "a b|/srv/x/vmlinux|c|")

    def test_tool_version_line(self):
        m = webui.TOOL_VERSION_RE.match("analyze-kdump 1.18.2 (commit abc1234), 설치 2026-11-06 04:43")
        self.assertEqual(m.groups(), ("1.18.2", "abc1234", "2026-11-06 04:43"))
        m = webui.TOOL_VERSION_RE.match("analyze-kdump 1.18.0, 설치 2026-11-06 04:43")
        self.assertEqual(m.groups(), ("1.18.0", None, "2026-11-06 04:43"))


class ReportSummaryTest(unittest.TestCase):
    REPORT = ("kdump summary report\n"
              "generated: 2026-11-06T04:10:43+00:00\n"
              "vmcore:    /var/crash/x/vmcore\n"
              "kernel:    5.14.0-687.el9.x86_64\n"
              "type:      hung task (D 상태로 오래 멈춘 태스크) [hung_task]\n"
              "evidence:  INFO: task kf_lock_waiter:2082 blocked for more than 30 seconds.\n"
              "\n===== crash> sys =====\n"
              '       PANIC: "Kernel panic - not syncing: hung_task: blocked tasks"\n')

    def write(self, d, report=True, summary=None):
        path = os.path.join(d, "kdump-report-20261106-041043-1843.txt")
        if report:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.REPORT)
        if summary is not None:
            with open(webui.summary_path(path), "w", encoding="utf-8") as f:
                f.write(summary)
        return path

    def test_header_type_and_evidence_without_json(self):
        with tempfile.TemporaryDirectory() as d:
            info = webui.parse_result_head(self.write(d))
        self.assertEqual((info["type"], info["type_label"]), ("hung_task", "hung task (D 상태로 오래 멈춘 태스크)"))
        self.assertIn("blocked for more than 30 seconds", info["evidence"])
        self.assertIn("hung_task: blocked tasks", info["panic"])
        self.assertNotIn("summary", info)

    def test_json_summary(self):
        data = {"crash_type": {"type": "hung_task", "label": "hung task", "evidence": "INFO: task x blocked"},
                "panic": "Kernel panic - not syncing: hung_task: blocked tasks",
                "sys": {"UPTIME": "00:52:06", "LOAD AVERAGE": "1.29, 0.56, 0.36", "NODENAME": "db01", "TASKS": "135"},
                "uninterruptible_tasks": 2, "tainted_modules": ["kdump_fault"], "module_symbols": ["xfs"],
                "crash_exit": 0}
        import json
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, summary=json.dumps(data))
            s = webui.load_summary(path)
            info = webui.parse_result_head(path)
        self.assertEqual((s["type"], s["uninterruptible"], s["tainted"], s["modules"]), ("hung_task", 2, ["kdump_fault"], ["xfs"]))
        # 화면에 보일 sys 값만 남기고 호스트 이름(NODENAME)은 넣지 않습니다.
        self.assertEqual(s["sys"], {"UPTIME": "00:52:06", "LOAD AVERAGE": "1.29, 0.56, 0.36", "TASKS": "135"})
        self.assertEqual(info["summary"], {"uninterruptible": 2, "tainted": ["kdump_fault"], "crash_exit": 0})

    def test_broken_or_odd_json_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(webui.load_summary(self.write(d, summary="{not json")))
            self.assertIsNone(webui.load_summary(self.write(d, summary="[1, 2]")))
            s = webui.load_summary(self.write(d, summary='{"crash_type": "x", "tainted_modules": "y", "uninterruptible_tasks": "3"}'))
        self.assertEqual((s["type"], s["tainted"], s["uninterruptible"]), ("", [], None))

    def test_move_script_and_targets(self):
        self.assertEqual(webui.MOVE_TARGET, "/opt/kdump-analyzer")
        self.assertTrue(webui.REMOTE_MOVE.startswith(webui.INSTALL_FALLBACK_SH))
        self.assertIn("--move-to", webui.REMOTE_MOVE)


class FetchLatestTest(unittest.TestCase):
    SHA = "e45af84913fee73f8ad27dee9bab870e64beb5d0"

    def setUp(self):
        self.orig = webui._http_get
        self.calls = []

    def tearDown(self):
        webui._http_get = self.orig

    def fake(self, routes):
        def _get(url, accept=None, timeout=8):
            self.calls.append(url)
            for key, value in routes.items():
                if key in url:
                    if isinstance(value, Exception):
                        raise value
                    return value
            raise AssertionError("unexpected url " + url)
        webui._http_get = _get

    def test_release_channel(self):
        self.fake({
            "/releases/latest": b'{"tag_name": "v1.18.2", "name": "v1.18.2", "html_url": "https://example/r"}',
            "/commits/v1.18.2": self.SHA.encode(),
            "/VERSION": b"1.18.2\n",
        })
        r = webui.fetch_latest("621dev/kdump-analyzer", "release", "main")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["tag"], r["ref_kind"], r["version"], r["commit"]), ("v1.18.2", "tags", "1.18.2", self.SHA))

    def test_branch_channel(self):
        self.fake({"/commits/main": self.SHA.encode(), "/VERSION": b"1.19.0\n"})
        r = webui.fetch_latest("621dev/kdump-analyzer", "branch", "main")
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["ref"], r["ref_kind"], r["version"]), ("main", "heads", "1.19.0"))
        self.assertFalse(any("releases" in u for u in self.calls))

    def test_no_release_message(self):
        self.fake({"/releases/latest": urllib.error.HTTPError("u", 404, "Not Found", {}, None)})
        r = webui.fetch_latest("621dev/kdump-analyzer", "release", "main")
        self.assertFalse(r["ok"])
        self.assertIn("릴리스가 없습니다", r["error"])

    def test_bad_repo_rejected_without_network(self):
        self.fake({})
        r = webui.fetch_latest("bad repo", "release", "main")
        self.assertFalse(r["ok"])
        self.assertEqual(self.calls, [])


@unittest.skipUnless(HAS_SH, "sh가 필요합니다")
class ShellSnippetTest(unittest.TestCase):
    def test_dump_list(self):
        with tempfile.TemporaryDirectory() as d:
            for rel in ("a/vmcore", "b/vmcore.flat", "c/vmcore.flat", "c/vmcore",
                        "d/dump.202611060456", "e/dump-incomplete", "linux-image-x.crash"):
                os.makedirs(os.path.join(d, os.path.dirname(rel) or "."), exist_ok=True)
                open(os.path.join(d, rel), "w").close()
            out = subprocess.run(["sh", "-c", webui.DUMP_LIST_SH, "sh", d], capture_output=True, text=True, check=True)
            paths = sorted(os.path.relpath(line.split(" ", 2)[2], d) for line in out.stdout.splitlines())
            self.assertEqual(paths, ["a/vmcore", "b/vmcore.flat", "c/vmcore", "d/dump.202611060456"])

    @unittest.skipUnless(shutil.which("setsid"), "setsid가 필요합니다")
    def test_remote_timeout_kills_and_returns_124(self):
        argv = webui.with_remote_timeout(["sh", "-c", "sleep 30 & sleep 30"], 1)
        start = time.time()
        rc = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True).returncode
        self.assertEqual(rc, 124)
        self.assertLess(time.time() - start, 15)

    @unittest.skipUnless(shutil.which("setsid"), "setsid가 필요합니다")
    def test_remote_timeout_passes_stdin_and_exit_code(self):
        argv = webui.with_remote_timeout(["sh", "-c", "cat; exit 3"], 30)
        r = subprocess.run(argv, input=b"hello\n", capture_output=True)
        self.assertEqual((r.returncode, r.stdout), (3, b"hello\n"))

    @unittest.skipUnless(shutil.which("base64"), "base64가 필요합니다")
    def test_install_bundle_unpacks(self):
        bundle = webui.build_bundle()
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["sh", "-s", "--", d], input=bundle, check=True)
            for rel in webui.BUNDLE_FILES + ("bin/analyze-kdump", "bin/analyze-kdump-ui"):
                with open(os.path.join(ROOT, rel), "rb") as f:
                    want = f.read().replace(b"\r\n", b"\n")
                with open(os.path.join(d, rel), "rb") as f:
                    self.assertEqual(f.read(), want, rel)
            self.assertTrue(os.access(os.path.join(d, "bin/analyze-kdump"), os.X_OK))


if __name__ == "__main__":
    unittest.main()
