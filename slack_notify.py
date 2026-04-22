"""Slack 발송 모듈: Block Kit 메시지 + 스레드에 엑셀 첨부."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from scraper import IpoItem


# 섹션당 최대 표시 건수. 각 종목을 별도 block으로 렌더링하므로
# 전체 block 수가 Slack 상한(50)을 넘지 않도록 여유있게 잡음.
MAX_ITEMS_PER_SECTION = 10

_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _format_header_date(run_date: str) -> str:
    """'2026-04-22' -> '2026-04-22(수)'"""
    try:
        dt = datetime.strptime(run_date, "%Y-%m-%d")
        return f"{run_date}({_WEEKDAY_KO[dt.weekday()]})"
    except ValueError:
        return run_date


def _format_item_full(it: IpoItem) -> str:
    """공모중·최근마감: 6컬럼 모두 세로 나열."""
    comp = it.competition if it.competition else "-"
    return (
        f"*<{it.detail_url}|{it.name}>*\n"
        f"- 공모주 일정 : {it.schedule}\n"
        f"- 확정 공모가 : {it.fixed_price}\n"
        f"- 희망 공모가 : {it.desired_price}\n"
        f"- 청약 경쟁률 : {comp}\n"
        f"- 주간사 : {it.underwriter}"
    )


def _format_item_upcoming(it: IpoItem) -> str:
    """공모예정: 4컬럼만 세로 나열."""
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
) -> list[dict]:
    """
    한 섹션의 Block Kit blocks 반환.
    비어있어도 '(0건)' 헤더는 항상 표시.
    종목 간에는 빈 block(divider) 없이 개별 section block 사이의
    자연스러운 여백으로 구분.
    """
    header_text = f"{emoji} *{title}* ({len(items)}건)"
    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
    ]

    if items:
        shown = items[:MAX_ITEMS_PER_SECTION]
        for it in shown:
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": formatter(it)}}
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

    blocks.append({"type": "divider"})
    return blocks


def build_blocks(
    ongoing: list[IpoItem],
    upcoming: list[IpoItem],
    recent_end: list[IpoItem],
    run_date: str,
) -> list[dict]:
    """세 섹션 합쳐 Block Kit 리스트 생성."""
    title = f"경쟁사 IPO 일정 ({_format_header_date(run_date)})"
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
    blocks += _section_blocks("현재 공모중인 상품", "🔥", ongoing, _format_item_full)
    blocks += _section_blocks("1주일 내 공모예정 상품", "📅", upcoming, _format_item_upcoming)
    blocks += _section_blocks("최근 마감한 상품", "✅", recent_end, _format_item_full)

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


def _fallback_text(ongoing, upcoming, recent_end, run_date: str) -> str:
    """알림 미리보기/접근성용 폴백."""
    return (
        f"[경쟁사 IPO {run_date}] "
        f"공모중 {len(ongoing)}건 · 예정 {len(upcoming)}건 · 최근마감 {len(recent_end)}건"
    )


def send(
    ongoing: list[IpoItem],
    upcoming: list[IpoItem],
    recent_end: list[IpoItem],
    excel_path: Path,
    run_date: str,
    token: Optional[str] = None,
    channel: Optional[str] = None,
) -> None:
    """메시지 전송 후 같은 스레드에 엑셀 첨부."""
    token = token or os.environ["SLACK_BOT_TOKEN"]
    channel = channel or os.environ["SLACK_CHANNEL_ID"]

    client = WebClient(token=token)
    blocks = build_blocks(ongoing, upcoming, recent_end, run_date)
    fallback = _fallback_text(ongoing, upcoming, recent_end, run_date)

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
            title=f"38_IPO_{run_date}",
            initial_comment="📎 최근 공모 현황 (10페이지 전체)",
        )
    except SlackApiError as e:
        # 업로드 실패해도 본 메시지는 이미 나갔으므로 로그만 남기고 진행
        print(f"[WARN] Slack file upload failed: {e.response.get('error')}")
        raise
