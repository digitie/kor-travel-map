# WSL ext4 작업 흐름

이 저장소의 기본 작업 위치는 WSL2 내부 ext4 파일시스템이다. Windows NTFS 경로는 최종
결과를 확인하거나 다른 Windows 도구가 읽을 수 있도록 export/sync하는 대상일 뿐이다.

## 표준 경로

- WSL 작업공간: `/home/digitie/dev/python-krtour-map`
- Windows export 대상: `F:\dev\python-krtour-map`
- WSL에서 보이는 export 대상: `/mnt/f/dev/python-krtour-map`

## 원칙

- Git 명령은 WSL ext4 작업공간에서 실행한다.
- 테스트, lint, compile 검증도 WSL ext4 작업공간에서 실행한다.
- NTFS repository에서는 반복적인 `git status`, `git diff`, `git commit`, `pytest`를 실행하지
  않는다.
- NTFS 경로는 느린 git metadata 접근을 피하기 위해 작업 기준 저장소로 쓰지 않는다.
- ext4 작업공간에서 변경, 검증, 커밋, push를 끝낸 뒤 NTFS 경로로 결과만 export한다.
- 짧은 명령마다 `wsl.exe`를 새로 실행하지 않는다. WSL 내부 shell을 유지하거나, 하나의
  `bash -lc` 호출에 여러 명령을 묶어 실행한다.

## 가장 효과적인 실행 방식

우선순위는 아래처럼 둔다.

1. WSL 안의 long-lived shell에서 작업한다.
2. 에이전트/Windows 도구가 반복적으로 명령을 보내야 하면 WSL의 `sshd`에 localhost SSH로 붙고
   SSH multiplexing을 켠다.
3. 단발성 작업만 `wsl.exe bash -lc "..."`로 묶어 실행한다.
4. 명령마다 `wsl.exe`를 새로 실행하는 방식은 피한다.

현재 Ubuntu 환경에는 SSH client는 있지만 `sshd` server가 설치되어 있지 않다. SSH 운영을 쓰려면
아래 절차로 한 번만 구성한다.

### 권장 옵션: localhost SSH + ControlMaster

WSL 쪽에서 OpenSSH server를 설치하고 loopback 전용 포트로 연다.

```bash
sudo apt-get update
sudo apt-get install -y openssh-server
sudo mkdir -p /run/sshd
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.krtour-map.bak
sudo tee /etc/ssh/sshd_config.d/krtour-map-local.conf >/dev/null <<'EOF'
Port 2222
ListenAddress 127.0.0.1
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowUsers digitie
EOF
sudo service ssh restart
```

Windows 쪽 `~/.ssh/config`에는 connection multiplexing을 켠 host를 둔다.

```sshconfig
Host wsl-ubuntu
  HostName 127.0.0.1
  Port 2222
  User digitie
  IdentityFile ~/.ssh/id_ed25519
  ControlMaster auto
  ControlPath ~/.ssh/cm-%r@%h:%p
  ControlPersist 30m
  ServerAliveInterval 30
```

이후 반복 명령은 새 WSL process를 만들지 않고 SSH control connection을 재사용한다.

```powershell
ssh wsl-ubuntu 'cd /home/digitie/dev/python-krtour-map && .venv/bin/python -m pytest'
ssh wsl-ubuntu 'cd /home/digitie/dev/python-krtour-map && git status --short --branch'
```

더 긴 작업은 interactive SSH session 하나를 열고 그 안에서 계속 실행한다.

```powershell
ssh -t wsl-ubuntu 'cd /home/digitie/dev/python-krtour-map && exec bash -l'
```

보안 원칙:

- `ListenAddress 127.0.0.1`로 Windows host local 접속만 허용한다.
- password login은 끄고 SSH key만 사용한다.
- 22번 포트는 Windows OpenSSH server와 충돌할 수 있으므로 2222 같은 별도 포트를 쓴다.

### GitHub 인증

GitHub push까지 WSL ext4에서 끝내려면 WSL 안에 별도 인증을 둔다. 권장 순서는 SSH key다.

```bash
ssh-keygen -t ed25519 -C "digitie@gmail.com"
cat ~/.ssh/id_ed25519.pub
git remote set-url origin git@github.com:digitie/python-krtour-map.git
ssh -T git@github.com
```

Windows Git Credential Manager를 WSL에서 재사용하는 방법도 있지만, WSL interop이 꺼져 있으면
Windows `.exe`를 실행할 수 없어 실패한다. 이 경우에는 WSL용 SSH key 또는 WSL 안의 GitHub CLI
로그인을 사용한다. Windows Git으로 `\\wsl.localhost\...` repository를 push하는 것은 인증
우회용 fallback으로만 사용하고, 반복 git 작업 경로로 삼지 않는다.

### 대안: VS Code Remote WSL

VS Code를 쓰는 경우에는 WSL extension으로 `/home/digitie/dev/python-krtour-map` 폴더를 직접 연다.
이 방식은 editor server와 terminal이 WSL 안에서 동작하므로 git/test/lint가 모두 ext4에서 돈다.

### 단발성 fallback

SSH를 구성하지 않은 상태에서 Windows process가 명령을 보내야 하면 하나의 `wsl.exe` 호출에 묶는다.

```powershell
wsl -e bash -lc "cd /home/digitie/dev/python-krtour-map && \
  .venv/bin/python -m ruff check . && \
  .venv/bin/python -m pytest && \
  .venv/bin/python -m compileall src tests"
```

## 속도 판단

속도 면에서는 `ext4에서 git 작업 후 Windows로 export`가 기본 선택이다.

`Windows NTFS에서 git 작업 후 ext4로 복사`는 겉보기에는 Windows 도구를 바로 쓰기 편하지만,
git이 `.git`과 working tree의 작은 파일을 많이 훑을 때 NTFS/WSL 경계 비용이 반복해서 발생한다.
특히 `status`, `diff`, `checkout`, `pytest`처럼 파일을 자주 스캔하는 작업에서 손해가 커진다.

`ext4에서 git 작업 후 Windows로 export`는 git metadata와 Python cache가 Linux 파일시스템 안에
머물기 때문에 반복 작업이 빠르다. Windows 쪽 비용은 작업 끝의 단방향 sync 한 번으로 제한된다.

주의할 점은 `wsl.exe` 실행 자체에도 시작 비용이 있다는 것이다. 따라서 아래처럼 명령을 잘게
쪼개지 않는다.

```powershell
wsl git status
wsl python -m pytest
wsl git diff
```

대신 WSL shell 안에서 작업하거나 한 번에 묶는다.

```powershell
wsl -e bash -lc "cd /home/digitie/dev/python-krtour-map && \
  .venv/bin/python -m ruff check . && \
  .venv/bin/python -m pytest && \
  .venv/bin/python -m compileall src tests"
```

기존 NTFS clone에 `.git`이 남아 있으면 그 위치에서는 git 명령을 실행하지 않는다. 완전한
export-only 폴더로 전환하려면 `.git` 제거 또는 별도 export 폴더 사용을 먼저 명시적으로 결정한다.

## 동기화

권장 동기화 명령:

```bash
rsync -a --delete \
  --exclude .git \
  --exclude .venv \
  --exclude .pytest_cache \
  --exclude .ruff_cache \
  --exclude __pycache__ \
  --exclude '*.egg-info' \
  /home/digitie/dev/python-krtour-map/ \
  /mnt/f/dev/python-krtour-map/
```

`--delete`를 사용할 때는 source와 destination을 위 표준 경로로 확인한 뒤 실행한다. NTFS
export에는 git metadata를 복사하지 않는다.

## 검증

검증은 아래처럼 WSL ext4 작업공간에서 실행한다.

```bash
cd /home/digitie/dev/python-krtour-map
python -m ruff check .
python -m pytest
python -m compileall src tests
```

필요한 경우 `.venv`도 ext4 작업공간에 만든다. `.venv`는 NTFS export 대상이 아니다.

## 참고 자료

- [Microsoft WSL file system guidance](https://learn.microsoft.com/en-us/windows/wsl/filesystems): Linux command line 작업은 WSL file system에 파일을 둘 때 가장 빠르다.
- [Microsoft WSL networking guidance](https://learn.microsoft.com/en-us/windows/wsl/networking): Windows host는 WSL 안의 network app을 `localhost`로 접근할 수 있다.
- [OpenSSH `ssh_config`](https://manpages.debian.org/bookworm/openssh-client/ssh_config.5.en.html): `ControlMaster`와 `ControlPersist`로 SSH 연결을 재사용할 수 있다.
- [VS Code Remote WSL](https://code.visualstudio.com/docs/remote/wsl): editor/terminal/extension 실행을 WSL 환경 안으로 붙일 수 있다.
