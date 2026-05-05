# 📦 MIM-Ops Pro Oracle Cloud 마이그레이션 완료 키트

## ✅ 포함된 파일 목록

### 📋 문서
- [ ] `CODE_REVIEW.md` - 현재 코드 검토 및 문제점 분석
- [ ] `MIGRATION_ROADMAP.md` - 6단계 마이그레이션 로드맵
- [ ] `COMPLETE_GUIDE.md` - 상세 설치 및 배포 가이드
- [ ] `README.md` - GitHub 저장소용 메인 문서 (준비 예정)

### 💻 소스 코드
- [ ] `api_server.py` - Flask REST API 서버
- [ ] `streamlit_app.py` - 수정된 Streamlit UI (Oracle API 연동)
- [ ] `solver/solver.py` - 원본 계산 엔진 (변수 없음)

### 🔧 설정 파일
- [ ] `requirements.txt` - Python 의존성
- [ ] `.env.example` - 환경 변수 템플릿
- [ ] `Dockerfile` - Docker 이미지 (프로덕션)
- [ ] `docker-compose.yml` - 로컬 개발 환경

### 🚀 배포 스크립트
- [ ] `oracle_setup.sh` - Oracle Cloud 자동 설치 스크립트

---

## 🎯 단계별 적용 방법

### Phase 1: GitHub 저장소 구조화 (완료됨)

**현재 상태:**
```
workshopcompany/MIM-Ops-Oracle/
├── app.py (기존) → app/streamlit_app.py
├── solver.py (기존) → solver/solver.py
└── 새 파일들...
```

**할 일:**
```bash
# 1. GitHub에서 클론
git clone https://github.com/workshopcompany/MIM-Ops-Oracle.git
cd MIM-Ops-Oracle

# 2. 디렉토리 구조 생성
mkdir -p app solver api

# 3. 파일 이동
mv app.py app/streamlit_app.py
mv solver.py solver/solver.py

# 4. 새 파일 추가
# 아래 단계에서 복사할 파일들을 추가

# 5. 커밋 & 푸시
git add .
git commit -m "chore: Oracle Cloud migration - structure refactoring"
git push origin main
```

---

### Phase 2: 로컬 개발 환경 설정 (5-10분)

**필요한 파일:**
```
.env.example
requirements.txt
docker-compose.yml
Dockerfile
```

**단계:**

```bash
# 1. 저장소 클론
git clone https://github.com/workshopcompany/MIM-Ops-Oracle.git
cd MIM-Ops-Oracle

# 2. 환경 파일 생성
cp .env.example .env
# (기본값으로 충분함, 필요시 수정)

# 3. Docker 실행
docker-compose up -d

# 4. 상태 확인
docker-compose ps

# 출력:
# NAME                    STATUS              PORTS
# mim-ops-api            Up 2 minutes        0.0.0.0:5000->5000/tcp
# mim-ops-streamlit      Up 2 minutes        0.0.0.0:8501->8501/tcp

# 5. 접속
# - API Health: http://localhost:5000/health
# - Streamlit: http://localhost:8501
# - API 문서: http://localhost:5000/api/simulate (POST)

# 6. 테스트
curl -s http://localhost:5000/health | jq
```

**테스트 시뮬레이션:**

```bash
# STL 파일 준비 (또는 샘플 다운로드)
# 예: https://example.com/sample.stl

# 시뮬레이션 실행
curl -X POST \
  -H "Authorization: Bearer default-key-change-in-production" \
  -F "stl_file=@sample.stl" \
  -F "gate_x=0" \
  -F "gate_y=0" \
  -F "gate_z=0" \
  -F "vel_mms=25" \
  -F "etime=1" \
  http://localhost:5000/api/simulate

# 응답:
# {
#   "job_id": "abc123def456",
#   "status": "queued",
#   "message": "Simulation queued successfully",
#   "est_time_sec": 60
# }

# 작업 상태 확인
curl -H "Authorization: Bearer default-key-change-in-production" \
  http://localhost:5000/api/jobs/abc123def456 | jq

# 결과 다운로드
curl -H "Authorization: Bearer default-key-change-in-production" \
  http://localhost:5000/api/results/abc123def456 | jq > results.json
```

---

### Phase 3: Oracle Cloud 계정 준비 (30분)

**할 일:**

1. **Oracle Cloud 계정 생성**
   ```
   - Free Tier 가입: https://www.oracle.com/cloud/free/
   - 신용카드 입력 (무료 사용 범위 내면 청구 안 됨)
   - 이메일 인증
   ```

2. **Compute Instance 생성**
   ```
   - Console → Compute → Instances → Create Instance
   - 설정:
     * Name: mim-ops-prod
     * OS: Ubuntu 22.04
     * Shape: Ampere A1 (4 OCPU, 24GB) [무료]
     * Storage: 50GB
     * Public IP: Enable
   ```

3. **SSH Key 준비**
   ```bash
   # Key pair 생성 (로컬에서)
   ssh-keygen -t rsa -b 4096 -f mim-ops-key
   
   # 퍼블릭 키를 Oracle에 업로드 (mim-ops-key.pub 내용)
   ```

4. **보안 규칙 설정**
   ```
   Port 22 (SSH): 0.0.0.0/0 또는 특정 IP
   Port 80 (HTTP): 0.0.0.0/0
   Port 443 (HTTPS): 0.0.0.0/0
   ```

---

### Phase 4: 프로덕션 배포 (10-20분)

**필요한 파일:**
```
oracle_setup.sh
api_server.py
app/streamlit_app.py
solver/solver.py
requirements.txt
.env.example
```

**단계:**

```bash
# 1. Instance에 SSH 접속
ssh -i mim-ops-key.pem ubuntu@<instance-public-ip>

# 2. 배포 스크립트 다운로드 및 실행
curl -O https://raw.githubusercontent.com/workshopcompany/MIM-Ops-Oracle/main/oracle_setup.sh
chmod +x oracle_setup.sh
./oracle_setup.sh

# 스크립트가 자동으로:
# ✓ 시스템 업데이트
# ✓ Python 3.10 설치
# ✓ 저장소 클론
# ✓ 가상환경 설정
# ✓ 의존성 설치
# ✓ Systemd 서비스 등록
# ✓ Nginx 리버스 프록시 설정
# ✓ SSL 인증서 (Let's Encrypt)

# 3. 환경 변수 설정
nano /opt/mim-ops/MIM-Ops-Oracle/.env

# 수정할 항목:
# - API_KEY: 강력한 키로 변경
# - ORACLE_API_KEY: 강력한 키로 변경
# - USE_ORACLE: true로 변경 (선택)
# - ORACLE_COMPARTMENT_ID: 실제 ID 입력

# 4. 서비스 시작
sudo systemctl start mim-ops-api
sudo systemctl status mim-ops-api

# 5. 로그 확인
sudo journalctl -fu mim-ops-api

# 6. API 테스트
curl http://<instance-ip>/health

# 응답:
# {
#   "status": "healthy",
#   "timestamp": "2024-01-15T10:30:45.123456",
#   "oracle_enabled": false
# }
```

---

### Phase 5: 모니터링 및 최적화 (지속적)

**주요 확인 항목:**

```bash
# 1. 서비스 상태
sudo systemctl status mim-ops-api
sudo systemctl status nginx

# 2. 리소스 사용량
free -h
df -h
top

# 3. 로그 모니터링
sudo journalctl -fu mim-ops-api --lines=50

# 4. 네트워크 확인
sudo netstat -tlnp | grep LISTEN

# 5. 방화벽 확인
sudo ufw status

# 6. 결과 파일 정리
find /opt/mim-ops/MIM-Ops-Oracle/results -mtime +30 -delete
```

**성능 최적화:**

```bash
# Worker 수 조정 (api/server.py에서)
# gunicorn --workers 4 → 8 또는 16 (CPU 코어 수에 따라)

# 메모리 모니터링
watch -n 1 free -h

# 디스크 사용량 모니터링
watch -n 5 df -h
```

---

## 📊 마이그레이션 체크리스트

### Pre-Migration (현재)
- [x] 코드 검토 완료
- [x] 아키텍처 설계
- [x] 문서 작성
- [x] API 서버 구현
- [x] Streamlit 앱 수정
- [x] Docker 설정

### Local Testing
- [ ] Docker Compose 실행 확인
- [ ] API 헬스 체크
- [ ] 시뮬레이션 요청 테스트
- [ ] 결과 다운로드 확인
- [ ] STL 파일 처리 테스트
- [ ] 대용량 파일 처리 테스트

### Oracle Cloud Setup
- [ ] Oracle 계정 생성
- [ ] Compute Instance 생성
- [ ] SSH 키 설정
- [ ] 보안 규칙 설정
- [ ] SSH 접속 테스트

### Production Deployment
- [ ] oracle_setup.sh 실행
- [ ] 환경 변수 설정
- [ ] 서비스 시작
- [ ] API 테스트
- [ ] SSL 인증서 설정
- [ ] Nginx 설정 확인

### Post-Deployment
- [ ] 성능 모니터링 설정
- [ ] 백업 정책 수립
- [ ] 로그 수집 설정
- [ ] 문제 발생 시 대응 계획
- [ ] 팀 교육

---

## 🔑 주요 API 엔드포인트

### Health Check
```bash
GET /health

Response:
{
  "status": "healthy",
  "timestamp": "ISO 8601",
  "oracle_enabled": boolean
}
```

### 시뮬레이션 요청
```bash
POST /api/simulate
Authorization: Bearer [API_KEY]
Content-Type: multipart/form-data

Form Data:
- stl_file: [binary] (required)
- signal_id: string
- gate_x, gate_y, gate_z: float
- gate_dia: float
- vel_mms: float
- etime: float
- num_frames: int
- mesh_res_mm: float
- material: string
- screw_dia: float

Response:
{
  "job_id": "string",
  "status": "queued",
  "message": "string",
  "est_time_sec": int
}
```

### 작업 상태 조회
```bash
GET /api/jobs/{job_id}
Authorization: Bearer [API_KEY]

Response:
{
  "job_id": "string",
  "status": "running|completed|failed",
  "created_at": "ISO 8601",
  "elapsed_sec": int,
  "progress": 0-100,
  "error": "optional error message"
}
```

### 결과 다운로드
```bash
GET /api/results/{job_id}
Authorization: Bearer [API_KEY]

Response:
{
  "job_id": "string",
  "status": "completed",
  "completed_at": "ISO 8601",
  "files": ["results.json", "frames.zip", ...],
  "results": {object}
}
```

### 작업 취소
```bash
DELETE /api/jobs/{job_id}
Authorization: Bearer [API_KEY]

Response:
{
  "status": "deleted"
}
```

---

## 📚 참고 자료

### 공식 문서
- [Oracle Cloud Documentation](https://docs.oracle.com/en-us/iaas/)
- [Oracle Cloud Python SDK](https://github.com/oracle/oci-python-sdk)
- [Flask Documentation](https://flask.palletsprojects.com/)
- [Streamlit Documentation](https://docs.streamlit.io/)

### 튜토리얼
- [Oracle Always Free Tier](https://www.oracle.com/cloud/free/)
- [OCI CLI Quick Start](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm)
- [Docker Getting Started](https://docs.docker.com/get-started/)

### 추가 도움
- GitHub Issues: 기술적 문제
- Stack Overflow: 일반 프로그래밍 질문
- Oracle Community: Oracle 관련 질문

---

## ⚠️ 주의사항

1. **보안**
   - 프로덕션에서 API_KEY 반드시 변경
   - SSH 키를 안전하게 관리
   - 정기적인 보안 업데이트

2. **비용**
   - Oracle Free Tier 리소스 모니터링
   - 초과 사용에 대한 비용 알림 설정
   - 필요 없는 리소스는 정리

3. **데이터**
   - 중요한 결과 백업
   - Object Storage 활용
   - 정기적인 일관성 검사

4. **성능**
   - 메모리 사용량 모니터링
   - 병목 지점 파악 및 최적화
   - 스케일링 계획 수립

---

## 📞 다음 단계

### 준비 완료! 다음과 같이 진행하세요:

1. **지금 바로**
   - [ ] 이 가이드 전체 읽기
   - [ ] GitHub에서 저장소 클론

2. **오늘 중**
   - [ ] Docker로 로컬 테스트
   - [ ] Oracle 계정 생성

3. **내일 또는 다음 날**
   - [ ] Instance 생성
   - [ ] 배포 스크립트 실행

4. **한주 내**
   - [ ] 프로덕션 테스트
   - [ ] 팀과 공유
   - [ ] 모니터링 설정

---

## 💬 문의사항

이 가이드에서 명확하지 않은 부분이 있으면:

1. **GitHub Issues** 에 질문 올리기
2. **이메일**로 기술 지원 요청
3. **문서** 다시 확인 (특히 트러블슈팅 섹션)

---

**축하합니다! 🎉 이제 Oracle Cloud에서 고성능 MIM-Ops를 운영할 준비가 되었습니다!**

**마지막 확인:** 모든 파일이 GitHub에 푸시되었나요?
```bash
git status
git add .
git commit -m "feat: Oracle Cloud migration complete"
git push origin main
```

**배포 성공을 기원합니다! 🚀**
