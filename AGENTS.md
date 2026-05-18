# AGENTS.md

## 역할

이 저장소는 TripMate의 지도 feature/source/weather/price 계약을 제공하는 하부 라이브러리입니다. 작업 전에 이 파일과 `README.md`, `docs/provider-contract.md`를 먼저 확인합니다.

## 지시 우선순위

1. 사용자 요청
2. 이 `AGENTS.md`
3. `docs/` 문서
4. `README.md`
5. 기존 코드와 테스트
6. 최소한의, 되돌릴 수 있는 가정

## Provider API 사용 원칙

- 외부 API 관련 작업은 다른 구현보다 먼저 wrapper/adapter/gateway 지양 원칙을 확인하고 문서/코드에 반영한 뒤 진행합니다.
- `python-krtour-map`은 provider 호출 wrapper가 아닙니다. 안정된 `python-*-api` public client와 typed model에서 나온 결과를 feature/source/weather/price 계약으로 정리합니다.
- 부족한 endpoint, typed model, pagination, cursor, exception, raw payload 보존 규칙은 TripMate나 이 저장소에 임시 facade를 만들지 않고 해당 `python-*-api` 저장소에서 먼저 안정화합니다.
- 단순 전달용 `KmaWrapper`, `VWorldAdapter`, `OpiNetGateway` 같은 계층을 만들지 않습니다.
- 필요한 경계는 provider model을 `Feature`, `SourceRecord`, `WeatherValue`, `PriceValue`로 바꾸는 순수 함수와 저장소 repository까지입니다.

## WSL/ext4 작업 원칙

- Git, 테스트, 패키지 설치, lint, compile 검증은 WSL2 내부 ext4 작업공간에서 실행합니다.
- NTFS 경로(`/mnt/f`, `F:\dev`)의 repository에서 직접 `git status`, `git diff`, `git commit`, `pytest` 같은 반복 작업을 하지 않습니다. NTFS는 git metadata 접근이 느리므로 작업 기준 저장소가 아닙니다.
- 표준 WSL 작업공간은 `/home/digitie/dev/python-krtour-map`입니다.
- `F:\dev\python-krtour-map`은 Windows 도구와 파일 확인을 위한 export/sync 대상입니다. ext4 작업공간에서 검증과 커밋을 끝낸 뒤 결과만 동기화합니다.
- 짧은 명령마다 `wsl.exe`를 새로 호출하지 않습니다. 가능하면 WSL 내부 shell 세션을 유지하거나, 하나의 `bash -lc` 안에서 여러 명령을 묶어 실행합니다.
- Windows 도구가 반복적으로 명령을 보내야 할 때는 WSL `sshd`에 localhost SSH로 접속하고 `ControlMaster`/`ControlPersist`를 사용해 연결을 재사용합니다.
- 동기화는 `rsync` 또는 동등한 파일 복사 도구를 사용하되 `.git`, `.venv`, cache, build 산출물은 NTFS export에서 제외합니다.
- 앞으로 이 저장소 작업은 이 방식을 기본값으로 유지합니다. 예외가 필요하면 먼저 사용자에게 이유와 범위를 설명합니다.

## 검증

```bash
python -m ruff check .
python -m pytest
python -m compileall src tests
```
