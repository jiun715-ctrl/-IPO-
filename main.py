"""일일 배치 엔트리포인트.

흐름:
  1) 38.co.kr 10페이지 크롤링
  2) 3섹션 분류 (공모중 / 1주일 내 예정 / 최근 마감)
  3) 스킵 조건 체크
     - 세 섹션 전부 비어있음 → exit (slack·excel 모두 미발송)
     - 오늘 스냅샷 == 전일 스냅샷 → exit
  4) 엑셀 생성
  5) 슬랙 메시지 + 엑셀 스레드 첨부
  6) 스냅샷 파일 갱신 (workflow가 이어서 commit)

환경변수:
  SLACK_BOT_TOKEN, SLACK_CHANNEL_ID
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scraper import IpoItem, fetch_all, classify_sections
from excel_writer import write_excel
import slack_notify


KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent
SNAPSHOT_PATH = ROOT / "snapshot.json"
OUTPUT_DIR = ROOT / "output"


def _snapshot_payload(sections: dict[str, list[IpoItem]]) -> dict:
    """비교용 스냅샷 — 로컬/네트워크 노이즈 없는 값만 포함."""
    def norm(it: IpoItem) -> dict:
        return {
            "name": it.name,
            "schedule": it.schedule,
            "fixed_price": it.fixed_price,
            "desired_price": it.desired_price,
            "competition": it.competition,
            "underwriter": it.underwriter,
        }
    return {
        "ongoing": [norm(x) for x in sections["ongoing"]],
        "upcoming": [norm(x) for x in sections["upcoming"]],
        "recent_end": [norm(x) for x in sections["recent_end"]],
    }


def _load_prev_snapshot() -> dict | None:
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_snapshot(payload: dict) -> None:
    SNAPSHOT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    now_kst = datetime.now(KST)
    run_date = now_kst.strftime("%Y-%m-%d")
    run_date_compact = now_kst.strftime("%Y%m%d")
    today = now_kst.date()

    print(f"[{run_date}] 38커뮤니케이션 크롤링 시작")
    items = fetch_all()
    print(f"  총 {len(items)}건 수집")

    sections = classify_sections(items, today=today)
    ongoing = sections["ongoing"]
    upcoming = sections["upcoming"]
    recent_end = sections["recent_end"]
    print(f"  공모중 {len(ongoing)} · 예정 {len(upcoming)} · 최근마감 {len(recent_end)}")

    # --- 스킵 조건 1: 세 섹션 전부 비어있음 ---
    if not ongoing and not upcoming and not recent_end:
        print("[SKIP] 세 섹션 모두 비어있음 → 슬랙·엑셀 미발송")
        return 0

    # --- 스킵 조건 2: 전일과 동일 ---
    today_payload = _snapshot_payload(sections)
    prev_payload = _load_prev_snapshot()
    if prev_payload == today_payload:
        print("[SKIP] 전일 스냅샷과 동일 → 슬랙·엑셀 미발송")
        return 0

    # --- 엑셀 생성 ---
    OUTPUT_DIR.mkdir(exist_ok=True)
    excel_path = OUTPUT_DIR / f"{run_date_compact}_38_ipo_schedule.xlsx"
    write_excel(items, excel_path)
    print(f"  엑셀 저장: {excel_path} ({excel_path.stat().st_size:,} bytes)")

    # --- 슬랙 발송 ---
    slack_notify.send(
        ongoing=ongoing,
        upcoming=upcoming,
        recent_end=recent_end,
        excel_path=excel_path,
        run_date=run_date,
    )
    print("  슬랙 발송 완료")

    # --- 스냅샷 업데이트 ---
    _write_snapshot(today_payload)
    print(f"  스냅샷 갱신: {SNAPSHOT_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
