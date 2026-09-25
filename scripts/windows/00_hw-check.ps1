# scripts/windows/00_hw-check.ps1
$cols = 'GPU','Name','VRAM_MiB','Used_MiB','Free_MiB','Driver','ComputeCap'
nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,driver_version,compute_cap --format=csv,noheader,nounits |
  ConvertFrom-Csv -Header $cols | ForEach-Object {
    [pscustomobject]@{
      GPU = $_.GPU.Trim(); Name = $_.Name.Trim()
      'VRAM (GB)' = [math]::Round([double]$_.VRAM_MiB / 1024, 1)
      'Used (GB)' = [math]::Round([double]$_.Used_MiB / 1024, 1)
      'Free (GB)' = [math]::Round([double]$_.Free_MiB / 1024, 1)
      Driver = $_.Driver.Trim(); 'Compute cap' = $_.ComputeCap.Trim()
    }
  } | Format-Table -AutoSize
$os = Get-CimInstance Win32_OperatingSystem; $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
[pscustomobject]@{ 'System RAM (GB)' = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1); CPU = $cpu.Name.Trim(); Cores = $cpu.NumberOfCores; Threads = $cpu.NumberOfLogicalProcessors } | Format-Table -AutoSize
