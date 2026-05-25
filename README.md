# 청구전문컨설팅Medium

병원 청구심사 업무용 Streamlit 프로그램입니다.

## 실행

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## 관리자 계정

기본값은 아래와 같습니다. 운영 전 반드시 환경변수로 변경하세요.

```powershell
$env:MEDIUM_ADMIN_ID="원하는아이디"
$env:MEDIUM_ADMIN_PASSWORD="강한비밀번호"
```

기본 관리자 계정:

- ID: `admin`
- PW: `medium!2026`

## 외부 AI 연결

외부 AI 진단은 선택 기능입니다.

```powershell
$env:OPENAI_API_KEY="..."
$env:OPENAI_MODEL="gpt-4.1-mini"
$env:GEMINI_API_KEY="..."
$env:GEMINI_MODEL="gemini-1.5-flash"
```

API 키가 없으면 내부 규칙 기반 진단만 표시됩니다.

## 업로드 자료 형식

관리자 화면에서 CSV 양식을 내려받아 처방 자료와 사례 자료를 등록할 수 있습니다.

처방 자료 필수 컬럼:

- `department`
- `order_code`
- `order_name`

사례 자료 필수 컬럼:

- `title`
- `summary`

## 주의

이 프로그램은 청구 심사 보조 도구입니다. 실제 청구 전에는 최신 심평원 고시, 심사기준, 급여기준, 병원 내부 기준을 반드시 확인해야 합니다.
