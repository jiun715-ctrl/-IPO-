"""전체 IPO 목록을 Excel로 저장."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from scraper import IpoItem


COLUMNS = [
    ("종목명", "name", 28),
    ("공모주일정", "schedule", 22),
    ("확정공모가", "fixed_price", 14),
    ("희망공모가", "desired_price", 18),
    ("청약경쟁률", "competition", 14),
    ("주간사", "underwriter", 30),
    ("상세 링크", "detail_url", 55),
    ("분석 링크", "analysis_url", 55),
]

HEADER_FILL = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")


def write_excel(items: Iterable[IpoItem], out_path: Path) -> Path:
    """IpoItem 목록을 xlsx로 저장하고 경로 반환."""
    wb = Workbook()
    ws = wb.active
    ws.title = "IPO 청약일정"

    # 헤더
    for col_idx, (header, _, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # 데이터
    for row_idx, item in enumerate(items, start=2):
        for col_idx, (_, attr, _) in enumerate(COLUMNS, start=1):
            value = getattr(item, attr) or ""
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = LEFT

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    wb.save(out_path)
    return out_path
