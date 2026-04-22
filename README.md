# 38-ipo-scraper (월간 배치)

38커뮤니케이션 공모주 청약일정 페이지(https://www.38.co.kr/html/fund/index.htm?o=k)를 **매월 1일 아침 8시(KST)** 에 크롤링해 Slack으로 발송합니다.

## 기능

- **크롤링 범위**: `o=k` 페이지 1~15 (약 450건, 최근 3년 커버)
- **분류 기준**: 배치일 기준 공모주일정의 **종료일**이 속한 달
  - 전월 완료 / 당월 공모 / 익월 공모 (경계 케이스는 종료일 기준)
- **Slack 메시지 3섹션**:
  - ✅ **전월(…년 …월) 공모 완료 내역** — 종목명/공모주일정/희망공모가/확정공모가/청약경쟁률/주간사
  - 🔥 **당월(…년 …월) 공모 예정 종목** — 종목명/공모주일정/희망공모가/주간사
  - 📅 **익월(…년 …월) 공모 예정 종목** — 종목명/공모주일정/희망공모가/주간사
  - 비어있어도 `(0건)` 표시 + 안내 문구
- **엑셀 첨부**: 증권사별·연도별 집계 (최근 3년)
  - 컬럼: 해당연도 / 증권사명 / 총 주간횟수 / 내역(청약시작일)
  - 정렬: 연도 desc → 주간횟수 desc → 증권사 가나다순
  - 한 종목에 주간사가 여러 개면 각 증권사에 1건씩 계상
  - 해당 연도에 0건인 증권사는 행 생성 안 함
- **스냅샷 diff**: 수동 재실행 시 중복 발송 방지

## 구성

```
.
├── scraper.py               # 크롤링 + 월 단위 분류
├── excel_writer.py          # 증권사별 연도별 집계 xlsx
├── slack_notify.py          # Block Kit 메시지 + 엑셀 업로드
├── main.py                  # 오케스트레이션
├── test_scraper.py          # 파서·분류 단위 테스트
├── requirements.txt
├── snapshot.json            # 전회 스냅샷 (Actions가 자동 커밋)
└── .github/workflows/daily.yml   # workflow_dispatch (외부 cron용)
```

## Secrets

GitHub repo Settings → Secrets and variables → Actions:
- `SLACK_BOT_TOKEN` — `xoxb-...`
- `SLACK_CHANNEL_ID` — 예: `C0123ABCD`

### Slack 앱 권한 (OAuth scopes)

- `chat:write`
- `files:write`

봇을 대상 채널에 초대해둬야 합니다 (`/invite @봇이름`).

## 스케줄링 (cron-job.org)

GitHub 내장 cron은 UTC 기준이라 월 경계(매월 1일) 계산 실수가 잦아 **cron-job.org** 외부 트리거로 돌립니다.

- **URL**: `https://api.github.com/repos/{owner}/{repo}/actions/workflows/daily.yml/dispatches`
- **Method**: POST
- **Headers**:
  - `Authorization: Bearer {GitHub PAT (Actions: Read and write)}`
  - `Accept: application/vnd.github+json`
  - `Content-Type: application/json`
- **Body**: `{"ref":"main"}`
- **Schedule**: Custom, `0 8 1 * *` (KST, 매월 1일 08:00)

## 로컬 실행 / 테스트

```bash
pip install -r requirements.txt

# 단위 테스트 (네트워크 안탐)
python test_scraper.py

# 실제 크롤링만 확인
python scraper.py

# 슬랙까지 풀런
SLACK_BOT_TOKEN=xoxb-... SLACK_CHANNEL_ID=C0... python main.py
```

## 주의사항

- 38커뮤니케이션은 EUC-KR 인코딩. `scraper.py`에서 `resp.encoding = "euc-kr"` 고정.
- 서버 SSL이 구식이라 `_LegacySSLAdapter`로 SECLEVEL=0 + legacy renegotiation 허용.
- 사이드바 노이즈 행은 공모주일정 파싱 실패로 자동 필터링.
- Actions는 `contents: write` 권한으로 `snapshot.json`을 자동 커밋합니다.
