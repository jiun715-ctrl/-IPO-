"""
전회 스냅샷 ↔ 오늘 스냅샷 차이를 카테고리별 카운트로 요약.

카테고리:
  - new          : 어제 어느 섹션에도 없던 종목이 신규 등장
  - removed      : 어제는 있었는데 오늘 3섹션 어디에도 없음 (마감 처리)
  - competition  : 같은 종목의 청약 경쟁률 변경
  - fixed_price  : 같은 종목의 확정 공모가 변경
  - other        : 위 외 필드(희망공모가/공모일정/주간사) 변경

월 경계(labels 변경) 첫 실행은 비교를 생략하고 안내 메시지를 띄움.
"""

from __future__ import annotations

from typing import Optional


SECTION_KEYS = ("last_month", "this_month", "next_month")


def _index_by_name(snapshot: dict) -> dict[str, dict]:
    """스냅샷의 모든 종목을 name → record 로 인덱싱."""
    out: dict[str, dict] = {}
    for key in SECTION_KEYS:
        for rec in snapshot.get(key, []):
            name = rec.get("name", "")
            if name:
                # 같은 이름이 여러 섹션에 있으면 마지막 것이 덮어쓰지만
                # 분류 로직상 한 종목이 여러 섹션에 동시에 들어가지는 않음
                out[name] = rec
    return out


def _labels_match(prev: Optional[dict], curr: dict) -> bool:
    if not prev:
        return False
    return prev.get("labels") == curr.get("labels")


def diff_summary(prev: Optional[dict], curr: dict) -> dict:
    """
    diff 결과를 dict 로 반환:
      {
        "kind": "first_run" | "month_changed" | "diff",
        "counts": {"new": int, "removed": int, "competition": int,
                   "fixed_price": int, "other": int},
      }
    - first_run    : 이전 스냅샷이 없거나 빈 dict
    - month_changed: labels (전월/당월/익월 월 자체) 가 바뀐 경우 — 카운트 비움
    - diff         : 정상 비교 결과
    """
    counts = {
        "new": 0,
        "removed": 0,
        "competition": 0,
        "fixed_price": 0,
        "other": 0,
    }

    if not prev or not any(prev.get(k) for k in SECTION_KEYS):
        return {"kind": "first_run", "counts": counts}

    if not _labels_match(prev, curr):
        return {"kind": "month_changed", "counts": counts}

    prev_idx = _index_by_name(prev)
    curr_idx = _index_by_name(curr)

    prev_names = set(prev_idx.keys())
    curr_names = set(curr_idx.keys())

    counts["new"] = len(curr_names - prev_names)
    counts["removed"] = len(prev_names - curr_names)

    # 양쪽에 다 있는 종목들 필드 변경 카운트
    for name in prev_names & curr_names:
        p = prev_idx[name]
        c = curr_idx[name]
        if p.get("competition") != c.get("competition"):
            counts["competition"] += 1
        if p.get("fixed_price") != c.get("fixed_price"):
            counts["fixed_price"] += 1
        # 그 외 필드 (schedule, desired_price, underwriter)
        if (
            p.get("schedule") != c.get("schedule")
            or p.get("desired_price") != c.get("desired_price")
            or p.get("underwriter") != c.get("underwriter")
        ):
            counts["other"] += 1

    return {"kind": "diff", "counts": counts}


def format_diff_text(summary: dict) -> Optional[str]:
    """
    Slack 헤더 위에 표시할 한 줄 안내문 생성.
    표시할 내용 없으면 None 반환.
    """
    kind = summary["kind"]

    if kind == "first_run":
        return None

    if kind == "month_changed":
        return (
            "🔔 *직전 내역에서 변동사항이 발생하였습니다.* "
            "월이 바뀌어 섹션 기준이 갱신되었습니다."
        )

    counts = summary["counts"]
    label_map = [
        ("new", "신규"),
        ("removed", "마감 처리"),
        ("competition", "청약 경쟁률 갱신"),
        ("fixed_price", "확정 공모가 갱신"),
        ("other", "기타 변경"),
    ]
    parts = [f"{label} {counts[k]}건" for k, label in label_map if counts[k] > 0]

    if not parts:
        # 종목·필드 변경은 없는데 어떤 이유로든 스냅샷 동등성 비교에서만
        # 차이가 났을 경우 (예: 키 정렬 순서). 안내 생략.
        return None

    return "🔔 *직전 내역에서 변동사항이 발생하였습니다.* " + ", ".join(parts) + "."
