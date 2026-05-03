# MIM-Ops Pro — Oracle Cloud Edition

Streamlit 기반 MIM(Metal Injection Molding) 복셀 플로우 시뮬레이션 UI.  
solver.py 는 GitHub Actions(2코어, 7GB RAM)에서 실행되며, 이 앱은 UI 및 결과 표시 전용입니다.

---

## 아키텍처

```
Oracle VM (UI)          GitHub Actions (Solver)
─────────────────       ─────────────────────────
app.py 실행           ← 🚀 Run 버튼 누르면 dispatch
브라우저: IP:8501       solver.py 실행 (복셀화 + Dijkstra)
결과 Sync ────────────→ Artifact 다운로드 → 렌더링
```

---

## Oracle Cloud 초기 세팅

### 1. 패키지 업데이트

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git
```

### 2. 저장소 클론

```bash
git clone https://github.com/workshopcompany/MIM-Ops-Oracle.git
cd MIM-Ops-Oracle
```

### 3. Python 가상환경 생성 (권장)

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. 의존성 설치

```bash
pip install -r requirements.txt
```

### 5. Streamlit secrets 설정

```bash
mkdir -p ~/.streamlit
cat > ~/.streamlit/secrets.toml << 'EOF'
GITHUB_TOKEN  = "ghp_xxxxxxxxxxxxxxxxxxxx"
REPO_OWNER    = "workshopcompany"
REPO_NAME     = "OpenFOAM-Injection-Automation"
GEMINI_API_KEY = ""   # 선택사항
EOF
```

### 6. 방화벽 포트 허용

Oracle Cloud 콘솔 → Compute → Instances → Security → Ingress Rules:

| Protocol | Port | Source      |
|----------|------|-------------|
| TCP      | 8501 | 0.0.0.0/0  |

또는 특정 IP만 허용 (보안 강화):

| Protocol | Port | Source           |
|----------|------|------------------|
| TCP      | 8501 | 내_IP주소/32     |

### 7. 실행

```bash
# 포그라운드 실행 (테스트용)
streamlit run app.py --server.port 8501 --server.address 0.0.0.0

# 백그라운드 실행 (상시 운영)
nohup streamlit run app.py --server.port 8501 --server.address 0.0.0.0 > streamlit.log 2>&1 &

# 프로세스 확인
ps aux | grep streamlit

# 로그 확인
tail -f streamlit.log
```

### 8. 브라우저에서 접속

```
http://[Oracle_Public_IP]:8501
```

---

## Streamlit Cloud 버전과 차이점

| 항목 | Streamlit Cloud | Oracle Cloud |
|------|----------------|--------------|
| RAM | 1GB | 6GB (업그레이드 시 최대 24GB) |
| Mesh Resolution | 0.5mm 고정 | **0.1 ~ 1.0mm 슬라이더** |
| 기본 해상도 | 0.5mm | **0.3mm** |
| 결과 렌더링 | 제한적 | 대용량 results.json 처리 가능 |

---

## Oracle Always Free 인스턴스 업그레이드

`VM.Standard.A1.Flex` 는 Always Free 범위 내에서 업그레이드 가능:

- **최대 4 OCPU**
- **최대 24GB RAM**

Compute → Instances → Edit → Shape 변경

---

## Mesh Resolution 가이드

| 해상도 | 예상 복셀 수* | GitHub Actions | Oracle 렌더링 |
|--------|-------------|----------------|--------------|
| 1.0mm  | ~10,000     | ✅ 빠름         | ✅ 가벼움      |
| 0.5mm  | ~70,000     | ✅ 안전         | ✅ 안전        |
| 0.3mm  | ~340,000    | ✅ 권장         | ✅ 6GB 충분   |
| 0.2mm  | ~1,200,000  | ⚠️ 파트 크기 주의 | ✅ 가능        |
| 0.1mm  | ~9,600,000  | ❌ OOM 위험     | ⚠️ 무거움      |

*40×25×15mm 기준 파트 추정값

---

## 프로세스 관리 (상시 운영)

### systemd 서비스 등록 (권장)

```bash
sudo tee /etc/systemd/system/mimops.service << 'EOF'
[Unit]
Description=MIM-Ops Pro Streamlit
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/MIM-Ops-Oracle
ExecStart=/home/ubuntu/MIM-Ops-Oracle/venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable mimops
sudo systemctl start mimops

# 상태 확인
sudo systemctl status mimops
```

---

## 업데이트 방법

```bash
cd MIM-Ops-Oracle
git pull origin main
sudo systemctl restart mimops   # systemd 사용 시
```
