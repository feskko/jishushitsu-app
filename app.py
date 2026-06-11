import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import base64
import unicodedata
import streamlit.components.v1 as components

# 日本時間の「今」を取得
jst_now = datetime.utcnow() + timedelta(hours=9)

# 講習期間の判定
def is_special_period(dt_date):
    if dt_date is None: return False
    m = dt_date.month
    d = dt_date.day
    # 春季講習: 3/15 〜 4/7
    if (m == 3 and d >= 15) or (m == 4 and d <= 7): return True
    # 夏期講習: 7/15 〜 8/31
    if (m == 7 and d >= 15) or m == 8: return True
    # 冬季講習: 12/1 〜 1/7
    if m == 12 or (m == 1 and d <= 7): return True
    return False

# 年間のテスト期間の定義 (開始月, 開始日, 終了月, 終了日)
TEST_PERIODS = [
    (5, 11, 5, 20),   # 5月中旬
    (6, 21, 6, 30),   # 6月下旬
    (7, 1, 7, 10),    # 7月上旬
    (9, 1, 9, 10),    # 9月上旬
    (10, 11, 10, 20), # 10月中旬
    (11, 1, 11, 10),  # 11月上旬
    (12, 1, 12, 10),  # 12月上旬
    (2, 20, 2, 29)    # 2月下旬
]

# 日付が「通常」「テスト1週間前」「テスト期間」のどれかを判定する
def get_period_status(dt_date):
    if dt_date is None: return "normal"
    y = dt_date.year
    curr_date = dt_date.date() if isinstance(dt_date, datetime) else dt_date
    
    for tm1, td1, tm2, td2 in TEST_PERIODS:
        try:
            start_date = datetime(y, tm1, td1).date()
            if tm2 == 2 and td2 == 29:
                is_leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
                end_date = datetime(y, 2, 29 if is_leap else 28).date()
            else:
                end_date = datetime(y, tm2, td2).date()
        except: continue
        
        before_start = start_date - timedelta(days=7)
        before_end = start_date - timedelta(days=1)
        
        if start_date <= curr_date <= end_date:
            return "test"
        elif before_start <= curr_date <= before_end:
            return "before_test"
            
    return "normal"

# 過去のデータから、テスト前・テスト中の「混雑倍率」を学習する関数
def learn_multipliers(df):
    default_test = 1.5   # 初期値: テスト中は1.5倍
    default_before = 1.2 # 初期値: テスト1週間前は1.2倍
    if df.empty: return default_test, default_before
    
    try:
        temp_df = df.copy()
        temp_df['date_only'] = temp_df['日付'].dt.date
        daily_users = temp_df.groupby('date_only')['名前'].nunique().reset_index()
        daily_users['status'] = daily_users['date_only'].apply(get_period_status)
        
        counts = daily_users.groupby('status')['名前'].agg(['mean', 'count'])
        
        # 通常期の平均来室人数
        normal_mean = counts.loc['normal', 'mean'] if 'normal' in counts.index and counts.loc['normal', 'count'] >= 5 else None
        
        test_mult = default_test
        if 'test' in counts.index and counts.loc['test', 'count'] >= 3 and normal_mean and normal_mean > 0:
            actual_mult = counts.loc['test', 'mean'] / normal_mean
            actual_mult = max(1.0, min(actual_mult, 3.0)) # 異常値除外
            weight = min(counts.loc['test', 'count'] / 10.0, 1.0) # データが蓄積するほど実績を重視
            test_mult = default_test * (1 - weight) + actual_mult * weight

        before_mult = default_before
        if 'before_test' in counts.index and counts.loc['before_test', 'count'] >= 3 and normal_mean and normal_mean > 0:
            actual_mult = counts.loc['before_test', 'mean'] / normal_mean
            actual_mult = max(1.0, min(actual_mult, 2.5))
            weight = min(counts.loc['before_test', 'count'] / 10.0, 1.0)
            before_mult = default_before * (1 - weight) + actual_mult * weight

        return test_mult, before_mult
    except:
        return default_test, default_before

# 分析用のタイムスロット取得
def get_time_slots_for_period(period_str):
    if period_str == "累計":
        return [f"{h:02d}:00" for h in range(9, 23)]
    try:
        m = int(period_str.split("年")[1].replace("月", ""))
        if m in [1, 3, 4, 7, 8, 12]:
            return [f"{h:02d}:00" for h in range(9, 23)]
        else:
            return [f"{h:02d}:00" for h in range(12, 23)]
    except:
        return [f"{h:02d}:00" for h in range(9, 23)]

# 時刻の柔軟なパース (全角対応、1223 -> 12:23)
def parse_custom_time(t_str):
    if not t_str: return None
    t_str = unicodedata.normalize('NFKC', str(t_str)).strip()
    if t_str == "" or "コマ" in t_str: return None
    
    if ":" in t_str:
        try: return datetime.strptime(t_str[:5], "%H:%M").time()
        except: return None
    elif t_str.isdigit() and (len(t_str) == 3 or len(t_str) == 4):
        try:
            h = int(t_str[:-2])
            m = int(t_str[-2:])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return datetime.strptime(f"{h:02d}:{m:02d}", "%H:%M").time()
        except: return None
    return None

# 時間計算用の関数
def calc_duration(in_time, out_time):
    def to_dt(t):
        if isinstance(t, str):
            parsed = parse_custom_time(t)
            return datetime.combine(datetime.today(), parsed) if parsed else None
        elif t is not None:
            return datetime.combine(datetime.today(), t)
        return None

    dt_in = to_dt(in_time)
    dt_out = to_dt(out_time)
    
    if dt_in and dt_out:
        if dt_out >= dt_in:
            return (dt_out - dt_in).total_seconds() / 3600.0
        else:
            return ((dt_out + timedelta(days=1)) - dt_in).total_seconds() / 3600.0
    return 0.0

# --- 1. ページ構成 ---
st.set_page_config(page_title="TKG Study Room Analytics", page_icon="icon.png", layout="wide")

if os.path.exists("icon.png"):
    with open("icon.png", "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    js_code = f"""
    <script>
        const doc = window.parent.document;
        let links = doc.querySelectorAll("link[rel~='apple-touch-icon']");
        links.forEach(link => link.remove());
        let newLink = doc.createElement('link');
        newLink.rel = 'apple-touch-icon';
        newLink.href = 'data:image/png;base64,{img_b64}';
        doc.head.appendChild(newLink);
    </script>
    """
    components.html(js_code, height=0, width=0)

st.markdown("""
<style>
    #MainMenu, header, footer, [data-testid="stToolbar"] {visibility: hidden !important; display: none !important;}
    .stApp { background-color: #F4F7FB; font-family: 'Helvetica Neue', Arial, 'Hiragino Kaku Gothic ProN', 'Hiragino Sans', Meiryo, sans-serif; }
    
    .main-title { font-weight: 900; color: #0A2B56; letter-spacing: 2px; margin-bottom: 25px; padding-bottom: 10px; border-bottom: 3px solid #E2E8F0; position: relative; font-size: 2.4rem; text-transform: uppercase;}
    .main-title::after { content: ''; position: absolute; left: 0; bottom: -3px; width: 100px; height: 3px; background: linear-gradient(90deg, #0A2B56, #005BAB); }
    .section-title { font-weight: 800; color: #0A2B56; margin-top: 2rem; margin-bottom: 1rem; padding-left: 10px; border-left: 5px solid #005BAB; font-size: 1.6rem; }
    
    div[role="radiogroup"] { display: flex; background-color: #FFFFFF; padding: 5px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); margin-bottom: 20px; margin-top: 5px; }
    div[role="radiogroup"] label { flex: 1; text-align: center; justify-content: center; padding: 10px 5px !important; margin: 0 !important; border-radius: 8px; transition: 0.2s; cursor: pointer; }
    div[role="radiogroup"] label[data-checked="true"] { background-color: #0A2B56; }
    div[role="radiogroup"] label[data-checked="true"] p { color: #FFFFFF !important; font-weight: 800; }
    div[role="radiogroup"] label p { color: #64748B; font-weight: 700; font-size: 0.85rem; }

    div[data-testid="stWidgetLabel"] p, 
    div[data-testid="stWidgetLabel"] label, 
    .stTextInput label p, 
    .stSelectbox label p, 
    .stDateInput label p { 
        color: #0A2B56 !important; 
        font-weight: 800 !important; 
        font-size: 1.05rem !important; 
    }

    button[data-baseweb="tab"] p {
        color: #0A2B56 !important;
        font-weight: bold !important;
        font-size: 1.1rem !important;
    }
    
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div { background-color: #FFFFFF !important; border-radius: 8px !important; border: 1px solid #CBD5E1 !important; box-shadow: inset 0 1px 2px rgba(0,0,0,0.02); height: 3.2rem; }
    div[data-baseweb="input"] input, div[data-baseweb="select"] div { color: #1E293B !important; font-weight: 700; font-size: 1.05rem; }
    div[data-baseweb="input"] input::placeholder { color: #94A3B8 !important; font-weight: 500; }
    
    button[kind="secondary"] { background-color: #FFFFFF !important; color: #0A2B56 !important; border: 2px solid #E2E8F0 !important; font-weight: 700 !important; border-radius: 6px !important; transition: 0.2s !important; min-height: 3.5rem !important; padding: 2px !important; }
    button[kind="secondary"]:hover { border-color: #005BAB !important; background-color: #F8FAFC !important; }
    
    button[kind="primary"] { background: linear-gradient(135deg, #0A2B56 0%, #005BAB 100%) !important; color: #FFFFFF !important; border: none !important; font-weight: 800 !important; border-radius: 6px !important; box-shadow: 0 4px 6px -1px rgba(0, 91, 171, 0.3) !important; min-height: 3.5rem !important; padding: 2px !important; transition: all 0.2s ease; }
    button[kind="primary"]:active { transform: translateY(2px); }
    button p { font-size: 1.3rem !important; margin: 0 !important; font-weight: bold; letter-spacing: 1px; }

    div[data-testid="stMetric"] { background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 12px; padding: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
    [data-testid="stMetricValue"] > div, [data-testid="stMetricValue"] { color: #0A2B56 !important; font-weight: 900 !important; font-size: 2.4rem !important; }
    [data-testid="stMetricLabel"] p, [data-testid="stMetricLabel"] { color: #475569 !important; font-size: 1.05rem !important; font-weight: bold !important; }

    @media (min-width: 768px) { 
        div[role="radiogroup"] { max-width: 600px; } 
        .rank-card { flex: 1; min-width: 30%; padding: 25px; border-radius: 16px; border: 1px solid #E2E8F0; } 
    }
    @media (max-width: 767px) { 
        .main-title { font-size: 1.8rem; } .section-title { font-size: 1.3rem; } 
        div[role="radiogroup"] { width: 100%; flex-wrap: wrap; } div[role="radiogroup"] label { min-width: 45%; } 
        .rank-card { width: 100%; padding: 20px; border-radius: 12px; margin-bottom: 15px; border: 1px solid #E2E8F0; } 
    }
</style>
""", unsafe_allow_html=True)

if "sys_msg" not in st.session_state: st.session_state.sys_msg = None
if "sys_err" not in st.session_state: st.session_state.sys_err = None

APP_PASSWORD = "tkg-1985" 

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h3 style='text-align: center; color: #0A2B56; margin-top: 15vh; margin-bottom: 30px; font-weight: 900; font-size: 2.5rem; letter-spacing: 2px;'>Study Room System</h3>", unsafe_allow_html=True)
    with st.form("login_form", clear_on_submit=False):
        st.markdown("<p style='color: #0A2B56; font-weight: bold; margin-bottom: 5px;'> 管理用パスワードを入力してください</p>", unsafe_allow_html=True)
        pwd = st.text_input("パスワード", type="password", placeholder="例: password123", label_visibility="collapsed")
        st.markdown("<br>", unsafe_allow_html=True)
        submitted = st.form_submit_button("システムにログイン", type="primary", use_container_width=True)
        if submitted:
            if pwd == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("パスワードが違います")
    st.stop()

scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
if "GCP_SERVICE_ACCOUNT" in st.secrets:
    secret_data = st.secrets["GCP_SERVICE_ACCOUNT"]
    service_account_info = json.loads(secret_data) if isinstance(secret_data, str) else dict(secret_data)
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
else:
    st.error("システムエラー: Secrets設定がありません")
    st.stop()

gc = gspread.authorize(credentials)
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1C9xD5xD3ZvGEV6IPuD2_dj9f_oqAIz_v923PMRabBu4/edit"

@st.cache_data(ttl=60)
def load_data():
    try:
        workbook = gc.open_by_url(SPREADSHEET_URL)
        df = pd.DataFrame(workbook.worksheet("メイン").get_all_records())
        if not df.empty: 
            df['日付'] = pd.to_datetime(df['日付'])
            df['名前'] = df['名前'].astype(str).str.replace(r'[\s　]+', '', regex=True)
        return df
    except: return pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）'])

def save_to_gs(df, sheet_name="メイン"):
    workbook = gc.open_by_url(SPREADSHEET_URL)
    worksheet = workbook.worksheet(sheet_name)
    worksheet.clear()
    if not df.empty:
        save_df = df.copy()
        save_df['日付'] = pd.to_datetime(save_df['日付']).dt.strftime('%Y-%m-%d')
        save_df = save_df.fillna("")
        worksheet.update(range_name="A1", values=[save_df.columns.tolist()] + save_df.values.tolist())
    else:
        worksheet.update(range_name="A1", values=[['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']])

if "form_key" not in st.session_state: st.session_state.form_key = 0

GRADES = ["--選択--"] + [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]

menu = st.radio("メニュー", ["一括入力", "1件ずつ", "ランキング", "分析", "管理"], horizontal=True, label_visibility="collapsed")

if st.session_state.sys_msg:
    st.success(st.session_state.sys_msg)
    st.session_state.sys_msg = None
if st.session_state.sys_err:
    st.error(st.session_state.sys_err)
    st.session_state.sys_err = None

if menu == "一括入力":
    st.markdown("<div class='main-title'>BATCH ENTRY PANEL</div>", unsafe_allow_html=True)
    
    f_date_batch = st.date_input("利用日 (全員共通)", jst_now.date(), max_value=jst_now.date())
    
    if "batch_data" not in st.session_state:
        st.session_state.batch_data = [{"氏名": "", "学年": "--選択--", "開始時間": "", "終了時間": ""} for _ in range(25)]
        
    df_empty = pd.DataFrame(st.session_state.batch_data)
    
    st.markdown("<p style='color:#64748B; font-weight:bold; margin-bottom:10px;'>💡 同姓同名がいない場合は、学年は「--選択--」のままでも登録可能です。</p>", unsafe_allow_html=True)
    
    edited_df = st.data_editor(
        df_empty,
        column_config={
            "氏名": st.column_config.TextColumn("氏名 (必須)", width="medium"),
            "学年": st.column_config.SelectboxColumn("学年 (同姓同名がいれば選択)", options=GRADES, width="medium"),
            "開始時間": st.column_config.TextColumn("開始時間 (例:1223, 全角OK)", width="small"),
            "終了時間": st.column_config.TextColumn("終了時間 (例:1530, 全角OK)", width="small"),
        },
        num_rows="dynamic",
        use_container_width=True,
        height=500,
        key=f"editor_{st.session_state.form_key}"
    )
    
    if st.button("表のデータをすべて保存する", type="primary", use_container_width=True):
        valid_rows = edited_df[edited_df["氏名"].str.strip() != ""]
        if valid_rows.empty:
            st.error("氏名が入力されている行がありません。")
        else:
            new_records = []
            error_msgs = []
            df_current = load_data()
            
            for idx, row in valid_rows.iterrows():
                name = row["氏名"].replace(" ", "").replace("　", "")
                grade_input = row["学年"]
                grade = grade_input if grade_input != "--選択--" else "" 
                
                in_dt_time = parse_custom_time(row["開始時間"])
                out_dt_time = parse_custom_time(row["終了時間"])
                
                if in_dt_time is None or out_dt_time is None:
                    error_msgs.append(f"{name}さん (開始・終了時間を正しく入力してください)")
                    continue
                    
                if not is_special_period(f_date_batch) and in_dt_time.hour < 12:
                    error_msgs.append(f"{name}さん (通常期間は12時以降を入力してください)")
                    continue
                
                duration = calc_duration(in_dt_time, out_dt_time)
                if duration <= 0:
                    error_msgs.append(f"{name}さん (終了時間が開始時間より前になっています)")
                    continue
                
                in_str = in_dt_time.strftime("%H:%M")
                out_str = out_dt_time.strftime("%H:%M")
                
                is_dup_current = not df_current[
                    (df_current['日付'] == pd.to_datetime(f_date_batch)) & 
                    (df_current['名前'] == name) & 
                    (df_current['入室時間'] == in_str) & 
                    (df_current['退室時間'] == out_str)
                ].empty
                
                is_dup_new = any(r['名前'] == name and r['入室時間'] == in_str and r['退室時間'] == out_str for r in new_records)
                
                if is_dup_current or is_dup_new:
                    error_msgs.append(f"{name}さん (既に同じ記録が登録されています)")
                    continue
                    
                new_records.append({
                    '日付': pd.to_datetime(f_date_batch),
                    '名前': name,
                    '学年': grade,
                    '入室時間': in_str,
                    '退室時間': out_str,
                    '利用時間（時間）': duration
                })
            
            if error_msgs:
                for err in error_msgs:
                    st.error(f"エラー: {err}")
            
            if new_records:
                df = pd.concat([df_current, pd.DataFrame(new_records)], ignore_index=True)
                save_to_gs(df)
                st.session_state.batch_data = [{"氏名": "", "学年": "--選択--", "開始時間": "", "終了時間": ""} for _ in range(25)]
                st.session_state.form_key += 1
                st.session_state.sys_msg = f"{len(new_records)}名分の記録を一括保存しました。（入力欄をリセットしました）"
                st.cache_data.clear()
                st.rerun()

elif menu == "1件ずつ":
    st.markdown("<div class='main-title'>SINGLE ENTRY PANEL</div>", unsafe_allow_html=True)
    
    df_history = load_data()
    user_list = ["-- 新規入力 (直接入力してください) --"]
    recent_users = pd.DataFrame()
    if not df_history.empty:
        recent_users = df_history[['名前', '学年']].drop_duplicates(subset=['名前']).dropna()
        user_list += recent_users['名前'].tolist()

    st.markdown("<p style='color:#3B82F6; font-weight:bold; margin-bottom:5px; font-size: 1.05rem;'> 過去の利用者から選ぶと自動入力されます</p>", unsafe_allow_html=True)
    selected_user = st.selectbox("過去の利用者検索", user_list, label_visibility="collapsed")
    
    if selected_user != "-- 新規入力 (直接入力してください) --":
        default_name = selected_user
        try:
            default_grade = recent_users[recent_users['名前'] == selected_user]['学年'].values[0]
            if not default_grade: default_grade = "--選択--"
        except:
            default_grade = "--選択--"
    else:
        default_name = ""
        default_grade = "--選択--"

    col1, col2 = st.columns([1, 1])
    with col1: f_date = st.date_input("利用日", jst_now.date(), max_value=jst_now.date())
    with col2: 
        g_index = GRADES.index(default_grade) if default_grade in GRADES else 0
        f_grade = st.selectbox("学年 (※同姓同名がいる場合のみ選択)", GRADES, index=g_index)
        
    k_name = f"name_{st.session_state.form_key}"
    f_name = st.text_input("氏名 (必須)", value=default_name, key=k_name, placeholder="例: 山田太郎")

    default_in = (jst_now - timedelta(hours=1)).strftime("%H%M")
    default_out = jst_now.strftime("%H%M")

    col_in, col_out = st.columns(2)
    with col_in:
        in_time_str = st.text_input("開始時間 (必須)", value=default_in, placeholder="例: 1223 (全角数字もOK)")
    with col_out:
        out_time_str = st.text_input("終了時間 (必須)", value=default_out, placeholder="例: 1530 (全角数字もOK)")

    st.markdown("<hr style='margin-top:20px; margin-bottom:20px;'>", unsafe_allow_html=True)

    if st.button("この内容で1件記録する", use_container_width=True, type="primary"):
        f_name_clean = f_name.replace(" ", "").replace("　", "")
        grade_to_save = f_grade if f_grade != "--選択--" else ""
        
        in_time = parse_custom_time(in_time_str)
        out_time = parse_custom_time(out_time_str)
        
        if not f_name_clean: st.error("氏名を入力してください。")
        elif in_time is None or out_time is None: st.error("開始時間と終了時間を正しく入力してください。(例: 1530 または １５３０)")
        elif not is_special_period(f_date) and in_time.hour < 12: st.error("通常期間は12時以降を入力してください。")
        else:
            duration = calc_duration(in_time, out_time)
            if duration <= 0: 
                st.error("終了時間は開始時間以降に設定してください")
            else:
                df = load_data()
                in_str = in_time.strftime("%H:%M")
                out_str = out_time.strftime("%H:%M")
                
                is_dup = not df[
                    (df['日付'] == pd.to_datetime(f_date)) & 
                    (df['名前'] == f_name_clean) & 
                    (df['入室時間'] == in_str) & 
                    (df['退室時間'] == out_str)
                ].empty
                
                if is_dup:
                    st.error("この記録は既に登録されています（重複エラー）。")
                else:
                    new_row = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name_clean, '学年': grade_to_save, '入室時間': in_str, '退室時間': out_str, '利用時間（時間）': duration}])
                    df = pd.concat([df, new_row], ignore_index=True)
                    save_to_gs(df)
                    st.session_state.form_key += 1 
                    st.session_state.sys_msg = f"{f_name_clean}さんの記録（{in_str} 〜 {out_str}）を保存しました。"
                    st.cache_data.clear()
                    st.rerun()

elif menu == "ランキング":
    st.markdown("<div class='main-title'>STUDY HOURS RANKING</div>", unsafe_allow_html=True)
    df = load_data()

    def render_premium_cards(agg):
        if agg.empty: return
        html = '<div style="display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap;">'
        top_rows = agg[agg['順位'] <= 3]
        for i, row in top_rows.iterrows():
            rank_val, name, time_val = row['順位'], row['名前'], row['利用時間（時間）']
            grade_disp = row['学年'] if pd.notnull(row['学年']) and row['学年'] != "" else "学年未設定"
            
            if rank_val == 1: rank_text, icon, border_color, bg_grad = "1st", "", "#F59E0B", "linear-gradient(135deg, #FFFFFF 0%, #FFFBEB 100%)"
            elif rank_val == 2: rank_text, icon, border_color, bg_grad = "2nd", "", "#94A3B8", "linear-gradient(135deg, #FFFFFF 0%, #F8FAFC 100%)"
            elif rank_val == 3: rank_text, icon, border_color, bg_grad = "3rd", "", "#B45309", "linear-gradient(135deg, #FFFFFF 0%, #FFF7ED 100%)"
            else: rank_text, icon, border_color, bg_grad = f"{rank_val}th", "", "#64748B", "linear-gradient(135deg, #FFFFFF 0%, #F1F5F9 100%)"
            html += f"<div class='rank-card' style='background: {bg_grad}; border-top: 5px solid {border_color}; box-shadow: 0 4px 6px rgba(0,0,0,0.05);'><div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;'><span style='font-size: 1.1rem; color: #475569; font-weight: 900; letter-spacing: 1px;'>{rank_text} PLACE</span><span style='font-size: 1.5rem;'>{icon}</span></div><div style='font-size: 0.9rem; color: #64748B; font-weight: bold; margin-bottom: 5px;'>{grade_disp}</div><div style='font-size: 2.2rem; font-weight: 900; color: #0F172A; margin-bottom: 15px;'>{name} <span style='font-size: 1rem; font-weight: 600; color: #64748B;'>さん</span></div><div style='display: inline-block; background-color: #FFFFFF; color: #1D4ED8; padding: 6px 16px; border-radius: 8px; font-weight: 900; font-size: 1.2rem; border: 1px solid #BFDBFE;'>{time_val:.1f} <span style='font-size: 0.9rem;'>HOURS</span></div></div>"
        html += '</div>'
        st.markdown(html, unsafe_allow_html=True)

    def render_section_ranking(full_agg, target_grades, section_title):
        section_df = full_agg[full_agg['学年'].isin(target_grades)].reset_index(drop=True)
        st.markdown(f"<div class='section-title'>{section_title}</div>", unsafe_allow_html=True)
        if section_df.empty: st.info("集計データがありません。"); return
        section_df['順位'] = section_df['利用時間（時間）'].rank(method='min', ascending=False).astype(int)
        render_premium_cards(section_df)
        st.dataframe(section_df[['順位', '名前', '学年', '利用時間（時間）']], use_container_width=True, hide_index=True, column_config={
            "順位": st.column_config.NumberColumn("順位"), "名前": st.column_config.TextColumn("氏名"), "学年": st.column_config.TextColumn("学年"),
            "利用時間（時間）": st.column_config.ProgressColumn("累計学習時間", format="%.1f h", min_value=0, max_value=float(section_df['利用時間（時間）'].max() if section_df['利用時間（時間）'].max() > 0 else 1))
        })

    if not df.empty:
        tab1, tab2, tab3 = st.tabs(["今月の集計", "直近3ヶ月", "累計"])
        def get_agg(target_df):
            if target_df.empty: return pd.DataFrame()
            return target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index().sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)

        jst_today = pd.Timestamp(jst_now.date())
        df_vp = df[df['日付'] <= jst_today]
        
        for tab, agg_data in zip([tab1, tab2, tab3], [get_agg(df_vp[(df_vp['日付'].dt.year == jst_today.year) & (df_vp['日付'].dt.month == jst_today.month)]), get_agg(df_vp[df_vp['日付'] >= (jst_today - pd.DateOffset(months=3))]), get_agg(df_vp)]):
            with tab:
                if agg_data.empty: st.info("データがありません。")
                else:
                    render_section_ranking(agg_data, [f"小{i}" for i in range(1, 7)], "小学生の部")
                    render_section_ranking(agg_data, [f"中{i}" for i in range(1, 4)], "中学生の部")
                    render_section_ranking(agg_data, [f"高{i}" for i in range(1, 4)] + ["既卒/その他", ""], "高校生・その他・学年未設定")
    else: st.info("データがありません。最初の記録を登録してください。")

elif menu == "分析":
    st.markdown("<div class='main-title'>ANALYTICS DASHBOARD</div>", unsafe_allow_html=True)
    df_ana = load_data()
    jst_today = pd.Timestamp(jst_now.date())

    st.markdown("<div class='section-title'>パフォーマンスサマリー（前月比）</div>", unsafe_allow_html=True)
    if not df_ana.empty:
        this_month_start = jst_today.replace(day=1)
        last_month_start = (this_month_start - pd.Timedelta(days=1)).replace(day=1)
        
        df_this = df_ana[df_ana['日付'] >= this_month_start]
        df_last = df_ana[(df_ana['日付'] >= last_month_start) & (df_ana['日付'] < this_month_start)]
        
        hours_this = df_this['利用時間（時間）'].sum()
        hours_last = df_last['利用時間（時間）'].sum()
        diff_hours = hours_this - hours_last
        pct_hours = (diff_hours / hours_last * 100) if hours_last > 0 else (100 if hours_this > 0 else 0)
        
        users_this = df_this['名前'].nunique()
        users_last = df_last['名前'].nunique()
        diff_users = users_this - users_last
        pct_users = (diff_users / users_last * 100) if users_last > 0 else (100 if users_this > 0 else 0)
        
        col_met1, col_met2, col_met3 = st.columns(3)
        col_met1.metric("今月の総学習時間", f"{hours_this:.1f} 時間", f"{pct_hours:+.1f}% ({diff_hours:+.1f} 時間)")
        col_met2.metric("今月の利用者数", f"{users_this} 名", f"{pct_users:+.1f}% ({diff_users:+d} 名)")
        if users_this > 0:
            avg_this = hours_this / users_this
            avg_last = hours_last / users_last if users_last > 0 else 0
            diff_avg = avg_this - avg_last
            pct_avg = (diff_avg / avg_last * 100) if avg_last > 0 else (100 if avg_this > 0 else 0)
            col_met3.metric("1人あたり平均学習時間", f"{avg_this:.1f} 時間", f"{pct_avg:+.1f}% ({diff_avg:+.1f} 時間)")
            
        # --- 翌月の利用予測 ---
        today_d = jst_today.day
        next_month_first = (jst_today.replace(day=1) + timedelta(days=32)).replace(day=1)
        days_in_month = (next_month_first - timedelta(days=1)).day
        
        proj_hours_this_month = hours_this / today_d * days_in_month if today_d > 0 else 0
        
        growth_rate_h = pct_hours / 100.0 if pct_hours != 100 else 0
        next_month_h = proj_hours_this_month * (1 + max(min(growth_rate_h, 0.15), -0.15))
        next_month_u = users_this * (1 + max(min((pct_users / 100.0), 0.1), -0.1))
        
        st.markdown(f"""
        <div style='background-color: #FFFFFF; border-left: 6px solid #F59E0B; padding: 20px; border-radius: 12px; margin-top: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);'>
            <div style='font-weight: 900; color: #0F172A; margin-bottom: 8px; font-size: 1.2rem;'> 翌月の着地予測</div>
            <div style='color: #475569; font-size: 1.05rem;'>
                現在のペースと成長トレンドを考慮すると、来月は <b style='color: #B45309; font-size: 1.3rem;'>約 {next_month_h:.0f} 時間</b> の利用と、<b style='color: #B45309; font-size: 1.3rem;'>約 {int(next_month_u)} 名</b> の生徒の来室が見込まれます。
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("データが蓄積されると前月比の利用率が表示されます。")
        
    st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["混雑状況", "生徒個別", "来週の予測"])

    def get_active_slots(in_str, out_str, slots_list):
        def parse_time(t_str):
            t_str = str(t_str).strip()
            if "コマ" in t_str:
                try:
                    koma = int(t_str.replace("コマ", ""))
                    hour = 13 + int((koma - 1) * 1.5)
                    return datetime.strptime(f"{hour:02d}:00", "%H:%M").time()
                except: return None
            try:
                parts = t_str.split(":")
                if len(parts) >= 2:
                    return datetime.strptime(f"{int(parts[0]):02d}:{int(parts[1]):02d}", "%H:%M").time()
            except: pass
            return None

        in_t = parse_time(in_str)
        out_t = parse_time(out_str)
        if not in_t or not out_t: return []
        
        slots = []
        for slot_str in slots_list:
            h = int(slot_str[:2])
            slot_start = datetime.strptime(f"{h:02d}:00", "%H:%M").time()
            slot_end = datetime.strptime(f"{h+1:02d}:00", "%H:%M").time() if h < 22 else datetime.strptime("23:59", "%H:%M").time()
            if in_t < slot_end and out_t > slot_start:
                slots.append(slot_str)
        return slots

    with tab1:
        st.markdown("<div class='section-title'>曜日・時間帯別の混雑状況</div>", unsafe_allow_html=True)
        if not df_ana.empty:
            df_ana['年月'] = pd.to_datetime(df_ana['日付']).dt.strftime('%Y年%m月')
            month_options = ["累計"] + sorted(df_ana['年月'].dropna().unique().tolist(), reverse=True)
            selected_period = st.selectbox("集計対象を選択", month_options)

            target_df = df_ana if selected_period == "累計" else df_ana[df_ana['年月'] == selected_period]
            
            current_time_slots = get_time_slots_for_period(selected_period)
            weekdays = ["月", "火", "水", "木", "金", "土", "日"]
            heatmap_data = pd.DataFrame(0, index=weekdays, columns=current_time_slots)

            for _, row in target_df.iterrows():
                if pd.isnull(row['日付']) or not row['入室時間'] or not row['退室時間']: continue
                try:
                    wd = weekdays[pd.to_datetime(row['日付']).weekday()]
                    for slot in get_active_slots(row['入室時間'], row['退室時間'], current_time_slots):
                        heatmap_data.loc[wd, slot] += 1
                except: continue

            max_val = heatmap_data.values.max()
            max_val = max(max_val, 1)

            html = "<div style='overflow-x: auto; background: white; padding: 15px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #E2E8F0;'><table style='width:100%; border-collapse: collapse; min-width: 600px;'>"
            html += "<tr><th style='border: 1px solid #CBD5E1; padding: 10px; background-color: #F8FAFC; color: #0F172A; position: sticky; left: 0; z-index: 1;'>曜日</th>"
            for tb in current_time_slots: html += f"<th style='border: 1px solid #CBD5E1; padding: 10px; background-color: #F8FAFC; color: #0F172A; font-size:0.85rem;'>{tb[:2]}時台</th>"
            html += "</tr>"

            for wd in weekdays:
                html += f"<tr><th style='border: 1px solid #CBD5E1; padding: 10px; background-color: #F8FAFC; color: #0F172A; position: sticky; left: 0; z-index: 1;'>{wd}</th>"
                for tb in current_time_slots:
                    val = heatmap_data.loc[wd, tb]
                    ratio = val / max_val if max_val > 0 else 0
                    bg_color = f"rgba(37, 99, 235, {ratio * 0.8})" if val > 0 else "transparent"
                    font_color = "white" if ratio > 0.5 else "#1E293B"
                    html += f"<td style='border: 1px solid #CBD5E1; padding: 10px; text-align: center; font-weight: bold; background-color: {bg_color}; color: {font_color};'>{val}</td>"
                html += "</tr>"
            html += "</table></div>"
            st.markdown(html, unsafe_allow_html=True)
        else:
            st.info("集計するデータがありません。")

    with tab2:
        st.markdown("<div class='section-title'>生徒個別 学習時間データ</div>", unsafe_allow_html=True)
        if not df_ana.empty:
            unique_names = df_ana['名前'].dropna().unique().tolist()
            unique_names = [n for n in unique_names if str(n).strip() != ""]

            if unique_names:
                selected_name = st.selectbox("生徒名で検索", ["-- 選択してください --"] + unique_names)
                if selected_name != "-- 選択してください --":
                    student_df = df_ana[df_ana['名前'] == selected_name].copy()
                    student_df['日付'] = pd.to_datetime(student_df['日付'])

                    this_month = jst_today.replace(day=1)
                    sm_df = student_df[student_df['日付'] >= this_month]
                    total_h = sm_df['利用時間（時間）'].sum()

                    st.markdown(f"<div style='background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%); padding: 25px; border-radius: 12px; color: white; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);'><h4 style='margin:0; font-size: 1.1rem; color: #94A3B8; font-weight: bold;'>{selected_name} さんの今月の学習時間</h4><div style='font-size: 3rem; font-weight: 900; margin-top: 5px; color: #FFFFFF;'>{total_h:.1f} <span style='font-size: 1.2rem; font-weight: bold; color: #94A3B8;'>時間</span></div></div>", unsafe_allow_html=True)

                    st.markdown("##### 日別の学習推移（今月）")
                    if not sm_df.empty:
                        daily_sum = sm_df.groupby('日付')['利用時間（時間）'].sum().reset_index()
                        daily_sum['日付ラベル'] = daily_sum['日付'].dt.strftime('%m/%d')
                        chart_data = daily_sum.set_index('日付ラベル')['利用時間（時間）']
                        st.bar_chart(chart_data)
                    else: st.info("今月の記録はまだありません。")

                    st.markdown("##### 直近の記録一覧")
                    display_history = student_df.sort_values('日付', ascending=False).head(10)
                    display_history['日付'] = display_history['日付'].dt.strftime('%Y/%m/%d')
                    st.dataframe(display_history[['日付', '入室時間', '退室時間', '利用時間（時間）']], use_container_width=True, hide_index=True)
            else: st.info("検索できる生徒データがありません。")
        else: st.info("集計するデータがありません。")

    with tab3:
        st.markdown("<div class='section-title'>来週の混雑予測（推計）</div>", unsafe_allow_html=True)
        st.markdown("<p style='color:#64748B; font-size:1rem; font-weight: bold;'>直近4週間（過去28日間）の実際の利用データを解析し、来週の各時間帯に平均して何人の生徒が来るかを推計しています。</p>", unsafe_allow_html=True)
        
        if not df_ana.empty:
            # 過去のデータから乗数を学習
            test_mult, before_mult = learn_multipliers(df_ana)
            
            four_weeks_ago = jst_today - pd.Timedelta(days=28)
            df_recent = df_ana[pd.to_datetime(df_ana['日付']) >= four_weeks_ago]
            
            # 来週の日付を特定し、テスト前やテスト期間が含まれるかチェック
            target_dates = [jst_today + timedelta(days=i) for i in range(1, 8)]
            has_test = any(get_period_status(dt) == "test" for dt in target_dates)
            has_before = any(get_period_status(dt) == "before_test" for dt in target_dates)
            
            if has_test or has_before:
                msg_parts = []
                if has_test: msg_parts.append("「テスト期間」")
                if has_before: msg_parts.append("「テスト1週間前」")
                status_str = " または ".join(msg_parts)
                st.markdown(f"<div style='background-color: #FEF2F2; border-left: 5px solid #DC2626; padding: 15px; margin-bottom: 20px; border-radius: 8px;'><p style='color:#DC2626; font-weight:bold; margin:0;'>⚠️ 来週は{status_str}に該当する日があるため、通常より混雑が予想されます。座席数を超える時間帯にご注意ください。</p></div>", unsafe_allow_html=True)

            if not df_recent.empty:
                pred_period_str = (jst_today + pd.Timedelta(days=7)).strftime('%Y年%m月')
                pred_time_slots = get_time_slots_for_period(pred_period_str)
                weekdays = ["月", "火", "水", "木", "金", "土", "日"]
                
                # 平準化用のベースライン計算
                predict_data = pd.DataFrame(0.0, index=weekdays, columns=pred_time_slots)

                for _, row in df_recent.iterrows():
                    if pd.isnull(row['日付']) or not row['入室時間'] or not row['退室時間']: continue
                    try:
                        dt = pd.to_datetime(row['日付'])
                        wd = weekdays[dt.weekday()]
                        status = get_period_status(dt)
                        
                        # 過去データが既にテスト前・テスト中だった場合、割引いて「通常時」の水準に戻す
                        div_factor = 1.0
                        if status == "test": div_factor = test_mult
                        elif status == "before_test": div_factor = before_mult
                        
                        for slot in get_active_slots(row['入室時間'], row['退室時間'], pred_time_slots):
                            predict_data.loc[wd, slot] += (0.25 / div_factor)
                    except: continue

                # 来週の該当曜日ごとに、適切な乗数を掛ける
                for dt in target_dates:
                    wd = weekdays[dt.weekday()]
                    status = get_period_status(dt)
                    mult = 1.0
                    if status == "test": mult = test_mult
                    elif status == "before_test": mult = before_mult
                    predict_data.loc[wd] = predict_data.loc[wd] * mult

                html = "<div style='overflow-x: auto; background: white; padding: 15px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #E2E8F0;'><table style='width:100%; border-collapse: collapse; min-width: 600px;'>"
                html += "<tr><th style='border: 1px solid #CBD5E1; padding: 10px; background-color: #F8FAFC; color: #0F172A; position: sticky; left: 0; z-index: 1;'>曜日</th>"
                for tb in pred_time_slots: html += f"<th style='border: 1px solid #CBD5E1; padding: 10px; background-color: #F8FAFC; color: #0F172A; font-size:0.85rem;'>{tb[:2]}時台</th>"
                html += "</tr>"

                for wd in weekdays:
                    html += f"<tr><th style='border: 1px solid #CBD5E1; padding: 10px; background-color: #F8FAFC; color: #0F172A; position: sticky; left: 0; z-index: 1;'>{wd}</th>"
                    for tb in pred_time_slots:
                        val = predict_data.loc[wd, tb]
                        
                        ratio = val / 20.0
                        if ratio > 1.0: ratio = 1.0
                        
                        rounded_val = int(round(val))
                        
                        if rounded_val >= 20:
                            bg_color = "rgba(220, 38, 38, 0.9)"
                            font_color = "white"
                            display_val = "満席⚠️"
                        elif rounded_val >= 15:
                            bg_color = f"rgba(234, 88, 12, {max(0.6, ratio)})"
                            font_color = "white"
                            display_val = f"約{rounded_val}人"
                        elif rounded_val > 0:
                            bg_color = f"rgba(37, 99, 235, {ratio * 0.8})"
                            font_color = "white" if ratio > 0.4 else "#1E293B"
                            display_val = f"約{rounded_val}人"
                        else:
                            bg_color = "transparent"
                            font_color = "#1E293B"
                            display_val = "-"
                            
                        html += f"<td style='border: 1px solid #CBD5E1; padding: 10px; text-align: center; font-size:0.85rem; font-weight: bold; background-color: {bg_color}; color: {font_color};'>{display_val}</td>"
                    html += "</tr>"
                html += "</table></div>"
                st.markdown(html, unsafe_allow_html=True)
            else:
                st.info("直近4週間のデータがないため、予測を計算できません。")
        else:
            st.info("集計するデータがありません。")

elif menu == "管理":
    st.markdown("<div class='main-title'>ADMIN PANEL</div>", unsafe_allow_html=True)
    df_manage = load_data()
    
    if not df_manage.empty:
        tab_edit, tab_del = st.tabs(["1件ずつ編集", "複数の一括削除"])
        
        options = []
        for i in reversed(df_manage.index):
            row = df_manage.loc[i]
            d_str = row['日付'].strftime('%m/%d') if pd.notnull(row['日付']) else "不明"
            options.append((str(i), f"{d_str} | {row['名前']} ({row['入室時間']} - {row['退室時間']})"))
            
        with tab_del:
            st.markdown("##### まとめて削除")
            selected_dels = st.multiselect("削除する記録を選択してください", options, format_func=lambda x: x[1])
            
            if st.button("選択した記録を完全に削除", type="primary"):
                if selected_dels:
                    indices_to_drop = [int(x[0]) for x in selected_dels]
                    df_manage = df_manage.drop(indices_to_drop).reset_index(drop=True)
                    save_to_gs(df_manage)
                    st.session_state.sys_msg = f"{len(indices_to_drop)}件の記録を削除しました。"
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.warning("削除する記録が選択されていません。")

        with tab_edit:
            st.markdown("##### 記録の編集")
            selected_mng = st.selectbox("編集する記録", [("-1", "-- 選択してください --")] + options[:50], format_func=lambda x: x[1])
            
            if selected_mng[0] != "-1":
                target_idx = int(selected_mng[0])
                target_row = df_manage.loc[target_idx]
                st.markdown("<div style='margin-top: 10px; padding: 25px; border-radius: 12px; background-color: #FFFFFF; border: 1px solid #E2E8F0; box-shadow: 0 4px 6px rgba(0,0,0,0.05);'>", unsafe_allow_html=True)
                
                default_date = target_row['日付'].date() if pd.notnull(target_row['日付']) else jst_now.date()
                edit_date = st.date_input("利用日", default_date)
                
                col_n, col_g = st.columns(2)
                with col_n: edit_name = st.text_input("氏名 (必須)", value=str(target_row['名前']), placeholder="例: 山田太郎")
                with col_g:
                    current_grade = str(target_row['学年'])
                    if not current_grade: current_grade = "--選択--"
                    g_index = GRADES.index(current_grade) if current_grade in GRADES else 0
                    edit_grade = st.selectbox("学年 (同姓同名がいる場合のみ)", GRADES, index=g_index)
                    
                col_in, col_out = st.columns(2)
                with col_in: edit_in_str = st.text_input("開始時間 (例: 1223, 全角OK)", value=str(target_row['入室時間']).replace(":", ""), placeholder="例: 1223")
                with col_out: edit_out_str = st.text_input("終了時間 (例: 1530, 全角OK)", value=str(target_row['退室時間']).replace(":", ""), placeholder="例: 1530")
                
                st.markdown("<br>", unsafe_allow_html=True)
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("この内容で上書き保存", use_container_width=True, type="primary"):
                        edit_name_clean = edit_name.replace(" ", "").replace("　", "")
                        grade_to_save = edit_grade if edit_grade != "--選択--" else ""
                        
                        edit_in = parse_custom_time(edit_in_str)
                        edit_out = parse_custom_time(edit_out_str)
                        
                        if edit_name_clean:
                            if edit_in is None or edit_out is None: st.error("開始と終了時間を正しく入力してください。")
                            elif not is_special_period(edit_date) and edit_in.hour < 12: st.error("通常期間は12時以降を入力してください。")
                            else:
                                duration = calc_duration(edit_in, edit_out)
                                if duration <= 0: st.error("終了時間は開始時間以降に設定してください")
                                else:
                                    df_manage.at[target_idx, '日付'] = pd.to_datetime(edit_date)
                                    df_manage.at[target_idx, '名前'] = edit_name_clean
                                    df_manage.at[target_idx, '学年'] = grade_to_save
                                    df_manage.at[target_idx, '入室時間'] = edit_in.strftime("%H:%M")
                                    df_manage.at[target_idx, '退室時間'] = edit_out.strftime("%H:%M")
                                    df_manage.at[target_idx, '利用時間（時間）'] = duration
                                    save_to_gs(df_manage)
                                    st.session_state.sys_msg = "記録を更新しました。"
                                    st.cache_data.clear()
                                    st.rerun()
                        else: st.error("氏名を入力してください。")
                with col_btn2:
                    if st.button("この記録を完全に削除", use_container_width=True):
                        df_manage = df_manage.drop(target_idx).reset_index(drop=True)
                        save_to_gs(df_manage)
                        st.session_state.sys_msg = "削除しました。"
                        st.cache_data.clear()
                        st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
    else: st.info("変更・削除できるデータがありません。")
