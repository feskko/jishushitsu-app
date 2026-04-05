import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import json
import os

# --- 認証設定 ---
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

# Streamlit CloudのSecretsを優先的に読み込む
if "GCP_SERVICE_ACCOUNT" in st.secrets:
    secret_data = st.secrets["GCP_SERVICE_ACCOUNT"]
    if isinstance(secret_data, str):
        service_account_info = json.loads(secret_data)
    else:
        service_account_info = dict(secret_data)
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
elif os.path.exists('secret.json'):
    credentials = Credentials.from_service_account_file('secret.json', scopes=scopes)
else:
    st.error("認証情報（Secrets）が設定されていません。")
    st.stop()

gc = gspread.authorize(credentials)

# ★自分のスプレッドシートURLに書き換えてください
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1C9xD5xD3ZvGEV6IPuD2_dj9f_oqAIz_v923PMRabBu4/edit" 

try:
    workbook = gc.open_by_url(SPREADSHEET_URL)
    worksheet_main = workbook.worksheet("メイン")
    worksheet_backup = workbook.worksheet("バックアップ")
except Exception as e:
    st.error(f"接続エラー: {e}")
    st.stop()

# --- 関数定義 ---
def load_data(sheet):
    data = sheet.get_all_records()
    if data:
        df = pd.DataFrame(data)
        if '日付' in df.columns:
            df['日付'] = pd.to_datetime(df['日付'])
        return df
    return pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）'])

def save_data(sheet, df):
    sheet.clear()
    if not df.empty:
        save_df = df.copy()
        if '日付' in save_df.columns:
            save_df['日付'] = pd.to_datetime(save_df['日付']).dt.strftime('%Y-%m-%d')
        save_df = save_df.fillna("")
        data_to_upload = [save_df.columns.tolist()] + save_df.values.tolist()
        sheet.update(range_name="A1", values=data_to_upload)
    else:
        headers = [['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']]
        sheet.update(range_name="A1", values=headers)

# --- アプリ本体 ---
st.title("自習室 利用時間記録＆ランキング")
df = load_data(worksheet_main)

# 記録入力
st.header("📝 記録の入力")
with st.form("record_form"):
    col1, col2 = st.columns(2)
    with col1:
        date = st.date_input("日付", datetime.now())
        name = st.text_input("名前")
        # 「しんうら」を削除したリスト
        grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
        grade = st.selectbox("学年", grades)
    with col2:
        start_time = st.time_input("入室時間", datetime.strptime("17:00", "%H:%M"))
        end_time = st.time_input("退室時間", datetime.strptime("21:00", "%H:%M"))
    
    if st.form_submit_button("記録を追加"):
        if name:
            start_dt = datetime.combine(date, start_time)
            end_dt = datetime.combine(date, end_time)
            if end_dt < start_dt:
                end_dt = datetime.combine(date + pd.Timedelta(days=1), end_time)
            duration = round((end_dt - start_dt).total_seconds() / 3600, 2)

            new_record = pd.DataFrame([{
                '日付': pd.to_datetime(date), '名前': name, '学年': grade,
                '入室時間': start_time.strftime('%H:%M'), '退室時間': end_time.strftime('%H:%M'),
                '利用時間（時間）': duration
            }])
            df = pd.concat([df, new_record], ignore_index=True)
            save_data(worksheet_main, df)
            st.success(f"{name}さんの記録を追加しました！")
            st.rerun()
        else:
            st.error("名前を入力してください。")

# ランキング
st.header("🏆 ランキング")
if not df.empty:
    def show_rank(target_df):
        if not target_df.empty:
            ranking = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
            ranking = ranking.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
            ranking.index += 1
            st.dataframe(ranking, use_container_width=True)
        else:
            st.write("データがありません。")

    t1, t2 = st.tabs(["今月", "全期間"])
    with t1:
        df['年月'] = df['日付'].dt.strftime('%Y-%m')
        this_month = datetime.now().strftime('%Y-%m')
        show_rank(df[df['年月'] == this_month])
    with t2:
        show_rank(df)
else:
    st.write("まだ記録がありません。")

# 管理
st.sidebar.header("管理メニュー")
if st.sidebar.button("データをリセット"):
    # 現在のデータをバックアップへ移動
    save_data(worksheet_backup, df)
    # メインを空にする
    save_data(worksheet_main, pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']))
    st.sidebar.success("バックアップを作成し、リセットしました。")
    st.rerun()

if st.sidebar.button("データを復元"):
    # バックアップから読み込んでメインに上書き
    backup_df = load_data(worksheet_backup)
    if not backup_df.empty:
        save_data(worksheet_main, backup_df)
        st.sidebar.success("バックアップから復元しました。")
        st.rerun()
    else:
        st.sidebar.error("バックアップデータがありません。")
# 記録入力
st.header("📝 記録の入力")
with st.form("record_form"):
    col1, col2 = st.columns(2)
    with col1:
        date = st.date_input("日付", datetime.now())
        name = st.text_input("名前")
        grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["しんうら", "既卒/その他"]
        grade = st.selectbox("学年", grades)
    with col2:
        start_time = st.time_input("入室時間", datetime.strptime("17:00", "%H:%M"))
        end_time = st.time_input("退室時間", datetime.strptime("21:00", "%H:%M"))
    
    if st.form_submit_button("記録を追加"):
        if name:
            start_dt = datetime.combine(date, start_time)
            end_dt = datetime.combine(date, end_time)
            if end_dt < start_dt:
                end_dt = datetime.combine(date + pd.Timedelta(days=1), end_time)
            duration = round((end_dt - start_dt).total_seconds() / 3600, 2)

            new_record = pd.DataFrame([{'日付': pd.to_datetime(date), '名前': name, '学年': grade, '入室時間': start_time.strftime('%H:%M'), '退室時間': end_time.strftime('%H:%M'), '利用時間（時間）': duration}])
            df = pd.concat([df, new_record], ignore_index=True)
            save_data(worksheet_main, df)
            st.success(f"{name}さんの記録を追加しました！")
            st.rerun()
        else:
            st.error("名前を入れてください")

# ランキング表示
st.header("🏆 ランキング")
if not df.empty:
    def show_rank(target_df):
        if not target_df.empty:
            ranking = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
            ranking = ranking.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
            ranking.index += 1
            st.dataframe(ranking, use_container_width=True)
        else:
            st.write("データがありません")

    t1, t2 = st.tabs(["今月", "全期間"])
    with t1:
        this_month = datetime.now().strftime('%Y-%m')
        show_rank(df[df['日付'].dt.strftime('%Y-%m') == this_month] if not df.empty else df)
    with t2:
        show_rank(df)
else:
    st.info("まだ記録がありません。")

# 管理
st.sidebar.header("管理メニュー")
if st.sidebar.button("データをリセット"):
    save_data(worksheet_backup, df)
    save_data(worksheet_main, pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']))
    st.rerun()
