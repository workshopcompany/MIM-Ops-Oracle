# 🚀 MIM-Ops Pro Oracle Cloud 마이그레이션 가이드

## 📋 목차

1. [개요](#개요)
2. [빠른 시작](#빠른-시작)
3. [상세 설치 가이드](#상세-설치-가이드)
4. [Oracle Cloud 설정](#oracle-cloud-설정)
5. [배포 및 테스트](#배포-및-테스트)
6. [트러블슈팅](#트러블슈팅)
7. [추가 정보](#추가-정보)

---

## 개요

### 이전 아키텍처
```
Streamlit (UI)
    ↓
GitHub Actions (제한된 리소스)
    ↓
GitHub Artifacts (느린 다운로드)
```

### 새로운 아키텍처
```
Streamlit (UI)
    ↓
Flask REST API
    ↓
Oracle Cloud Compute (고성능)
    ↓
Oracle Object Storage (빠른 저장소)
```

### 개선 사항
| 항목 | 이전 | 새 버전 |
|------|------|--------|
| CPU | 2 코어 | 4+ 코어 |
| 메모리 | 7GB | 16GB+ |
| 저장소 | 5GB (임시) | 100GB+ |
| 병렬 처리 | 불가 | 가능 |
| 비용 | - | $27/월 (또는 무료) |

---

## 빠른 시작

### 로컬 개발 (5분)

```bash
# 1. 저장소 클론
git clone https://github.com/workshopcompany/MIM-Ops-Oracle.git
cd MIM-Ops-Oracle

# 2. 환경 설정
cp .env.example .env

# 3. Docker Compose 실행
docker-compose up -d

# 4. 접속
# API: http://localhost:5000/health
# UI: http://localhost:8501
```

### 프로덕션 배포 (30분)

```bash
# 1. Oracle Cloud Compute Instance에 SSH 접속
ssh -i your-key.key ubuntu@your-instance-ip

# 2. 배포 스크립트 실행
curl -O https://raw.githubusercontent.com/workshopcompany/MIM-Ops-Oracle/main/oracle_setup.sh
chmod +x oracle_setup.sh
./oracle_setup.sh

# 3. 환경 변수 설정
nano /opt/mim-ops/MIM-Ops-Oracle/.env

# 4. 서비스 시작
sudo systemctl start mim-ops-api
```

---

## 상세 설치 가이드

### 요구사항

**개발 환경:**
- Docker & Docker Compose
- Python 3.10+
- 4GB RAM 이상

**프로덕션 (Oracle Cloud):**
- Oracle Compute Instance (2 OCPU, 16GB RAM)
- Ubuntu 22.04 LTS
- Internet access

### Step 1: 로컬 개발 환경 설정

#### 1.1 저장소 준비

```bash
# GitHub에서 클론
git clone https://github.com/workshopcompany/MIM-Ops-Oracle.git
cd MIM-Ops-Oracle

# 브랜치 확인
git branch -a
git checkout main
```

#### 1.2 환경 변수 설정

```bash
# .env 파일 생성
cp .env.example .env

# 편집 (기본값 사용 가능)
nano .env
```

**최소 필수 설정:**
```
API_KEY=your-secure-key
ORACLE_API_KEY=your-secure-key
USE_ORACLE=false  # 로컬에서는 false
```

#### 1.3 Docker Compose 실행

```bash
# 빌드 및 실행
docker-compose up -d

# 상태 확인
docker-compose ps

# 로그 확인
docker-compose logs -f api
docker-compose logs -f streamlit
```

#### 1.4 접속 및 테스트

```bash
# API 헬스 체크
curl -s http://localhost:5000/health | jq

# Streamlit UI
# 브라우저에서 http://localhost:8501 접속

# 테스트 시뮬레이션 (STL 파일 필요)
curl -X POST \
  -H "Authorization: Bearer your-secure-key" \
  -F "stl_file=@sample.stl" \
  -F "vel_mms=25" \
  -F "etime=1" \
  http://localhost:5000/api/simulate
```

### Step 2: Oracle Cloud 설정

#### 2.1 Oracle Cloud 계정 생성

1. [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/) 방문
2. 무료 계정 생성 또는 기존 계정 사용
3. Compute 리소스 할당 확인

#### 2.2 Compute Instance 생성

**Oracle Cloud Console에서:**

1. **왼쪽 메뉴** → Compute → Instances
2. **Create Instance** 클릭
3. 다음 설정:
   ```
   Name: mim-ops-prod
   Image: Ubuntu 22.04
   Shape: Ampere A1 (4 OCPU, 24GB) - 무료
   또는 Standard E2 (2 OCPU, 16GB) - 유료
   Storage: 50GB
   Public IP: Enable
   Subnet: Public subnet
   ```
4. **SSH Key** 생성 또는 업로드
5. Create 클릭

#### 2.3 네트워크 설정

**Security List 규칙 추가:**

| Protocol | Port | Source |
|----------|------|--------|
| TCP | 22 | 0.0.0.0/0 (또는 특정 IP) |
| TCP | 80 | 0.0.0.0/0 |
| TCP | 443 | 0.0.0.0/0 |

#### 2.4 Object Storage 설정 (선택사항)

```bash
# Oracle Cloud CLI 설치
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"

# 설정
oci setup config

# Bucket 생성
oci os bucket create -c [COMPARTMENT-ID] -ns [NAMESPACE] \
  --name mim-ops-results

# Bucket 확인
oci os bucket list -c [COMPARTMENT-ID] -ns [NAMESPACE]
```

### Step 3: 서버 배포

#### 3.1 Instance에 접속

```bash
# SSH 접속
ssh -i your-key.key ubuntu@[INSTANCE-PUBLIC-IP]

# 또는 OCI Console에서 OKE를 통해 접속
```

#### 3.2 자동 배포 스크립트 실행

```bash
# 스크립트 다운로드
curl -O https://raw.githubusercontent.com/workshopcompany/MIM-Ops-Oracle/main/oracle_setup.sh

# 실행 권한 부여
chmod +x oracle_setup.sh

# 실행 (약 5-10분 소요)
./oracle_setup.sh
```

#### 3.3 환경 변수 설정

```bash
# 설정 파일 편집
nano /opt/mim-ops/MIM-Ops-Oracle/.env

# 수정 항목:
API_KEY=your-production-secure-key  # 변경!
ORACLE_API_KEY=your-production-secure-key  # 변경!
USE_ORACLE=true  # Oracle Storage 사용
ORACLE_COMPARTMENT_ID=ocid1.compartment.oc1...  # 입력
ORACLE_BUCKET_NAME=mim-ops-results
ORACLE_REGION=ap-seoul-1  # 또는 ap-tokyo-1
```

#### 3.4 서비스 시작

```bash
# API 서비스 시작
sudo systemctl start mim-ops-api

# 상태 확인
sudo systemctl status mim-ops-api

# 자동 시작 설정
sudo systemctl enable mim-ops-api

# 로그 확인
sudo journalctl -fu mim-ops-api
```

---

## Oracle Cloud 설정

### Object Storage 연동

Object Storage를 사용하려면:

#### 1. API Key 생성

```bash
# OCI CLI가 설치되어 있으면
oci setup config

# 또는 Oracle Cloud Console에서:
# Profile Icon → User Settings → API Keys → Add API Key
# Private Key를 ~/.oci/mim-ops_key.pem에 저장
```

#### 2. 정책(Policy) 설정

Oracle Cloud Console에서 Policies 설정:

```
Compartment: [YOUR-COMPARTMENT]
Statement: allow group [YOUR-GROUP] to manage object-family in compartment [YOUR-COMPARTMENT]
```

#### 3. 환경 변수 설정

```bash
# ~/.oci/config 파일 위치 확인
cat ~/.oci/config

# .env 파일 수정
ORACLE_COMPARTMENT_ID=[복사한 ID]
USE_ORACLE=true
```

---

## 배포 및 테스트

### 로컬 테스트

```bash
# 1. Docker Compose 시작
docker-compose up -d

# 2. 샘플 STL 파일 준비
# (또는 생성)

# 3. 시뮬레이션 요청
curl -X POST \
  -H "Authorization: Bearer your-secure-key" \
  -F "stl_file=@test.stl" \
  -F "gate_x=0" \
  -F "gate_y=0" \
  -F "gate_z=0" \
  -F "vel_mms=25" \
  http://localhost:5000/api/simulate

# 응답: {"job_id": "abc123", "status": "queued"}

# 4. 작업 상태 확인
curl -H "Authorization: Bearer your-secure-key" \
  http://localhost:5000/api/jobs/abc123 | jq

# 5. 결과 다운로드
curl -H "Authorization: Bearer your-secure-key" \
  http://localhost:5000/api/results/abc123 | jq
```

### 프로덕션 테스트

```bash
# Instance IP 확인
PUBLIC_IP=$(oci compute instance list-vnic-attachments \
  --instance-id [INSTANCE-ID] --query 'data[0]."public-ip"' --raw-output)

# API 테스트
curl -s http://$PUBLIC_IP/health | jq

# 시뮬레이션 테스트
curl -X POST \
  -H "Authorization: Bearer [API_KEY]" \
  -F "stl_file=@test.stl" \
  http://$PUBLIC_IP/api/simulate
```

### Streamlit 배포

#### Option 1: Oracle App Server 사용

```bash
# Instance에 접속
ssh -i key.key ubuntu@$PUBLIC_IP

# Streamlit 설치
pip install streamlit plotly pyvista

# 앱 실행
streamlit run /opt/mim-ops/MIM-Ops-Oracle/app/streamlit_app.py \
  --server.port=8501 \
  --server.address=0.0.0.0
```

#### Option 2: Streamlit Cloud 사용

1. [streamlit.io](https://streamlit.io) 가입
2. GitHub 저장소 연결
3. Deploy → New app
4. `app/streamlit_app.py` 선택

---

## 트러블슈팅

### API 서버 연결 안 됨

```bash
# 1. 서비스 상태 확인
sudo systemctl status mim-ops-api

# 2. 포트 확인
sudo netstat -tlnp | grep 5000

# 3. 방화벽 확인
sudo ufw status

# 4. 로그 확인
sudo journalctl -n 100 -u mim-ops-api

# 5. API 직접 테스트
curl -v http://localhost:5000/health
```

### 시뮬레이션 타임아웃

```bash
# 1. 메모리 확인
free -h

# 2. CPU 확인
top

# 3. 메쉬 해상도 조정 (더 크게)
# .env에서 MESH_RES_MM을 1.0으로 늘림

# 4. 타임아웃 시간 연장
SOLVER_TIMEOUT=7200  # 2시간
```

### Oracle Storage 연결 실패

```bash
# 1. OCI 설정 확인
oci os ns get

# 2. API Key 확인
cat ~/.oci/config | grep -A 5 "[DEFAULT]"

# 3. Bucket 접근 권한 확인
oci os bucket get -ns [NAMESPACE] -bn mim-ops-results

# 4. 정책 확인
oci iam policy list -c [COMPARTMENT-ID]
```

### 디스크 공간 부족

```bash
# 1. 디스크 사용량 확인
df -h

# 2. 오래된 결과 정리
find /opt/mim-ops/MIM-Ops-Oracle/results -mtime +7 -delete

# 3. Docker 정리 (필요시)
docker system prune -a
```

---

## 추가 정보

### 파일 구조

```
MIM-Ops-Oracle/
├── app/
│   ├── streamlit_app.py     # Streamlit UI
│   └── material_property.txt # 재료 DB
├── solver/
│   ├── solver.py            # 계산 엔진
│   └── requirements.txt      # 의존성
├── api/
│   └── server.py            # Flask API
├── infra/
│   ├── Dockerfile           # Docker 이미지
│   └── docker-compose.yml    # 로컬 테스트
├── .env.example             # 환경 변수 템플릿
├── oracle_setup.sh          # 배포 스크립트
├── requirements.txt         # Python 의존성
└── README.md
```

### 모니터링

#### Systemd 로그

```bash
# 실시간 로그
sudo journalctl -fu mim-ops-api

# 마지막 50줄
sudo journalctl -u mim-ops-api -n 50

# 특정 시간대 로그
sudo journalctl -u mim-ops-api --since "2024-01-01" --until "2024-01-02"
```

#### API 메트릭

```bash
# 활성 작업 수
curl -H "Authorization: Bearer [KEY]" http://localhost:5000/api/status

# 결과 디렉토리 크기
du -sh /opt/mim-ops/MIM-Ops-Oracle/results
```

### 성능 최적화

#### 1. Solver 병렬 처리

```python
# solver.py에서 multiprocessing 활용
from multiprocessing import Pool

# 여러 메쉬 해상도로 병렬 계산
with Pool(4) as p:
    results = p.map(run_solver, mesh_resolutions)
```

#### 2. API 캐싱

```python
# Flask-Cache 사용
from flask_caching import Cache

cache = Cache(app, config={'CACHE_TYPE': 'simple'})

@app.route('/api/results/<job_id>')
@cache.cached(timeout=3600)
def get_results(job_id):
    # ...
```

#### 3. 데이터베이스 활용

```bash
# PostgreSQL로 작업 상태 추적
docker-compose up postgres -d

# SQLAlchemy로 ORM 사용
pip install sqlalchemy psycopg2
```

### 보안

#### API Key 관리

```bash
# 강력한 키 생성
openssl rand -base64 32

# 환경 변수로 전달 (파일 아님)
export API_KEY=$(openssl rand -base64 32)

# .env 파일 보호
chmod 600 .env
```

#### SSL/TLS 인증서

```bash
# Let's Encrypt 자동 갱신
sudo certbot renew --dry-run

# 자동 갱신 서비스 확인
sudo systemctl list-timers certbot
```

### 비용 절감

**무료 Tier 사용:**
- Compute: Ampere A1 (4 OCPU, 24GB, 3개까지)
- Storage: 20GB 무료

**경제적 운영:**
- Always Free 리소스 활용
- 사용량 모니터링 (Budgets)
- 자동 종료 (예약 작업)

---

## 연락처 & 지원

- **GitHub Issues**: https://github.com/workshopcompany/MIM-Ops-Oracle/issues
- **Documentation**: https://github.com/workshopcompany/MIM-Ops-Oracle/wiki

---

## 라이센스

MIT License - 자유롭게 사용, 수정, 배포 가능

---

## 변경 이력

### v3.2 (현재)
- ✅ Oracle Cloud 기본 지원
- ✅ REST API 서버 구현
- ✅ Docker Compose 로컬 테스트
- ✅ 자동 배포 스크립트

### v3.1 (이전)
- GitHub Actions 기반
- Streamlit 직접 계산

---

## 다음 단계

1. ✅ **코드 검토 완료**
2. **로컬 환경에서 테스트** (Docker)
3. **Oracle Cloud 계정 생성**
4. **프로덕션 배포**
5. **성능 최적화**

**준비되셨나요? 궁금한 점이 있으면 물어봐주세요!**
