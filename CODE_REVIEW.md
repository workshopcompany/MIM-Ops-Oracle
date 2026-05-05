# MIM-Ops Pro v3.1 → Oracle Cloud 마이그레이션
## 코드 검토 & 체크리스트

### 📌 app.py 검토 결과

#### ✅ 정상 부분
- [x] Streamlit 구조 잘 짜여있음 (UI 전용)
- [x] Session state 관리 좋음
- [x] Material DB 관리 체계적
- [x] Plotly/PyVista 시각화 안정적

#### ⚠️ 수정 필요 부분

1. **API 엔드포인트 하드코딩**
   ```python
   Line 30-34: ZAPIER_URL, GITHUB_TOKEN 등이 GitHub Actions 기반으로 설정됨
   → Oracle Cloud API 엔드포인트로 변경 필요
   ```

2. **GitHub Actions 의존성**
   ```python
   Line 713-800: dispatch_github_workflow() 함수
   → Oracle Cloud의 REST API 호출로 변경 필요
   ```

3. **GitHub Artifacts 다운로드**
   ```python
   Line 810-900: list_workflow_artifacts(), download_artifact() 함수
   → Oracle Object Storage API로 변경 필요
   ```

#### 수정 방법
- API 엔드포인트 추상화 (config 파일 사용)
- GitHub 관련 함수 → 범용 API 함수로 재설계
- 인증 방식 개선 (GitHub Token → Oracle API Key)

---

### 📌 solver.py 검토 결과

#### ✅ 정상 부분
- [x] Argument parsing 안정적
- [x] Dijkstra 알고리즘 최적화됨
- [x] VTK/matplotlib 헤드리스 환경 대응 완료
- [x] 에러 핸들링 좋음

#### ⚠️ 주의사항

1. **의존성 확인**
   ```
   필수: numpy, trimesh, matplotlib, scipy
   선택: vtk (있으면 VTK 출력, 없으면 스킵)
   ```

2. **메모리 사용**
   ```
   대형 메쉬 (>5M voxels) 시 메모리 급증
   → Oracle Compute에서 충분한 RAM 필요 (16GB 이상 권장)
   ```

3. **입력 파라미터 안정성**
   ```python
   Line 43-49: mesh_res_mm 파싱 로직 복잡
   → JSON 입력 방식으로 단순화 권장
   ```

---

### 🔧 필수 수정 사항 (우선순위)

#### **Priority 1: 데이터 흐름 재구성**
- [ ] REST API 서버 (Flask/FastAPI) 작성
- [ ] Oracle Object Storage 연동
- [ ] 인증 토큰 관리 시스템

#### **Priority 2: 파라미터 입력 표준화**
- [ ] JSON 기반 입력 스키마 정의
- [ ] 타입 검증 강화
- [ ] 에러 메시지 명확화

#### **Priority 3: 성능 최적화**
- [ ] Solver 병렬 처리 (multiprocessing)
- [ ] 메모리 프로파일링
- [ ] 계산 시간 측정 추가

#### **Priority 4: 배포 자동화**
- [ ] Docker 이미지 준비
- [ ] Oracle Cloud 배포 스크립트
- [ ] CI/CD 파이프라인

---

### 📦 필요한 Dependencies

```
streamlit==1.28.0
plotly==5.17.0
pyvista==0.41.1
trimesh==3.21.8
numpy==1.24.3
scipy==1.11.2
matplotlib==3.7.2
flask==2.3.3  (신규)
flask-cors==4.0.0  (신규)
oci==2.119.0  (Oracle SDK - 신규)
python-dotenv==1.0.0  (신규)
```

---

### 🚀 다음 단계

1. ✅ **코드 검토** (지금 진행 중)
2. **API 서버 프로토타입 작성** (Flask 기반)
3. **Oracle Cloud 계정 설정**
4. **Compute Instance 생성 & 환경 구성**
5. **배포 테스트**
6. **마이그레이션 완료**

---

### 💾 GitHub 저장소 구조 (권장)

```
workshopcompany/MIM-Ops-Oracle/
├── app/
│   ├── streamlit_app.py      (현재 app.py)
│   ├── config.yaml           (신규: 설정)
│   └── material_property.txt
├── solver/
│   ├── solver.py             (현재 solver.py)
│   ├── requirements.txt
│   └── tests/
├── api/
│   ├── server.py             (신규: Flask REST API)
│   ├── auth.py               (신규: 인증)
│   └── oracle_client.py       (신규: Oracle SDK)
├── infra/
│   ├── Dockerfile            (신규)
│   ├── docker-compose.yml     (신규)
│   └── oracle_setup.sh        (신규: 배포 스크립트)
├── .github/workflows/
│   └── deploy.yml            (신규: 배포 자동화)
└── README.md
```

