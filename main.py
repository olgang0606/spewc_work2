import streamlit as st
import pandas as pd
import requests
import re
from datetime import datetime
from streamlit_calendar import calendar

st.set_page_config(
    page_title="통합 근태 관리 시스템",
    page_icon="📅",
    layout="wide"
)

WORKERS = ["박은경", "채미혜", "박인미", "조윤희", "성지영"]
CATEGORIES = ["연차", "대체휴무", "병가", "공가"]

# 근로자별 달력 배색 지정
COLOR_MAP = {
    "박은경": "#FF6B6B", # 빨강 계열
    "채미혜": "#4ECDC4", # 민트 계열
    "박인미": "#45B7D1", # 파랑 계열
    "조윤희": "#FFA07A", # 주황 계열
    "성지영": "#98D8C8"  # 연녹색 계열
}

# ---------------------------------------------------------
# 시간 계산 및 정제 헬퍼 함수
# ---------------------------------------------------------
def clean_str(val):
    if pd.isna(val) or val is None:
        return ""
    return str(val).strip().replace("'", "").replace('"', '')

def hhmm_to_minutes(s):
    try:
        val_str = clean_str(s)
        if not val_str or ":" not in val_str:
            return 0
        match = re.search(r'(\d{1,2}):(\d{1,2})', val_str)
        if match:
            return int(match.group(1)) * 60 + int(match.group(2))
        return 0
    except:
        return 0

def minutes_to_hhmm(mins):
    mins = max(0, int(mins))
    return f"{mins // 60:02d}:{mins % 60:02d}"

# ---------------------------------------------------------
# 구글 시트 전체 데이터 데이터 로드
# ---------------------------------------------------------
@st.cache_data(ttl=1)
def load_all_worker_data():
    try:
        sheet_url = st.secrets["SHEET_URL"]
        res = requests.get(sheet_url, params={"action": "getAll"})
        data = res.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        st.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")
        return []

# ---------------------------------------------------------
# UI 구성
# ---------------------------------------------------------
st.title("🏢 통합 근태 및 휴가 관리 시스템")
st.markdown("---")

raw_data = load_all_worker_data()

# 1. 근로자 5명 구분별 사용시간 합계 요약표
st.subheader("📊 근로자별 근무/휴가 유형 합계 요약")

# 요약 데이터 프레임 생성
summary_list = []
for worker in WORKERS:
    worker_rows = [r for r in raw_data if r.get("근로자명") == worker]
    
    worker_summary = {"근로자명": worker}
    for cat in CATEGORIES:
        # 해당 구분의 총 시간(분) 합산
        total_mins = sum(
            hhmm_to_minutes(r.get("총시간", "")) 
            for r in worker_rows 
            if clean_str(r.get("구분", "")) == cat
        )
        worker_summary[f"총 {cat} 시간"] = minutes_to_hhmm(total_mins)
        
    summary_list.append(worker_summary)

df_summary = pd.DataFrame(summary_list)
st.dataframe(df_summary, use_container_width=True, hide_index=True)

st.markdown("---")

# 2. 월간 일정표 (Calendar)
st.subheader("📅 전체 근로자 월간 근태 달력")

events = []
for item in raw_data:
    worker = item.get("근로자명", "")
    date_str = item.get("날짜", "")
    category = item.get("구분", "근무")
    start_t = item.get("시작시간", "")
    end_t = item.get("종료시간", "")
    destination = item.get("목적지", "")
    reason = item.get("사유", "")

    if date_str:
        # 달력 카드 타이틀 구성
        title = f"[{worker}] {category}"
        if start_t and end_t:
            title += f" ({start_t}~{end_t})"
        if destination:
            title += f" @{destination}"

        events.append({
            "title": title,
            "start": date_str,
            "end": date_str,
            "backgroundColor": COLOR_MAP.get(worker, "#3174AD"),
            "borderColor": COLOR_MAP.get(worker, "#3174AD"),
            "allDay": True,
            "extendedProps": {
                "근로자명": worker,
                "구분": category,
                "사유": reason
            }
        })

# 달력 컴포넌트 옵션 설정
calendar_options = {
    "headerToolbar": {
        "left": "prev,next today",
        "center": "title",
        "right": "dayGridMonth,timeGridWeek"
    },
    "initialView": "dayGridMonth",
    "locale": "ko",
    "selectable": True,
    "navLinks": True,
}

if events:
    calendar(events=events, options=calendar_options, key="main_attendance_calendar")
else:
    st.info("등록된 일정 데이터가 없거나 시트 연결을 확인해야 합니다.")

st.markdown("---")
st.markdown("💡 **근로자별 범례:** " + " | ".join([f"{color_code} {name}" for name, color_code in [
    ("🔴 박은경", "#45B7D1"),
    ("🟢 채미혜", "#98D8C8"),
    ("🔵 박인미", "#4ECDC4"),
    ("🟠 조윤희", "#FFA07A"),
    ("🟢 성지영", "#FF6B6B")
]]))
