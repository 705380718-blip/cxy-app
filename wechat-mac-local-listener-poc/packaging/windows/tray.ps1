. (Join-Path $PSScriptRoot 'common.ps1')
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$context=Ensure-RuntimeEnvironment
$mutex=New-Object Threading.Mutex($false,('Local\WechatDeliveryTray-'+[Security.Principal.WindowsIdentity]::GetCurrent().User.Value))
$acquired=$false
try {
    try { $acquired=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $acquired=$true }
    if (-not $acquired) { return }
    $icon=New-Object Windows.Forms.NotifyIcon
    $icon.Icon=[Drawing.SystemIcons]::Application; $icon.Text='Wechat Delivery';$icon.Visible=$true
    $menu=New-Object Windows.Forms.ContextMenuStrip
    $open=$menu.Items.Add('Open');$open.add_Click({ Open-Organizer $context })
    $pause=$menu.Items.Add('Pause (stop service)');$pause.add_Click({ try { & (Join-Path $PSScriptRoot 'stop-service.ps1');$icon.Text='Wechat Delivery - paused' } catch { [Windows.Forms.MessageBox]::Show($_.Exception.Message) } })
    $resume=$menu.Items.Add('Resume');$resume.add_Click({ try { & (Join-Path $PSScriptRoot 'start-service.ps1') -NoTray; $icon.Text='Wechat Delivery' } catch { [Windows.Forms.MessageBox]::Show($_.Exception.Message) } })
    $quit=$menu.Items.Add('Stop and exit');$quit.add_Click({ try { & (Join-Path $PSScriptRoot 'stop-service.ps1');[Windows.Forms.Application]::ExitThread() } catch { [Windows.Forms.MessageBox]::Show($_.Exception.Message) } })
    $icon.ContextMenuStrip=$menu;$icon.add_DoubleClick({ Open-Organizer $context })
    [Windows.Forms.Application]::Run()
} finally { if ($null -ne (Get-Variable icon -ErrorAction SilentlyContinue)) { $icon.Visible=$false;$icon.Dispose() };if($acquired){$mutex.ReleaseMutex()};$mutex.Dispose() }
