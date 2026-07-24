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

# 🎨 요청하신 근로자별 색상 계열 설정
COLOR_MAP = {
    "박은경": "#3563E9", # 파랑 계열
    "채미혜": "#2E7D32", # 초록 계열
    "박인미": "#38BDF8", # 하늘색 계열
    "조윤희": "#FF7A00", # 주황색 계열
    "성지영": "#8B5CF6"  # 보라색 계열
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
# 구글 시트 전체 데이터 로드
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

summary_list = []
for worker in WORKERS:
    worker_rows = [r for r in raw_data if r.get("근로자명") == worker]
    
    worker_summary = {"근로자명": worker}
    for cat in CATEGORIES:
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

# 범례 HTML/CSS 구성 (색상 박스 형태)
legend_html = """
<div style="display: flex; gap: 15px; flex-wrap: wrap; align-items: center; font-size: 15px;">
    <strong>💡 근로자별 범례:</strong>
    <span style="display: inline-flex; align-items: center;"><span style="width: 12px; height: 12px; background-color: #3563E9; display: inline-block; border-radius: 50%; margin-right: 5px;"></span>박은경 (파랑)</span>
    <span style="display: inline-flex; align-items: center;"><span style="width: 12px; height: 12px; background-color: #2E7D32; display: inline-block; border-radius: 50%; margin-right: 5px;"></span>채미혜 (초록)</span>
    <span style="display: inline-flex; align-items: center;"><span style="width: 12px; height: 12px; background-color: #38BDF8; display: inline-block; border-radius: 50%; margin-right: 5px;"></span>박인미 (하늘)</span>
    <span style="display: inline-flex; align-items: center;"><span style="width: 12px; height: 12px; background-color: #FF7A00; display: inline-block; border-radius: 50%; margin-right: 5px;"></span>조윤희 (주황)</span>
    <span style="display: inline-flex; align-items: center;"><span style="width: 12px; height: 12px; background-color: #8B5CF6; display: inline-block; border-radius: 50%; margin-right: 5px;"></span>성지영 (보라)</span>
</div>
"""
st.markdown(legend_html, unsafe_allow_html=True)
