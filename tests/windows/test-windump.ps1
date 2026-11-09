# analyze-windump.ps1 테스트 (실제 덤프·cdb 없이, 가짜 cdb로)
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tests\windows\test-windump.ps1
#
# Windows PowerShell 5.1과 PowerShell 7 모두에서 돌아갑니다.
$ErrorActionPreference = "Stop"
# 도구가 UTF-8로 출력하므로 받는 쪽도 UTF-8로 읽습니다(한글 메시지 비교).
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$tool = Join-Path $root "winbin\analyze-windump.ps1"
$fake = Join-Path $PSScriptRoot "fake-cdb.ps1"
$shell = (Get-Process -Id $PID).Path
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("windump-test-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $tmp | Out-Null
$script:pass = 0
$script:fail = 0
$script:failed = @()

function Check([string]$desc, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host "  ok    $desc" }
    else { $script:fail++; $script:failed += $desc; Write-Host "  FAIL  $desc" }
}

# 도구를 새 프로세스로 실행해 출력과 종료 코드를 받습니다.
function Run([string]$case, [string[]]$extra) {
    $env:FAKE_CDB_CASE = $case
    $out = & $shell -NoProfile -ExecutionPolicy Bypass -File $tool @extra 2>&1 | Out-String
    return [pscustomobject]@{ Out = $out; Code = $LASTEXITCODE }
}

function Report-Of($r) {
    $m = [regex]::Match($r.Out, "(?m)^report:\s+(.+?)\s*$")
    if ($m.Success) { return [IO.File]::ReadAllText($m.Groups[1].Value) }
    return ""
}

function Json-Of($r) {
    $m = [regex]::Match($r.Out, "(?m)^json:\s+(.+?)\s*$")
    if ($m.Success) { return ([IO.File]::ReadAllText($m.Groups[1].Value) | ConvertFrom-Json) }
    return $null
}

try {
    $dumps = Join-Path $tmp "Minidump"
    New-Item -ItemType Directory -Path $dumps | Out-Null
    $old = Join-Path $dumps "110525-1-01.dmp"
    $new = Join-Path $dumps "110625-2-01.dmp"
    Set-Content -LiteralPath $old -Value "old" -Encoding ascii
    Set-Content -LiteralPath $new -Value "new" -Encoding ascii
    (Get-Item $old).LastWriteTime = (Get-Date).AddDays(-1)
    # 재부팅 직후 Windows가 만들어 두는 0바이트 미니덤프: 가장 새 파일이지만 고르지 않아야 합니다.
    $empty = Join-Path $dumps "110725-3-01.dmp"
    New-Item -ItemType File -Path $empty | Out-Null
    (Get-Item $empty).LastWriteTime = (Get-Date).AddMinutes(5)
    $out = Join-Path $tmp "logs"
    $common = @("-CdbPath", $fake, "-OutDir", $out, "-SymbolPath", "srv*$tmp\sym*https://example.invalid")

    Write-Host "analyze-windump"

    $r = Run "d1" @("-Version")
    Check "-Version" ($r.Code -eq 0 -and $r.Out -match "^analyze-windump \d+\.\d+\.\d+")
    $version = (Get-Content (Join-Path $root "VERSION") -TotalCount 1).Trim()
    Check "스크립트 버전이 VERSION($version)과 같음" ($r.Out -match [regex]::Escape("analyze-windump $version"))

    # 드라이버 오류(0xD1), 디렉터리를 주면 가장 최근 덤프
    $r = Run "d1" (@("-Dump", $dumps) + $common)
    $rep = Report-Of $r
    $j = Json-Of $r
    Check "D1: 종료 코드 0" ($r.Code -eq 0)
    Check "D1: 가장 최근 덤프 선택" ($rep -match [regex]::Escape("vmcore:    $new"))
    Check "D1: 유형 oops" ($rep -match "(?m)^type:\s+.+\[oops\]$")
    Check "D1: 근거에 버그체크 이름과 원인 드라이버" ($rep -match "evidence:  DRIVER_IRQL_NOT_LESS_OR_EQUAL 0xd1, 원인 후보: myfault.sys \(myfault\+12d0\)")
    Check "D1: PANIC 줄(웹 UI 기록용)" ($rep -match 'PANIC: "DRIVER_IRQL_NOT_LESS_OR_EQUAL \(0xd1\)"')
    Check "D1: 커널 버전 줄" ($rep -match "kernel:    Windows 10 Kernel Version 26100 MP")
    Check "D1: !analyze -v 섹션" ($rep -match "(?m)^===== cdb> !analyze -v =====$" -and $rep -match "MODULE_NAME: myfault")
    Check "D1: 다른 섹션(lm t n)" ($rep -match "(?m)^===== cdb> lm t n =====$" -and $rep -match "fake output: lm t n")
    Check "D1: 표시 줄은 리포트에 남지 않음" ($rep -notmatch "=====KDA=====")
    Check "D1: 실행 로그 섹션" ($rep -match "(?m)^===== cdb 실행 로그 \(exit 0\) =====$")
    # 프로세스 목록은 오래 걸려 기본에서 빼고 -ProcessList로만 넣습니다.
    Check "D1: 기본은 프로세스 목록 없음" ($rep -notmatch "(?m)^===== cdb> !process 0 0 =====$")
    $r2 = Run "d1" (@("-Dump", $new, "-ProcessList") + $common)
    Check "-ProcessList: 프로세스 목록 섹션" ((Report-Of $r2) -match "(?m)^===== cdb> !process 0 0 =====$")
    Check "D1: JSON 유형·버그체크" ($j -and $j.crash_type.type -eq "oops" -and $j.bugcheck.code -eq "0xd1" -and $j.bugcheck.image -eq "myfault.sys")
    Check "D1: JSON 원인 후보 모듈" ($j -and @($j.suspect_modules) -contains "myfault.sys")
    Check "D1: JSON 시스템 값" ($j -and $j.sys.UPTIME -eq "0 days 0:12:34.567" -and $j.os -eq "windows")
    Check "D1: 리포트는 UTF-8 (BOM 없음)" (([IO.File]::ReadAllBytes($j.report)[0..2] -join ",") -ne "239,187,191")

    # NMI 주입 (Hyper-V Debug-VM -InjectNonMaskableInterrupt)
    $r = Run "nmi" (@("-Dump", $new) + $common)
    Check "NMI: 유형 nmi" ((Report-Of $r) -match "(?m)^type:\s+.+\[nmi\]$")
    # 실제 Hyper-V NMI 덤프에서 !analyze는 GenuineIntel.sys를 지목하지만 원인이 아닙니다.
    Check "NMI: 처리 드라이버는 원인 후보가 아님" ((Report-Of $r) -match "(?m)^evidence:  NMI_HARDWARE_FAILURE 0x80, 처리 드라이버: GenuineIntel.sys \(NMI")
    $jn = Json-Of $r
    Check "NMI: JSON 원인 후보 비어 있음" (@($jn.suspect_modules).Count -eq 0 -and $jn.bugcheck.image -eq "GenuineIntel.sys")

    # 수동 덤프
    $r = Run "manual" (@("-Dump", $new) + $common)
    Check "수동: 유형 sysrq(수동 덤프)" ((Report-Of $r) -match "(?m)^type:\s+.+\[sysrq\]$")

    # !analyze 결과가 비면 실패로 끝나지만 리포트는 남김
    $r = Run "empty" (@("-Dump", $new) + $common)
    Check "분석 실패: 종료 코드 2" ($r.Code -eq 2)
    Check "분석 실패: 판단 불가" ((Report-Of $r) -match "\[unknown\]")

    # 시간 제한
    $r = Run "hang" (@("-Dump", $new, "-TimeoutSec", "3") + $common)
    Check "시간 초과: 종료 코드 2" ($r.Code -eq 2)
    Check "시간 초과: 안내" ($r.Out -match "제한 시간")

    # JSON 끄기
    $r = Run "d1" (@("-Dump", $new, "-NoJson") + $common)
    Check "JSON 끄기" ($r.Code -eq 0 -and $r.Out -notmatch "(?m)^json:")

    # 오류 경로
    $r = Run "d1" (@("-Dump", (Join-Path $tmp "none.dmp")) + $common)
    Check "덤프 없음: 종료 코드 1" ($r.Code -eq 1 -and $r.Out -match "덤프 파일을 찾을 수 없습니다")
    $r = Run "d1" (@("-Dump", $empty) + $common)
    Check "빈 덤프: 종료 코드 1과 안내" ($r.Code -eq 1 -and $r.Out -match "덤프 파일이 비어 있습니다")
    $r = Run "d1" @("-Dump", $new, "-CdbPath", (Join-Path $tmp "no-cdb.exe"), "-OutDir", $out)
    Check "cdb 없음: 종료 코드 1" ($r.Code -eq 1 -and $r.Out -match "cdb.exe를 찾을 수 없습니다")
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\FAKE_CDB_CASE -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "통과 $($script:pass), 실패 $($script:fail)"
if ($script:fail -gt 0) {
    $script:failed | ForEach-Object { Write-Host "  실패: $_" }
    exit 1
}
exit 0
