"""Slack 발송 모듈: Block Kit 메시지 + 스레드에 엑셀 첨부."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from scraper import IpoItem


MAX_ITEMS_PER_SECTION = 15  # 섹션당 최대 표시 건수 (Slack 메시지 길이 안전장치)


def _format_ongoing_line(it: IpoItem) -> str:
    """공모중·최근마감: 6컬럼 모두."""
    parts = [
        f"<{it.detail_url}|*{it.name}*>",
        f"`{it.schedule}`",
        f"확정 {it.fixed_price}",
        f"희망 {it.desired_price}",
    ]
    if it.competition:
        parts.append(f"경쟁률 {it.competition}")
    parts.append(f"주간사 {it.underwriter}")
    return " · ".join(parts)


def _format_upcoming_line(it: IpoItem) -> str:
    """공모예정: 4컬럼만."""
    parts = [
        f"<{it.detail_url}|*{it.name}*>",
        f"`{it.schedule}`",
        f"희망 {it.desired_price}",
        f"주간사 {it.underwriter}",
    ]
    return " · ".join(parts)


def _section_blocks(title: str, emoji: str, items: list[IpoItem], formatter) -> list[dict]:
    """한 섹션에 해당하는 Block Kit blocks 반환. 빈 리스트면 []."""
    if not items:
        return []
    header = f"{emoji} *{title}* ({len(items)}건)"
    shown = items[:MAX_ITEMS_PER_SECTION]
    lines = [formatter(it) for it in shown]
    body = "\n".join(f"• {line}" for line in lines)
    if len(items) > MAX_ITEMS_PER_SECTION:
        body += f"\n_...외 {len(items) - MAX_ITEMS_PER_SECTION}건_"

    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        {"type": "divider"},
    ]


def build_blocks(
    ongoing: list[IpoItem],
    upcoming: list[IpoItem],
    recent_end: list[IpoItem],
    run_date: str,
) -> list[dict]:
    """세 섹션 합쳐 Block Kit 리스트 생성."""
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📊 38커뮤니케이션 IPO 일정 ({run_date})"},
        },
        {"type": "divider"},
    ]
    blocks += _section_blocks("현재 공모중인 상품", "🔥", ongoing, _format_ongoing_line)
    blocks += _section_blocks("1주일 내 공모예정 상품", "📅", upcoming, _format_upcoming_line)
    blocks += _section_blocks("최근 마감한 상품", "✅", recent_end, _format_ongoing_line)

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "출처: <https://www.38.co.kr/html/fund/index.htm?o=k|38커뮤니케이션> · 상세 데이터는 첨부 엑셀 참고",
                }
            ],
        }
    )
    return blocks


def _fallback_text(ongoing, upcoming, recent_end, run_date: str) -> str:
    """알림 미리보기/접근성용 폴백."""
    return (
        f"[38 IPO {run_date}] "
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
