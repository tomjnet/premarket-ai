#!/usr/bin/env bash
# scripts/wsl/04_hw-check.sh
if command -v nvidia-smi >/dev/null 2>&1; then
  { echo "GPU,Name,VRAM_GB,Used_GB,Free_GB,Driver,ComputeCap"
    nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,driver_version,compute_cap \
               --format=csv,noheader,nounits |
    awk -F', ' '{printf "%s,%s,%.1f,%.1f,%.1f,%s,%s\n",$1,$2,$3/1024,$4/1024,$5/1024,$6,$7}'
  } | column -t -s,
else
  echo "nvidia-smi not found (no NVIDIA driver?). GPUs seen by the OS:"; lspci | grep -Ei 'vga|3d'
fi
echo
{ echo "RAM_GB,CPU,Cores,Threads"
  echo "$(awk '/MemTotal/{printf "%.1f",$2/1048576}' /proc/meminfo),$(lscpu | sed -n 's/^Model name:[[:space:]]*//p'),$(lscpu -p=core | grep -v '^#' | sort -u | wc -l),$(nproc)"
} | column -t -s,
