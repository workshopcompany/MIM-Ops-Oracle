# 🎨 MIM-Ops Pro v3.2 GUI 업그레이드 가이드

**완전히 새로워진 고급 기능들이 복원되었습니다!**

---

## ✨ 새로 추가된 기능들

### 1️⃣ **STL 파일 업로드 및 3D 시각화**

#### 기능
- STL 파일 드래그&드롭 업로드
- 파트 정보 실시간 표시:
  - 📊 **Volume**: 파트 부피 (mm³)
  - 📐 **Size**: 길이 × 너비 × 높이 (mm)
  - 📈 **Faces**: 메시 면의 개수
- **3D 인터랙티브 시각화** (Plotly 기반)
  - 마우스로 회전, 확대/축소 가능
  - 게이트 위치를 빨간 점으로 표시

#### 사용 방법
```
1. "STL 파일 선택" 버튼 클릭
2. 파일 선택 또는 드래그&드롭
3. 자동으로 3D 모델 로드 및 표시
4. 하단 "3D Visualization" 섹션에서 모델 확인
```

---

### 2️⃣ **게이트 위치 자동 추천**

#### 기능
- **🎯 자동 분석 기반 추천** (3가지 옵션)
  1. **Bottom-Center**: 균형 잡힌 충전
  2. **Side Direction**: 긴 축 방향 충전
  3. **Top-Center**: 상단 중심 충전

- **🤖 Gemini AI 조언** (설정 시)
  - 재료 특성 + 형상 기반 최적 위치 추천
  - 한국어로 자세한 설명 제공

#### 사용 방법
```
1. STL 파일 업로드 후
2. "🎯 게이트 위치 추천" 버튼 클릭
3. 자동으로 3개 위치 분석 (약 2초)
4. 추천 위치 중 하나를 선택하면 자동 적용
5. 또는 수동으로 X, Y, Z 좌표 직접 입력
```

#### 예시
```
Bottom-Center 클릭
→ 게이트 위치: (45.2, 32.1, 15.8) mm 자동 설정
→ 3D 모델에 빨간 점으로 표시
```

---

### 3️⃣ **재료 데이터베이스 자동 로드**

#### 포함된 재료 (총 29종)

**MIM Feedstocks:**
- CATAMOLD-304L, CATAMOLD-4140, CATAMOLD-17-4PH, CATAMOLD-316L, CATAMOLD-Fe-Ni, CATAMOLD-Al6061, CATAMOLD-Al7075, CATAMOLD-Ti-6Al-4V, CATAMOLD-TiH2
- WAXBASE-304L, WAXBASE-4140, WAXBASE-17-4PH, WAXBASE-316L, WAXBASE-Fe-Ni, WAXBASE-Al6061, WAXBASE-Al7075, WAXBASE-Ti-6Al-4V, WAXBASE-TiH2

**Engineering Plastics:**
- PP, PE-HD, PE-LD, ABS, PC, PC+ABS, PA6, PA66, PA66+GF30, PA12, POM, PBT, PET, PPS, PPS+GF40, PEEK, PEI, PSU, LCP, PMMA, HIPS, PVC, TPU, TPE, EPDM

#### 각 재료의 데이터
```
기본 정보:
  • 점도 (Viscosity)
  • 밀도 (Density)
  • 용융 온도 (Tmelt)
  • 금형 온도 (Tmold)
  • 권장 압력 (Pressure)
  • 권장 속도 (Velocity)
```

---

### 4️⃣ **재료 선택 시 조건값 자동 업데이트** ⭐

#### 기능
재료를 선택하면 **모든 시뮬레이션 조건이 자동으로 업데이트**됩니다!

#### 자동 업데이트되는 값
```
재료 선택
    ↓
조회: get_material_properties()
    ↓
다음 항목 자동 설정:
  ✅ Melt Temperature (용융 온도)
  ✅ Injection Pressure (사출 압력)
  ✅ Injection Velocity (사출 속도)
```

#### 예시
```
기존 값:
  • Temperature: 230°C
  • Pressure: 70 MPa
  • Velocity: 80 mm/s

"PA66+GF30" 선택
    ↓ 자동 업데이트
  
새로운 값:
  • Temperature: 285°C (PA66의 용융점)
  • Pressure: 110 MPa (PA66의 권장값)
  • Velocity: 80 mm/s (PA66의 권장값)
```

#### 사용 방법
```
1. Process Parameters 섹션에서
2. "Material" 드롭다운 선택
3. 자동으로 온도, 압력, 속도 업데이트됨
4. 필요하면 수동으로 조정 가능
```

---

### 5️⃣ **재료 정보 확인**

#### 기능
선택된 재료의 상세 정보를 한눈에 확인

#### 표시 정보
```
📊 재료 정보 (expandable)
  ├─ 점도: 4.0e-03 m²/s
  ├─ 밀도: 7900 kg/m³
  ├─ 용융점: 185.0 °C
  ├─ 금형온도: 40.0 °C
  ├─ 권장 압력: 110.0 MPa
  └─ 권장 속도: 25.0 mm/s
```

#### 사용 방법
```
1. Process Parameters에서 재료 선택
2. "📊 재료 정보" 확장
3. 상세 정보 확인
```

---

## 📖 탭별 사용 가이드

### **탭 1: Simulation** (메인)

```
┌─────────────────────────────────────────────────────┐
│ 좌측 (Part 설정)          │ 우측 (Process 파라미터)     │
├───────────────────────────┼──────────────────────────┤
│ 1. STL 파일 업로드        │ 3. 재료 선택              │
│ 2. 게이트 위치 추천       │ 4. 온도, 압력, 속도 설정  │
│ 3. 게이트 수동 설정       │ 5. 게이트 직경 설정       │
│ 4. 3D 시각화             │ 6. 시뮬레이션 시간 설정   │
│                          │ 7. 🚀 Run Simulation    │
└─────────────────────────────────────────────────────┘
```

#### 작업 흐름
```
Step 1: STL 파일 업로드
  └─ 자동으로 파트 정보 표시
  └─ 3D 모델 렌더링

Step 2: 게이트 위치 추천 (선택사항)
  └─ "🎯 게이트 위치 추천" 클릭
  └─ 3개 추천 위치 표시
  └─ AI 조언 표시

Step 3: 재료 선택
  └─ Dropdown에서 재료 선택
  └─ 자동으로 온도, 압력, 속도 업데이트
  └─ 📊 재료 정보 확인

Step 4: 프로세스 파라미터 설정 (필요시 조정)
  └─ Temperature (온도)
  └─ Pressure (압력)
  └─ Velocity (속도)
  └─ Gate Diameter (게이트 직경)
  └─ End Time (시뮬레이션 시간)

Step 5: 시뮬레이션 실행
  └─ "🚀 Run Simulation" 클릭
  └─ Job ID 받음
  └─ 상태 모니터링 시작
```

---

### **탭 2: Material Library**

재료 데이터베이스 검색 및 조회

```
기능:
  • 전체 29개 재료 표시
  • 검색 기능 (예: "PA66", "CATAMOLD")
  • 테이블 형식으로 비교 조회
  
표시 항목:
  • Material (재료명)
  • Viscosity (점도)
  • Density (밀도)
  • Melt Temp (용융점)
  • Mold Temp (금형온도)
  • Pressure (압력)
  • Velocity (속도)
```

#### 검색 예시
```
검색: "PA66"
  ├─ PA66
  ├─ PA66+GF30
  └─ (이외 PA66 관련 재료)

검색: "CATAMOLD"
  ├─ CATAMOLD-304L
  ├─ CATAMOLD-4140
  ├─ CATAMOLD-17-4PH
  └─ ... (9개 CATAMOLD 재료)
```

---

### **탭 3: Results**

시뮬레이션 결과 모니터링 및 다운로드

```
기능:
  • 작업 상태 실시간 조회
  • 진행률 표시
  • 결과 다운로드
  
상태 표시:
  ✅ 완료 (Completed)
  ⏳ 실행 중 (Running)
  📋 대기 중 (Queued)
```

---

### **탭 4: Settings**

API 연결 설정 및 테스트

```
표시 정보:
  • Oracle Cloud API URL
  • API Key (암호화 표시)
  • 연결 상태 테스트
  • 앱 정보
```

---

## 🔧 설정 및 설치

### 파일 교체
```bash
# 기존 파일 백업
cp app/streamlit_app.py app/streamlit_app.py.backup

# 새 파일로 교체
cp streamlit_app_advanced.py app/streamlit_app.py
```

### 필요한 패키지 (자동 설치)
```
streamlit==1.28.1
requests
numpy
trimesh==3.21.7
plotly
pyvista
```

### Docker로 실행
```bash
# .streamlit/secrets.toml 파일 생성
mkdir -p .streamlit
cat > .streamlit/secrets.toml << EOF
ORACLE_API_URL = "http://localhost:5000"
API_KEY = "your-api-key"
GEMINI_API_KEY = "your-gemini-key"  # 선택사항
EOF

# Docker Compose 실행
docker-compose up -d

# Streamlit 접속
# http://localhost:8501
```

---

## 🎯 사용 팁 및 베스트 프랙티스

### ✅ 추천 사항

1. **재료 선택은 가장 먼저**
   ```
   게이트 위치 추천 → AI 조언에 재료 정보 활용
   ```

2. **AI 조언 활용**
   ```
   GEMINI_API_KEY 설정 시 더 정확한 게이트 위치 추천
   ```

3. **프로세스 파라미터는 재료 기본값부터 시작**
   ```
   자동 설정값이 해당 재료의 최적값
   ```

4. **3D 모델 확인은 필수**
   ```
   게이트 위치가 파트에 제대로 접하는지 확인
   ```

5. **게이트 직경은 조심스럽게**
   ```
   너무 작으면: 사출 압력 증가, 형상 왜곡
   너무 크면: 게이트 흔적 커짐, 시간 낭비
   권장: 2.0 ~ 3.0 mm (파트 크기에 따라)
   ```

---

## 🐛 문제 해결

### Q1: 3D 모델이 안 보여요
```
A: 
  1. STL 파일 형식 확인 (바이너리 또는 ASCII)
  2. 파일 크기 확인 (너무 크면 로드 불가)
  3. Plotly 로드 대기 (인터넷 속도 확인)
```

### Q2: 게이트 위치 추천이 안 뜨네요
```
A:
  1. "🎯 게이트 위치 추천" 버튼 다시 클릭
  2. STL 파일이 제대로 로드되었는지 확인
  3. 콘솔 로그 확인 (오류 메시지)
```

### Q3: 재료 선택 시 값이 안 바뀌어요
```
A:
  1. 페이지 새로고침 (Ctrl+R 또는 F5)
  2. 재료명 정확히 확인 (대소문자 무시)
  3. material_property.txt 파일 위치 확인
```

### Q4: AI 조언이 안 나와요
```
A:
  1. GEMINI_API_KEY 설정 확인
  2. API Key 유효성 확인
  3. secrets.toml 파일 다시 생성
```

### Q5: 시뮬레이션 제출 실패
```
A:
  1. Oracle Cloud API 연결 테스트 (Settings 탭)
  2. API_KEY 정확성 확인
  3. STL 파일 크기 확인 (100MB 초과 시 분할)
```

---

## 📊 주요 기능 비교

| 기능 | v3.1 | v3.2 Advanced |
|------|------|--------------|
| STL 업로드 | ✅ | ✅ |
| 3D 시각화 | ❌ | ✅ **NEW** |
| 게이트 자동 추천 | ❌ | ✅ **NEW** |
| AI 조언 (Gemini) | ❌ | ✅ **NEW** |
| 재료 DB | ✅ | ✅ |
| 자동 값 업데이트 | ❌ | ✅ **NEW** |
| 재료 정보 표시 | ❌ | ✅ **NEW** |
| 결과 모니터링 | ✅ | ✅ |

---

## 🚀 다음 단계

1. **기존 streamlit_app.py 백업**
   ```bash
   cp app/streamlit_app.py app/streamlit_app_old.py
   ```

2. **새 파일로 교체**
   ```bash
   cp streamlit_app_advanced.py app/streamlit_app.py
   ```

3. **Docker 재시작**
   ```bash
   docker-compose restart mim-ops-streamlit
   ```

4. **새 기능 테스트**
   ```
   http://localhost:8501
   ```

---

## 📝 파일 정보

| 파일 | 설명 | 위치 |
|------|------|------|
| streamlit_app_advanced.py | 업그레이드된 GUI | app/ |
| material_property.txt | 재료 DB | . |
| .streamlit/secrets.toml | API 설정 | .streamlit/ |

---

## ✨ 요약

**새로워진 MIM-Ops Pro v3.2 GUI의 주요 개선사항:**

✅ **직관적인 3D 시각화** - 파트 형상 한눈에 파악
✅ **스마트 게이트 추천** - 기하학 분석 + AI 조언
✅ **자동화된 재료 설정** - 한 번의 클릭으로 모든 조건 자동 설정
✅ **포괄적인 재료 라이브러리** - 29개 재료 데이터베이스
✅ **사용자 친화적 인터페이스** - 신입도 쉽게 사용 가능

**이제 더욱 전문적이고 효율적인 MIM 시뮬레이션이 가능합니다!** 🎉

---

**질문이나 피드백은 GitHub Issues에 올려주세요.**
