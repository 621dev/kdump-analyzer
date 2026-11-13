<#
.SYNOPSIS
    Windows 메모리 덤프(블루스크린)를 cdb로 분석해 리포트와 JSON 요약을 만듭니다.

.DESCRIPTION
    kdump-analyzer의 Windows용 분석 스크립트입니다. Linux의 analyze-kdump -r과 같은 형식의 리포트를 만들어
    웹 UI의 분석 기록, 요약 상자, LLM 분석을 그대로 쓸 수 있게 합니다.

      analyze-windump.ps1                          # 가장 최근 덤프(C:\Windows\MEMORY.DMP, Minidump)
      analyze-windump.ps1 -Dump C:\Windows\MEMORY.DMP
      analyze-windump.ps1 -Dump C:\Windows\Minidump
      analyze-windump.ps1 -ProcessList                # 프로세스 목록(!process 0 0)도 넣기 (커널 덤프에서 1~2분 더 걸림)
      analyze-windump.ps1 -Version

    필요한 것: Debugging Tools for Windows(cdb.exe), 심볼 서버 접속(또는 -SymbolPath로 지정한 사내 심볼 저장소)
    Windows PowerShell 5.1에서 동작합니다.

    종료 코드
      0: 정상
      1: 사용법/환경/입력 오류
      2: cdb 실행 실패 또는 시간 초과 (리포트는 남을 수 있음)
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Dump = "",
    [string]$OutDir = "",
    [string]$CdbPath = "",
    [string]$SymbolPath = "",
    [int]$TimeoutSec = 1800,
    [string[]]$Commands = @(),
    [switch]$ProcessList,
    [switch]$NoJson,
    [switch]$Version
)

$ErrorActionPreference = "Stop"
# 출력은 UTF-8로 내보냅니다(원격에서 SSH로 읽을 때 한글이 깨지지 않게).
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$ScriptVersion = "1.28.0"
$Marker = "=====KDA====="

# ---------------------------------------------------------------- 기본 위치

# 설치 위치: <base>\bin\analyze-windump.ps1 로 설치돼 있으면 <base>, 아니면(무설치 실행 등) C:\ProgramData\kdump-analyzer
function Get-ToolBase {
    $root = $PSScriptRoot
    if ($root -and (Split-Path -Leaf $root) -eq "bin" -and (Test-Path (Join-Path (Split-Path -Parent $root) ".install-info"))) {
        return (Split-Path -Parent $root)
    }
    return (Join-Path $env:ProgramData "kdump-analyzer")
}

function Get-Setting([string]$name, [string]$default) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($value) { return $value }
    return $default
}

# ---------------------------------------------------------------- 덤프 찾기

function Get-DumpCandidates([string]$path) {
    $items = @()
    if (-not $path) {
        $windir = $env:SystemRoot
        if (-not $windir) { $windir = "C:\Windows" }
        $items += Get-Item -LiteralPath (Join-Path $windir "MEMORY.DMP") -ErrorAction SilentlyContinue
        $items += Get-ChildItem -LiteralPath (Join-Path $windir "Minidump") -Filter *.dmp -File -ErrorAction SilentlyContinue
    } elseif (Test-Path -LiteralPath $path -PathType Container) {
        $items += Get-ChildItem -LiteralPath $path -Filter *.dmp -File -ErrorAction SilentlyContinue
    } else {
        $items += Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
    }
    # 블루스크린 뒤 재부팅 직후에는 Windows가 미니덤프를 0바이트로 만들어 두고 채웁니다. 빈 파일은 고르지 않습니다.
    return @($items | Where-Object { $_ -and $_.Length -gt 0 } | Sort-Object LastWriteTime -Descending)
}

# ---------------------------------------------------------------- cdb 찾기

function Find-Cdb([string]$explicit) {
    # -CdbPath로 직접 지정했으면 그 경로만 씁니다. 없을 때 다른 cdb로 조용히 넘어가지 않습니다.
    if ($explicit) {
        if (Test-Path -LiteralPath $explicit -PathType Leaf) { return (Resolve-Path -LiteralPath $explicit).Path }
        return $null
    }
    $candidates = @()
    $fromEnv = [Environment]::GetEnvironmentVariable("KDUMP_CDB")
    if ($fromEnv) { $candidates += $fromEnv }
    foreach ($pf in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if ($pf) { $candidates += (Join-Path $pf "Windows Kits\10\Debuggers\x64\cdb.exe") }
    }
    $onPath = Get-Command cdb.exe -ErrorAction SilentlyContinue
    if ($onPath) { $candidates += $onPath.Source }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c -PathType Leaf)) { return (Resolve-Path -LiteralPath $c).Path }
    }
    return $null
}

# ---------------------------------------------------------------- 장애 유형 (버그체크 코드)

# 버그체크 코드 -> (키, 설명). 키는 Linux 리포트와 같은 이름을 최대한 씁니다(웹 UI 배지 색이 같게).
$BugcheckTypes = @{
    "0xa" = @("oops", "커널 예외 (잘못된 IRQL에서 메모리 접근)")
    "0xd1" = @("oops", "커널 예외 (드라이버가 잘못된 IRQL에서 메모리 접근)")
    "0x50" = @("oops", "커널 예외 (잘못된 메모리 주소 참조)")
    "0x1e" = @("oops", "커널 예외 (처리되지 않은 커널 모드 예외)")
    "0x3b" = @("oops", "커널 예외 (시스템 서비스 처리 중 예외)")
    "0x7e" = @("oops", "커널 예외 (시스템 스레드의 처리되지 않은 예외)")
    "0x7f" = @("oops", "커널 예외 (예상치 못한 커널 모드 트랩)")
    "0x8e" = @("oops", "커널 예외 (처리되지 않은 커널 모드 예외)")
    "0x139" = @("oops", "커널 예외 (커널 보안 검사 실패, 구조 손상)")
    "0x19" = @("memory", "메모리 풀 손상")
    "0xc2" = @("memory", "메모리 풀 사용 오류")
    "0xc5" = @("memory", "메모리 풀 손상 (드라이버)")
    "0x1a" = @("memory", "메모리 관리 오류")
    "0x4e" = @("memory", "메모리 페이지 목록(PFN) 손상")
    "0x133" = @("soft_lockup", "CPU 지연 (DPC watchdog 위반)")
    "0x101" = @("hard_lockup", "CPU 응답 없음 (clock watchdog 시간 초과)")
    "0x9f" = @("hung_task", "드라이버 전원 상태 전환 응답 없음")
    "0x9e" = @("hung_task", "사용자 모드 상태 감시 시간 초과 (클러스터 등)")
    "0xef" = @("critical_process", "핵심 시스템 프로세스 종료")
    "0xf4" = @("critical_process", "핵심 시스템 프로세스 종료")
    "0x124" = @("mce", "하드웨어 오류 (WHEA 복구 불가 오류)")
    "0x9c" = @("mce", "하드웨어 오류 (Machine Check)")
    "0x80" = @("nmi", "NMI (하드웨어 또는 NMI 주입)")
    "0xe2" = @("sysrq", "수동 덤프 (키보드·명령으로 일으킨 크래시)")
    "0xdeaddead" = @("sysrq", "수동 덤프 (키보드로 일으킨 크래시)")
    "0x1c8" = @("sysrq", "수동 덤프 (전원 버튼 길게 누름)")
    "0x7b" = @("storage", "부팅 장치에 접근할 수 없음")
    "0xed" = @("storage", "부팅 볼륨을 마운트할 수 없음")
    "0x77" = @("storage", "커널 데이터 페이지 읽기 오류 (디스크)")
    "0x7a" = @("storage", "커널 데이터 페이지 읽기 오류 (디스크·페이지 파일)")
}

# !analyze -v 출력에서 "KEY: 값" 줄 읽기
function Get-AnalyzeField([string]$text, [string]$key) {
    $m = [regex]::Match($text, "(?m)^" + [regex]::Escape($key) + ":\s*(.+?)\s*$")
    if ($m.Success) { return $m.Groups[1].Value }
    return ""
}

function Get-BugcheckInfo([string]$analyze, [string]$bugcheckSection) {
    $code = $null
    $raw = Get-AnalyzeField $analyze "BUGCHECK_CODE"
    if ($raw -match "^(0x)?([0-9a-fA-F]+)$") { $code = [Convert]::ToInt64($Matches[2], 16) }
    if ($null -eq $code -and $bugcheckSection -match "Bugcheck code ([0-9a-fA-F]+)") { $code = [Convert]::ToInt64($Matches[1], 16) }
    $name = Get-AnalyzeField $analyze "BUGCHECK_STR"
    if (-not $name) {
        # 예: "DRIVER_IRQL_NOT_LESS_OR_EQUAL (d1)" 형태의 줄
        $m = [regex]::Match($analyze, "(?m)^([A-Z][A-Z0-9_]{5,})\s+\(([0-9a-fA-F]+)\)\s*$")
        if ($m.Success) { $name = $m.Groups[1].Value }
    }
    return [pscustomobject]@{
        Code = $code
        Hex = $(if ($null -ne $code) { "0x{0:x}" -f $code } else { "" })
        Name = $name
        Module = Get-AnalyzeField $analyze "MODULE_NAME"
        Image = Get-AnalyzeField $analyze "IMAGE_NAME"
        Symbol = Get-AnalyzeField $analyze "SYMBOL_NAME"
        Process = Get-AnalyzeField $analyze "PROCESS_NAME"
        Bucket = Get-AnalyzeField $analyze "FAILURE_BUCKET_ID"
    }
}

function Get-CrashType($bc) {
    if ($null -eq $bc.Code) { return @("unknown", "판단 불가 (버그체크 코드를 찾지 못함)") }
    $entry = $BugcheckTypes[$bc.Hex]
    if ($entry) { return $entry }
    return @("other", "기타 버그체크")
}

# NMI·수동 덤프는 외부에서 일부러 낸 것이라 !analyze가 지목한 드라이버(GenuineIntel.sys, ntoskrnl.exe 등)는
# 그 순간 처리를 맡았을 뿐 원인이 아닙니다. 이 유형에서는 원인 후보로 내세우지 않습니다.
$NoSuspectTypes = @("nmi", "sysrq")

function Get-Suspects($bc, [string]$typeKey) {
    if ($NoSuspectTypes -contains $typeKey) { return @() }
    return @(@($bc.Image) | Where-Object { $_ })
}

function Get-Evidence($bc, [string]$typeKey) {
    $parts = @()
    $title = (@($bc.Name, $bc.Hex) | Where-Object { $_ }) -join " "
    if ($title) { $parts += $title }
    $suspect = (@($bc.Image, $(if ($bc.Symbol) { "($($bc.Symbol))" })) | Where-Object { $_ }) -join " "
    if ($suspect) {
        if ($NoSuspectTypes -contains $typeKey) {
            $parts += "처리 드라이버: $suspect (NMI·수동 덤프라 원인이 아님)"
        } else {
            $parts += "원인 후보: $suspect"
        }
    }
    return ($parts -join ", ")
}

# ---------------------------------------------------------------- cdb 실행

# cdb 명령과 섹션 표시를 만듭니다. .echo 줄은 출력을 섹션으로 나누는 표시입니다.
function Get-ReportCommands([string[]]$extra) {
    $list = @(
        "!analyze -v",
        ".bugcheck",
        "vertarget",
        "!thread",
        "kv",
        "!running -it",
        "lm t n",
        "!vm",
        "!locks"
    )
    # 프로세스 목록은 커널 메모리 덤프에서 1~2분이 걸려(실제 VM에서 분석 시간의 대부분) 기본에서 뺍니다.
    if ($ProcessList) { $list += "!process 0 0" }
    foreach ($c in $extra) { if ($c -and ($list -notcontains $c)) { $list += $c } }
    return $list
}

function Invoke-Cdb([string]$cdb, [string]$dumpPath, [string]$symbols, [string[]]$cmds, [string]$outFile, [int]$timeout) {
    $script = ($cmds | ForEach-Object { ".echo $Marker $_; $_" }) -join "; "
    $script += "; .echo $Marker END; q"
    # cdb 인자: -z 덤프, -y 심볼 경로, -c 실행할 명령, -lines 소스 줄 정보
    $argLine = "-lines -z `"$dumpPath`" -y `"$symbols`" -c `"$script`""
    if ($cdb -like "*.ps1") {
        # 테스트용 가짜 cdb(PowerShell 스크립트)
        $exe = (Get-Process -Id $PID).Path
        $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$cdb`" $argLine"
    } else {
        $exe = $cdb
    }
    $errFile = "$outFile.err"
    $p = Start-Process -FilePath $exe -ArgumentList $argLine -NoNewWindow -PassThru `
        -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    $start = Get-Date
    $last = $start
    while (-not $p.WaitForExit(2000)) {
        $elapsed = [int]((Get-Date) - $start).TotalSeconds
        if ($elapsed -ge $timeout) {
            try { Stop-Process -Id $p.Id -Force } catch { }
            # 끝낸 프로세스가 출력 파일을 놓을 때까지 잠시 기다립니다(바로 읽으면 "다른 프로세스가 사용 중"이 남).
            try { [void]$p.WaitForExit(10000) } catch { }
            return [pscustomobject]@{ ExitCode = 124; TimedOut = $true; Seconds = $elapsed }
        }
        if (((Get-Date) - $last).TotalSeconds -ge 15) {
            # 함수의 반환값에 섞이지 않도록 콘솔에 바로 씁니다.
            [Console]::Out.WriteLine(("cdb 실행 중 ({0}초, 처음에는 심볼을 내려받느라 오래 걸릴 수 있음)" -f $elapsed))
            $last = Get-Date
        }
    }
    $p.WaitForExit()
    $code = $p.ExitCode
    if ($null -eq $code) { $code = 0 }
    if (Test-Path -LiteralPath $errFile) {
        $err = Get-Content -LiteralPath $errFile -Raw -ErrorAction SilentlyContinue
        if ($err) { Add-Content -LiteralPath $outFile -Value $err -Encoding UTF8 }
        Remove-Item -LiteralPath $errFile -ErrorAction SilentlyContinue
    }
    return [pscustomobject]@{ ExitCode = $code; TimedOut = $false; Seconds = [int]((Get-Date) - $start).TotalSeconds }
}

# 다른 프로세스가 아직 쥐고 있을 수 있는 파일을 공유 모드로 읽습니다. 시간 초과로 cdb를 끝낸 직후에는
# 파일 핸들이 잠시 남아 있어, 그대로 읽으면 실패하고 리포트를 남기지 못했습니다.
function Read-SharedText([string]$path) {
    for ($i = 0; $i -lt 10; $i++) {
        try {
            $fs = New-Object IO.FileStream($path, [IO.FileMode]::Open, [IO.FileAccess]::Read,
                ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
            try {
                $reader = New-Object IO.StreamReader($fs, [Text.Encoding]::UTF8, $true)
                return $reader.ReadToEnd()
            } finally { $fs.Dispose() }
        } catch [IO.IOException] {
            Start-Sleep -Milliseconds 500
        }
    }
    return ""
}

# cdb 출력을 섹션(명령별 출력)으로 나눕니다. 표시 줄 앞에 프롬프트가 붙는 경우도 있어 줄 안에서 찾습니다.
function Split-CdbOutput([string]$text) {
    $sections = [ordered]@{}
    $log = New-Object System.Collections.Generic.List[string]
    $current = $null
    $buffer = $null
    foreach ($line in ($text -split "`r?`n")) {
        $idx = $line.IndexOf($Marker + " ")
        if ($idx -ge 0 -and $line -notmatch "\.echo\s+$([regex]::Escape($Marker))") {
            if ($null -ne $current) { $sections[$current] = ($buffer -join "`n").Trim("`n") }
            $name = $line.Substring($idx + $Marker.Length + 1).Trim()
            if ($name -eq "END") { $current = $null; $buffer = $null; continue }
            $current = $name
            $buffer = New-Object System.Collections.Generic.List[string]
            continue
        }
        if ($null -ne $current) {
            # cdb가 명령 줄을 다시 보여 주는 프롬프트 줄은 섹션 내용에서 뺍니다.
            if ($line -match "^\d+: kd> " -or $line -match "^\d+:\d+> ") { continue }
            $buffer.Add($line)
        } else {
            $log.Add($line)
        }
    }
    if ($null -ne $current) { $sections[$current] = ($buffer -join "`n").Trim("`n") }
    return [pscustomobject]@{ Sections = $sections; Log = ($log -join "`n").Trim() }
}

# ---------------------------------------------------------------- 리포트

function Get-OsLine([string]$vertarget) {
    foreach ($line in ($vertarget -split "`r?`n")) {
        if ($line -match "Windows .*Kernel Version") { return $line.Trim() }
    }
    return ""
}

function Get-VertargetValue([string]$vertarget, [string]$label) {
    $m = [regex]::Match($vertarget, "(?m)^" + [regex]::Escape($label) + ":\s*(.+?)\s*$")
    if ($m.Success) { return $m.Groups[1].Value }
    return ""
}

function Write-Report($ctx) {
    # 줄바꿈은 Linux 리포트와 같은 LF로 씁니다(웹 UI·LLM이 같은 방식으로 읽음).
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append("windows dump summary report" + "`n")
    [void]$sb.Append("generated: " + (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz") + "`n")
    [void]$sb.Append("vmcore:    " + $ctx.Dump + "`n")
    [void]$sb.Append("kernel:    " + $ctx.Kernel + "`n")
    [void]$sb.Append("os:        windows" + "`n")
    [void]$sb.Append("debugger:  " + $ctx.Cdb + "`n")
    [void]$sb.Append("symbols:   " + $ctx.Symbols + "`n")
    [void]$sb.Append("type:      " + $ctx.TypeLabel + " [" + $ctx.TypeKey + "]" + "`n")
    if ($ctx.Evidence) { [void]$sb.Append("evidence:  " + $ctx.Evidence + "`n") }
    if ($ctx.Panic) { [void]$sb.Append("PANIC: `"" + $ctx.Panic + "`"`n") }
    foreach ($name in $ctx.Sections.Keys) {
        [void]$sb.Append("`n")
        [void]$sb.Append("===== cdb> $name =====" + "`n")
        [void]$sb.Append($ctx.Sections[$name] + "`n")
    }
    [void]$sb.Append("`n")
    [void]$sb.Append("===== cdb 실행 로그 (exit $($ctx.ExitCode)) =====" + "`n")
    [void]$sb.Append($ctx.Log + "`n")
    # UTF-8(BOM 없음)로 씁니다. 웹 UI·LLM이 UTF-8로 읽습니다.
    [IO.File]::WriteAllText($ctx.ReportFile, $sb.ToString(), (New-Object System.Text.UTF8Encoding $false))
}

function Write-Summary($ctx, $bc) {
    $sysInfo = [ordered]@{}
    if ($ctx.Kernel) { $sysInfo["OS"] = $ctx.Kernel }
    $uptime = Get-VertargetValue $ctx.Vertarget "System Uptime"
    if ($uptime) { $sysInfo["UPTIME"] = $uptime }
    if ($bc.Process) { $sysInfo["PROCESS"] = $bc.Process }
    $summary = [ordered]@{
        report = $ctx.ReportFile
        vmcore = $ctx.Dump
        kernel = $ctx.Kernel
        os = "windows"
        debugger = $ctx.Cdb
        crash_type = [ordered]@{ type = $ctx.TypeKey; label = $ctx.TypeLabel; evidence = $(if ($ctx.Evidence) { $ctx.Evidence } else { $null }) }
        bugcheck = [ordered]@{ code = $bc.Hex; name = $bc.Name; module = $bc.Module; image = $bc.Image; symbol = $bc.Symbol; bucket = $bc.Bucket }
        panic = $(if ($ctx.Panic) { $ctx.Panic } else { $null })
        sys = $sysInfo
        suspect_modules = @(Get-Suspects $bc $ctx.TypeKey)
        tainted_modules = @()
        module_symbols = @()
        crash_exit = [int]$ctx.ExitCode
        sections = @($ctx.Sections.Keys | ForEach-Object {
            [ordered]@{ title = "cdb> $_"; lines = @($ctx.Sections[$_] -split "`n").Count }
        })
    }
    $json = $summary | ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText($ctx.JsonFile, $json, (New-Object System.Text.UTF8Encoding $false))
}

# ---------------------------------------------------------------- 실행

if ($Version) {
    $base = Get-ToolBase
    $info = Join-Path $base ".install-info"
    $installed = ""
    if (Test-Path -LiteralPath $info) {
        $line = Select-String -LiteralPath $info -Pattern "^INSTALLED_AT=(.*)$" | Select-Object -First 1
        if ($line) { $installed = ", 설치 " + $line.Matches[0].Groups[1].Value }
    }
    Write-Output "analyze-windump $ScriptVersion$installed"
    exit 0
}

$dumps = Get-DumpCandidates $Dump
if (-not $dumps -or $dumps.Count -eq 0) {
    if ($Dump -and (Test-Path -LiteralPath $Dump -PathType Leaf)) {
        Write-Output "덤프 파일이 비어 있습니다: $Dump (재부팅 직후라면 Windows가 아직 쓰는 중일 수 있으니 잠시 뒤 다시 실행하세요)"
    }
    elseif ($Dump) { Write-Output "덤프 파일을 찾을 수 없습니다: $Dump" }
    else { Write-Output "덤프 파일을 찾을 수 없습니다 (C:\Windows\MEMORY.DMP, C:\Windows\Minidump\*.dmp)." }
    exit 1
}
$dumpFile = $dumps[0].FullName

$cdb = Find-Cdb $CdbPath
if (-not $cdb -and $CdbPath) {
    Write-Output "cdb.exe를 찾을 수 없습니다: -CdbPath로 지정한 $CdbPath 가 없습니다."
    exit 1
}
if (-not $cdb) {
    Write-Output "cdb.exe를 찾을 수 없습니다. Debugging Tools for Windows(Windows SDK)를 설치하거나 -CdbPath로 지정해 주세요."
    exit 1
}

$base = Get-ToolBase
if (-not $OutDir) { $OutDir = Get-Setting "REPORT_DIR" (Join-Path $base "logs") }
if (-not $SymbolPath) {
    $cache = Join-Path $base "symbols"
    $SymbolPath = Get-Setting "KDUMP_SYMBOL_PATH" "srv*$cache*https://msdl.microsoft.com/download/symbols"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$runId = (Get-Date).ToString("yyyyMMdd-HHmmss") + "-" + $PID
$reportFile = Join-Path $OutDir "kdump-report-$runId.txt"
$jsonFile = Join-Path $OutDir "kdump-report-$runId.json"
$rawFile = Join-Path $OutDir "kdump-report-$runId.cdb.log"

Write-Output "vmcore:  $dumpFile"
Write-Output "cdb:     $cdb"
Write-Output "symbols: $SymbolPath"

$cmds = Get-ReportCommands $Commands
$result = Invoke-Cdb $cdb $dumpFile $SymbolPath $cmds $rawFile $TimeoutSec
$raw = ""
if (Test-Path -LiteralPath $rawFile) {
    $raw = Read-SharedText $rawFile
    Remove-Item -LiteralPath $rawFile -ErrorAction SilentlyContinue
}
$parsed = Split-CdbOutput $raw
$sections = $parsed.Sections
$analyze = $(if ($sections.Contains("!analyze -v")) { $sections["!analyze -v"] } else { "" })
$bugcheckText = $(if ($sections.Contains(".bugcheck")) { $sections[".bugcheck"] } else { "" })
$vertarget = $(if ($sections.Contains("vertarget")) { $sections["vertarget"] } else { "" })

$bc = Get-BugcheckInfo $analyze $bugcheckText
$type = Get-CrashType $bc
$exitCode = $result.ExitCode
$logText = $parsed.Log
if ($result.TimedOut) { $logText = ("cdb가 제한 시간({0}초)을 넘겨 중단했습니다.`n" -f $TimeoutSec) + $logText }

$ctx = [pscustomobject]@{
    Dump = $dumpFile
    Kernel = Get-OsLine $vertarget
    Cdb = $cdb
    Symbols = $SymbolPath
    TypeKey = $type[0]
    TypeLabel = $type[1]
    Evidence = Get-Evidence $bc $type[0]
    Panic = (@($bc.Name, $(if ($bc.Hex) { "($($bc.Hex))" })) | Where-Object { $_ }) -join " "
    Sections = $sections
    Log = $logText
    ExitCode = $exitCode
    ReportFile = $reportFile
    JsonFile = $jsonFile
    Vertarget = $vertarget
}
Write-Report $ctx
Write-Output "type:    $($ctx.TypeLabel)"
Write-Output "report:  $reportFile"
if (-not $NoJson) {
    Write-Summary $ctx $bc
    Write-Output "json:    $jsonFile"
}
if ($result.TimedOut) {
    Write-Output "cdb가 제한 시간($TimeoutSec초)을 넘겨 중단했습니다. 리포트는 일부만 담겼을 수 있습니다."
    exit 2
}
if ($exitCode -ne 0) {
    Write-Output "cdb 실행이 실패했습니다 (종료 코드 $exitCode). 리포트 끝의 실행 로그를 확인해 주세요."
    exit 2
}
if ($null -eq $bc.Code) {
    # 심볼을 못 받는 등으로 !analyze가 버그체크를 읽지 못한 경우입니다.
    Write-Output "버그체크 코드를 찾지 못했습니다. 심볼 경로(-SymbolPath, 인터넷 또는 사내 심볼 저장소)와 리포트 끝의 실행 로그를 확인해 주세요."
    exit 2
}
exit 0
