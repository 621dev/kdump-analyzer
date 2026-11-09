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
        self.assertEqual(info["summary"], {"uninterruptible": 2, "tainted": ["kdump_fault"], "crash_exit": 0, "suspect": []})

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


class WindowsServerTest(unittest.TestCase):
    SERVER = dict(webui.DEFAULT_SERVER, name="win01", target="Administrator@10.0.0.5", os="windows",
                  tool=webui.WIN_TOOL, crash_dir=webui.WIN_DUMP_DIR, sudo=True)

    def setUp(self):
        self.orig = (webui.ssh_text, webui.ssh_run)
        self.sent = []

    def tearDown(self):
        webui.ssh_text, webui.ssh_run = self.orig

    def decode(self, argv):
        import base64
        self.assertEqual(argv[:6], ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand"])
        return base64.b64decode(argv[6]).decode("utf-16-le")

    def test_command_has_no_sudo_and_needs_no_quoting(self):
        argv = webui.win_argv("'a b' + \"c\"")
        command = webui.remote_command(self.SERVER, argv)
        self.assertFalse(command.startswith("sudo"))
        self.assertEqual(command, " ".join(argv))  # base64라 따옴표가 붙지 않음
        self.assertLess(len(command), 8191)
        self.assertTrue(self.decode(argv).endswith("'a b' + \"c\""))

    def test_script_is_sent_by_scp_not_stdin(self):
        # Windows OpenSSH를 거친 PowerShell은 큰 표준 입력에서 불규칙하게 멈춥니다(실제 VM에서 확인). 스크립트는 scp로 보냅니다.
        _, name = webui.win_install_command(self.SERVER, "1.22.0", "abc", "t")
        self.assertRegex(name, r"^kdump-analyzer-[0-9a-f]{32}\.ps1$")
        _, name2 = webui.win_report_command(self.SERVER, r"C:\Windows\MEMORY.DMP", "upload", 60)
        self.assertNotEqual(name, name2)
        self.assertIsNone(webui.win_report_command(self.SERVER, r"C:\Windows\MEMORY.DMP", "installed", 60)[1])

    def test_split_stream_handles_crlf(self):
        # 실제 VM에서 \r\n 줄이 모두 진행 표시로 취급돼 report: 줄을 놓치던 문제
        pieces, rest = webui.split_stream("cdb 실행 중\r\nreport:  C:\\x.txt\r\njson:  C:\\x.json\r")
        self.assertEqual(pieces, [("cdb 실행 중", "\n"), ("report:  C:\\x.txt", "\n")])
        self.assertEqual(rest, "json:  C:\\x.json\r")  # 다음 조각의 \n을 기다림
        pieces, rest = webui.split_stream(rest + "\n")
        self.assertEqual((pieces, rest), ([("json:  C:\\x.json", "\n")], ""))
        # Linux의 진행 표시(\r로 갱신)와 일반 줄은 그대로
        pieces, rest = webui.split_stream("[1/3] a\r[2/3] b\rdone\nnext")
        self.assertEqual(pieces, [("[1/3] a", "\r"), ("[2/3] b", "\r"), ("done", "\n")])
        self.assertEqual(rest, "next")

    def test_stream_keeps_output_when_remote_stops_reading(self):
        # 원격이 표준 입력(설치 묶음)을 다 받기 전에 끝나도 BrokenPipeError 대신 원격의 이유가 로그에 남습니다.
        code = "import sys; print('no install prefix: x'); sys.stdout.flush(); sys.exit(3)"
        orig = webui.ssh_args
        webui.ssh_args = lambda server: [sys.executable, "-c", code]
        try:
            job = webui.Job("upgrade", "srv")
            jobs = webui.Jobs.__new__(webui.Jobs)
            rc, text = jobs._stream(job, dict(webui.DEFAULT_SERVER, name="srv", target="u@h"), ["true"],
                                    stdin=b"x" * (4 * 1024 * 1024), timeout=60)
        finally:
            webui.ssh_args = orig
        self.assertEqual(rc, 3)
        self.assertIn("no install prefix: x", text)

    def test_vmcore_path_follows_server_os(self):
        # 실제 VM에서 Windows 경로가 '/'로 시작하지 않는다고 분석 작업이 거부되던 문제
        linux = dict(self.SERVER, os="linux")
        self.assertTrue(webui.valid_vmcore_path(self.SERVER, r"C:\Windows\MEMORY.DMP"))
        self.assertTrue(webui.valid_vmcore_path(self.SERVER, r"D:\dumps\Minidump\110826-3234-01.dmp"))
        self.assertFalse(webui.valid_vmcore_path(self.SERVER, "/var/crash/x/vmcore"))
        self.assertFalse(webui.valid_vmcore_path(self.SERVER, "C:\\a\nb"))
        self.assertTrue(webui.valid_vmcore_path(linux, "/var/crash/x/vmcore"))
        self.assertFalse(webui.valid_vmcore_path(linux, r"C:\Windows\MEMORY.DMP"))
        self.assertFalse(webui.valid_vmcore_path(linux, None))

    def test_scp_upload_arguments(self):
        calls = []

        class Done:
            returncode, stdout = 0, b""

        orig = webui.subprocess.run
        webui.subprocess.run = lambda argv, **kw: (calls.append(argv), Done())[1]
        try:
            server = dict(self.SERVER, target="Administrator@172.17.178.80", port=2222, key_file="C:/k/id")
            self.assertEqual(webui.scp_upload(server, "a.ps1", "kdump-analyzer-x.ps1")[0], 0)
            with self.assertRaises(webui.ApiError):
                webui.scp_upload(server, "a.ps1", "../evil.ps1")
        finally:
            webui.subprocess.run = orig
        argv = calls[-1]
        self.assertEqual(argv[:2], ["scp", "-q"])
        self.assertEqual(argv[argv.index("-P") + 1], "2222")
        self.assertNotIn("-p", argv)
        self.assertEqual(argv[argv.index("-i") + 1], "C:/k/id")
        self.assertEqual(argv[-2:], ["a.ps1", "Administrator@172.17.178.80:kdump-analyzer-x.ps1"])

    def test_ps_quote(self):
        self.assertEqual(webui.ps_quote("C:\\it's"), "'C:\\it''s'")

    def test_list_vmcores_parses_powershell_output(self):
        def fake(server, argv, timeout=60):
            self.sent.append(self.decode(argv))
            return 0, "1793950000 1048576 C:\\Windows\\MEMORY.DMP\r\n1793940000 262144 C:\\Windows\\Minidump\\110625-1-01.dmp\r\n"
        webui.ssh_text = fake
        items = webui.list_vmcores(self.SERVER)
        self.assertEqual([i["path"] for i in items], ["C:\\Windows\\MEMORY.DMP", "C:\\Windows\\Minidump\\110625-1-01.dmp"])
        self.assertIn("'C:\\Windows'", self.sent[0])

    def test_fetch_remote_file_decodes_base64(self):
        import base64
        payload = "리포트\n".encode("utf-8")

        def fake(server, argv, stdin=None, timeout=60, data=False):
            self.sent.append(self.decode(argv))
            return 0, base64.b64encode(payload) + b"\r\n"
        webui.ssh_run = fake
        self.assertEqual(webui.fetch_remote_file(self.SERVER, "C:\\x\\r.txt"), (0, payload))
        self.assertIn("ReadAllBytes('C:\\x\\r.txt')", self.sent[0])

    def test_save_server_validates_windows(self):
        with tempfile.TemporaryDirectory() as d:
            store = webui.Store(d)
            saved = store.save_server(dict(self.SERVER))
            self.assertEqual((saved["os"], saved["sudo"]), ("windows", False))
            with self.assertRaises(webui.ApiError):
                store.save_server(dict(self.SERVER, tool="/opt/kdump-analyzer/bin/analyze-kdump"))
            with self.assertRaises(webui.ApiError):
                store.save_server(dict(self.SERVER, os="solaris"))

    def test_windows_summary_and_prompt(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "kdump-report-1.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("windows dump summary report\n")
            with open(webui.summary_path(path), "w", encoding="utf-8") as f:
                json.dump({"os": "windows", "crash_type": {"type": "oops"}, "suspect_modules": ["myfault.sys"]}, f)
            s = webui.load_summary(path)
        self.assertEqual((s["os"], s["suspect"]), ("windows", ["myfault.sys"]))
        system, _ = kdump_llm.build_input("windows dump summary report\n===== cdb> !analyze -v =====\nx\n", {"mask": False})
        self.assertIn("Windows kernel crash dump", system)
        system, _ = kdump_llm.build_input("kdump summary report\n", {"mask": False})
        self.assertIn("Linux kernel crash dump", system)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell이 필요합니다")
    def test_powershell_snippets_run_locally(self):
        # 이 PC에서 원격용 PowerShell 명령을 그대로 실행해 문법 오류가 없는지와 출력 형식을 확인합니다.
        def run(argv):
            r = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
            return r.returncode, r.stdout.decode("utf-8", errors="replace")

        webui.ssh_text = lambda server, argv, timeout=60: run(argv)
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "Minidump"))
            open(os.path.join(d, "Minidump", "1.dmp"), "wb").close()
            open(os.path.join(d, "MEMORY.DMP"), "wb").close()
            server = dict(self.SERVER, crash_dir=d, tool=os.path.join(d, "bin", "analyze-windump.ps1"))
            self.assertEqual(sorted(os.path.basename(i["path"]) for i in webui.list_vmcores(server)), ["1.dmp", "MEMORY.DMP"])
            info = webui.win_test_server(server)
            self.assertTrue(info["ok"], info)
            self.assertEqual((info["vmcores"], info["tool"]), ("2", ""))
            self.assertEqual(webui.win_server_version(server)["installed"], False)
            check = webui.win_prepare_check(server)
            self.assertEqual(check["family"], "Windows")
            self.assertIn("cdb", [i["id"] for i in check["items"]])
            self.assertIn(webui.probe_method(server), ("upload", "none"))

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell이 필요합니다")
    def test_install_and_report_end_to_end_locally(self):
        # SSH 대신 이 PC에서 그대로 실행: 노트북 버전 설치 -> 설치본 실행, 무설치 실행 -> 리포트 가져오기
        fake_cdb = os.path.join(ROOT, "tests", "windows", "fake-cdb.ps1")

        def run(argv, stdin=None, env=None):
            r = subprocess.run(argv, input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL,
                               capture_output=True, timeout=300, env=env)
            return r.returncode, r.stdout

        webui.ssh_run = lambda server, argv, stdin=None, timeout=60, data=False: run(argv, stdin)
        webui.ssh_text = lambda server, argv, timeout=60: (lambda c, o: (c, o.decode("utf-8", "replace")))(*run(argv))
        with tempfile.TemporaryDirectory() as d:
            d = os.path.realpath(d)  # 짧은 이름(GSITM-~1)을 실제 이름으로
            dumps = os.path.join(d, "Windows")
            os.makedirs(os.path.join(dumps, "Minidump"))
            dump = os.path.join(dumps, "MEMORY.DMP")
            open(dump, "wb").close()
            server = dict(self.SERVER, crash_dir=dumps, tool=os.path.join(d, "ka", "bin", "analyze-windump.ps1"))
            env = dict(os.environ, KDUMP_CDB=fake_cdb, FAKE_CDB_CASE="d1", REPORT_DIR=os.path.join(d, "upload-logs"))

            # scp 대신 이 PC의 홈 폴더(원격 명령이 보는 $HOME)에 복사합니다.
            home = os.path.expanduser("~")

            def upload(name):
                shutil.copyfile(webui.WIN_SCRIPT, os.path.join(home, name))

            # 설치
            argv, name = webui.win_install_command(server, "1.22.0", "abc1234", "webui:test")
            upload(name)
            code, out = run(argv)
            self.assertEqual(code, 0, out.decode("utf-8", "replace"))
            info = webui.win_server_version(server)
            self.assertEqual((info["installed"], info["version"], info["prefix"]), (True, webui.version_text(), os.path.join(d, "ka")))
            self.assertEqual(webui.probe_method(server), "installed")

            for method in ("installed", "upload"):
                argv, name = webui.win_report_command(server, dump, method, 60)
                if name:
                    upload(name)
                # 설치본은 설치 위치의 logs에, 무설치 실행은 REPORT_DIR에 씁니다.
                run_env = dict(env)
                if method == "installed":
                    run_env.pop("REPORT_DIR")
                code, out = run(argv, None, run_env)
                text = out.decode("utf-8", "replace")
                self.assertEqual(code, 0, text)
                report = [l.split(":", 1)[1].strip() for l in text.splitlines() if l.startswith("report:")][0]
                summary = [l.split(":", 1)[1].strip() for l in text.splitlines() if l.startswith("json:")][0]
                if method == "installed":
                    self.assertTrue(report.startswith(os.path.join(d, "ka", "logs")), report)  # 설치 위치의 logs
                else:
                    self.assertTrue(report.startswith(env["REPORT_DIR"]), report)
                code, data = webui.fetch_remote_file(server, report)
                self.assertEqual(code, 0)
                body = data.decode("utf-8")
                self.assertTrue(body.startswith("windows dump summary report\n"), method)
                self.assertIn("type:      커널 예외 (드라이버가 잘못된 IRQL에서 메모리 접근) [oops]", body)
                code, data = webui.fetch_remote_file(server, summary)
                self.assertEqual(json_loads(data)["bugcheck"]["image"], "myfault.sys")
            # 설치·무설치 실행 모두 보낸 임시 스크립트를 남기지 않습니다.
            leftovers = [f for f in os.listdir(home) if f.startswith("kdump-analyzer-") and f.endswith(".ps1")]
            self.assertEqual(leftovers, [])

            # 삭제: 프로그램만 -> bin·설치 정보만 지우고 logs는 남김
            base = os.path.join(d, "ka")
            code, out = run(webui.win_uninstall_command(server, "program"))
            self.assertEqual(code, 0, out.decode("utf-8", "replace"))
            self.assertFalse(os.path.exists(os.path.join(base, "bin")))
            self.assertFalse(os.path.exists(os.path.join(base, ".install-info")))
            self.assertTrue(os.path.isdir(os.path.join(base, "logs")))
            self.assertFalse(webui.win_server_version(server)["installed"])
            # 이미 지웠으면 실패(설치 정보도 스크립트도 없음)
            self.assertNotEqual(run(webui.win_uninstall_command(server, "program"))[0], 0)
            # 다시 설치한 뒤 전부 -> 설치 폴더 통째로
            argv, name = webui.win_install_command(server, "1.22.0", "abc1234", "webui:test")
            upload(name)
            self.assertEqual(run(argv)[0], 0)
            code, out = run(webui.win_uninstall_command(server, "all"))
            self.assertEqual(code, 0, out.decode("utf-8", "replace"))
            self.assertFalse(os.path.exists(base))

    def test_uninstall_refuses_unsafe_locations(self):
        # 드라이브 바로 아래(C:\bin\...)나 bin이 아닌 폴더는 지우지 않습니다.
        for tool in (r"C:\bin\analyze-windump.ps1", r"C:\ProgramData\kdump-analyzer\tools\analyze-windump.ps1"):
            script = self.decode(webui.win_uninstall_command(dict(self.SERVER, tool=tool), "all"))
            self.assertIn("-ne 'bin'", script)
            self.assertIn("$base.Length -le 3", script)
            if shutil.which("powershell") and os.name == "nt":
                r = subprocess.run(webui.win_uninstall_command(dict(self.SERVER, tool=tool), "all"),
                                   capture_output=True, timeout=60)
                self.assertEqual(r.returncode, 5, r.stdout.decode("utf-8", "replace"))

    def test_prepare_actions_follow_server_os(self):
        linux = dict(self.SERVER, os="linux")
        self.assertTrue(webui.valid_prepare_actions(self.SERVER, ["cdb", "dumpconf", "pagefile", "tool"]))
        self.assertFalse(webui.valid_prepare_actions(self.SERVER, ["kdump"]))
        self.assertFalse(webui.valid_prepare_actions(linux, ["cdb"]))
        self.assertTrue(webui.valid_prepare_actions(linux, ["kdump", "tool"]))
        self.assertFalse(webui.valid_prepare_actions(linux, []))
        self.assertFalse(webui.valid_prepare_actions(linux, "kdump"))

    def test_prepare_scripts_fit_and_parse(self):
        # cmd.exe 한 줄 제한(8191자) 안에 들어가고 PowerShell 문법 오류가 없어야 합니다.
        for action, script in webui.WIN_PREPARE.items():
            argv = webui.win_argv(script)
            self.assertLess(len(" ".join(argv)), 8000, action)
            self.assertIn(action, webui.WIN_PREPARE_ACTIONS)
        self.assertIn("Get-AuthenticodeSignature", webui.WIN_PREPARE["cdb"])
        self.assertIn("O=Microsoft Corporation", webui.WIN_PREPARE["cdb"])
        self.assertIn(webui.WIN_SDK_URL, webui.WIN_PREPARE["cdb"])
        argv = webui.win_uninstall_command(self.SERVER, "all")
        self.assertLess(len(" ".join(argv)), 8000)
        if not (shutil.which("powershell") and os.name == "nt"):
            return
        with tempfile.TemporaryDirectory() as d:
            for name, script in list(webui.WIN_PREPARE.items()) + [("uninstall", self.decode(argv))]:
                path = os.path.join(d, name + ".ps1")
                with open(path, "w", encoding="utf-8-sig") as f:
                    f.write(script)
                check = ("$e=$null;[void][Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e);"
                         "if($e){$e|ForEach-Object{$_.Message};exit 1}" % path)
                r = subprocess.run(["powershell", "-NoProfile", "-Command", check], capture_output=True, timeout=60)
                self.assertEqual(r.returncode, 0, "%s: %s" % (name, r.stdout.decode("utf-8", "replace")))

    def test_fetch_win_script_from_github(self):
        orig = (webui.fetch_latest, webui._http_get)
        info = {"ok": True, "ref": "v1.22.0", "commit": "e3b332d7543993a98d080368a6308aa086e7d769", "version": "1.22.0"}
        urls = []
        with open(webui.WIN_SCRIPT, "rb") as f:
            script = f.read()
        try:
            webui.fetch_latest = lambda repo, channel, branch, base="": dict(info)
            webui._http_get = lambda url, accept=None, timeout=8: (urls.append(url), script)[1]
            got, data = webui.fetch_win_script("621dev/kdump-analyzer", "release", "main")
            self.assertEqual(got["ref"], "v1.22.0")
            self.assertEqual(urls, ["https://raw.githubusercontent.com/621dev/kdump-analyzer/%s/winbin/analyze-windump.ps1" % info["commit"]])
            # 1.22.0 전 릴리스에는 스크립트가 없습니다.
            webui._http_get = lambda url, accept=None, timeout=8: (_ for _ in ()).throw(
                urllib.error.HTTPError(url, 404, "Not Found", {}, None))
            with self.assertRaises(webui.ApiError) as ctx:
                webui.fetch_win_script("621dev/kdump-analyzer", "release", "main")
            self.assertIn("1.22.0부터", ctx.exception.message)
            # 엉뚱한 내용은 거부
            webui._http_get = lambda url, accept=None, timeout=8: b"<html>not found</html>"
            with self.assertRaises(webui.ApiError):
                webui.fetch_win_script("621dev/kdump-analyzer", "release", "main")
            # GitHub 버전 확인 실패
            webui.fetch_latest = lambda repo, channel, branch, base="": {"ok": False, "error": "GitHub에 접속하지 못했습니다"}
            with self.assertRaises(webui.ApiError):
                webui.fetch_win_script("621dev/kdump-analyzer", "release", "main")
        finally:
            webui.fetch_latest, webui._http_get = orig


def json_loads(data):
    import json
    return json.loads(data.decode("utf-8"))


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

    def test_install_prefix_for_bare_command_name(self):
        # 서버 설정이 명령 이름(analyze-kdump)이고 등록된 명령이 없으면(삭제 뒤 다시 설치) 기본 위치를 씁니다.
        # 가짜 id(일반 사용자)로 root 확인에서 멈추게 해 실제로 설치하지는 않습니다.
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "id"), "w") as f:
                f.write("#!/bin/sh\necho 1000\n")
            os.chmod(os.path.join(d, "id"), 0o755)
            env = dict(os.environ, PATH=d + os.pathsep + "/usr/bin:/bin")

            def run(tool):
                return subprocess.run(["sh", "-c", webui.REMOTE_INSTALL, "sh", tool, "local", "r", "main", "", "t", "heads"],
                                      stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env)

            r = run("analyze-kdump")
            self.assertEqual(r.returncode, 4, r.stdout)  # 설치 위치는 정했고 root 확인에서 멈춤
            self.assertRegex(r.stdout, r"등록된 analyze-kdump 명령이 없어 /opt/kdump-(analyzer|tools) 에 설치합니다")
            r = run("kdump-thing")
            self.assertEqual(r.returncode, 3, r.stdout)
            self.assertIn("설치 위치를 알 수 없습니다", r.stdout)

    @unittest.skipIf(sys.platform == "win32", "심볼릭 링크와 readlink -f가 있는 Linux에서만 실행합니다")
    def test_remote_uninstall(self):
        # 가짜 id(root)로 임시 설치 위치를 지웁니다. 명령 등록 링크는 같은 설치를 가리키는 것만 지웁니다.
        with tempfile.TemporaryDirectory() as d:
            d = os.path.realpath(d)
            fakebin = os.path.join(d, "fakebin")
            os.makedirs(fakebin)
            with open(os.path.join(fakebin, "id"), "w") as f:
                f.write("#!/bin/sh\necho 0\n")
            os.chmod(os.path.join(fakebin, "id"), 0o755)
            env = dict(os.environ, PATH=fakebin + os.pathsep + os.environ["PATH"])

            def install():
                prefix, sbin = os.path.join(d, "ka"), os.path.join(d, "sbin")
                os.makedirs(os.path.join(prefix, "bin"), exist_ok=True)
                os.makedirs(os.path.join(prefix, "vmlinux"), exist_ok=True)
                os.makedirs(os.path.join(prefix, "completion"), exist_ok=True)
                os.makedirs(sbin, exist_ok=True)
                for name in ("analyze-kdump", "analyze-kdump-ui"):
                    path = os.path.join(prefix, "bin", name)
                    with open(path, "w") as f:
                        f.write("#!/bin/sh\n")
                    os.chmod(path, 0o755)
                    if not os.path.lexists(os.path.join(sbin, name)):
                        os.symlink(path, os.path.join(sbin, name))
                for name, text in (("install.sh", "#"), ("VERSION", "1.23.0\n"), ("analyze-kdump.conf", "KEEP=1\n"),
                                   (".install-info", "VERSION=1.23.0\nBIN_DIR=%s\n" % sbin)):
                    with open(os.path.join(prefix, name), "w") as f:
                        f.write(text)
                other = os.path.join(sbin, "other-tool")
                if not os.path.lexists(other):
                    os.symlink("/bin/true", other)
                return prefix, sbin

            def run(prefix, mode):
                argv = ["sh", "-c", webui.REMOTE_UNINSTALL, "sh", os.path.join(prefix, "bin", "analyze-kdump"), mode] \
                    + list(webui.PROGRAM_FILES)
                return subprocess.run(argv, capture_output=True, text=True, env=env)

            prefix, sbin = install()
            r = run(prefix, "program")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(sorted(os.listdir(prefix)), ["analyze-kdump.conf", "vmlinux"])  # 설정·vmlinux는 남김
            self.assertEqual(os.listdir(sbin), ["other-tool"])  # 다른 명령 링크는 그대로
            self.assertIn("남긴 것", r.stdout)

            prefix, sbin = install()
            r = run(prefix, "all")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertFalse(os.path.exists(prefix))
            self.assertEqual(os.listdir(sbin), ["other-tool"])

            # 설치가 아닌 곳과 위험한 위치는 지우지 않습니다.
            empty = os.path.join(d, "empty")
            os.makedirs(os.path.join(empty, "bin"))
            self.assertEqual(run(empty, "all").returncode, 5)
            self.assertTrue(os.path.isdir(empty))
            r = subprocess.run(["sh", "-c", webui.REMOTE_UNINSTALL, "sh", "/usr/bin/analyze-kdump", "all"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 5, r.stdout)

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
