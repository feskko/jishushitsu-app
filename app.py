import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import re

# --- 1. ページ構成（自作感を消す設定） ---
st.set_page_config(page_title="Study Room Analytics", page_icon="icon.png", layout="wide")

# 徹底的なUIカスタマイズ（StreamlitのデフォルトUIを隠す）
st.markdown("""
<style>
    /* ヘッダー、フッター、右上のメニューを非表示にしてアプリ感を出す */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}

    /* アプリ全体の背景とフォント */
    .stApp {
        background-color: #F0F4F8;
        font-family: 'Helvetica Neue', Arial, 'Hiragino Kaku Gothic ProN', 'Hiragino Sans', Meiryo, sans-serif;
    }

    /* メインタイトル */
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        color: #1A365D;
        letter-spacing: 1px;
        margin-bottom: 25px;
        padding-bottom: 10px;
        border-bottom: 3px solid #cbd5e1;
    }

    /* サイドバー（深い藍色） */
    [data-testid="stSidebar"] {
        background-color: #1A365D;
        border-right: 1px solid #E2E8F0;
    }
    /* サイドバー内のテキストを白に統一 */
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] p, [data-testid="stSidebar"] label {
        color: #FFFFFF !important;
    }

    /* 入力フォームのデザイン（白背景に丸み） */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important;
        border-radius: 8px !important;
        border: 1px solid #CBD5E1 !important;
    }
    /* 入力される文字の色（黒系にして見やすく） */
    div[data-baseweb="input"] input, div[data-baseweb="select"] div {
        color: #1E293B !important;
        font-weight: 600;
        font-size: 1rem;
    }

    /* メインボタンのグラデーション・デザイン */
    .stButton>button {
        background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%);
        color: #FFFFFF !important;
        font-weight: bold;
        font-size: 1.1rem;
        border-radius: 8px;
        border: none;
        height: 3.2rem;
        width: 100%;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2);
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(37, 99, 235, 0.3);
    }

    /* トップ3のカード（メトリック）デザイン */
    [data-testid="stMetric"] {
        background-color: #FFFFFF;
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        border: 1px solid #E2E8F0;
        border-left: 6px solid #2563EB; /* 左側に青いアクセントライン */
    }
    [data-testid="stMetric"] label {
        color: #64748B !important;
        font-size: 1rem;
        font-weight: 600;
    }
    [data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #1E293B !important;
        font-weight: 800;
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

# --- 3. 時刻の魔法（自動フォーマット機能） ---
# セッション状態の初期化
if "in_time" not in st.session_state: st.session_state.in_time = ""
if "out_time" not in st.session_state: st.session_state.out_time = ""

def auto_format_times():
    """入力された数字（1900）を即座に（19:00）に書き換えるコールバック関数"""
    for key in ["in_time", "out_time"]:
        val = st.session_state[key]
        if not val: continue
        # すでにコロンが含まれていればそのまま
        if ":" in val: continue
        
        # 数字だけを抽出してフォーマット
        clean = re.sub(r'[^0-9]', '', val)
        if len(clean) == 3: clean = "0" + clean
        if len(clean) == 4:
            st.session_state[key] = f"{clean[:2]}:{clean[2:]}"

def parse_final_time(t_str):
    try:
        return datetime.strptime(t_str, "%H:%M").time()
    except: return None

# --- 4. ユーザーインターフェース ---
with st.sidebar:
    if os.path.exists("icon.png"): st.image("icon.png", width=80)
    st.markdown("### ENTRY PANEL")
    
    f_date = st.date_input("利用日", datetime.now())
    f_name = st.text_input("氏名", placeholder="山田 太郎")
    grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
    f_grade = st.selectbox("学年", grades)
    
    col_in, col_out = st.columns(2)
    with col_in:
        # on_changeを使って、入力完了時に自動で auto_format_times を実行する
        st.text_input("入室時刻", placeholder="19:00", key="in_time", on_change=auto_format_times)
    with col_out:
        st.text_input("退室時刻", placeholder="21:30", key="out_time", on_change=auto_format_times)
    
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("記録を登録する"):
        t_start = parse_final_time(st.session_state.in_time)
        t_end = parse_final_time(st.session_state.out_time)
        
        if f_name and t_start and t_end:
            start_dt = datetime.combine(f_date, t_start)
            end_dt = datetime.combine(f_date, t_end)
            if end_dt < start_dt: end_dt += timedelta(days=1)
            duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
            
            df = load_data()
            new_row = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name, '学年': f_grade, '入室時間': t_start.strftime('%H:%M'), '退室時間': t_end.strftime('%H:%M'), '利用時間（時間）': duration}])
            df = pd.concat([df, new_row], ignore_index=True)
            save_to_gs(df)
            
            # 登録成功したら入力欄をリセット
            st.session_state.in_time = ""
            st.session_state.out_time = ""
            st.success(f"{f_name}さんの記録を保存しました")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("入力内容に誤りがあります（時刻は 1900 または 19:00 の形式）")

    st.markdown("<br><hr>", unsafe_allow_html=True)
    admin_pass = st.text_input("管理者パスワード", type="password", placeholder="Admin Only")
    if admin_pass == "admin123":
        if st.button("🚨 データをリセット"):
            save_to_gs(load_data(), "バックアップ")
            save_to_gs(pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']), "メイン")
            st.cache_data.clear()
            st.rerun()
        if st.button("⏪ バックアップから復元"):
            workbook = gc.open_by_url(SPREADSHEET_URL)
            backup_df = pd.DataFrame(workbook.worksheet("バックアップ").get_all_records())
            save_to_gs(backup_df, "メイン")
            st.cache_data.clear()
            st.rerun()
    
    # ソフトウェアっぽさを出すバージョン表記
    st.markdown("<div style='text-align: center; font-size: 0.8rem; color: #94A3B8; margin-top: 20px;'>Study Room System v2.0 Premium</div>", unsafe_allow_html=True)

# メインパネル
st.markdown("<div class='main-title'>🏆 塾生学習時間ランキング</div>", unsafe_allow_html=True)
df = load_data()

if not df.empty:
    tab1, tab2, tab3 = st.tabs(["🗓 今月の集計", "🔥 直近3ヶ月", "👑 殿堂入り（累計）"])
    
    def render_board(target_df):
        if target_df.empty:
            st.info("この期間のデータはまだありません。")
            return
        agg = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        agg = agg.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
        agg.index += 1
        
        m_cols = st.columns(3)
        medals = ["🥇 1位", "🥈 2位", "🥉 3位"]
        for i in range(min(3, len(agg))):
            with m_cols[i]:
                st.metric(label=f"{medals[i]} / {agg.iloc[i]['学年']}", value=f"{agg.iloc[i]['名前']} さん", delta=f"{agg.iloc[i]['利用時間（時間）']} 時間", delta_color="normal")
        
        st.write("")
        st.dataframe(agg, use_container_width=True, hide_index=True, column_config={
            "名前": st.column_config.TextColumn("氏名"),
            "学年": st.column_config.TextColumn("学年"),
            "利用時間（時間）": st.column_config.ProgressColumn("トータル学習時間", format="%.2f h", min_value=0, max_value=float(agg['利用時間（時間）'].max() if not agg.empty else 1))
        })

    with tab1: render_board(df[df['日付'].dt.month == datetime.now().month])
    with tab2: render_board(df[df['日付'] >= (datetime.now() - timedelta(days=90))])
    with tab3: render_board(df)

    with st.expander("📝 過去のすべての履歴を確認する"):
        st.dataframe(df.sort_values(by='日付', ascending=False), use_container_width=True, hide_index=True)
else:
    st.info("データがありません。左のパネルから最初の記録を登録してください。")
