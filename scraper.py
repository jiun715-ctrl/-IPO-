"""
38커뮤니케이션 공모주 청약일정 크롤러.

페이지: https://www.38.co.kr/html/fund/index.htm?o=k
- EUC-KR 인코딩
- 정적 HTML (requests + BeautifulSoup로 충분)
- 페이지네이션: &page=N
"""

from __future__ import annotations

import re
import ssl
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

BASE_URL = "https://www.38.co.kr"
LIST_URL = f"{BASE_URL}/html/fund/index.htm"

# 페이지당 약 30건 × 10페이지 = 최근 3년치 커버
MAX_PAGES = 10
REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


class _LegacySSLAdapter(HTTPAdapter):
    """
    38.co.kr 같은 구 SSL 서버 대응.

    OpenSSL 3.x(Ubuntu 24.04)의 기본 SECLEVEL=2는 legacy renegotiation을 거부해
    SSLV3_ALERT_HANDSHAKE_FAILURE가 발생한다. SECLEVEL=0으로 낮추고
    legacy 서버 호환 플래그를 켜서 연결 허용.
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _build_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", _LegacySSLAdapter())
    s.headers.update(HEADERS)
    return s


# 모듈 전역 세션 (legacy SSL 어댑터 부착)
_SESSION = _build_session()


@dataclass
class IpoItem:
    """한 건의 공모주 청약 일정."""

    name: str                      # 종목명
    schedule: str                  # 공모주일정 (원문, 예: "2026.05.20~05.21")
    start_date: Optional[str]      # "YYYY-MM-DD" 또는 None (파싱 실패 시)
    end_date: Optional[str]        # "YYYY-MM-DD"
    fixed_price: str               # 확정공모가 ("-" 포함 원문 그대로)
    desired_price: str             # 희망공모가
    competition: str               # 청약경쟁률
    underwriter: str               # 주간사
    detail_url: str                # 종목명 하이퍼링크
    analysis_url: str              # 분석 하이퍼링크

    def to_dict(self) -> dict:
        return asdict(self)


def _fetch_page(page: int) -> str:
    """한 페이지 HTML을 EUC-KR로 디코딩해 반환."""
    params = {"o": "k", "page": page}
    # verify=False 는 _LegacySSLAdapter에서 이미 켜져있지만 urllib3 경고 억제용
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    resp = _SESSION.get(LIST_URL, params=params, timeout=REQUEST_TIMEOUT, verify=False)
    resp.raise_for_status()
    # 사이트 인코딩은 EUC-KR. apparent_encoding은 가끔 틀리므로 고정.
    resp.encoding = "euc-kr"
    return resp.text


def _parse_schedule(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    '2026.05.20~05.21' → ('2026-05-20', '2026-05-21')
    '2025.12.29~2026.01.02' 같은 연도 넘김도 처리.
    파싱 실패 시 (None, None).
    """
    text = text.strip()
    # 시작: YYYY.MM.DD, 끝: MM.DD 또는 YYYY.MM.DD
    m = re.match(
        r"(\d{4})\.(\d{2})\.(\d{2})\s*~\s*(?:(\d{4})\.)?(\d{2})\.(\d{2})",
        text,
    )
    if not m:
        return None, None
    sy, sm, sd, ey, em, ed = m.groups()
    start = f"{sy}-{sm}-{sd}"
    end_year = ey if ey else sy
    # 연도 넘김 보정: 끝월이 시작월보다 작으면 다음해로
    if not ey and int(em) < int(sm):
        end_year = str(int(sy) + 1)
    end = f"{end_year}-{em}-{ed}"
    return start, end


def _parse_row(tr) -> Optional[IpoItem]:
    """테이블 tr 하나를 IpoItem으로 파싱. 헤더/빈 행이면 None."""
    tds = tr.find_all("td")
    if len(tds) < 7:
        return None

    # 첫 칸: 종목명 + 상세 링크
    name_a = tds[0].find("a")
    if not name_a:
        return None
    name = name_a.get_text(strip=True)
    if not name:
        return None
    detail_href = name_a.get("href", "")
    detail_url = urljoin(BASE_URL, detail_href)

    schedule = tds[1].get_text(strip=True)
    start_date, end_date = _parse_schedule(schedule)

    fixed_price = tds[2].get_text(strip=True)
    desired_price = tds[3].get_text(strip=True)
    competition = tds[4].get_text(strip=True)
    underwriter = tds[5].get_text(strip=True)

    # 분석 링크
    analysis_a = tds[6].find("a")
    analysis_href = analysis_a.get("href", "") if analysis_a else ""
    analysis_url = urljoin(BASE_URL, analysis_href) if analysis_href else ""

    return IpoItem(
        name=name,
        schedule=schedule,
        start_date=start_date,
        end_date=end_date,
        fixed_price=fixed_price,
        desired_price=desired_price,
        competition=competition,
        underwriter=underwriter,
        detail_url=detail_url,
        analysis_url=analysis_url,
    )


def _parse_list_html(html: str) -> list[IpoItem]:
    """리스트 페이지 HTML에서 IpoItem 목록 추출."""
    soup = BeautifulSoup(html, "html.parser")
    items: list[IpoItem] = []

    # 공모주 리스트 테이블은 "종목명/공모주일정/확정공모가/..." 헤더를 가짐.
    # 단순하게 종목 상세링크(/html/fund/?o=v&no=...)를 포함한 tr만 선별.
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=re.compile(r"/html/fund/\?o=v&no=\d+"))
        if not a:
            continue
        item = _parse_row(tr)
        if item:
            items.append(item)
    return items


def fetch_all(max_pages: int = MAX_PAGES) -> list[IpoItem]:
    """1~max_pages 페이지 전부 크롤링해 한 리스트로 합침."""
    all_items: list[IpoItem] = []
    seen_urls: set[str] = set()  # 중복 방지 (detail_url 기준)
    for page in range(1, max_pages + 1):
        html = _fetch_page(page)
        items = _parse_list_html(html)
        if not items:
            # 더 이상 데이터 없으면 중단
            break
        new_count = 0
        for it in items:
            if it.detail_url in seen_urls:
                continue
            seen_urls.add(it.detail_url)
            all_items.append(it)
            new_count += 1
        # 새로 추가된 행이 하나도 없으면 페이지네이션 끝으로 간주
        if new_count == 0:
            break
    return all_items


# ------------------------------ 섹션 분류 ------------------------------ #

def classify_sections(
    items: list[IpoItem],
    today: Optional[date] = None,
) -> dict[str, list[IpoItem]]:
    """
    3개 섹션으로 분류:
      - ongoing     : start_date <= today <= end_date
      - upcoming    : today < start_date <= today + 7d
      - recent_end  : today - 7d <= end_date < today
    """
    if today is None:
        today = date.today()

    ongoing: list[IpoItem] = []
    upcoming: list[IpoItem] = []
    recent_end: list[IpoItem] = []

    for it in items:
        if not it.start_date or not it.end_date:
            continue
        start = datetime.strptime(it.start_date, "%Y-%m-%d").date()
        end = datetime.strptime(it.end_date, "%Y-%m-%d").date()

        if start <= today <= end:
            ongoing.append(it)
        elif today < start <= today.fromordinal(today.toordinal() + 7):
            upcoming.append(it)
        elif today.fromordinal(today.toordinal() - 7) <= end < today:
            recent_end.append(it)

    # 공모중: 마감 임박순 (end asc)
    ongoing.sort(key=lambda x: x.end_date or "")
    # 예정: 시작 빠른순 (start asc)
    upcoming.sort(key=lambda x: x.start_date or "")
    # 최근 마감: 최근 마감순 (end desc)
    recent_end.sort(key=lambda x: x.end_date or "", reverse=True)

    return {
        "ongoing": ongoing,
        "upcoming": upcoming,
        "recent_end": recent_end,
    }


if __name__ == "__main__":
    # 로컬 점검용
    items = fetch_all()
    print(f"총 {len(items)}건 크롤링")
    sections = classify_sections(items)
    for key, lst in sections.items():
        print(f"[{key}] {len(lst)}건")
        for it in lst[:5]:
            print(f"  - {it.name} | {it.schedule} | {it.underwriter}")
