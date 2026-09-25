# Setup scripts

The project runs in **Podman inside Ubuntu-24.04 on WSL2**. Only **Ollama and the local models** run natively on Windows. Details are in [PLAN.md](../docs/PLAN.md) under "Runtime topology" and "WSL configuration files".

Run these **once**, in file-name order: first all of `windows/`, then all of `wsl/`. The ⏸ rows are manual steps between scripts.

## 1. Windows (PowerShell), `scripts/windows/`
Run from the repo folder. If script execution is blocked, prefix each script with `powershell -ExecutionPolicy Bypass -File`.

| Order | Script | Admin? | What it does |
|---|---|---|---|
| 00 | `scripts\windows\00_hw-check.ps1` | no | Prints the GPU/VRAM/RAM/CPU table |
| 01 | `scripts\windows\01_setup-wslconfig.ps1` | no | Installs `C:\Users\<you>\.wslconfig` (backs up the old one) |
| 02 | `scripts\windows\02_ollama-env.ps1` | no | Sets `OLLAMA_HOST=0.0.0.0:11434` etc. and restarts Ollama |
| 03 | `scripts\windows\03_ollama-firewall.ps1` | **yes** | Blocks LAN access to port 11434 (Ollama has no auth) |
| 04 | `scripts\windows\04_pull-models.ps1` | no | Pulls the `gpu4gb` models (~12 GB) |
| ⏸ | `wsl --shutdown` | no | Applies `.wslconfig` (wait ~8 s before opening Ubuntu) |

## 2. Ubuntu WSL (bash), `scripts/wsl/`
Open Ubuntu. Until step 01 has moved the repo, run the scripts from the Windows copy:
```bash
cd /mnt/d/github_tomjnet/trader-news-ai
```

| Order | Command | What it does |
|---|---|---|
| 00 | `sudo bash scripts/wsl/00_setup-wsl.sh` | Installs `/etc/wsl.conf` (systemd on) and the Redis sysctl |
| ⏸ | `wsl --shutdown` (from Windows), then reopen Ubuntu | Applies `wsl.conf` |
| 01 | `bash scripts/wsl/01_move-repo.sh` | Copies the project to `~/src/premarket-ai` (incl. `.git`) |
| 02 | `cd ~/src/premarket-ai && scripts/wsl/02_setup-podman.sh` | Installs Podman + docker-compose v2 and enables the user services |
| 03 | `scripts/wsl/03_check-ollama.sh` | Checks WSL/containers → Windows Ollama and prints `OLLAMA_BASE_URL` |
| 04 | `scripts/wsl/04_hw-check.sh` | Hardware table from inside WSL |

After step 01, work only in `~/src/premarket-ai`. The `D:\` copy can be deleted once you've checked the new one.

## Other scripts (not part of the setup order)
| Script | What it does |
|---|---|
| `scripts/convert-cpp-guide.sh` | Regenerates `docs/Google_Cpp_Style_Guide_20260925.md` from the official Google C++ Style Guide page (needs `sudo apt install pandoc`) |
