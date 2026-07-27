import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime, timedelta
import re
from streamlit_calendar import calendar

st.set_page_config(page_title="근태 및 시간외근무 관리 시스템", page_icon="🏢", layout="wide")

WORKERS = [
    {"name": "박은경", "hire_date": date(2016, 3, 1), "color": "#3182CE"},
    {"name": "채미혜", "hire_date": date(2018, 3, 1), "color": "#38A169"},
    {"name": "박인미", "hire_date": date(2023, 8, 1), "color": "#00B5D8"},
    {"name": "조윤희", "hire_date": date(2023, 8, 1), "color": "#DD6B20"},
    {"name": "성지영", "hire_date": date(2026, 7, 1), "color": "#805AD5"},
]
WORKER_NAMES = [w["name"] for w in WORKERS]
WORKER_COLOR_MAP = {w["name"]: w["color"] for w in WORKERS}

# ---------------------------------------------------------
# Google Sheets API 연동
# ---------------------------------------------------------
@st.cache_resource
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes
    )
    return gspread.authorize(credentials)

def get_spreadsheet():
    gc = get_gspread_client()
    return gc.open_by_url(st.secrets["SPREADSHEET_URL"])

@st.cache_data(ttl=1)
def load_sheet_raw_data(sheet_name):
    try:
        sh = get_spreadsheet()
        worksheet = sh.worksheet(sheet_name)
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame()
        return pd.DataFrame(records)
    except Exception as e:
        return pd.DataFrame()

# ---------------------------------------------------------
# 시간 계산 및 변환 유틸리티
# ---------------------------------------------------------
def extract_time_str(val):
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip().replace("'", "").replace('"', '')
    match = re.search(r'(\d{1,2}:\d{2})', s)
    return match.group(1) if match else ""

def parse_time_to_minutes(val):
    if pd.isna(val) or val is None:
        return 0
    s = str(val).strip().replace("'", "").replace('"', '')
    if not s or s == "-":
        return 0
    if ":" in s:
        try:
            parts = s.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            return 0
    try:
        val_float = float(s)
        return int(val_float * 60) if val_float < 24 else int(val_float)
    except Exception:
        return 0

def calculate_net_minutes(start_str, end_str):
    s_hhmm = extract_time_str(start_str)
    e_hhmm = extract_time_str(end_str)
    if not s_hhmm or not e_hhmm:
        return 0
    try:
        s_dt = datetime.strptime(s_hhmm, "%H:%M")
        e_dt = datetime.strptime(e_hhmm, "%H:%M")
        if e_dt <= s_dt:
            return 0
        total_mins = int((e_dt - s_dt).total_seconds() // 60)
        
        # 휴게시간 (12:00~13:00) 차감
        lunch_start = datetime.strptime("12:00", "%H:%M")
        lunch_end = datetime.strptime("13:00", "%H:%M")
        if s_dt <= lunch_start and e_dt >= lunch_end:
            total_mins -= 60
        return max(0, total_mins)
    except Exception:
        return 0

def minutes_to_hhmm(mins):
    mins = max(0, int(mins))
    return f"{mins // 60:02d}:{mins % 60:02d}"

def get_current_period(hire_d, ref_date=None):
    if ref_date is None:
        ref_date = date.today()
    try:
        this_year_hire = date(ref_date.year, hire_d.month, hire_d.day)
    except ValueError:
        this_year_hire = date(ref_date.year, hire_d.month, 28)
        
    if ref_date >= this_year_hire:
        start_date = this_year_hire
        try:
            end_date = date(ref_date.year + 1, hire_d.month, hire_d.day) - timedelta(days=1)
        except ValueError:
            end_date = date(ref_date.year + 1, hire_d.month, 28) - timedelta(days=1)
    else:
        try:
            start_date = date(ref_date.year - 1, hire_d.month, hire_d.day)
        except ValueError:
            start_date = date(ref_date.year - 1, hire_d.month, 28)
        end_date = this_year_hire - timedelta(days=1)
        
    return start_date, end_date

# ---------------------------------------------------------
# 사이드바: 근로자별 수당 단가 설정
# ---------------------------------------------------------
st.sidebar.title("⚙️ 근로자별 수당 단가 설정")

wage_rates = {}

with st.sidebar.expander("🔻 근로자별 통상/시간외 단가 입력", expanded=True):
    for w in WORKERS:
        name = w["name"]
        st.markdown(f"**[{name}]**")
        col_ot, col_ord = st.columns(2)
        
        with col_ot:
            ot_rate = st.number_input(
                f"{name} 시간외단가", 
                value=20000, 
                step=1000, 
                key=f"ot_rate_{name}"
            )
        with col_ord:
            ord_rate = st.number_input(
                f"{name} 통상단가", 
                value=15000, 
                step=1000, 
                key=f"ord_rate_{name}"
            )
            
        wage_rates[name] = {
            "ot_rate": ot_rate,
            "ord_rate": ord_rate
        }

# ---------------------------------------------------------
# 메인 UI & 연산 로직
# ---------------------------------------------------------
st.title("🏢 근태 및 시간외근무 종합 대시보드")

col_top1, col_top2 = st.columns([1, 4])
with col_top1:
    if st.button("🔄 전체 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()

calendar_events = []
worker_weekly_mins = {name: {} for name in WORKER_NAMES}
worker_dfs = {}
categories = ["연차", "대체휴무", "병가", "공가"]

# 1. 개별 근로자 탭 처리 (총시간 계산 및 달력 이벤트 등록)
for w in WORKERS:
    name = w["name"]
    df = load_sheet_raw_data(name)
    worker_dfs[name] = df
    
    if not df.empty and "날짜" in df.columns:
        clean_dates = df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.replace("/", "-").str.strip()
        df['date_dt'] = pd.to_datetime(clean_dates, errors='coerce')
        
        # 박은경~성지영 탭 총시간 = 종료시간 - 시작시간
        df['calc_total_mins'] = df.apply(lambda r: calculate_net_minutes(r.get("시작시간", ""), r.get("종료시간", "")), axis=1)
        df['calc_total_str'] = df['calc_total_mins'].apply(minutes_to_hhmm)
        
        # 월~일 주 단위 기준 주차 키 연산
        for _, r in df.dropna(subset=['date_dt']).iterrows():
            d = r['date_dt'].date()
            monday = d - timedelta(days=d.weekday())
            week_key = monday.strftime("%Y-%m-%d")
            worker_weekly_mins[name][week_key] = worker_weekly_mins[name].get(week_key, 0) + r['calc_total_mins']
            
            # 달력 이벤트 (휴가)
            d_str = r['date_dt'].strftime("%Y-%m-%d")
            s_time = extract_time_str(r.get('시작시간', ''))
            e_time = extract_time_str(r.get('종료시간', ''))
            cat = str(r.get('구분', '')).strip()
            if ":" in s_time and ":" in e_time:
                calendar_events.append({
                    "title": f"[{name}] {cat} ({s_time}~{e_time})",
                    "start": f"{d_str}T{s_time:0>5}:00",
                    "end": f"{d_str}T{e_time:0>5}:00",
                    "color": w["color"],
                    "textColor": "#FFFFFF"
                })

# 2. 시간외근무 탭 연산 및 달력 이벤트 등록
ot_df = load_sheet_raw_data("시간외근무")
monthly_payouts = {}
worker_summary_map = {name: {"ot_pay_mins": 0, "ord_mins": 0} for name in WORKER_NAMES}

if not ot_df.empty and "날짜" in ot_df.columns:
    clean_ot_dates = ot_df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.replace("/", "-").str.strip()
    ot_df['date_dt'] = pd.to_datetime(clean_ot_dates, errors='coerce')
    
    ot_df['total_mins'] = ot_df.apply(lambda r: calculate_net_minutes(r.get("시작시간", ""), r.get("종료시간", "")), axis=1)
    
    monthly_acc = {}
    
    for idx, r in ot_df.iterrows():
        name = str(r.get("이름", "")).strip()
        d_dt = r.get('date_dt')
        
        if pd.isna(d_dt) or name not in WORKER_NAMES:
            continue
            
        d_str = d_dt.strftime("%Y-%m-%d")
        s_time = extract_time_str(r.get('시작시간', ''))
        e_time = extract_time_str(r.get('종료시간', ''))
        w_color = WORKER_COLOR_MAP.get(name, "#4A5568")
        
        # 달력 이벤트 (시간외근무)
        if ":" in s_time and ":" in e_time:
            calendar_events.append({
                "title": f"[{name}] 시간외 ({s_time}~{e_time})",
                "start": f"{d_str}T{s_time:0>5}:00",
                "end": f"{d_str}T{e_time:0>5}:00",
                "color": w_color,
                "textColor": "#FFFFFF"
            })
            
        d_val = d_dt.date()
        month_str = d_val.strftime("%Y-%m")
        monday = d_val - timedelta(days=d_val.weekday())
        week_key = monday.strftime("%Y-%m-%d")
        
        # 통상임금적용시간 = 주 단위(월~일) 합계
        ord_mins = worker_weekly_mins[name].get(week_key, 0)
        tot_mins = r['total_mins']
        
        # 시간외수당적용시간 = 종료시간 - 시작시간 - 통상임금적용시간
        ot_pay_mins = max(0, tot_mins - ord_mins)
        
        # 대체휴무시간
        alt_vac_mins = parse_time_to_minutes(r.get("대체휴무시간", 0))
        
        # 요약표용 대시보드 누적
        worker_summary_map[name]["ot_pay_mins"] += ot_pay_mins
        worker_summary_map[name]["ord_mins"] += ord_mins
        
        # 월별 수당 집계용
        key = (name, month_str)
        if key not in monthly_acc:
            monthly_acc[key] = {'ot_mins': 0, 'ord_mins': 0, 'alt_vac_equals_ord': True}
            
        monthly_acc[key]['ot_mins'] += ot_pay_mins
        monthly_acc[key]['ord_mins'] += ord_mins
        if alt_vac_mins != ord_mins:
            monthly_acc[key]['alt_vac_equals_ord'] = False

    # 월 단위 1시간 미만 절사(버림) 및 지급수당 조건 계산
    for (name, month_str), acc in monthly_acc.items():
        rates = wage_rates.get(name, {"ot_rate": 20000, "ord_rate": 15000})
        
        ot_hours = acc['ot_mins'] // 60
        ord_hours = acc['ord_mins'] // 60
        
        # 대체휴무시간 == 통상임금적용시간 일 때 계산 조건
        if acc['alt_vac_equals_ord']:
            payout = ot_hours * rates['ot_rate']
        else:
            payout = (ot_hours * rates['ot_rate']) + (ord_hours * rates['ord_rate'])
            
        if month_str not in monthly_payouts:
            monthly_payouts[month_str] = {}
        monthly_payouts[month_str][name] = payout

# 구글 시트 업데이트 버튼
with col_top1:
    if st.button("💾 계산 결과 구글 시트에 업데이트"):
        try:
            sh = get_spreadsheet()
            for name in WORKER_NAMES:
                ws = sh.worksheet(name)
                df_w = worker_dfs[name]
                if not df_w.empty and 'calc_total_str' in df_w.columns:
                    col_idx = df_w.columns.get_loc("총시간") + 1 if "총시간" in df_w.columns else len(df_w.columns) + 1
                    cell_list = ws.range(2, col_idx, len(df_w) + 1, col_idx)
                    for i, val in enumerate(df_w['calc_total_str']):
                        cell_list[i].value = val
                    ws.update_cells(cell_list)
            st.success("구글 시트에 연산 결과가 업데이트 되었습니다!")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"시트 업데이트 오류: {e}")

st.markdown("---")

# ---------------------------------------------------------
# 1. 근로자별 산정주기 누적 현황 표
# ---------------------------------------------------------
st.subheader("📊 근로자별 산정주기 누적 사용 현황 (휴가, 통상임금 및 시간외 수당)")

summary_list = []
curr_month = date.today().strftime("%Y-%m")

for w in WORKERS:
    name = w["name"]
    rates = wage_rates[name]
    p_start, p_end = get_current_period(w["hire_date"])
    
    ot_m = worker_summary_map[name]["ot_pay_mins"]
    ord_m = worker_summary_map[name]["ord_mins"]
    payout = monthly_payouts.get(curr_month, {}).get(name, 0)
    
    summary_list.append({
        "근로자명": name,
        "입사일": w["hire_date"].strftime("%Y-%m-%d"),
        "현재 산정주기": f"{p_start.strftime('%Y-%m-%d')} ~ {p_end.strftime('%Y-%m-%d')}",
        "시간외수당 적용시간": minutes_to_hhmm(ot_m),
        "통상임금 적용시간": minutes_to_hhmm(ord_m),
        "당월 시간외 지급수당 (1시간미만 절사)": f"{payout:,}원"
    })

st.dataframe(pd.DataFrame(summary_list), use_container_width=True, hide_index=True)

# ---------------------------------------------------------
# 2. 8번 지출내역 탭/표 (월별 근로자 수당 합계)
# ---------------------------------------------------------
st.markdown("---")
st.subheader("💳 월별 근로자 지출내역 (시간외근무 수당 합계)")

expense_rows = []
all_months = sorted(monthly_payouts.keys(), reverse=True)

for m in all_months:
    row = {"월": m}
    tot = 0
    for w_name in WORKER_NAMES:
        amt = monthly_payouts[m].get(w_name, 0)
        row[w_name] = f"{amt:,}원"
        tot += amt
    row["총 지출합계"] = f"{tot:,}원"
    expense_rows.append(row)

if expense_rows:
    st.dataframe(pd.DataFrame(expense_rows), use_container_width=True, hide_index=True)
else:
    st.info("지출내역 데이터가 없거나 수당이 집계되지 않았습니다.")

# ---------------------------------------------------------
# 3. 월간 통합 일정표 (달력 복원 🗓️)
# ---------------------------------------------------------
st.markdown("---")
st.subheader("📅 월간 통합 일정표 (휴가 및 시간외근무 총괄표)")

st.markdown("""
<div style="display: flex; gap: 15px; margin-bottom: 15px; font-weight: bold;">
    <span style="color: #3182CE;">■ 박은경</span>
    <span style="color: #38A169;">■ 채미혜</span>
    <span style="color: #00B5D8;">■ 박인미</span>
    <span style="color: #DD6B20;">■ 조윤희</span>
    <span style="color: #805AD5;">■ 성지영</span>
</div>
""", unsafe_allow_html=True)

calendar_options = {
    "editable": False,
    "selectable": True,
    "headerToolbar": {
        "left": "prev,next today",
        "center": "title",
        "right": "dayGridMonth,timeGridWeek"
    },
    "initialView": "dayGridMonth",
    "locale": "ko",
    "eventTimeFormat": {"hour": "2-digit", "minute": "2-digit", "hour12": False},
    "slotLabelFormat": {"hour": "2-digit", "minute": "2-digit", "hour12": False}
}

calendar(events=calendar_events, options=calendar_options, key="total_attendance_calendar")
