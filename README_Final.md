# 🔬 MIM-Ops Pro v3.2 — Oracle Cloud Edition

**Metal Injection Molding (MIM) 복셀 플로우 시뮬레이션 자동화 플랫폼**

고성능 Oracle Cloud 컴퓨팅으로 강화된 Streamlit 기반 UI 및 Flask REST API 서버

---

## ✨ 주요 특징

| 기능 | 설명 |
|------|------|
| 🚀 **고성능 계산** | Oracle Cloud Compute (4 OCPU, 24GB RAM) |
| 🎨 **사용자 친화적** | Streamlit 웹 인터페이스 |
| 📡 **REST API** | Flask 기반 확장 가능 아키텍처 |
| 📊 **3D 시각화** | Plotly + PyVista로 실시간 렌더링 |
| 💾 **클라우드 스토리지** | Oracle Object Storage 지원 |
| 🐳 **컨테이너 배포** | Docker Compose 로컬 테스트 + 프로덕션 배포 |

---

## 📈 이전 버전과의 비교

| 항목 | v3.1 (GitHub Actions) | v3.2 (Oracle Cloud) |
|------|---------------------|-------------------|
| **CPU** | 2 코어 | 4+ 코어 |
| **메모리** | 7GB | 16GB+ (최대 24GB) |
| **병렬 처리** | ❌ 불가 | ✅ 가능 |
| **실행 속도** | 느림 | **5-10배 빠름** |
| **스토리지** | 5GB (임시) | 100GB+ |
| **비용** | - | **무료 또는 $27/월** |
| **확장성** | 제한적 | **우수함** |

---

## 🚀 빠른 시작 (5분)

### 요구사항
- Docker Desktop (Windows/Mac) 또는 Docker (Linux)
- Git
- 4GB 이상 RAM

### 명령어

```bash
# 1. 저장소 클론
git clone https://github.com/workshopcompany/MIM-Ops-Oracle.git
cd MIM-Ops-Oracle

# 2. 환경 설정
cp .env.example .env

# 3. .streamlit 폴더 및 secrets.toml 생성
mkdir -p .streamlit
cat > .streamlit/secrets.toml << EOF
ORACLE_API_URL = "http://mim-ops-api:5000"
API_KEY = "default-key-change-in-production"
EOF

# 4. Docker Compose 시작
docker-compose up -d

# 5. 브라우저에서 접속
# - Streamlit UI: http://localhost:8501
# - API 헬스 체크: http://localhost:5000/health
```

### 상태 확인

```bash
# 컨테이너 상태
docker-compose ps

# API 테스트
curl http://localhost:5000/health
```

---

## 📊 아키텍처

```
┌─────────────────────────────────────────────────────┐
│              Streamlit Web UI (8501)                │
│         http://localhost:8501 또는 공개 IP          │
└────────────────┬──────────────────────────────────┘
                 │ HTTP REST API 호출
┌────────────────▼──────────────────────────────────┐
│           Flask API Server (5000)                  │
│     ├─ POST /api/simulate - 시뮬레이션 시작        │
│     ├─ GET /api/jobs/{id} - 작업 상태 조회         │
│     ├─ GET /api/results/{id} - 결과 다운로드       │
│     └─ DELETE /api/jobs/{id} - 작업 취소           │
└────────────────┬──────────────────────────────────┘
                 │ 백그라운드 작업
┌────────────────▼──────────────────────────────────┐
│         Python Solver (solver.py)                  │
│     ├─ STL 메쉬 복셀화                            │
│     ├─ Dijkstra 알고리즘 (흐름 시뮬레이션)        │
│     └─ 3D 시각화 프레임 생성                       │
└────────────────┬──────────────────────────────────┘
                 │ 결과 저장
┌────────────────▼──────────────────────────────────┐
│          Storage Layer                             │
│     ├─ 로컬: /results 디렉토리                     │
│     └─ 클라우드: Oracle Object Storage (선택)     │
└──────────────────────────────────────────────────┘
```

---

## 📁 프로젝트 구조

```
MIM-Ops-Oracle/
│
├── 📂 app/
│   ├── streamlit_app.py           # Streamlit UI
│   └── material_property.txt       # 재료 데이터베이스
│
├── 📂 solver/
│   ├── solver.py                  # 시뮬레이션 엔진
│   └── requirements.txt            # 의존성
│
├── 📂 api/
│   └── server.py                  # Flask API 서버
│
├── 📂 .streamlit/
│   └── secrets.toml               # Streamlit 설정 (생성 필요)
│
├── 📂 results/                     # 시뮬레이션 결과 (자동 생성)
│
├── docker-compose.yml             # 로컬 개발 환경
├── Dockerfile                     # Docker 이미지 빌드
├── requirements.txt               # Python 패키지
├── .env.example                   # 환경 변수 템플릿
├── oracle_setup.sh                # 프로덕션 배포 스크립트
│
└── 📚 문서/
    ├── README.md                  # 이 파일
    ├── QUICK_START.md             # 빠른 시작 가이드
    ├── COMPLETE_GUIDE.md          # 상세 설치 가이드
    └── CODE_REVIEW.md             # 코드 분석
```

---

## 🔧 설치 및 배포

### 로컬 개발 (Docker)

```bash
# 빌드
docker-compose build

# 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f api
docker-compose logs -f streamlit

# 중지
docker-compose down
```

### Oracle Cloud 프로덕션

```bash
# Oracle Compute Instance에 SSH 접속
ssh -i your-key.pem ubuntu@[INSTANCE-IP]

# 배포 스크립트 실행 (자동 설치)
curl -O https://raw.githubusercontent.com/workshopcompany/MIM-Ops-Oracle/main/oracle_setup.sh
chmod +x oracle_setup.sh
./oracle_setup.sh

# 환경 변수 설정
nano /opt/mim-ops/MIM-Ops-Oracle/.env

# 서비스 시작
sudo systemctl start mim-ops-api
sudo systemctl status mim-ops-api

# 로그 확인
sudo journalctl -fu mim-ops-api
```

---

## 📖 문서

| 문서 | 용도 | 시간 |
|------|------|------|
| **QUICK_START.md** | 최소 단계로 시작 | 5-10분 |
| **COMPLETE_GUIDE.md** | 모든 세부사항 + 트러블슈팅 | 30분+ |
| **CODE_REVIEW.md** | 코드 분석 및 개선사항 | 15분 |

---

## 💡 주요 API 엔드포인트

### 시뮬레이션 요청

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "stl_file=@part.stl" \
  -F "gate_x=0" \
  -F "gate_y=0" \
  -F "gate_z=0" \
  -F "gate_dia=2.0" \
  -F "vel_mms=25" \
  -F "etime=1" \
  -F "num_frames=15" \
  http://localhost:5000/api/simulate
```

**응답:**
```json
{
  "job_id": "abc123def456",
  "status": "queued",
  "message": "Simulation queued successfully",
  "est_time_sec": 60
}
```

### 작업 상태 조회

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:5000/api/jobs/abc123def456
```

**응답:**
```json
{
  "job_id": "abc123def456",
  "status": "running",
  "created_at": "2024-01-15T10:30:45",
  "elapsed_sec": 45,
  "progress": 75
}
```

### 결과 다운로드

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:5000/api/results/abc123def456 | jq
```

---

## ⚙️ 환경 변수 설정

### .env 파일 (로컬 개발)

```env
# API 설정
API_KEY=your-secure-api-key
ORACLE_API_URL=http://localhost:5000
ORACLE_API_KEY=your-secure-api-key

# Oracle Cloud (선택사항)
USE_ORACLE=false
ORACLE_COMPARTMENT_ID=
ORACLE_BUCKET_NAME=mim-ops-results
ORACLE_REGION=ap-seoul-1

# Solver 설정
SOLVER_TIMEOUT=3600
MESH_RES_MM=0.5
MAX_FILE_SIZE=104857600

# 디렉토리
TEMP_DIR=/tmp/mim-ops
RESULTS_DIR=./results
```

### .streamlit/secrets.toml (Streamlit 설정)

```toml
ORACLE_API_URL = "http://mim-ops-api:5000"
API_KEY = "default-key-change-in-production"
```

---

## 🎯 사용 예시

### 기본 시뮬레이션

1. Streamlit UI 열기: `http://localhost:8501`
2. STL 파일 업로드
3. 파라미터 설정:
   - **Gate Position**: (X, Y, Z) 좌표
   - **Gate Diameter**: 2.0 mm
   - **Injection Velocity**: 25 mm/s
   - **End Time**: 1.0 s
4. **Run Simulation** 클릭
5. 결과 모니터링 및 다운로드

### 고급 설정

```python
# 메쉬 해상도 조정 (정확도 vs 속도)
# 0.1mm: 가장 정확 (느림, 메모리 많음)
# 0.5mm: 균형 (권장)
# 1.0mm: 빠름 (덜 정확)

# 프레임 수 증가 (더 부드러운 애니메이션)
# 15: 기본값
# 30: 부드러움
# 60: 매우 부드러움
```

---

## 🐛 트러블슈팅

### Docker 실행 안 될 때

```bash
# 1. Docker Desktop 실행 확인
docker --version

# 2. docker-compose.yml 문법 검사
docker-compose config

# 3. 권한 문제 (Windows/Mac)
# Docker Desktop 관리자 권한으로 실행
```

### API 연결 실패

```bash
# 1. 서비스 상태 확인
docker-compose ps

# 2. 포트 확인
netstat -an | grep 5000  # Mac/Linux
netstat -ano | findstr :5000  # Windows

# 3. 로그 확인
docker-compose logs api
```

### Streamlit 에러

```bash
# 1. secrets.toml 확인
cat .streamlit/secrets.toml

# 2. 권한 확인
ls -la .streamlit/

# 3. 캐시 삭제
rm -rf ~/.streamlit/
```

더 자세한 내용은 **COMPLETE_GUIDE.md**의 "Troubleshooting" 섹션을 참고하세요.

---

## 🚀 프로덕션 배포 (Oracle Cloud)

### 최소 30분 내 배포 완료

```bash
# 1. Oracle Compute Instance 생성 (Ampere A1, 4 OCPU, 24GB)
# 2. SSH 접속
ssh -i key.pem ubuntu@INSTANCE_IP

# 3. 자동 배포
curl -O https://raw.githubusercontent.com/workshopcompany/MIM-Ops-Oracle/main/oracle_setup.sh
chmod +x oracle_setup.sh
./oracle_setup.sh

# 4. 완료!
curl http://localhost:5000/health
```

**배포 완료 후:**
- ✅ API 서버 자동 시작
- ✅ Systemd 서비스 등록 (자동 재시작)
- ✅ SSL 인증서 설정 (선택)
- ✅ 모니터링 설정 (선택)

---

## 💰 비용

### Oracle Cloud Always Free (권장)

```
• Compute: Ampere A1 (4 OCPU, 24GB) - 무료
• Storage: 20GB - 무료
• 총 비용: $0/월
```

### 유료 옵션 (필요시)

```
• Standard E2 (2 OCPU, 16GB): $20/월
• 추가 Storage: $5/월
• 총 비용: ~$25/월
```

---

## 📊 성능 기준

| 파트 크기 | 메쉬 해상도 | 복셀 수 | 예상 시간 | 메모리 |
|-----------|-----------|--------|-----------|--------|
| 작음 | 1.0mm | 10K | 10초 | 100MB |
| 중간 | 0.5mm | 80K | 30초 | 500MB |
| 중간 | 0.3mm | 400K | 2분 | 2GB |
| 크지 않음 | 0.2mm | 1.5M | 5분 | 5GB |
| 매우 큼 | 0.1mm | 10M | 20분+ | 16GB+ |

---

## 🔐 보안

### 프로덕션 체크리스트

- [ ] API_KEY 변경 (강력한 키 생성)
- [ ] SSH 키 보안 관리
- [ ] SSL/TLS 인증서 설정
- [ ] 방화벽 규칙 제한
- [ ] 정기 백업 설정
- [ ] 로그 모니터링

### API Key 생성

```bash
# 강력한 키 생성
openssl rand -base64 32

# 환경 변수에 설정
export API_KEY="생성된-키"
```

---

## 📞 지원 및 기여

### 문제 보고
- GitHub Issues: https://github.com/workshopcompany/MIM-Ops-Oracle/issues

### 기여 방법
1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

---

## 📄 라이센스

MIT License - 자유롭게 사용, 수정, 배포 가능

---

## 🙏 감사

- **Trimesh**: 3D 메쉬 처리
- **Streamlit**: 웹 UI 프레임워크
- **Flask**: REST API 서버
- **Oracle Cloud**: 클라우드 인프라

---

## 📝 변경 이력

### v3.2 (현재) - Oracle Cloud Edition ✨
- ✅ Flask REST API 서버 구현
- ✅ Oracle Cloud Compute 지원
- ✅ Docker Compose 로컬 개발 환경
- ✅ Oracle Object Storage 선택 지원
- ✅ 자동 배포 스크립트
- ✅ Streamlit secrets.toml 설정

### v3.1 - GitHub Actions Edition
- GitHub Actions 기반 계산
- 2 코어, 7GB RAM 제약
- Streamlit Cloud 배포

### v3.0 - 아키텍처 변경
- Streamlit에서 계산 분리
- GitHub Artifacts 결과 저장

---

## 🎯 다음 단계

1. ✅ **로컬에서 테스트** - Docker로 확인
2. **Oracle Cloud 배포** - 프로덕션 환경
3. **성능 모니터링** - 메트릭 수집
4. **자동화 확장** - CI/CD 파이프라인
5. **병렬 처리** - 여러 시뮬레이션 동시 실행

---

## 📚 더 알아보기

- **빠른 시작**: [QUICK_START.md](QUICK_START.md) (5-10분)
- **완전한 가이드**: [COMPLETE_GUIDE.md](COMPLETE_GUIDE.md) (모든 세부사항)
- **코드 분석**: [CODE_REVIEW.md](CODE_REVIEW.md) (기술 상세)

---

## ✨ 최신 업데이트

**2024년 1월 15일**
- ✅ Docker Compose 환경 오류 해결
- ✅ secrets.toml 설정 개선
- ✅ 문서 완성
- ✅ 프로덕션 배포 준비 완료

---

**시작할 준비가 되셨나요?**

```bash
git clone https://github.com/workshopcompany/MIM-Ops-Oracle.git
cd MIM-Ops-Oracle
docker-compose up -d
```

**그리고 `http://localhost:8501`에서 시작하세요!** 🚀

---

**문제가 있으세요?** → [COMPLETE_GUIDE.md](COMPLETE_GUIDE.md)의 Troubleshooting 섹션을 참고하세요.

**더 자세히 알고 싶으세요?** → [QUICK_START.md](QUICK_START.md) 또는 [COMPLETE_GUIDE.md](COMPLETE_GUIDE.md)를 읽으세요.
