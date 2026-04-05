import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import json
import os


# --- ページ設定（ブラウザのタブ名や幅の設定） ---
# 変更後（画像ファイル名に！）
st.set_page_config(page_title="自習室ランキング", page_icon="icon.png", layout="wide")

# --- カスタムCSS（デザインの微調整） ---
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stMetric {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    div[data-testid="stExpander"] {
        border: none;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        background-color: white;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 認証設定 ---
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

if "GCP_SERVICE_ACCOUNT" in st.secrets:
    secret_data = st.secrets["GCP_SERVICE_ACCOUNT"]
    service_account_info = json.loads(secret_data) if isinstance(secret_data, str) else dict(secret_data)
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
elif os.path.exists('secret.json'):
    credentials = Credentials.from_service_account_file('secret.json', scopes=scopes)
else:
    st.error("認証情報が見つかりません。")
    st.stop()

gc = gspread.authorize(credentials)

# ★自分のスプレッドシートURL
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1C9xD5xD3ZvGEV6IPuD2_dj9f_oqAIz_v923PMRabBu4/edit"

@st.cache_data(ttl=60) # 1分間はデータをキャッシュして高速化
def load_data_from_gs():
    try:
        workbook = gc.open_by_url(SPREADSHEET_URL)
        worksheet = workbook.worksheet("メイン")
        data = worksheet.get_all_records()
        if not data:
            return pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）'])
        df = pd.DataFrame(data)
        df['日付'] = pd.to_datetime(df['日付'])
        return df
    except Exception as e:
        st.error(f"接続エラー: {e}")
        return pd.DataFrame()

def save_to_gs(df, sheet_name="メイン"):
    workbook = gc.open_by_url(SPREADSHEET_URL)
    worksheet = workbook.worksheet(sheet_name)
    worksheet.clear()
    if not df.empty:
        save_df = df.copy()
        # ↓ ここを「絶対に日付として扱う」ように修正しました
        save_df['日付'] = pd.to_datetime(save_df['日付']).dt.strftime('%Y-%m-%d')
        save_df = save_df.fillna("")
        data_to_upload = [save_df.columns.tolist()] + save_df.values.tolist()
        worksheet.update(range_name="A1", values=data_to_upload)
    else:
        worksheet.update(range_name="A1", values=[['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']])="A1", values=[['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']])

# --- アプリメイン表示 ---
st.title("🥇 自習室 利用時間ランキング")
df = load_data_from_gs()

# サイドバー：入力フォーム
with st.sidebar:
    st.header("📋 新規記録")
    with st.form("record_form", clear_on_submit=True):
        f_date = st.date_input("日付", datetime.now())
        f_name = st.text_input("名前")
        grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
        f_grade = st.selectbox("学年", grades)
        col_t1, col_t2 = st.columns(2)
        f_start = col_t1.time_input("入室", datetime.strptime("17:00", "%H:%M"))
        f_end = col_t2.time_input("退室", datetime.strptime("21:00", "%H:%M"))
        
        if st.form_submit_button("記録を保存"):
            if f_name:
                start_dt = datetime.combine(f_date, f_start)
                end_dt = datetime.combine(f_date, f_end)
                if end_dt < start_dt: end_dt += timedelta(days=1)
                duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
                
                new_data = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name, '学年': f_grade, '入室時間': f_start.strftime('%H:%M'), '退室時間': f_end.strftime('%H:%M'), '利用時間（時間）': duration}])
                df = pd.concat([df, new_data], ignore_index=True)
                save_to_gs(df)
                st.success(f"{f_name}さんの記録を保存しました")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("名前を入力してください")

    st.divider()
    st.header("⚙️ 管理画面")
    if st.button("データをリセット（バックアップ作成）"):
        save_to_gs(df, "バックアップ")
        save_to_gs(pd.DataFrame(columns=df.columns), "メイン")
        st.cache_data.clear()
        st.rerun()
    if st.button("バックアップから復元"):
        workbook = gc.open_by_url(SPREADSHEET_URL)
        backup_df = pd.DataFrame(workbook.worksheet("バックアップ").get_all_records())
        save_to_gs(backup_df, "メイン")
        st.cache_data.clear()
        st.rerun()

# メインコンテンツ
if not df.empty:
    tabs = st.tabs(["🗓 今月の集計", "期間：直近3ヶ月", "🏆 全期間ランキング"])
    
    # ランキング表示関数
    def render_ranking(target_df):
        if target_df.empty:
            st.info("対象期間のデータがありません")
            return
        
        agg = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        agg = agg.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
        agg.index += 1
        
        # トップ3のメダル表示
        cols = st.columns(3)
        medals = ["🥇 1位", "🥈 2位", "🥉 3位"]
        for i in range(min(3, len(agg))):
            with cols[i]:
                st.metric(label=f"{medals[i]}：{agg.iloc[i]['名前']}さん", value=f"{agg.iloc[i]['利用時間（時間）']}時間", help=f"学年: {agg.iloc[i]['学年']}")
        
        st.write("---")
        st.dataframe(agg, use_container_width=True)

    with tabs[0]: # 今月
        this_month_df = df[df['日付'].dt.month == datetime.now().month]
        render_ranking(this_month_df)
        
    with tabs[1]: # 直近3ヶ月
        three_months_ago = datetime.now() - timedelta(days=90)
        recent_df = df[df['日付'] >= three_months_ago]
        render_ranking(recent_df)
        
    with tabs[2]: # 全期間
        render_ranking(df)

    with st.expander("📝 全ての利用履歴を表示"):
        st.table(df.sort_values(by='日付', ascending=False))
else:
    st.info("データがまだ登録されていません。サイドバーから入力を始めてください。")
