"""Slack 발송 모듈: Block Kit 메시지 + 스레드에 엑셀 첨부."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from scraper import IpoItem
from excel_writer import _split_underwriters


# 섹션당 최대 표시 건수. 각 종목을 별도 block으로 렌더링하므로
# 전체 block 수가 Slack 상한(50)을 넘지 않도록 여유있게 잡음.
MAX_ITEMS_PER_SECTION = 12

_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]

_OWN_FIRM = "NH투자증권"  # 섹션 요약에서 항상 맨 앞에 표시


def _format_header_date(run_date: str) -> str:
    """'2026-05-01' → '2026-05-01(금)'"""
    try:
        dt = datetime.strptime(run_date, "%Y-%m-%d")
        return f"{run_date}({_WEEKDAY_KO[dt.weekday()]})"
    except ValueError:
        return run_date


def _yy_mm(year: int, month: int) -> str:
    """2026, 5 → \"'26년 5월\""""
    return f"'{year % 100:02d}년 {month}월"


def _underwriter_summary(items: list[IpoItem]) -> str:
    """
    섹션 내 증권사별 주간 건수 요약.
    - 한 종목에 주간사가 N개면 각 증권사에 1건씩 카운트 (엑셀 집계와 동일)
    - NH투자증권을 항상 맨 앞에 (있을 경우)
    - 그 뒤는 건수 desc → 증권사명 가나다순
    - 섹션이 비어있으면 빈 문자열
    """
    counts: dict[str, int] = {}
    for it in items:
        for uw in _split_underwriters(it.underwriter):
            counts[uw] = counts.get(uw, 0) + 1
    if not counts:
        return ""

    others = [(k, v) for k, v in counts.items() if k != _OWN_FIRM]
    others.sort(key=lambda x: (-x[1], x[0]))

    parts: list[str] = []
    if _OWN_FIRM in counts:
        parts.append(f"{_OWN_FIRM}({counts[_OWN_FIRM]}건)")
    parts.extend(f"{k}({v}건)" for k, v in others)
    return ", ".join(parts)


def _format_item_full(it: IpoItem) -> str:
    """전월 완료: 6컬럼 세로."""
    comp = it.competition if it.competition else "-"
    return (
        f"*<{it.detail_url}|{it.name}>*\n"
        f"- 공모주 일정 : {it.schedule}\n"
        f"- 희망 공모가 : {it.desired_price}\n"
        f"- 확정 공모가 : {it.fixed_price}\n"
        f"- 청약 경쟁률 : {comp}\n"
        f"- 주간사 : {it.underwriter}"
    )


def _format_item_upcoming(it: IpoItem) -> str:
    """당월/익월 공모 예정: 4컬럼 세로."""
    return (
        f"*<{it.detail_url}|{it.name}>*\n"
        f"- 공모주 일정 : {it.schedule}\n"
        f"- 희망 공모가 : {it.desired_price}\n"
        f"- 주간사 : {it.underwriter}"
    )


def _section_blocks(
    title: str,
    emoji: str,
    items: list[IpoItem],
    formatter: Callable[[IpoItem], str],
    empty_text: str,
) -> list[dict]:
    """
    한 섹션의 Block Kit blocks 반환.
    - 비어있지 않으면 헤더 아래에 증권사별 요약 한 줄 추가
    - 비어있으면 '(0건)' 헤더 + 안내 문구
    """
    header_text = f"{emoji} *{title}* ({len(items)}건)"
    summary = _underwriter_summary(items)
    if summary:
        header_text += f"\n* {summary}"

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
    ]

    if items:
        shown = items[:MAX_ITEMS_PER_SECTION]
        for idx, it in enumerate(shown, start=1):
            text = f"{idx}) " + formatter(it)
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": text}}
            )
        if len(items) > MAX_ITEMS_PER_SECTION:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"_...외 {len(items) - MAX_ITEMS_PER_SECTION}건_",
                        }
                    ],
                }
            )
    else:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_{empty_text}_"}],
            }
        )

    blocks.append({"type": "divider"})
    return blocks


def build_blocks(
    last_month: list[IpoItem],
    this_month: list[IpoItem],
    next_month: list[IpoItem],
    run_date: str,
    labels: dict[str, tuple[int, int]],
) -> list[dict]:
    """세 섹션 합쳐 Block Kit 리스트 생성."""
    title = f"경쟁사 IPO 일정 ({_format_header_date(run_date)})"

    last_y, last_m = labels["last"]
    this_y, this_m = labels["this"]
    next_y, next_m = labels["next"]

    last_label = f"전월({_yy_mm(last_y, last_m)}) 공모 완료 내역"
    this_label = f"당월({_yy_mm(this_y, this_m)}) 공모 예정 종목"
    next_label = f"익월({_yy_mm(next_y, next_m)}) 공모 예정 종목"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "종목명을 클릭하실 경우 상세 페이지로 이동합니다. "
                        "Slack 메시지는 전일과 내용이 바뀔 경우에만 게시됩니다."
                    ),
                }
            ],
        },
        {"type": "divider"},
    ]
    blocks += _section_blocks(
        last_label, "✅", last_month, _format_item_full,
        empty_text="전월 공모 완료 내역이 없습니다.",
    )
    blocks += _section_blocks(
        this_label, "🔥", this_month, _format_item_upcoming,
        empty_text="당월 공모 예정 종목이 없습니다.",
    )
    blocks += _section_blocks(
        next_label, "📅", next_month, _format_item_upcoming,
        empty_text="익월 공모 예정 종목이 없습니다.",
    )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "출처: "
                        "<https://www.38.co.kr/html/fund/index.htm?o=k|38커뮤니케이션>"
                        " · 상세 데이터는 첨부 엑셀 참고"
                    ),
                }
            ],
        }
    )
    return blocks


def _fallback_text(last_m, this_m, next_m, run_date: str) -> str:
    """알림 미리보기/접근성용 폴백."""
    return (
        f"[경쟁사 IPO {run_date}] "
        f"전월 완료 {len(last_m)}건 · 당월 예정 {len(this_m)}건 · 익월 예정 {len(next_m)}건"
    )


def send(
    last_month: list[IpoItem],
    this_month: list[IpoItem],
    next_month: list[IpoItem],
    excel_path: Path,
    run_date: str,
    labels: dict[str, tuple[int, int]],
    token: Optional[str] = None,
    channel: Optional[str] = None,
) -> None:
    """메시지 전송 후 같은 스레드에 엑셀 첨부."""
    token = token or os.environ["SLACK_BOT_TOKEN"]
    channel = channel or os.environ["SLACK_CHANNEL_ID"]

    client = WebClient(token=token)
    blocks = build_blocks(last_month, this_month, next_month, run_date, labels)
    fallback = _fallback_text(last_month, this_month, next_month, run_date)

    # 1) 본 메시지
    resp = client.chat_postMessage(channel=channel, text=fallback, blocks=blocks)
    thread_ts = resp["ts"]

    # 2) 엑셀을 같은 스레드에 첨부
    try:
        client.files_upload_v2(
            channel=channel,
            thread_ts=thread_ts,
            file=str(excel_path),
            filename=excel_path.name,
            title=f"경쟁사_IPO_집계_{run_date}",
            initial_comment="📎 증권사별 IPO 주간 집계 (최근 3년)",
        )
    except SlackApiError as e:
        print(f"[WARN] Slack file upload failed: {e.response.get('error')}")
        raise
