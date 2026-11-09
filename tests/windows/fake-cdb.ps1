# 테스트용 가짜 cdb. analyze-windump.ps1이 넘기는 인자(-z 덤프, -y 심볼, -c 명령)를 받아
# FAKE_CDB_CASE에 맞는 가짜 출력을 냅니다.
#   d1      DRIVER_IRQL_NOT_LESS_OR_EQUAL, 원인 myfault.sys
#   nmi     NMI_HARDWARE_FAILURE (Hyper-V NMI 주입과 같은 경우)
#   manual  MANUALLY_INITIATED_CRASH
#   empty   !analyze 결과 없음 (심볼 실패 등)
#   hang    끝나지 않음 (시간 제한 시험)
$script = ""
for ($i = 0; $i -lt $args.Count; $i++) {
    if ($args[$i] -eq "-c" -and $i + 1 -lt $args.Count) { $script = $args[$i + 1] }
}
$case = $env:FAKE_CDB_CASE
if (-not $case) { $case = "d1" }

"Microsoft (R) Windows Debugger Version 10.0.26100.1 AMD64 (fake)"
"Loading Dump File [fake]"
if ($case -eq "hang") { Start-Sleep -Seconds 60 }

$analyze = @{
    d1 = @"
*******************************************************************************
*                        Bugcheck Analysis                                    *
*******************************************************************************

DRIVER_IRQL_NOT_LESS_OR_EQUAL (d1)
An attempt was made to access a pageable (or completely invalid) address at an
interrupt request level (IRQL) that is too high.

BUGCHECK_CODE:  d1
BUGCHECK_P1: ffffc8058ab2c010
PROCESS_NAME:  System
STACK_TEXT:
ffff8d01`2a1f7c98 fffff803`1a40a729 : nt!KeBugCheckEx
ffff8d01`2a1f7ca0 fffff803`1a405f43 : nt!KiBugCheckDispatch+0x69
ffff8d01`2a1f7de0 fffff803`3c2b12d0 : myfault+0x12d0

SYMBOL_NAME:  myfault+12d0
MODULE_NAME: myfault
IMAGE_NAME:  myfault.sys
FAILURE_BUCKET_ID:  AV_myfault!unknown_function
"@
    nmi = @"
NMI_HARDWARE_FAILURE (80)
This is typically due to a hardware malfunction.

BUGCHECK_CODE:  80
PROCESS_NAME:  System
MODULE_NAME: GenuineIntel
IMAGE_NAME:  GenuineIntel.sys
FAILURE_BUCKET_ID:  0x80_4F4454_GenuineIntel_NOERRREC_IMAGE_GenuineIntel.sys
"@
    manual = @"
MANUALLY_INITIATED_CRASH (e2)
The user manually initiated this crash dump.

BUGCHECK_CODE:  e2
PROCESS_NAME:  System
IMAGE_NAME:  ntoskrnl.exe
"@
}

foreach ($part in ($script -split ";\s*")) {
    $cmd = $part.Trim()
    if (-not $cmd) { continue }
    if ($cmd -eq "q") { "quit:"; break }
    if ($cmd.StartsWith(".echo ")) { $cmd.Substring(6); continue }
    switch ($cmd) {
        "!analyze -v" { if ($analyze.ContainsKey($case)) { $analyze[$case] } else { "Unable to load image ntoskrnl.exe" } }
        ".bugcheck" {
            $code = @{ d1 = "000000D1"; nmi = "00000080"; manual = "000000E2" }[$case]
            if ($code) { "Bugcheck code $code" }
        }
        "vertarget" {
            "Windows 10 Kernel Version 26100 MP (2 procs) Free x64"
            "Built by: 26100.1.amd64fre.ge_release.240331-1435"
            "System Uptime: 0 days 0:12:34.567"
        }
        default { "fake output: $cmd" }
    }
}
exit 0
