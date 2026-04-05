import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import re

# --- 1. ページ構成（システムUIのオーバーライド） ---
st.set_page_config(page_title="Study Room Analytics", page_icon="icon.png", layout="wide")

st.markdown("""
<style>
    /* 不要なシステムUIを非表示 */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}

    /* アプリ全体のデザイン */
    .stApp {
        background-color: #F8FAFC;
        font-family: 'Helvetica Neue', Arial, 'Hiragino Kaku Gothic ProN', 'Hiragino Sans', Meiryo, sans-serif;
    }

    /* メインタイトル */
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        color: #0F172A;
        margin-bottom: 25px;
        padding-bottom: 15px;
        border-bottom: 3px solid #E2E8F0;
    }

    /* サイドバー */
    [data-testid="stSidebar"] { background-color: #1E293B; }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] p, [data-testid="stSidebar"] label {
        color: #F8FAFC !important;
    }

    /* データフレーム（表）のヘッダー背景色 */
    [data-testid="stDataFrame"] table th { background-color: #F1F5F9 !important; color: #334155 !important; }

    /* 印刷時の専用スタイル */
    @media print {
        header, footer, [data-testid="stSidebar"], div.stButton, .stTabs [data-baseweb="tab-list"], [data-testid="stExpander"] {
            display: none !important;
        }
        .stApp { background-color: white !important; }
        .print-area { display: block !important; }
    }
</style>
""", unsafe_allow_html=True)

# --- 2. バックエンド設定 ---
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
        if not df.empty: df['日付'] = pd.to_datetime(df['日付'])
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

# --- 3. 時刻フォーマット関数 ---
def format_time_str(t_str):
    if not t_str: return ""
    clean = re.sub(r'[^0-9]', '', str(t_str))
    if len(clean) == 3: clean = "0" + clean
    if len(clean) == 4: return f"{clean[:2]}:{clean[2:]}"
    return t_str

def parse_final_time(t_str):
    try: return datetime.strptime(t_str, "%H:%M").time()
    except: return None

# --- 4. ユーザーインターフェース（サイドバー） ---
if "confirm_data" not in st.session_state:
    st.session_state.confirm_data = None

with st.sidebar:
    if os.path.exists("icon.png"): st.image("icon.png", width=60)
    
    if st.session_state.confirm_data is None:
        # 【入力モード】
        st.markdown("### 📝 ENTRY PANEL")
        f_date = st.date_input("利用日", datetime.now())
        f_name = st.text_input("氏名", placeholder="山田 太郎")
        grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
        f_grade = st.selectbox("学年", grades)
        
        col_in, col_out = st.columns(2)
        with col_in: raw_in = st.text_input("入室 (例:1900)")
        with col_out: raw_out = st.text_input("退室 (例:2130)")
        
        if st.button("確認画面へ進む", use_container_width=True):
            fmt_in = format_time_str(raw_in)
            fmt_out = format_time_str(raw_out)
            t_start = parse_final_time(fmt_in)
            t_end = parse_final_time(fmt_out)
            
            if f_name and t_start and t_end:
                st.session_state.confirm_data = {
                    "date": f_date, "name": f_name, "grade": f_grade,
                    "in_time": fmt_in, "out_time": fmt_out,
                    "t_start": t_start, "t_end": t_end
                }
                st.rerun()
            else:
                st.error("入力内容に誤りがあります。")
        
        st.markdown("<hr>", unsafe_allow_html=True)
        admin_pass = st.text_input("Admin Password", type="password")
        if admin_pass == "admin123":
            if st.button("🚨 データをリセット", use_container_width=True):
                save_to_gs(load_data(), "バックアップ")
                save_to_gs(pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']), "メイン")
                st.cache_data.clear()
                st.rerun()
    else:
        # 【確認モード】
        d = st.session_state.confirm_data
        st.markdown("### ⚠️ 登録内容の確認")
        st.markdown(f"""
        <div style="background-color:#F1F5F9; padding: 15px; border-radius: 8px; color:#0F172A; font-size:0.95rem; margin-bottom:15px;">
            <b>利用日：</b> {d['date'].strftime('%Y-%m-%d')}<br>
            <b>氏名：</b> {d['name']} ({d['grade']})<br>
            <b>時刻：</b> {d['in_time']} ～ {d['out_time']}
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("✅ 確定して保存", type="primary", use_container_width=True):
            start_dt = datetime.combine(d['date'], d['t_start'])
            end_dt = datetime.combine(d['date'], d['t_end'])
            if end_dt < start_dt: end_dt += timedelta(days=1)
            duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
            
            df = load_data()
            new_row = pd.DataFrame([{'日付': pd.to_datetime(d['date']), '名前': d['name'], '学年': d['grade'], '入室時間': d['in_time'], '退室時間': d['out_time'], '利用時間（時間）': duration}])
            df = pd.concat([df, new_row], ignore_index=True)
            save_to_gs(df)
            st.session_state.confirm_data = None
            st.cache_data.clear()
            st.rerun()
            
        if st.button("🔙 修正する", use_container_width=True):
            st.session_state.confirm_data = None
            st.rerun()

# --- 5. メインパネル（ランキング） ---
st.markdown("<div class='main-title'>🏆 塾生学習時間ランキング</div>", unsafe_allow_html=True)
df = load_data()

# オリジナルデザインのトップ3カード描画関数
def render_premium_cards(agg):
    if agg.empty: return
    html = '<div style="display: flex; gap: 20px; margin-bottom: 30px; flex-wrap: wrap;">'
    medals = [("🥇 1位", "#3B82F6"), ("🥈 2位", "#64748B"), ("🥉 3位", "#F59E0B")]
    
    for i in range(min(3, len(agg))):
        rank_text, border_color = medals[i]
        name = agg.iloc[i]['名前']
        grade = agg.iloc[i]['学年']
        time_val = agg.iloc[i]['利用時間（時間）']
        
        html += f"""
        <div style="flex: 1; min-width: 250px; background: #FFFFFF; padding: 25px; border-radius: 12px; border-left: 6px solid {border_color}; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); border-top: 1px solid #E2E8F0; border-right: 1px solid #E2E8F0; border-bottom: 1px solid #E2E8F0;">
            <div style="font-size: 0.95rem; color: #64748B; font-weight: bold; margin-bottom: 8px;">{rank_text} / {grade}</div>
            <div style="font-size: 2.2rem; font-weight: 800; color: #0F172A; margin-bottom: 12px;">{name} <span style="font-size: 1.2rem; font-weight: 600; color: #475569;">さん</span></div>
            <div style="display: inline-block; background-color: #ECFDF5; color: #059669; padding: 4px 16px; border-radius: 20px; font-weight: 700; font-size: 1.1rem;">
                ↑ {time_val:.2f} 時間
            </div>
        </div>
        """
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)

# 印刷用画面の生成関数
def render_printable_table(agg, title):
    if agg.empty: return
    print_html = f"<h2 style='color: black; margin-top: 0;'>{title}</h2>"
    print_html += "<table style='width: 100%; border-collapse: collapse; font-family: sans-serif; color: black; margin-bottom: 40px;'>"
    print_html += "<tr><th style='border: 1px solid #000; padding: 12px; background-color: #f1f5f9; text-align: center;'>順位</th><th style='border: 1px solid #000; padding: 12px; background-color: #f1f5f9;'>氏名</th><th style='border: 1px solid #000; padding: 12px; background-color: #f1f5f9; text-align: center;'>学年</th><th style='border: 1px solid #000; padding: 12px; background-color: #f1f5f9; text-align: right;'>トータル学習時間</th></tr>"
    for i, row in agg.iterrows():
        print_html += f"<tr><td style='border: 1px solid #000; padding: 10px; text-align: center;'>{i+1}位</td><td style='border: 1px solid #000; padding: 10px; font-weight: bold;'>{row['名前']}</td><td style='border: 1px solid #000; padding: 10px; text-align: center;'>{row['学年']}</td><td style='border: 1px solid #000; padding: 10px; text-align: right;'>{row['利用時間（時間）']:.2f} h</td></tr>"
    print_html += "</table>"
    st.markdown(print_html, unsafe_allow_html=True)

if not df.empty:
    tab1, tab2, tab3, tab4 = st.tabs(["🗓 今月の集計", "🔥 直近3ヶ月", "👑 殿堂入り（累計）", "🖨️ 印刷用画面"])
    
    # データの集計処理
    def get_agg_data(target_df):
        if target_df.empty: return pd.DataFrame()
        agg = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        return agg.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)

    agg_month = get_agg_data(df[df['日付'].dt.month == datetime.now().month])
    agg_3months = get_agg_data(df[df['日付'] >= (datetime.now() - timedelta(days=90))])
    agg_all = get_agg_data(df)

    # 画面描画
    for tab, agg_data in zip([tab1, tab2, tab3], [agg_month, agg_3months, agg_all]):
        with tab:
            if agg_data.empty: st.info("データがありません。")
            else:
                render_premium_cards(agg_data)
                agg_data.index += 1
                st.dataframe(agg_data, use_container_width=True, hide_index=True, column_config={
                    "名前": st.column_config.TextColumn("氏名"),
                    "学年": st.column_config.TextColumn("学年"),
                    "利用時間（時間）": st.column_config.ProgressColumn("トータル学習時間", format="%.2f h", min_value=0, max_value=float(agg_data['利用時間（時間）'].max()))
                })

    with tab4:
        st.markdown("### 🖨️ 張り出し用ランキング印刷")
        st.info("ブラウザの印刷機能（`Ctrl + P` または `Cmd + P`）を利用してください。白黒で表のみが綺麗に出力されます。")
        st.markdown("<div class='print-area'>", unsafe_allow_html=True)
        render_printable_table(agg_month, "【今月の集計】学習時間ランキング")
        render_printable_table(agg_3months, "【直近3ヶ月】学習時間ランキング")
        render_printable_table(agg_all, "【殿堂入り】学習時間ランキング")
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("📝 過去のすべての履歴を確認する"):
        st.dataframe(df.sort_values(by='日付', ascending=False), use_container_width=True, hide_index=True)
else:
    st.info("データがありません。")
