"""웹 UI에 문자열로 들어 있는 원격 셸 스크립트(REMOTE_*, DUMP_LIST_SH)를 shellcheck로 검사합니다.

    python3 tests/shellcheck-embedded.py

원격 서버에서 sh -c로 실행하므로 POSIX sh 기준(-s sh)으로 봅니다. shellcheck가 없으면 건너뜁니다.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "webui"))
spec = importlib.util.spec_from_file_location("kdump_webui", os.path.join(ROOT, "webui", "kdump-webui.py"))
webui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(webui)

if not shutil.which("shellcheck"):
    print("shellcheck가 없어 건너뜁니다.")
    sys.exit(0)

# 임시 파일은 저장소 밖에 있어 .shellcheckrc를 찾지 못하므로, 그 파일의 disable 목록을 직접 넘깁니다.
excludes = []
with open(os.path.join(ROOT, ".shellcheckrc"), encoding="utf-8") as f:
    for line in f:
        if line.strip().startswith("disable="):
            excludes += [code.strip() for code in line.split("=", 1)[1].split(",") if code.strip()]

names = sorted(n for n in dir(webui)
               if (n.startswith("REMOTE_") or n == "DUMP_LIST_SH") and isinstance(getattr(webui, n), str))
failed = []
with tempfile.TemporaryDirectory() as tmp:
    for name in names:
        path = os.path.join(tmp, name + ".sh")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            # 원격에서 sh -c '<스크립트>' sh <인자...>로 실행하는 스크립트입니다.
            f.write("#!/bin/sh\n" + getattr(webui, name) + "\n")
        cmd = ["shellcheck", "-s", "sh", "-f", "gcc"] + (["-e", ",".join(excludes)] if excludes else []) + [path]
        result = subprocess.run(cmd,
                                capture_output=True, text=True, cwd=ROOT)
        status = "ok" if result.returncode == 0 else "FAIL"
        print("%-4s %s" % (status, name))
        if result.returncode != 0:
            failed.append(name)
            print(result.stdout.replace(path, name))
sys.exit(1 if failed else 0)
