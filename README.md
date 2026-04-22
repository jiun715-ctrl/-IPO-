# 38-ipo-scraper

38커뮤니케이션 공모주 청약일정 페이지(https://www.38.co.kr/html/fund/index.htm?o=k)를 매일 크롤링해 Slack으로 발송합니다.

## 기능

- **크롤링 범위**: `o=k` 페이지 1~10 (약 300건, 최근 3년 수준)
- **Slack 메시지 3섹션**:
  - 🔥 현재 공모중인 상품 — 종목명 / 공모주일정 / 확정공모가 / 희망공모가 / 청약경쟁률 / 주간사
  - 📅 1주일 내 공모예정 상품 — 종목명 / 공모주일정 / 희망공모가 / 주간사
  - ✅ 최근 마감한 상품 (지난 7일) — 종목명 / 공모주일정 / 확정공모가 / 희망공모가 / 청약경쟁률 / 주간사
- **엑셀 첨부**: 10페이지 전체를 메시지 스레드에 첨부 (`{YYYYMMDD}_38_ipo_schedule.xlsx`)
- **스킵 조건**: 세 섹션이 모두 비어있거나, 전일과 완전히 동일하면 슬랙·엑셀 모두 미발송
- **스케줄**: KST 매일 08:00 (UTC 23:00) GitHub Actions cron

## 구성

```
.
├── scraper.py         # 크롤링 + 섹션 분류
├── excel_writer.py    # xlsx 생성
├── slack_notify.py    # Block Kit 메시지 + 엑셀 업로드
├── main.py            # 오케스트레이션
├── test_scraper.py    # 파서 단위 테스트
├── requirements.txt
├── snapshot.json      # 전일 스냅샷 (Actions가 자동 커밋)
└── .github/workflows/daily.yml
```

## Secrets

GitHub repo Settings → Secrets and variables → Actions에 다음 두 개 등록:

- `SLACK_BOT_TOKEN` — `xoxb-...` (봇 토큰)
- `SLACK_CHANNEL_ID` — 예: `C0123ABCD` (채널 ID, 채널명 아님)

### Slack 앱 권한 (OAuth scopes)

- `chat:write`
- `files:write`

봇을 대상 채널에 초대해둬야 합니다 (`/invite @봇이름`).

## 로컬 실행 / 테스트

```bash
pip install -r requirements.txt

# 파서 단위 테스트 (네트워크 안탐)
python test_scraper.py

# 실제 크롤링만 확인
python scraper.py

# 슬랙까지 풀런 (환경변수 필요)
SLACK_BOT_TOKEN=xoxb-... SLACK_CHANNEL_ID=C0... python main.py
```

## 주의사항

- 38커뮤니케이션은 EUC-KR 인코딩. `scraper.py`에서 `resp.encoding = "euc-kr"` 고정.
- 공모주일정 문자열(`2025.12.29~01.02` 같은 연도 넘김)도 파싱 처리.
- Actions는 `contents: write` 권한으로 `snapshot.json`을 자동 커밋합니다.
