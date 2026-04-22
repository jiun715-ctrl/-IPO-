"""파서 로직 단위 검증. 실제 38.co.kr HTML 일부를 본떠 테스트."""

from datetime import date

from scraper import (
    _parse_schedule,
    _parse_row,
    _parse_list_html,
    classify_sections,
    IpoItem,
)
from bs4 import BeautifulSoup


# 1) 일정 파싱
def test_schedule_parsing():
    cases = [
        ("2026.05.20~05.21", ("2026-05-20", "2026-05-21")),
        ("2026.04.20~04.21", ("2026-04-20", "2026-04-21")),
        ("2025.12.29~01.02", ("2025-12-29", "2026-01-02")),  # 연도 넘김
        ("2025.12.15~2026.01.02", ("2025-12-15", "2026-01-02")),  # 연도 명시
        ("-", (None, None)),
        ("", (None, None)),
    ]
    for text, expected in cases:
        got = _parse_schedule(text)
        assert got == expected, f"{text!r} → {got} (expected {expected})"
    print("  ✓ _parse_schedule")


# 2) 행 파싱
SAMPLE_ROW_HTML = """
<table><tr>
  <td><a href="http://www.38.co.kr/html/fund/?o=v&no=2287&l=&page=1">피스피스스튜디오</a></td>
  <td>2026.05.20~05.21</td>
  <td>-</td>
  <td>19,000~21,500</td>
  <td>&nbsp;</td>
  <td>NH투자증권,미래에셋증권</td>
  <td><a href="http://www.38.co.kr/html/fund/index.htm?o=v&no=2287&l=&page=1">분석보기</a></td>
</tr></table>
"""

def test_row_parsing():
    soup = BeautifulSoup(SAMPLE_ROW_HTML, "html.parser")
    tr = soup.find("tr")
    item = _parse_row(tr)
    assert item is not None
    assert item.name == "피스피스스튜디오"
    assert item.schedule == "2026.05.20~05.21"
    assert item.start_date == "2026-05-20"
    assert item.end_date == "2026-05-21"
    assert item.fixed_price == "-"
    assert item.desired_price == "19,000~21,500"
    assert item.underwriter == "NH투자증권,미래에셋증권"
    assert "no=2287" in item.detail_url
    assert "no=2287" in item.analysis_url
    print("  ✓ _parse_row")


# 3) 분류 로직
def test_classify():
    # 오늘 = 2026-04-22로 고정 (today 파라미터)
    today = date(2026, 4, 22)

    def make(name, start, end):
        return IpoItem(
            name=name, schedule=f"{start}~{end}",
            start_date=start, end_date=end,
            fixed_price="-", desired_price="1,000",
            competition="", underwriter="X증권",
            detail_url="https://x/"+name, analysis_url="",
        )

    items = [
        make("공모중A", "2026-04-20", "2026-04-22"),   # 오늘 마감 → ongoing
        make("공모중B", "2026-04-22", "2026-04-23"),   # 오늘 시작 → ongoing
        make("예정A",  "2026-04-27", "2026-04-28"),    # +5일 → upcoming
        make("예정B",  "2026-04-29", "2026-04-30"),    # +7일 → upcoming
        make("예정외", "2026-05-15", "2026-05-16"),    # +23일 → 제외
        make("마감A",  "2026-04-15", "2026-04-21"),    # 어제 마감 → recent_end
        make("마감B",  "2026-04-14", "2026-04-15"),    # -7일 → recent_end
        make("마감외", "2026-03-01", "2026-03-02"),    # 한달전 → 제외
    ]
    result = classify_sections(items, today=today)

    ongoing_names = [x.name for x in result["ongoing"]]
    upcoming_names = [x.name for x in result["upcoming"]]
    recent_names = [x.name for x in result["recent_end"]]

    assert set(ongoing_names) == {"공모중A", "공모중B"}, ongoing_names
    assert set(upcoming_names) == {"예정A", "예정B"}, upcoming_names
    assert set(recent_names) == {"마감A", "마감B"}, recent_names

    # 정렬 확인
    assert ongoing_names[0] == "공모중A"  # 먼저 마감
    assert upcoming_names[0] == "예정A"   # 먼저 시작
    assert recent_names[0] == "마감A"     # 최근 마감
    print("  ✓ classify_sections")


# 4) 실제 페이지 HTML로 뽑은 샘플 (web_fetch로 받은 스냅샷의 축약본)
FULL_SAMPLE = """
<table>
<tr><td>종목명</td><td>공모주일정</td><td>확정공모가</td><td>희망공모가</td><td>청약경쟁률</td><td>주간사</td><td>분석</td></tr>
<tr>
  <td><a href="http://www.38.co.kr/html/fund/?o=v&no=2287&l=&page=1">피스피스스튜디오</a></td>
  <td>2026.05.20~05.21</td><td>-</td><td>19,000~21,500</td><td>&nbsp;</td>
  <td>NH투자증권,미래에셋증권</td>
  <td><a href="http://www.38.co.kr/html/fund/index.htm?o=v&no=2287">분석보기</a></td>
</tr>
<tr>
  <td><a href="http://www.38.co.kr/html/fund/?o=v&no=2275&l=&page=1">인벤테라</a></td>
  <td>2026.03.23~03.24</td><td>16,600</td><td>12,100~16,600</td><td>1913:1</td>
  <td>NH투자증권,유진투자증권</td>
  <td><a href="http://www.38.co.kr/html/fund/index.htm?o=v&no=2275">분석보기</a></td>
</tr>
</table>
"""

def test_list_html():
    items = _parse_list_html(FULL_SAMPLE)
    assert len(items) == 2
    assert items[0].name == "피스피스스튜디오"
    assert items[0].competition == ""  # &nbsp; → 빈 문자열
    assert items[1].name == "인벤테라"
    assert items[1].competition == "1913:1"
    assert items[1].fixed_price == "16,600"
    print("  ✓ _parse_list_html")


if __name__ == "__main__":
    print("파서 단위 테스트:")
    test_schedule_parsing()
    test_row_parsing()
    test_classify()
    test_list_html()
    print("\n전체 통과 ✓")
