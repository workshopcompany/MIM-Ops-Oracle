# 🚀 MIM-Ops Pro → Oracle Cloud 마이그레이션 로드맵

## Phase 1️⃣: 준비 단계 (1-2일)

### 1.1 GitHub 저장소 구조화
```bash
# 현재 저장소: workshopcompany/MIM-Ops-Oracle

# 디렉토리 생성
mkdir -p app solver api infra tests

# 파일 이동 및 재구성
mv app.py app/streamlit_app.py
mv solver.py solver/solver.py
touch solver/requirements.txt
touch api/server.py
touch api/oracle_client.py
touch infra/Dockerfile
```

### 1.2 필수 설정 파일 생성
- requirements.txt (Python 의존성)
- .env.example (환경 변수 템플릿)
- oracle_setup.sh (Oracle Cloud 초기화 스크립트)
- docker-compose.yml (로컬 테스트용)

### 1.3 Oracle Cloud 계정 준비
- Oracle Cloud Free Tier 계정 생성 (또는 기존 계정)
- Compute Instance 권한 확인
- Object Storage 권한 확인
- API Key 생성

**예상 비용** (소형 배포):
- Compute (1 OCPU, 6GB RAM): 무료 tier 또는 $10/월
- Object Storage (100GB): $5/월
- 총: ~$15/월 (또는 무료 tier 사용 시 $0)

---

## Phase 2️⃣: REST API 서버 구축 (2-3일)

### 2.1 Flask API 서버 작성 (`api/server.py`)

**필수 엔드포인트:**

```
POST /api/simulate
  Input:  {signal_id, stl_file, gate_pos, vel_mms, etime, material, ...}
  Output: {job_id, status, est_time}

GET /api/jobs/{job_id}
  Output: {status, progress, result_url}

GET /api/results/{job_id}
  Output: {frames, results.json, logs}

DELETE /api/jobs/{job_id}
  Output: {status: "deleted"}
```

### 2.2 Oracle Object Storage 연동

```python
# api/oracle_client.py
import oci

class OracleStorageClient:
    def upload_stl(self, file_path, job_id):
        # STL 파일을 Object Storage에 업로드
        
    def download_results(self, job_id):
        # 결과 다운로드
        
    def cleanup(self, job_id):
        # 완료된 작업 정리
```

### 2.3 인증 & 보안

```python
# api/auth.py
def verify_api_key(request):
    # API Key 검증
    # Oracle SDK 또는 JWT 사용
    
def rate_limit(request):
    # API 요청 제한 (DOS 방지)
```

**설정 예시:**
```yaml
# config.yaml
oracle:
  compartment_id: "ocid1.compartment.oc1..xxxxx"
  bucket_name: "mim-ops-results"
  region: "ap-seoul-1"  # 또는 us-phoenix-1

api:
  host: "0.0.0.0"
  port: 5000
  timeout: 3600  # 1시간
  max_file_size: 100MB
```

---

## Phase 3️⃣: Oracle Compute Instance 설정 (1-2일)

### 3.1 Compute Instance 생성

**권장 사양:**
```
OS Image:     Ubuntu 22.04
Shape:        Standard E2 (2 OCPU, 16 GB memory)
또는 Free Tier: Ampere A1 (4 OCPU, 24 GB memory)
Storage:      50 GB (Root volume)
Network:      VCN with public subnet
```

### 3.2 환경 구성

```bash
#!/bin/bash
# infra/oracle_setup.sh

# 1. 기본 패키지 설치
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.10 python3-pip python3-venv git docker.io

# 2. Python 환경 구성
python3 -m venv /opt/mim-ops/venv
source /opt/mim-ops/venv/bin/activate

# 3. 저장소 클론
cd /opt/mim-ops
git clone https://github.com/workshopcompany/MIM-Ops-Oracle.git
cd MIM-Ops-Oracle

# 4. 의존성 설치
pip install -r solver/requirements.txt
pip install -r api/requirements.txt

# 5. 환경 변수 설정
cp .env.example .env
# .env 파일 편집 (Oracle credentials)
nano .env

# 6. systemd 서비스 등록
sudo tee /etc/systemd/system/mim-ops-api.service > /dev/null <<EOF
[Unit]
Description=MIM-Ops Pro API Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/mim-ops/MIM-Ops-Oracle
ExecStart=/opt/mim-ops/venv/bin/python api/server.py
Restart=always
Environment="PATH=/opt/mim-ops/venv/bin"

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable mim-ops-api
sudo systemctl start mim-ops-api
```

### 3.3 Firewall & Security

```bash
# 80, 443 포트만 열기 (API 통신)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# SSL 인증서 (Let's Encrypt)
sudo apt install -y certbot python3-certbot-nginx
sudo certbot certonly --standalone -d your-oracle-domain.com
```

---

## Phase 4️⃣: Streamlit 앱 수정 (2-3일)

### 4.1 API 연동으로 변경

**변경 전:**
```python
# GitHub Actions 호출
def dispatch_github_workflow():
    # GitHub API 호출
    requests.post("https://api.github.com/repos/.../dispatches", ...)
```

**변경 후:**
```python
# Oracle API 호출
def submit_simulation(params):
    response = requests.post(
        f"{ORACLE_API_URL}/api/simulate",
        json=params,
        headers={"Authorization": f"Bearer {ORACLE_API_KEY}"}
    )
    return response.json()

def check_job_status(job_id):
    response = requests.get(
        f"{ORACLE_API_URL}/api/jobs/{job_id}",
        headers={"Authorization": f"Bearer {ORACLE_API_KEY}"}
    )
    return response.json()

def download_results(job_id):
    response = requests.get(
        f"{ORACLE_API_URL}/api/results/{job_id}",
        headers={"Authorization": f"Bearer {ORACLE_API_KEY}"}
    )
    return response.json()
```

### 4.2 설정 변경

**변경 전:**
```python
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
REPO_OWNER = st.secrets.get("REPO_OWNER", "workshopcompany")
```

**변경 후:**
```python
ORACLE_API_URL = st.secrets.get("ORACLE_API_URL", "https://your-oracle-instance.com")
ORACLE_API_KEY = st.secrets.get("ORACLE_API_KEY", "")
```

### 4.3 UI 개선 (선택사항)

```python
# 실시간 진행률 표시
def show_progress():
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    while True:
        job_status = check_job_status(job_id)
        progress_bar.progress(job_status['progress'] / 100)
        status_text.write(f"진행 중: {job_status['message']}")
        
        if job_status['status'] == 'completed':
            break
        time.sleep(1)
```

---

## Phase 5️⃣: Docker 컨테이너화 (1-2일)

### 5.1 Dockerfile 작성

```dockerfile
# infra/Dockerfile
FROM python:3.10-slim

WORKDIR /app

# 의존성 설치
RUN apt-get update && apt-get install -y \
    git libvtk9-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지
COPY solver/requirements.txt requirements_solver.txt
COPY api/requirements.txt requirements_api.txt
RUN pip install -r requirements_solver.txt -r requirements_api.txt

# 코드 복사
COPY . .

# API 서버 시작
CMD ["python", "api/server.py"]
```

### 5.2 Docker Compose (로컬 테스트)

```yaml
# infra/docker-compose.yml
version: '3.9'

services:
  api:
    build: .
    ports:
      - "5000:5000"
    environment:
      - ORACLE_COMPARTMENT_ID=${ORACLE_COMPARTMENT_ID}
      - ORACLE_BUCKET_NAME=${ORACLE_BUCKET_NAME}
    volumes:
      - ./:/app
      - /var/run/docker.sock:/var/run/docker.sock

  streamlit:
    image: python:3.10-slim
    ports:
      - "8501:8501"
    environment:
      - ORACLE_API_URL=http://api:5000
    volumes:
      - ./app:/app
    command: pip install streamlit pyvista plotly trimesh && streamlit run /app/streamlit_app.py
    depends_on:
      - api
```

---

## Phase 6️⃣: 배포 & 테스트 (2-3일)

### 6.1 GitHub Actions 배포 자동화

```yaml
# .github/workflows/deploy.yml
name: Deploy to Oracle Cloud

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build Docker image
        run: docker build -t mim-ops-api:latest infra/
      
      - name: Connect to Oracle Compute
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.ORACLE_HOST }}
          username: ubuntu
          key: ${{ secrets.ORACLE_PRIVATE_KEY }}
          script: |
            cd /opt/mim-ops/MIM-Ops-Oracle
            git pull origin main
            docker pull gcr.io/your-registry/mim-ops-api:latest
            docker-compose restart api
```

### 6.2 테스트 체크리스트

```
[ ] API 서버 정상 시작
[ ] STL 파일 업로드 테스트
[ ] Solver 실행 테스트
[ ] 결과 다운로드 테스트
[ ] Streamlit ↔ API 통신 테스트
[ ] 대용량 파일 처리 테스트 (>100MB)
[ ] 동시 요청 테스트 (병렬 작업)
[ ] 에러 핸들링 테스트
[ ] 보안 테스트 (인증, Rate limit)
[ ] 성능 테스트 (응답시간, CPU, 메모리)
```

### 6.3 모니터링 & 로깅

```python
# api/logger.py
import logging
from pythonjsonlogger import jsonlogger

logger = logging.getLogger()
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter()
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)

# 사용 예시
logger.info("Job started", extra={
    "job_id": job_id,
    "user": user,
    "action": "simulate"
})
```

---

## 📅 예상 일정

| Phase | 작업 | 일수 | 누적 |
|-------|------|------|------|
| 1 | 준비 | 1-2 | 1-2 |
| 2 | REST API | 2-3 | 3-5 |
| 3 | Oracle Setup | 1-2 | 4-7 |
| 4 | Streamlit 수정 | 2-3 | 6-10 |
| 5 | Docker화 | 1-2 | 7-12 |
| 6 | 배포 & 테스트 | 2-3 | 9-15 |
| **총계** | | | **9-15일** |

---

## 💰 비용 추정

### 초기 투자 (일회)
- 도메인: $12/년
- SSL 인증서: 무료 (Let's Encrypt)

### 월간 운영비
| 항목 | 무료Tier | 소형 | 중형 |
|------|---------|------|------|
| Compute | $0 | $20 | $50 |
| Storage | $0 | $5 | $20 |
| Bandwidth | $0 | $2 | $10 |
| **합계** | **$0** | **$27** | **$80** |

---

## 🔗 참고 자료

- Oracle Cloud Always Free: https://www.oracle.com/cloud/free/
- Oracle SDK for Python: https://github.com/oracle/oci-python-sdk
- Flask REST API: https://flask-restful.readthedocs.io/
- Streamlit Secrets: https://docs.streamlit.io/library/advanced-features/secrets-management

---

## ✅ 다음 단계

1. **코드 검토 완료** ✅
2. **Step 1 시작**: GitHub 저장소 구조화
3. **Step 2 시작**: Flask REST API 작성 (상세 코드 필요)
4. **Step 3 시작**: Oracle Compute 설정

**준비되셨나요? 어느 단계부터 상세하게 진행할지 말씀해주세요!**

