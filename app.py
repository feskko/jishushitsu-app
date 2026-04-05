import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import re

# 日本時間の「今」を取得（海外サーバーでの時間ズレ対策）
jst_now = datetime.utcnow() + timedelta(hours=9)

# --- 1. ページ構成（スマホ向けに layout="centered" に変更） ---
st.set_page_config(page_title="TKG Study Room Analytics", page_icon="icon.png", layout="centered")

st.markdown("""
<style>
    /* ========== システムUIの完全非表示 ========== */
    #MainMenu, header, footer, [data-testid="stToolbar"] {visibility: hidden !important; display: none !important;}

    /* ========== 全体テーマ（知的で清潔感のある背景） ========== */
    .stApp {
        background-color: #F4F7FB;
        font-family: 'Helvetica Neue', Arial, 'Hiragino Kaku Gothic ProN', 'Hiragino Sans', Meiryo, sans-serif;
    }

    /* ========== スマホライクなメニュー切替（Radioをタブ風に） ========== */
    div[role="radiogroup"] {
        display: flex; justify-content: space-between; background-color: #FFFFFF;
        padding: 5px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05);
        margin-bottom: 25px; margin-top: 10px;
    }
    div[role="radiogroup"] label {
        flex: 1; text-align: center; justify-content: center;
        padding: 10px 5px !important; margin: 0 !important;
        border-radius: 8px; transition: 0.2s;
    }
    div[role="radiogroup"] label[data-checked="true"] {
        background-color: #0A2B56;
    }
    div[role="radiogroup"] label[data-checked="true"] p {
        color: #FFFFFF !important; font-weight: 800;
    }
    div[role="radiogroup"] label p {
        color: #64748B; font-weight: 700; font-size: 0.95rem;
    }

    /* ========== メインタイトル（TKGネイビー） ========== */
    .main-title {
        font-size: 1.8rem; /* スマホ向けに最適化 */
        font-weight: 900; color: #0A2B56; letter-spacing: 1px;
        margin-bottom: 25px; padding-bottom: 10px; border-bottom: 3px solid #E2E8F0;
        position: relative;
    }
    .main-title::after {
        content: ''; position: absolute; left: 0; bottom: -3px; width: 80px; height: 3px;
        background: linear-gradient(90deg, #0A2B56, #005BAB);
    }

    /* ========== 部門ごとのサブタイトル ========== */
    .section-title {
        font-size: 1.4rem; font-weight: 800; color: #0A2B56;
        margin-top: 2rem; margin-bottom: 1rem; padding-left: 10px;
        border-left: 5px solid #005BAB; display: flex; align-items: center; gap: 8px;
    }

    /* ========== スマホ向け入力フォームの洗練 ========== */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important; border-radius: 10px !important;
        border: 1px solid #CBD5E1 !important; height: 3.2rem; /* タップしやすい高さ */
        box-shadow: inset 0 1px 2px rgba(0,0,0,0.02);
    }
    div[data-baseweb="input"] input, div[data-baseweb="select"] div {
        color: #1E293B !important; font-weight: 700; font-size: 1.05rem;
    }

    /* ========== ボタンデザイン（重なり合う青のグラデーション） ========== */
    .stButton>button {
        background: linear-gradient(135deg, #0A2B56 0%, #005BAB 100%);
        color: #FFFFFF !important; font-weight: bold; font-size: 1.1rem;
        letter-spacing: 1px; border-radius: 12px; border: none; height: 3.8rem; width: 100%;
        box-shadow: 0 4px 8px -1px rgba(0, 91, 171, 0.3); transition: all 0.2s ease;
        margin-top: 10px;
    }
    .stButton>button:active {
        transform: scale(0.98); box-shadow: 0 2px 4px -1px rgba(0, 91, 171, 0.3);
    }

    /* カードデザインのスマホ最適化 */
    .rank-card {
        flex: 1; min-width: 100%; /* スマホでは縦並びになるよう強制 */
        padding: 20px; border-radius: 16px; 
        box-shadow: 0 8px 15px -3px rgba(10, 43, 86, 0.08); 
        border: 1px solid #E2E8F0; margin-bottom: 15px;
    }

    @media (min-width: 768px) {
        .rank-card { min-width: 250px; margin-bottom: 0px; } /* PCなら横並び */
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

# --- 3. セッション管理と時刻フォーマット ---
if "form_key" not in st.session_state: st.session_state.form_key = 0
if "current_menu" not in st.session_state: st.session_state.current_menu = "📝 記録する"

def auto_format_times():
    for prefix in ["in_time", "out_time"]:
        k = f"{prefix}_{st.session_state.form_key}"
        val = st.session_state.get(k, "")
        if not val or ":" in val: continue
        clean = re.sub(r'[^0-9]', '', str(val))
        if len(clean) == 3: clean = "0" + clean
        if len(clean) == 4: st.session_state[k] = f"{clean[:2]}:{clean[2:]}"

def parse_final_time(t_str):
    try: return datetime.strptime(t_str, "%H:%M").time()
    except: return None

# --- 4. メインUI構築（スマホアプリ風ナビゲーション） ---
menu = st.radio("メニュー", ["📝 記録する", "🏆 ランキング", "⚙️ 管理"], horizontal=True, label_visibility="collapsed")

# ---------------------------------------------------------
# 【モード1】📝 記録・入力画面
# ---------------------------------------------------------
if menu == "📝 記録する":
    st.markdown("<div class='main-title'>ENTRY PANEL</div>", unsafe_allow_html=True)
    
    # 💡【未来日付ブロック】
    f_date = st.date_input("利用日", jst_now.date(), max_value=jst_now.date())
    
    k_name = f"name_{st.session_state.form_key}"
    k_in = f"in_time_{st.session_state.form_key}"
    k_out = f"out_time_{st.session_state.form_key}"
    
    f_name = st.text_input("氏名", placeholder="山田太郎（スペース不要）", key=k_name)
    grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
    f_grade = st.selectbox("学年", grades)
    
    col_in, col_out = st.columns(2)
    with col_in: st.text_input("入室", placeholder="19:00", key=k_in, on_change=auto_format_times)
    with col_out: st.text_input("退室", placeholder="21:30", key=k_out, on_change=auto_format_times)
    
    val_in = st.session_state.get(k_in, "")
    val_out = st.session_state.get(k_out, "")
    disp_in = val_in if val_in else "--:--"
    disp_out = val_out if val_out else "--:--"
    
    st.markdown(f"<div style='background-color: #FFFFFF; padding: 10px; border-radius: 8px; color: #64748B; font-size: 1rem; text-align: center; margin-top: 5px; margin-bottom: 15px; font-weight: bold; border: 1px dashed #CBD5E1;'>🕒 確認： {disp_in} 〜 {disp_out}</div>", unsafe_allow_html=True)
    
    if st.button("記録を登録する", use_container_width=True):
        t_start = parse_final_time(val_in)
        t_end = parse_final_time(val_out)
        f_name_clean = f_name.replace(" ", "").replace("　", "") # 💡【表記ゆれブロック】
        
        if f_name_clean and t_start and t_end:
            start_dt = datetime.combine(f_date, t_start)
            end_dt = datetime.combine(f_date, t_end)
            if end_dt < start_dt: end_dt += timedelta(days=1)
            duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
            
            df = load_data()
            new_row = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name_clean, '学年': f_grade, '入室時間': val_in, '退室時間': val_out, '利用時間（時間）': duration}])
            df = pd.concat([df, new_row], ignore_index=True)
            save_to_gs(df)
            
            st.session_state.form_key += 1 
            st.success(f"✓ {f_name_clean}さんの記録を保存しました！")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("⚠️ 入力内容に誤りがあります（時刻は 1900 または 19:00 と入力）")

# ---------------------------------------------------------
# 【モード2】🏆 ランキング画面
# ---------------------------------------------------------
elif menu == "🏆 ランキング":
    st.markdown("<div class='main-title'>RANKING</div>", unsafe_allow_html=True)
    
    # スマホで見やすいプルダウン式の期間選択
    period_sel = st.selectbox("集計期間を選択", ["🗓️ 今月の集計", "🔥 直近3ヶ月", "👑 全期間（累計）"])
    
    df = load_data()
    
    def get_agg_data(target_df):
        if target_df.empty: return pd.DataFrame()
        agg = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        agg = agg.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
        agg['順位'] = agg['利用時間（時間）'].rank(method='min', ascending=False).astype(int)
        return agg[['順位', '名前', '学年', '利用時間（時間）']]

    def render_premium_cards(agg):
        if agg.empty: return
        html = '<div style="display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap;">'
        
        # 💡【同率3位バグ解消】 順位が3位以下の人を全員取得する
        top_rows = agg[agg['順位'] <= 3]
        
        for i, row in top_rows.iterrows():
            rank_val = row['順位']
            name = row['名前']
            grade = row['学年']
            time_val = row['利用時間（時間）']
            
            if rank_val == 1:
                rank_text, icon, border_color, bg_grad = "1st", "🥇", "#C9B037", "linear-gradient(135deg, #FFFFFF 0%, #FFFDF0 100%)"
            elif rank_val == 2:
                rank_text, icon, border_color, bg_grad = "2nd", "🥈", "#B4B4B4", "linear-gradient(135deg, #FFFFFF 0%, #F8F9FA 100%)"
            elif rank_val == 3:
                rank_text, icon, border_color, bg_grad = "3rd", "🥉", "#AD8A56", "linear-gradient(135deg, #FFFFFF 0%, #FCF9F5 100%)"
            
            html += f"<div class='rank-card' style='background: {bg_grad}; border-top: 5px solid {border_color};'>"
            html += f"<div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;'><span style='font-size: 1rem; color: #64748B; font-weight: 800; letter-spacing: 1px;'>{rank_text} PLACE</span><span style='font-size: 1.5rem;'>{icon}</span></div>"
            html += f"<div style='font-size: 0.85rem; color: #0A2B56; font-weight: bold; margin-bottom: 2px;'>{grade}</div>"
            html += f"<div class='rank-name' style='font-size: 2rem; font-weight: 900; color: #0F172A; margin-bottom: 12px;'>{name} <span style='font-size: 1rem; font-weight: 600; color: #64748B;'>さん</span></div>"
            html += f"<div style='display: inline-block; background-color: #F1F5F9; color: #0A2B56; padding: 6px 16px; border-radius: 8px; font-weight: 800; font-size: 1.2rem; border: 1px solid #E2E8F0;'>{time_val:.2f} <span style='font-size: 0.9rem;'>HOURS</span></div>"
            html += "</div>"
        html += '</div>'
        st.markdown(html, unsafe_allow_html=True)

    def render_section_ranking(full_agg, target_grades, section_title, icon):
        section_df = full_agg[full_agg['学年'].isin(target_grades)].reset_index(drop=True)
        st.markdown(f"<div class='section-title'>{icon} {section_title}</div>", unsafe_allow_html=True)
        if section_df.empty:
            st.info("集計データがありません。")
            return
        # 同率順位を振り直し（部門別）
        section_df['順位'] = section_df['利用時間（時間）'].rank(method='min', ascending=False).astype(int)
        
        render_premium_cards(section_df)
        display_df = section_df[['順位', '名前', '学年', '利用時間（時間）']]
        st.dataframe(display_df, use_container_width=True, hide_index=True, column_config={
            "順位": st.column_config.NumberColumn("順位"),
            "名前": st.column_config.TextColumn("氏名"),
            "学年": st.column_config.TextColumn("学年"),
            "利用時間（時間）": st.column_config.ProgressColumn("累計学習時間", format="%.2f h", min_value=0, max_value=float(section_df['利用時間（時間）'].max()))
        })

    if not df.empty:
        jst_today = pd.Timestamp(jst_now.date())
        df_valid_past = df[df['日付'] <= jst_today]
        
        if period_sel == "🗓️ 今月の集計":
            target_df = df_valid_past[(df_valid_past['日付'].dt.year == jst_today.year) & (df_valid_past['日付'].dt.month == jst_today.month)]
        elif period_sel == "🔥 直近3ヶ月":
            three_months_ago = jst_today - pd.DateOffset(months=3)
            target_df = df_valid_past[df_valid_past['日付'] >= three_months_ago]
        else:
            target_df = df_valid_past
            
        agg_data = get_agg_data(target_df)
        
        elem_grades = [f"小{i}" for i in range(1, 7)]
        jh_grades = [f"中{i}" for i in range(1, 4)]
        hs_grades = [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
        
        if agg_data.empty:
            st.info("この期間のデータはまだありません。")
        else:
            render_section_ranking(agg_data, elem_grades, "小学生の部", "🎒")
            render_section_ranking(agg_data, jh_grades, "中学生の部", "📓")
            render_section_ranking(agg_data, hs_grades, "高校生・その他", "🎓")
    else:
        st.info("データがありません。最初の記録を登録してください。")

# ---------------------------------------------------------
# 【モード3】⚙️ 管理画面（削除機能）
# ---------------------------------------------------------
elif menu == "⚙️ 管理":
    st.markdown("<div class='main-title'>ADMIN PANEL</div>", unsafe_allow_html=True)
    st.markdown("#### 🗑️ 直近の記録を取り消す")
    st.write("間違えて登録してしまったデータを選択して削除できます。")
    
    df_for_delete = load_data()
    if not df_for_delete.empty:
        options = [("-1", "-- 削除する記録を選択してください --")]
        recent_indices = reversed(df_for_delete.index[-30:])
        for i in recent_indices:
            row = df_for_delete.loc[i]
            d_str = row['日付'].strftime('%m/%d') if pd.notnull(row['日付']) else "不明"
            disp = f"{d_str} | {row['名前']} ({row['入室時間']}-{row['退室時間']})"
            options.append((str(i), disp))
        
        selected_del = st.selectbox("削除対象", options, format_func=lambda x: x[1], label_visibility="collapsed")
        
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚨 データを削除する", use_container_width=True):
            if selected_del[0] != "-1":
                df_for_delete = df_for_delete.drop(int(selected_del[0])).reset_index(drop=True)
                save_to_gs(df_for_delete)
                st.success("削除しました。")
                st.cache_data.clear()
                st.rerun()
            else:
                st.warning("記録を選択してください。")
    else:
        st.info("削除できるデータがありません。")

st.markdown("<div style='text-align: center; font-size: 0.75rem; color: #94A3B8; margin-top: 60px;'>Tokyo Kobetsu Shido Gakuin<br>Mobile System v4.0</div>", unsafe_allow_html=True)
