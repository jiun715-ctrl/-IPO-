"""월간 배치 엔트리포인트.

흐름:
  1) 38.co.kr 15페이지 크롤링
  2) 배치일 기준 전월/당월/익월로 분류 (공모주일정 종료일 기준)
  3) 스냅샷이 전회와 동일하면 스킵 (수동 재실행 중복 방지)
  4) 최근 3년(배치일 기준 year-2, year-1, year) 증권사별 집계 엑셀 생성
  5) 슬랙 메시지 + 엑셀 스레드 첨부
  6) 스냅샷 파일 갱신 (workflow가 이어서 commit)

스케줄: 매월 1일 KST 08:00 — cron-job.org 외부 트리거 권장

환경변수:
  SLACK_BOT_TOKEN, SLACK_CHANNEL_ID
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scraper import IpoItem, fetch_all, classify_sections, month_labels
from excel_writer import write_excel
import slack_notify


KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent
SNAPSHOT_PATH = ROOT / "snapshot.json"
OUTPUT_DIR = ROOT / "output"

# 엑셀 집계 연도 수 (배치일 연도 포함 최근 N년)
YEARS_WINDOW = 3


def _snapshot_payload(
    sections: dict[str, list[IpoItem]],
    labels: dict[str, tuple[int, int]],
) -> dict:
    """비교용 스냅샷 — 섹션 구성 + 기준 월 포함."""
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
        "labels": {k: list(v) for k, v in labels.items()},
        "last_month": [norm(x) for x in sections["last_month"]],
        "this_month": [norm(x) for x in sections["this_month"]],
        "next_month": [norm(x) for x in sections["next_month"]],
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
    run_date_compact = now_kst.strftime("%Y%m")  # 월 단위 배치이므로 YYYYMM
    today = now_kst.date()

    print(f"[{run_date}] 38커뮤니케이션 월간 배치 시작")
    items = fetch_all()
    print(f"  총 {len(items)}건 크롤링")

    labels = month_labels(today)
    print(f"  기준 월 — 전월: {labels['last']}, 당월: {labels['this']}, 익월: {labels['next']}")

    sections = classify_sections(items, today=today)
    last_m = sections["last_month"]
    this_m = sections["this_month"]
    next_m = sections["next_month"]
    print(f"  전월 완료 {len(last_m)} · 당월 예정 {len(this_m)} · 익월 예정 {len(next_m)}")

    # --- 스킵 조건: 전회 스냅샷과 동일 (수동 재실행 중복 방지) ---
    today_payload = _snapshot_payload(sections, labels)
    prev_payload = _load_prev_snapshot()
    if prev_payload == today_payload:
        print("[SKIP] 전회 스냅샷과 동일 → 슬랙·엑셀 미발송")
        return 0

    # --- 엑셀 생성: 최근 3년 증권사별 집계 ---
    target_years = [today.year - i for i in range(YEARS_WINDOW - 1, -1, -1)]
    # 오름차순으로 만들어두지만 엑셀 내부에서는 desc로 정렬됨
    print(f"  엑셀 집계 연도: {target_years}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    excel_path = OUTPUT_DIR / f"{run_date_compact}_경쟁사_IPO_집계.xlsx"
    write_excel(items, excel_path, target_years=target_years)
    print(f"  엑셀 저장: {excel_path} ({excel_path.stat().st_size:,} bytes)")

    # --- 슬랙 발송 ---
    slack_notify.send(
        last_month=last_m,
        this_month=this_m,
        next_month=next_m,
        excel_path=excel_path,
        run_date=run_date,
        labels=labels,
    )
    print("  슬랙 발송 완료")

    # --- 스냅샷 업데이트 ---
    _write_snapshot(today_payload)
    print(f"  스냅샷 갱신: {SNAPSHOT_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
