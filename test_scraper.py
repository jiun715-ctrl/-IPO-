"""파서·분류·집계 단위 검증 (네트워크 없음)."""

from datetime import date

from bs4 import BeautifulSoup

from scraper import (
    IpoItem,
    _parse_schedule,
    _parse_row,
    _parse_list_html,
    month_labels,
    month_range,
    classify_sections,
)


# ----- 1) schedule 파싱 -----
def test_schedule_parsing():
    cases = [
        ("2026.05.20~05.21", ("2026-05-20", "2026-05-21")),
        ("2025.12.29~01.02", ("2025-12-29", "2026-01-02")),
        ("2025.12.15~2026.01.02", ("2025-12-15", "2026-01-02")),
        ("-", (None, None)),
        ("", (None, None)),
    ]
    for text, expected in cases:
        assert _parse_schedule(text) == expected, text
    print("  ✓ _parse_schedule")


# ----- 2) 사이드바 노이즈 필터링 (공모주일정 형식 아니면 제외) -----
NOISY_HTML = """
<table>
<!-- 정상 행 -->
<tr>
  <td><a href="http://www.38.co.kr/html/fund/?o=v&no=2287">피스피스스튜디오</a></td>
  <td>2026.05.20~05.21</td><td>-</td><td>19,000~21,500</td><td>&nbsp;</td>
  <td>NH투자증권,미래에셋증권</td>
  <td><a href="http://www.38.co.kr/html/fund/index.htm?o=v&no=2287">분석</a></td>
</tr>
<!-- 사이드바: 공모주일정 칸이 비어있음 -->
<tr>
  <td><a href="http://www.38.co.kr/html/fund/?o=v&no=9999">05/04 폴레드</a></td>
  <td></td><td></td><td></td><td></td><td></td><td></td>
</tr>
<tr>
  <td><a href="http://www.38.co.kr/html/fund/?o=v&no=2275">인벤테라</a></td>
  <td>2026.03.23~03.24</td><td>16,600</td><td>12,100~16,600</td><td>1913:1</td>
  <td>NH투자증권,유진투자증권</td>
  <td><a href="http://www.38.co.kr/html/fund/index.htm?o=v&no=2275">분석</a></td>
</tr>
</table>
"""

def test_noise_filter():
    items = _parse_list_html(NOISY_HTML)
    assert len(items) == 2
    assert [i.name for i in items] == ["피스피스스튜디오", "인벤테라"]
    print("  ✓ 사이드바 노이즈 제외")


# ----- 3) month_labels / month_range -----
def test_month_utils():
    assert month_labels(date(2026, 5, 1)) == {"last": (2026, 4), "this": (2026, 5), "next": (2026, 6)}
    assert month_labels(date(2026, 1, 1)) == {"last": (2025, 12), "this": (2026, 1), "next": (2026, 2)}
    assert month_labels(date(2026, 12, 1)) == {"last": (2026, 11), "this": (2026, 12), "next": (2027, 1)}

    assert month_range(2026, 2) == (date(2026, 2, 1), date(2026, 2, 28))
    assert month_range(2024, 2) == (date(2024, 2, 1), date(2024, 2, 29))  # 윤년
    assert month_range(2026, 12) == (date(2026, 12, 1), date(2026, 12, 31))
    print("  ✓ month_labels / month_range")


# ----- 4) classify_sections 경계 케이스 -----
def _item(name, start, end, uw="X증권"):
    return IpoItem(
        name=name, schedule=f"{start}~{end}",
        start_date=start, end_date=end,
        fixed_price="-", desired_price="1,000", competition="",
        underwriter=uw, detail_url=f"x/{name}", analysis_url="",
    )


def test_classify_monthly():
    base = date(2026, 5, 1)  # 5월 1일 배치

    items = [
        _item("전월종료",   "2026-04-20", "2026-04-21"),   # end=4/21 → last
        _item("전월말일",   "2026-04-29", "2026-04-30"),   # end=4/30 → last
        _item("경계_4to5",  "2026-04-29", "2026-05-02"),   # end=5/2  → this (종료일 기준)
        _item("당월",       "2026-05-10", "2026-05-11"),   # end=5/11 → this
        _item("당월말일",   "2026-05-30", "2026-05-31"),   # end=5/31 → this
        _item("익월",       "2026-06-05", "2026-06-06"),   # end=6/6  → next
        _item("경계_5to6",  "2026-05-30", "2026-06-02"),   # end=6/2  → next
        _item("익월말일",   "2026-06-29", "2026-06-30"),   # end=6/30 → next
        _item("범위밖_미래","2026-07-01", "2026-07-02"),   # 7월: 제외
        _item("범위밖_과거","2026-03-31", "2026-03-31"),   # 3월: 제외
    ]
    sec = classify_sections(items, today=base)

    last_names = [x.name for x in sec["last_month"]]
    this_names = [x.name for x in sec["this_month"]]
    next_names = [x.name for x in sec["next_month"]]

    assert set(last_names) == {"전월종료", "전월말일"}, last_names
    assert set(this_names) == {"경계_4to5", "당월", "당월말일"}, this_names
    assert set(next_names) == {"익월", "경계_5to6", "익월말일"}, next_names
    print("  ✓ classify_sections (월 단위, 경계 케이스 포함)")


# ----- 5) 1월 경계: 전월이 전년도 12월 -----
def test_classify_january():
    base = date(2026, 1, 15)
    items = [
        _item("작년12월", "2025-12-20", "2025-12-22"),  # 전월(2025-12)
        _item("당월",     "2026-01-10", "2026-01-12"),  # 당월(2026-01)
        _item("익월",     "2026-02-05", "2026-02-06"),  # 익월(2026-02)
    ]
    sec = classify_sections(items, today=base)
    assert [x.name for x in sec["last_month"]] == ["작년12월"]
    assert [x.name for x in sec["this_month"]] == ["당월"]
    assert [x.name for x in sec["next_month"]] == ["익월"]
    print("  ✓ 1월 배치에서 전월이 전년도 12월")


# ----- 6) 12월 경계: 익월이 다음해 1월 -----
def test_classify_december():
    base = date(2026, 12, 1)
    items = [
        _item("전월11월", "2026-11-25", "2026-11-26"),
        _item("당월12월", "2026-12-15", "2026-12-16"),
        _item("다음해1월", "2027-01-10", "2027-01-11"),
    ]
    sec = classify_sections(items, today=base)
    assert [x.name for x in sec["last_month"]] == ["전월11월"]
    assert [x.name for x in sec["this_month"]] == ["당월12월"]
    assert [x.name for x in sec["next_month"]] == ["다음해1월"]
    print("  ✓ 12월 배치에서 익월이 다음해 1월")


if __name__ == "__main__":
    print("파서 / 분류 테스트:")
    test_schedule_parsing()
    test_noise_filter()
    test_month_utils()
    test_classify_monthly()
    test_classify_january()
    test_classify_december()
    print("\n전체 통과 ✓")
