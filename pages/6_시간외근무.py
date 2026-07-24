@st.cache_data(ttl=3)
def load_overtime_data():
    target_cols = [
        "이름", "날짜", "시작시간", "종료시간", "근무시간", "근무내용",
        "시간외수당수당적용시간", "통상임금적용시간", "대체휴무시간", "지급수당"
    ]
    try:
        gc = get_gspread_client()
        sh = gc.open_by_url(st.secrets["SPREADSHEET_URL"])
        worksheet = sh.worksheet("시간외근무")
        records = worksheet.get_all_records()
        
        # 레코드가 없거나 빈 시트인 경우
        if not records:
            return pd.DataFrame(columns=target_cols), worksheet
            
        df = pd.DataFrame(records)
        
        # 필수 컬럼이 누락되어 있다면 빈 문자열로 채워줌
        for col in target_cols:
            if col not in df.columns:
                df[col] = ""
                
        # 컬럼 순서 맞춤
        df = df[target_cols]
        
        # '이름'이나 '날짜'가 모두 비어있는 유령 행 제거
        df = df[df["이름"].astype(str).str.strip() != ""]
        
        return df, worksheet
    except Exception as e:
        # 에러 발생 시 UI에 원인 표시
        st.error(f"구글 시트 '시간외근무' 데이터 읽기 실패: {e}")
        return pd.DataFrame(columns=target_cols), None
