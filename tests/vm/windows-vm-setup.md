# Windows Server 테스트 VM 준비

Windows 메모리 덤프 분석(`winbin/analyze-windump.ps1`)을 실제 블루스크린 덤프로 검증하기 위한 Hyper-V VM 준비 순서입니다.
**테스트 전용 VM에서만** 하세요. 마지막 단계에서 일부러 블루스크린을 냅니다.

## 1. VM 만들기 (호스트, 관리자 PowerShell)

Windows Server 평가판 ISO(예: Windows Server 2025 Evaluation)를 Microsoft Evaluation Center에서 받아 둡니다.

```powershell
$name = "kdump-win"
$dir  = "C:\HyperV\$name"
$iso  = "C:\HyperV\iso\WindowsServer2025_Eval.iso"   # 받은 ISO 경로로 바꿔 주세요

New-VM -Name $name -Generation 2 -MemoryStartupBytes 4GB -Path $dir `
       -NewVHDPath "$dir\$name.vhdx" -NewVHDSizeBytes 60GB -SwitchName "Default Switch"
Set-VMMemory -VMName $name -DynamicMemoryEnabled $false   # 동적 메모리는 덤프를 방해할 수 있어 끕니다
Set-VMProcessor -VMName $name -Count 2
Add-VMDvdDrive -VMName $name -Path $iso
Set-VMFirmware -VMName $name -FirstBootDevice (Get-VMDvdDrive -VMName $name)
Start-VM -Name $name
vmconnect localhost $name
```

화면에서 Windows Server를 설치합니다(데스크톱 환경이든 Core든 상관없습니다). Administrator 비밀번호를 정합니다.

## 2. OpenSSH 서버와 키 등록 (VM 안, 관리자 PowerShell)

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service sshd -StartupType Automatic

# 관리자 계정은 이 파일의 키로 접속합니다. 아래 키는 C:\HyperV\kdump-test\ssh\id_ed25519.pub 내용입니다.
$key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPn5FC63A4UZnj8htIP4ImNymVOmjXq4rGHMRF7tDeah kdump-test-vm'
Add-Content -Path C:\ProgramData\ssh\administrators_authorized_keys -Value $key -Encoding ascii
icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"

# 방화벽 규칙(보통 자동으로 생깁니다). Hyper-V Default Switch 네트워크는 보통 '공용'으로 잡히는데,
# 자동으로 생긴 규칙은 '개인(Private)'에만 열려 있을 수 있어 모든 프로필로 넓힙니다.
Set-NetFirewallRule -Name OpenSSH-Server-In-TCP -Profile Any
Get-NetFirewallRule -Name *OpenSSH* | Select-Object Name, Enabled, Profile
```

## 3. 덤프 설정 (VM 안, 관리자 PowerShell)

```powershell
$cc = "HKLM:\SYSTEM\CurrentControlSet\Control\CrashControl"
Set-ItemProperty $cc -Name CrashDumpEnabled -Value 2   # 커널 메모리 덤프 -> C:\Windows\MEMORY.DMP
Set-ItemProperty $cc -Name AutoReboot       -Value 1
Set-ItemProperty $cc -Name Overwrite        -Value 1
Set-ItemProperty $cc -Name NMICrashDump     -Value 1   # 호스트에서 NMI를 보내 블루스크린을 낼 수 있게
```

## 4. 디버깅 도구 설치 (VM 안)

Windows SDK 설치 파일(`winsdksetup.exe`)을 받아 **Debugging Tools for Windows만** 설치합니다.
아래 링크는 2026년 9월 기준 최신(10.0.28000.2957) 설치 관리자입니다. 바뀌었으면 [Windows SDK 다운로드 페이지](https://learn.microsoft.com/windows/apps/windows-sdk/downloads) 맨 위의 **설치 관리자** 링크를 쓰세요.

```powershell
cd $env:USERPROFILE\Downloads
Invoke-WebRequest "https://go.microsoft.com/fwlink/?linkid=2382519" -OutFile winsdksetup.exe
# /quiet 설치는 끝나기 전에 돌아올 수 있어 -Wait로 기다립니다.
Start-Process .\winsdksetup.exe -ArgumentList "/features OptionId.WindowsDesktopDebuggers /quiet /norestart" -Wait
Test-Path "${env:ProgramFiles(x86)}\Windows Kits\10\Debuggers\x64\cdb.exe"   # True면 준비 완료
```

심볼은 Microsoft 심볼 서버(`https://msdl.microsoft.com/download/symbols`)에서 자동으로 받으므로 VM에 인터넷이 필요합니다.

## 5. 재부팅 후 알려 줄 것

```powershell
Restart-Computer
# 재부팅 뒤
(Get-NetIPAddress -AddressFamily IPv4 | Where-Object InterfaceAlias -notlike "*Loopback*").IPAddress
```

IP 주소와 계정 이름(Administrator)을 알려 주시면, 웹 UI를 실행하는 컴퓨터에서 SSH 접속부터 확인합니다.

Hyper-V 기본 스위치(Default Switch)는 VM을 다시 켜거나 Hyper-V 호스트를 재부팅하면 IP를 새로 줍니다. 웹 UI의 접속 대상은 IP 대신 `Administrator@<컴퓨터 이름>.mshome.net`(예: `Administrator@WIN-AIEOPDLV85N.mshome.net`)으로 넣으면 IP가 바뀌어도 그대로 접속됩니다. 컴퓨터 이름은 VM에서 `hostname`으로 확인합니다.

## 6. 블루스크린 내기 (분석 시험 때, 호스트 관리자 PowerShell)

```powershell
Debug-VM -Name kdump-win -InjectNonMaskableInterrupt -Force
```

VM이 NMI로 블루스크린(`NMI_HARDWARE_FAILURE`, 0x80)을 내고 `C:\Windows\MEMORY.DMP`를 남긴 뒤 다시 켜집니다.
다른 종류의 장애(드라이버 오류 등)는 Sysinternals의 NotMyFault로 낼 수 있습니다.
