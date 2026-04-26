import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import base64
import streamlit.components.v1 as components

jst_now = datetime.utcnow() + timedelta(hours=9)

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
    .main-title { font-weight: 900; color: #0A2B56; letter-spacing: 2px; margin-bottom: 25px; padding-bottom: 10px; border-bottom: 3px solid #E2E8F0; position: relative; }
    .main-title::after { content: ''; position: absolute; left: 0; bottom: -3px; width: 100px; height: 3px; background: linear-gradient(90deg, #0A2B56, #005BAB); }
    .section-title { font-weight: 800; color: #0A2B56; margin-top: 2rem; margin-bottom: 1rem; padding-left: 10px; border-left: 5px solid #005BAB; display: flex; align-items: center; gap: 8px; }
    
    div[role="radiogroup"] { display: flex; background-color: #FFFFFF; padding: 5px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); margin-bottom: 25px; margin-top: 10px; }
    div[role="radiogroup"] label { flex: 1; text-align: center; justify-content: center; padding: 10px 5px !important; margin: 0 !important; border-radius: 8px; transition: 0.2s; cursor: pointer; }
    div[role="radiogroup"] label[data-checked="true"] { background-color: #0A2B56; }
    div[role="radiogroup"] label[data-checked="true"] p { color: #FFFFFF !important; font-weight: 800; }
    div[role="radiogroup"] label p { color: #64748B; font-weight: 700; font-size: 0.85rem; }

    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div { background-color: #FFFFFF !important; border-radius: 8px !important; border: 1px solid #CBD5E1 !important; box-shadow: inset 0 1px 2px rgba(0,0,0,0.02); }
    div[data-baseweb="input"] input, div[data-baseweb="select"] div { color: #1E293B !important; font-weight: 700; font-size: 1.05rem; }
    
    button[kind="secondary"] { background-color: #FFFFFF !important; color: #0A2B56 !important; border: 2px solid #E2E8F0 !important; font-weight: 700 !important; border-radius: 6px !important; transition: 0.2s !important; min-height: 3.2rem !important; padding: 2px !important; }
    button[kind="secondary"]:hover { border-color: #005BAB !important; background-color: #F8FAFC !important; }
    
    button[kind="primary"] { background: linear-gradient(135deg, #0A2B56 0%, #005BAB 100%) !important; color: #FFFFFF !important; border: none !important; font-weight: 800 !important; border-radius: 6px !important; box-shadow: 0 4px 6px -1px rgba(0, 91, 171, 0.3) !important; min-height: 3.2rem !important; padding: 2px !important; transition: all 0.2s ease; }
    button[kind="primary"]:active { transform: translateY(2px); }
    button p { font-size: 1rem !important; margin: 0 !important; font-weight: bold; }

    @media (min-width: 768px) { .main-title { font-size: 2.4rem; } .section-title { font-size: 1.6rem; } div[role="radiogroup"] { max-width: 600px; } .rank-card { flex: 1; min-width: 30%; padding: 25px; border-radius: 16px; border: 1px solid #E2E8F0; } div[data-baseweb="input"] > div, div[data-baseweb="select"] > div { height: 3.2rem; } }
    @media (max-width: 767px) { 
        .main-title { font-size: 1.8rem; } .section-title { font-size: 1.3rem; } 
        div[role="radiogroup"] { width: 100%; flex-wrap: wrap; } div[role="radiogroup"] label { min-width: 45%; } 
        .rank-card { width: 100%; padding: 20px; border-radius: 12px; margin-bottom: 15px; border: 1px solid #E2E8F0; } 
        div[data-baseweb="input"] > div, div[data-baseweb="select"] > div { height: 3.5rem; } 
        div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"]:nth-child(4)) { flex-wrap: wrap !important; }
        div[data-testid="stHorizontalBlock"]:has(> div[data-testid="column"]:nth-child(4)) > div[data-testid="column"] { flex: 1 1 23% !important; min-width: 23% !important; padding: 0 3px !important; margin-bottom: 6px !important; }
    }
</style>
""", unsafe_allow_html=True)

APP_PASSWORD = "tkg-1985" 

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h3 style='text-align: center; color: #0A2B56; margin-top: 15vh; margin-bottom: 20px; font-weight: 900; font-size: 2rem;'>Study Room System</h3>", unsafe_allow_html=True)
    pwd = st.text_input("パスワード", type="password", placeholder="****")
    if st.button("ロック解除", type="primary", use_container_width=True):
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
if "start_idx" not in st.session_state: st.session_state.start_idx = None
if "end_idx" not in st.session_state: st.session_state.end_idx = None

def handle_time_click(idx):
    if st.session_state.start_idx is None:
        st.session_state.start_idx = idx
        st.session_state.end_idx = None
    elif st.session_state.end_idx is None:
        if idx > st.session_state.start_idx: st.session_state.end_idx = idx
        elif idx < st.session_state.start_idx: st.session_state.start_idx = idx 
        else: st.session_state.start_idx = None 
    else:
        st.session_state.start_idx = idx
        st.session_state.end_idx = None

def reset_time_selection():
    st.session_state.start_idx = None
    st.session_state.end_idx = None

TIME_OPTIONS = [f"{i}コマ" for i in range(1, 9)]
GRADES = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]

menu = st.radio("メニュー", ["一括入力", "1件ずつ", "ランキング", "分析", "管理"], horizontal=True, label_visibility="collapsed")

if menu == "一括入力":
    st.markdown("<div class='main-title'>BATCH ENTRY PANEL</div>", unsafe_allow_html=True)
    f_date_batch = st.date_input("利用日 (全員共通)", jst_now.date(), max_value=jst_now.date())
    
    if "batch_data" not in st.session_state:
        st.session_state.batch_data = [{"氏名": "", "学年": "高1", "入室": "5コマ", "退室": "6コマ"} for _ in range(25)]
        
    df_empty = pd.DataFrame(st.session_state.batch_data)
    
    edited_df = st.data_editor(
        df_empty,
        column_config={
            "氏名": st.column_config.TextColumn("氏名", width="medium"),
            "学年": st.column_config.SelectboxColumn("学年", options=GRADES, width="small"),
            "入室": st.column_config.SelectboxColumn("入室", options=TIME_OPTIONS, width="medium"),
            "退室": st.column_config.SelectboxColumn("退室", options=TIME_OPTIONS, width="medium"),
        },
        num_rows="dynamic",
        use_container_width=True,
        height=500
    )
    
    if st.button("表のデータをすべて保存する", type="primary", use_container_width=True):
        valid_rows = edited_df[edited_df["氏名"].str.strip() != ""]
        if valid_rows.empty:
            st.error("氏名が入力されている行がありません。")
        else:
            new_records = []
            error_msgs = []
            
            for idx, row in valid_rows.iterrows():
                name = row["氏名"].replace(" ", "").replace("　", "")
                in_str = row["入室"]
                out_str = row["退室"]
                
                in_idx = TIME_OPTIONS.index(in_str)
                out_idx = TIME_OPTIONS.index(out_str)
                
                if out_idx >= in_idx:
                    duration = float((out_idx - in_idx + 1) * 1.5)
                    new_records.append({
                        '日付': pd.to_datetime(f_date_batch),
                        '名前': name,
                        '学年': row["学年"],
                        '入室時間': in_str,
                        '退室時間': out_str,
                        '利用時間（時間）': duration
                    })
                else:
                    error_msgs.append(f"{name}さん (退室コマが入室コマより前になっています)")
            
            if error_msgs:
                for err in error_msgs:
                    st.error(f"エラー: {err}")
            
            if new_records:
                df = load_data()
                df = pd.concat([df, pd.DataFrame(new_records)], ignore_index=True)
                save_to_gs(df)
                st.session_state.batch_data = [{"氏名": "", "学年": "高1", "入室": "5コマ", "退室": "6コマ"} for _ in range(25)]
                st.success(f"{len(new_records)}名分の記録を一括保存しました。")
                st.cache_data.clear()
                st.rerun()

elif menu == "1件ずつ":
    st.markdown("<div class='main-title'>SINGLE ENTRY PANEL</div>", unsafe_allow_html=True)
    col1, col2 = st.columns([1, 1])
    with col1: f_date = st.date_input("利用日", jst_now.date(), max_value=jst_now.date())
    with col2: f_grade = st.selectbox("学年", GRADES)
        
    k_name = f"name_{st.session_state.form_key}"
    f_name = st.text_input("氏名", key=k_name)

    val_in_disp = TIME_OPTIONS[st.session_state.start_idx] if st.session_state.start_idx is not None else "--"
    val_out_disp = TIME_OPTIONS[st.session_state.end_idx] if st.session_state.end_idx is not None else "--"

    st.markdown(f"<div style='background-color: #FFFFFF; padding: 15px; border-radius: 8px; color: #0A2B56; font-size: 1.5rem; text-align: center; margin-bottom: 10px; font-weight: 900; border: 2px dashed #005BAB;'>🕒 {val_in_disp} 〜 {val_out_disp}</div>", unsafe_allow_html=True)

    if st.button("コマ選択をリセット", use_container_width=True, type="secondary"):
        reset_time_selection()
        st.rerun()

    st.markdown("<p style='color: #0A2B56; font-weight: 900; margin-top: 25px; margin-bottom: 10px; font-size: 1.1rem;'>利用コマ</p>", unsafe_allow_html=True)
    for row in range(0, len(TIME_OPTIONS), 4):
        cols = st.columns(4)
        for col_idx in range(4):
            if row + col_idx < len(TIME_OPTIONS):
                idx = row + col_idx
                t = TIME_OPTIONS[idx]
                is_start = (idx == st.session_state.start_idx)
                is_end = (idx == st.session_state.end_idx)
                in_range = False
                if st.session_state.start_idx is not None and st.session_state.end_idx is not None:
                    if st.session_state.start_idx <= idx <= st.session_state.end_idx: in_range = True
                b_type = "primary" if (is_start or is_end or in_range) else "secondary"
                cols[col_idx].button(t, key=f"timebtn_{idx}_{st.session_state.form_key}", on_click=handle_time_click, args=(idx,), type=b_type, use_container_width=True)

    st.markdown("<hr style='margin-top:20px; margin-bottom:20px;'>", unsafe_allow_html=True)

    if st.button("1件記録する", use_container_width=True, type="primary"):
        f_name_clean = f_name.replace(" ", "").replace("　", "")
        if not f_name_clean: st.error("氏名を入力してください。")
        elif st.session_state.start_idx is None or st.session_state.end_idx is None: st.error("入室コマと退室コマの両方を選択してください。")
        else:
            in_idx = st.session_state.start_idx
            out_idx = st.session_state.end_idx
            if out_idx < in_idx: st.error("退室コマは入室コマ以降を選択してください")
            else:
                duration = float((out_idx - in_idx + 1) * 1.5)
                df = load_data()
                new_row = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name_clean, '学年': f_grade, '入室時間': TIME_OPTIONS[in_idx], '退室時間': TIME_OPTIONS[out_idx], '利用時間（時間）': duration}])
                df = pd.concat([df, new_row], ignore_index=True)
                save_to_gs(df)
                st.session_state.form_key += 1 
                reset_time_selection()
                st.success(f"{f_name_clean}さんの記録を保存しました。")
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
            rank_val, name, grade, time_val = row['順位'], row['名前'], row['学年'], row['利用時間（時間）']
            if rank_val == 1: rank_text, icon, border_color, bg_grad = "1st", "🥇", "#C9B037", "linear-gradient(135deg, #FFFFFF 0%, #FFFDF0 100%)"
            elif rank_val == 2: rank_text, icon, border_color, bg_grad = "2nd", "🥈", "#B4B4B4", "linear-gradient(135deg, #FFFFFF 0%, #F8F9FA 100%)"
            elif rank_val == 3: rank_text, icon, border_color, bg_grad = "3rd", "🥉", "#AD8A56", "linear-gradient(135deg, #FFFFFF 0%, #FCF9F5 100%)"
            else: rank_text, icon, border_color, bg_grad = f"{rank_val}th", "🏅", "#64748B", "linear-gradient(135deg, #FFFFFF 0%, #F8FAFC 100%)"
            html += f"<div class='rank-card' style='background: {bg_grad}; border-top: 5px solid {border_color};'><div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;'><span style='font-size: 1rem; color: #64748B; font-weight: 800; letter-spacing: 1px;'>{rank_text} PLACE</span><span style='font-size: 1.5rem;'>{icon}</span></div><div style='font-size: 0.9rem; color: #0A2B56; font-weight: bold; margin-bottom: 5px;'>{grade}</div><div style='font-size: 2.2rem; font-weight: 900; color: #0F172A; margin-bottom: 15px;'>{name} <span style='font-size: 1rem; font-weight: 600; color: #64748B;'>さん</span></div><div style='display: inline-block; background-color: #F1F5F9; color: #0A2B56; padding: 6px 16px; border-radius: 8px; font-weight: 800; font-size: 1.2rem; border: 1px solid #E2E8F0;'>{time_val:.1f} <span style='font-size: 0.9rem;'>HOURS</span></div></div>"
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
                    render_section_ranking(agg_data, [f"高{i}" for i in range(1, 4)] + ["既卒/その他"], "高校生・その他")
    else: st.info("データがありません。最初の記録を登録してください。")

elif menu == "分析":
    st.markdown("<div class='main-title'>ANALYTICS DASHBOARD</div>", unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["混雑状況ヒートマップ", "生徒個別ダッシュボード"])
    df_ana = load_data()

    with tab1:
        st.markdown("<div class='section-title'>曜日・コマ別の混雑状況</div>", unsafe_allow_html=True)
        if not df_ana.empty:
            weekdays = ["月", "火", "水", "木", "金", "土", "日"]
            heatmap_data = pd.DataFrame(0, index=weekdays, columns=TIME_OPTIONS)

            for _, row in df_ana.iterrows():
                if pd.isnull(row['日付']) or not row['入室時間'] or not row['退室時間']: continue
                try:
                    dt = pd.to_datetime(row['日付'])
                    wd = weekdays[dt.weekday()]
                    in_idx = TIME_OPTIONS.index(row['入室時間'])
                    out_idx = TIME_OPTIONS.index(row['退室時間'])
                    for i in range(in_idx, out_idx + 1):
                        heatmap_data.loc[wd, TIME_OPTIONS[i]] += 1
                except: continue

            max_val = heatmap_data.values.max()
            max_val = max(max_val, 1)

            html = "<div style='overflow-x: auto;'><table style='width:100%; border-collapse: collapse; margin-bottom: 20px; min-width: 600px;'>"
            html += "<tr><th style='border: 1px solid #CBD5E1; padding: 8px; background-color: #F8FAFC; color: #0A2B56; position: sticky; left: 0; z-index: 1;'>曜日</th>"
            for tb in TIME_OPTIONS: html += f"<th style='border: 1px solid #CBD5E1; padding: 8px; background-color: #F8FAFC; color: #0A2B56; font-size:0.8rem;'>{tb}</th>"
            html += "</tr>"

            for wd in weekdays:
                html += f"<tr><th style='border: 1px solid #CBD5E1; padding: 8px; background-color: #F8FAFC; color: #0A2B56; position: sticky; left: 0; z-index: 1;'>{wd}</th>"
                for tb in TIME_OPTIONS:
                    val = heatmap_data.loc[wd, tb]
                    ratio = val / max_val if max_val > 0 else 0
                    bg_color = f"rgba(0, 91, 171, {ratio * 0.8})" if val > 0 else "transparent"
                    font_color = "white" if ratio > 0.5 else "#1E293B"
                    html += f"<td style='border: 1px solid #CBD5E1; padding: 8px; text-align: center; font-weight: bold; background-color: {bg_color}; color: {font_color};'>{val}</td>"
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

                    this_month = pd.Timestamp(jst_now.date()).replace(day=1)
                    sm_df = student_df[student_df['日付'] >= this_month]
                    total_h = sm_df['利用時間（時間）'].sum()

                    st.markdown(f"<div style='background: linear-gradient(135deg, #0A2B56 0%, #005BAB 100%); padding: 20px; border-radius: 12px; color: white; margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0, 91, 171, 0.3);'><h4 style='margin:0; font-size: 1.1rem; font-weight: normal;'>{selected_name} さんの今月の学習時間</h4><div style='font-size: 2.8rem; font-weight: 900; margin-top: 5px;'>{total_h:.1f} <span style='font-size: 1.2rem; font-weight: bold;'>時間</span></div></div>", unsafe_allow_html=True)

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

elif menu == "管理":
    st.markdown("<div class='main-title'>ADMIN PANEL</div>", unsafe_allow_html=True)
    st.markdown("#### 直近の記録の変更・削除")
    df_manage = load_data()
    if not df_manage.empty:
        options = [("-1", "-- 編集・削除する記録を選択してください --")]
        for i in reversed(df_manage.index[-30:]):
            row = df_manage.loc[i]
            d_str = row['日付'].strftime('%m/%d') if pd.notnull(row['日付']) else "不明"
            options.append((str(i), f"{d_str} | {row['名前']} ({row['入室時間']} - {row['退室時間']})"))
        
        selected_mng = st.selectbox("対象記録", options, format_func=lambda x: x[1], label_visibility="collapsed")
        
        if selected_mng[0] != "-1":
            target_idx = int(selected_mng[0])
            target_row = df_manage.loc[target_idx]
            st.markdown("<div style='margin-top: 20px; padding: 20px; border-radius: 12px; background-color: #FFFFFF; border: 1px solid #CBD5E1;'>", unsafe_allow_html=True)
            st.markdown("##### 記録の編集", unsafe_allow_html=True)
            
            default_date = target_row['日付'].date() if pd.notnull(target_row['日付']) else jst_now.date()
            edit_date = st.date_input("利用日", default_date)
            
            col_n, col_g = st.columns(2)
            with col_n: edit_name = st.text_input("氏名", value=str(target_row['名前']))
            with col_g:
                current_grade = str(target_row['学年'])
                g_index = GRADES.index(current_grade) if current_grade in GRADES else 0
                edit_grade = st.selectbox("学年", GRADES, index=g_index)
                
            col_in, col_out = st.columns(2)
            in_val = target_row['入室時間']
            out_val = target_row['退室時間']
            in_idx = TIME_OPTIONS.index(in_val) if in_val in TIME_OPTIONS else 0
            out_idx = TIME_OPTIONS.index(out_val) if out_val in TIME_OPTIONS else 0
            
            with col_in: edit_in = st.selectbox("入室コマ", TIME_OPTIONS, index=in_idx)
            with col_out: edit_out = st.selectbox("退室コマ", TIME_OPTIONS, index=out_idx)
            
            st.markdown("<br>", unsafe_allow_html=True)
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("この内容で上書き保存", use_container_width=True, type="primary"):
                    edit_name_clean = edit_name.replace(" ", "").replace("　", "")
                    in_id = TIME_OPTIONS.index(edit_in)
                    out_id = TIME_OPTIONS.index(edit_out)
                    
                    if edit_name_clean:
                        if out_id < in_id: st.error("退室コマは入室コマ以降を選択してください")
                        else:
                            duration = float((out_id - in_id + 1) * 1.5)
                            df_manage.at[target_idx, '日付'] = pd.to_datetime(edit_date)
                            df_manage.at[target_idx, '名前'] = edit_name_clean
                            df_manage.at[target_idx, '学年'] = edit_grade
                            df_manage.at[target_idx, '入室時間'] = edit_in
                            df_manage.at[target_idx, '退室時間'] = edit_out
                            df_manage.at[target_idx, '利用時間（時間）'] = duration
                            save_to_gs(df_manage)
                            st.success("記録を更新しました。")
                            st.cache_data.clear()
                            st.rerun()
                    else: st.error("氏名を入力してください。")
            with col_btn2:
                if st.button("この記録を完全に削除", use_container_width=True):
                    df_manage = df_manage.drop(target_idx).reset_index(drop=True)
                    save_to_gs(df_manage)
                    st.success("削除しました。")
                    st.cache_data.clear()
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
    else: st.info("変更・削除できるデータがありません。")
# ==========================================
# 🔒 セキュリティロック画面
# ==========================================
APP_PASSWORD = "tkg-1985" 

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h3 style='text-align: center; color: #0A2B56; margin-top: 15vh; margin-bottom: 20px; font-weight: 900; font-size: 2rem;'>🔒 Study Room System</h3>", unsafe_allow_html=True)
    
    pwd = st.text_input("パスワード（合言葉）", type="password", placeholder="****")
    if st.button("🔓 ロック解除", type="primary", use_container_width=True):
        if pwd == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("⚠️ パスワードが違います")
    st.stop()

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

# 変数準備
if "form_key" not in st.session_state: st.session_state.form_key = 0
if "start_idx" not in st.session_state: st.session_state.start_idx = None
if "end_idx" not in st.session_state: st.session_state.end_idx = None

def parse_final_time(t_str):
    try: return datetime.strptime(t_str, "%H:%M").time()
    except: return None

TIME_OPTIONS = [
    "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
    "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30",
    "15:50 (5コマ開始)", "16:00", "16:30", "17:00", "17:10 (5コマ終了)",
    "17:20 (6コマ開始)", "17:30", "18:00", "18:30", "18:40 (6コマ終了)",
    "18:50 (7コマ開始)", "19:00", "19:30", "20:00", "20:10 (7コマ終了)",
    "20:20 (8コマ開始)", "20:30", "21:00", "21:30", "21:40 (8コマ終了)", "22:00"
]
GRADES = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]

# --- 4. メインUI構築 ---
menu = st.radio("メニュー", ["⚡ 一括入力", "📝 1件ずつ", "🏆 ランキング", "📊 分析", "⚙️ 管理"], horizontal=True, label_visibility="collapsed")

# ---------------------------------------------------------
# 【モード0】⚡ エクセル風 一括入力（NEW）
# ---------------------------------------------------------
if menu == "⚡ 一括入力":
    st.markdown("<div class='main-title'>BATCH ENTRY PANEL</div>", unsafe_allow_html=True)
    st.markdown("<p style='color:#475569; font-size:0.95rem;'>紙のリストを見ながら、Excelのように一気に入力できます。（PC推奨）<br>氏名を入力し、Tabキーで隣のセルに移動できます。</p>", unsafe_allow_html=True)
    
    f_date_batch = st.date_input("利用日 (全員共通)", jst_now.date(), max_value=jst_now.date())
    
    # 25行分の空データを作成
    if "batch_data" not in st.session_state:
        st.session_state.batch_data = [{"氏名": "", "学年": "高1", "入室": "17:20 (6コマ開始)", "退室": "21:40 (8コマ終了)"} for _ in range(25)]
        
    df_empty = pd.DataFrame(st.session_state.batch_data)
    
    # データエディタの表示
    edited_df = st.data_editor(
        df_empty,
        column_config={
            "氏名": st.column_config.TextColumn("氏名 (フルネームで入力)", width="medium"),
            "学年": st.column_config.SelectboxColumn("学年", options=GRADES, width="small"),
            "入室": st.column_config.SelectboxColumn("入室", options=TIME_OPTIONS, width="medium"),
            "退室": st.column_config.SelectboxColumn("退室", options=TIME_OPTIONS, width="medium"),
        },
        num_rows="dynamic",
        use_container_width=True,
        height=500
    )
    
    if st.button("💾 表のデータをすべて一括保存する", type="primary", use_container_width=True):
        # 氏名が空欄の行を除外
        valid_rows = edited_df[edited_df["氏名"].str.strip() != ""]
        
        if valid_rows.empty:
            st.error("⚠️ 氏名が入力されている行がありません。")
        else:
            new_records = []
            error_msgs = []
            
            for idx, row in valid_rows.iterrows():
                name = row["氏名"].replace(" ", "").replace("　", "")
                in_str = row["入室"][:5]
                out_str = row["退室"][:5]
                t_in = parse_final_time(in_str)
                t_out = parse_final_time(out_str)
                
                if t_in and t_out and t_out > t_in:
                    duration = round((datetime.combine(f_date_batch, t_out) - datetime.combine(f_date_batch, t_in)).total_seconds() / 3600, 2)
                    new_records.append({
                        '日付': pd.to_datetime(f_date_batch),
                        '名前': name,
                        '学年': row["学年"],
                        '入室時間': in_str,
                        '退室時間': out_str,
                        '利用時間（時間）': duration
                    })
                else:
                    error_msgs.append(f"{name}さん (入室と退室の時間が不正です)")
            
            if error_msgs:
                for err in error_msgs:
                    st.error(f"⚠️ エラー: {err}")
            
            if new_records:
                df = load_data()
                df = pd.concat([df, pd.DataFrame(new_records)], ignore_index=True)
                save_to_gs(df)
                # 入力表をリセット
                st.session_state.batch_data = [{"氏名": "", "学年": "高1", "入室": "17:20 (6コマ開始)", "退室": "21:40 (8コマ終了)"} for _ in range(25)]
                st.success(f"✅ {len(new_records)}名分の記録を一括保存しました！")
                st.cache_data.clear()
                st.rerun()


# ---------------------------------------------------------
# 【モード1】📝 1件ずつ記録・入力画面（従来のマトリクス）
# ---------------------------------------------------------
elif menu == "📝 1件ずつ":
    def handle_time_click(idx):
        if st.session_state.start_idx is None:
            st.session_state.start_idx = idx
            st.session_state.end_idx = None
        elif st.session_state.end_idx is None:
            if idx > st.session_state.start_idx: st.session_state.end_idx = idx
            elif idx < st.session_state.start_idx: st.session_state.start_idx = idx 
            else: st.session_state.start_idx = None 
        else:
            st.session_state.start_idx = idx
            st.session_state.end_idx = None

    def reset_time_selection():
        st.session_state.start_idx = None
        st.session_state.end_idx = None

    st.markdown("<div class='main-title'>SINGLE ENTRY PANEL</div>", unsafe_allow_html=True)
    col1, col2 = st.columns([1, 1])
    with col1: f_date = st.date_input("利用日", jst_now.date(), max_value=jst_now.date())
    with col2: f_grade = st.selectbox("学年", GRADES)
        
    k_name = f"name_{st.session_state.form_key}"
    f_name = st.text_input("氏名", placeholder="山田太郎", key=k_name)

    val_in_disp = TIME_OPTIONS[st.session_state.start_idx][:5] if st.session_state.start_idx is not None else "--:--"
    val_out_disp = TIME_OPTIONS[st.session_state.end_idx][:5] if st.session_state.end_idx is not None else "--:--"

    st.markdown(f"<div style='background-color: #FFFFFF; padding: 15px; border-radius: 8px; color: #0A2B56; font-size: 1.5rem; text-align: center; margin-bottom: 10px; font-weight: 900; border: 2px dashed #005BAB;'>🕒 {val_in_disp} 〜 {val_out_disp}</div>", unsafe_allow_html=True)

    if st.button("🔄 時間の選択をリセット", use_container_width=True, type="secondary"):
        reset_time_selection()
        st.rerun()

    am_options = [(i, t) for i, t in enumerate(TIME_OPTIONS) if int(t[:2]) < 13]
    pm_options = [(i, t) for i, t in enumerate(TIME_OPTIONS) if int(t[:2]) >= 13]

    def render_time_grid(title, options_list):
        st.markdown(f"<p style='color: #0A2B56; font-weight: 900; margin-top: 25px; margin-bottom: 10px; font-size: 1.1rem;'>{title}</p>", unsafe_allow_html=True)
        for row in range(0, len(options_list), 4):
            cols = st.columns(4)
            for col_idx in range(4):
                if row + col_idx < len(options_list):
                    idx, t = options_list[row + col_idx]
                    short_label = t.replace("コマ開始", "開").replace("コマ終了", "終").replace("(", "[").replace(")", "]")
                    is_start = (idx == st.session_state.start_idx)
                    is_end = (idx == st.session_state.end_idx)
                    in_range = False
                    if st.session_state.start_idx is not None and st.session_state.end_idx is not None:
                        if st.session_state.start_idx <= idx <= st.session_state.end_idx: in_range = True
                    b_type = "primary" if (is_start or is_end or in_range) else "secondary"
                    cols[col_idx].button(short_label, key=f"timebtn_{idx}_{st.session_state.form_key}", on_click=handle_time_click, args=(idx,), type=b_type, use_container_width=True)

    render_time_grid("☀️ 午前（9:00 〜 12:30）", am_options)
    render_time_grid("🌙 午後（13:00 〜 22:00）", pm_options)

    st.markdown("<hr style='margin-top:20px; margin-bottom:20px;'>", unsafe_allow_html=True)

    if st.button("💾 1件記録する", use_container_width=True, type="primary"):
        f_name_clean = f_name.replace(" ", "").replace("　", "")
        if not f_name_clean: st.error("⚠️ 氏名を入力してください。")
        elif st.session_state.start_idx is None or st.session_state.end_idx is None: st.error("⚠️ 入室時間と退室時間の「両方」をセルから選択してください。")
        else:
            t_start_str = TIME_OPTIONS[st.session_state.start_idx][:5]
            t_end_str = TIME_OPTIONS[st.session_state.end_idx][:5]
            t_start = parse_final_time(t_start_str)
            t_end = parse_final_time(t_end_str)
            start_dt = datetime.combine(f_date, t_start)
            end_dt = datetime.combine(f_date, t_end)
            
            if end_dt <= start_dt: st.error("⚠️ 退室時刻は入室時刻より後の時間を選択してください")
            else:
                duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
                df = load_data()
                new_row = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name_clean, '学年': f_grade, '入室時間': t_start_str, '退室時間': t_end_str, '利用時間（時間）': duration}])
                df = pd.concat([df, new_row], ignore_index=True)
                save_to_gs(df)
                st.session_state.form_key += 1 
                reset_time_selection()
                st.success(f"✓ {f_name_clean}さんの記録を保存しました。")
                st.cache_data.clear()
                st.rerun()

elif menu == "🏆 ランキング":
    st.markdown("<div class='main-title'>STUDY HOURS RANKING</div>", unsafe_allow_html=True)
    df = load_data()

    def render_premium_cards(agg):
        if agg.empty: return
        html = '<div style="display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap;">'
        top_rows = agg[agg['順位'] <= 3]
        for i, row in top_rows.iterrows():
            rank_val, name, grade, time_val = row['順位'], row['名前'], row['学年'], row['利用時間（時間）']
            if rank_val == 1: rank_text, icon, border_color, bg_grad = "1st", "🥇", "#C9B037", "linear-gradient(135deg, #FFFFFF 0%, #FFFDF0 100%)"
            elif rank_val == 2: rank_text, icon, border_color, bg_grad = "2nd", "🥈", "#B4B4B4", "linear-gradient(135deg, #FFFFFF 0%, #F8F9FA 100%)"
            elif rank_val == 3: rank_text, icon, border_color, bg_grad = "3rd", "🥉", "#AD8A56", "linear-gradient(135deg, #FFFFFF 0%, #FCF9F5 100%)"
            else: rank_text, icon, border_color, bg_grad = f"{rank_val}th", "🏅", "#64748B", "linear-gradient(135deg, #FFFFFF 0%, #F8FAFC 100%)"
            html += f"<div class='rank-card' style='background: {bg_grad}; border-top: 5px solid {border_color};'><div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;'><span style='font-size: 1rem; color: #64748B; font-weight: 800; letter-spacing: 1px;'>{rank_text} PLACE</span><span style='font-size: 1.5rem;'>{icon}</span></div><div style='font-size: 0.9rem; color: #0A2B56; font-weight: bold; margin-bottom: 5px;'>{grade}</div><div style='font-size: 2.2rem; font-weight: 900; color: #0F172A; margin-bottom: 15px;'>{name} <span style='font-size: 1rem; font-weight: 600; color: #64748B;'>さん</span></div><div style='display: inline-block; background-color: #F1F5F9; color: #0A2B56; padding: 6px 16px; border-radius: 8px; font-weight: 800; font-size: 1.2rem; border: 1px solid #E2E8F0;'>{time_val:.2f} <span style='font-size: 0.9rem;'>HOURS</span></div></div>"
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
            "利用時間（時間）": st.column_config.ProgressColumn("累計学習時間", format="%.2f h", min_value=0, max_value=float(section_df['利用時間（時間）'].max() if section_df['利用時間（時間）'].max() > 0 else 1))
        })

    if not df.empty:
        tab1, tab2, tab3 = st.tabs(["🗓 今月の集計", "🔥 直近3ヶ月", "👑 累計"])
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
                    render_section_ranking(agg_data, [f"高{i}" for i in range(1, 4)] + ["既卒/その他"], "高校生・その他")
    else: st.info("データがありません。最初の記録を登録してください。")

elif menu == "📊 分析":
    st.markdown("<div class='main-title'>ANALYTICS DASHBOARD</div>", unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["🔥 混雑状況ヒートマップ", "👤 生徒個別ダッシュボード"])
    
    df_ana = load_data()

    with tab1:
        st.markdown("<div class='section-title'>曜日・時間帯別の混雑状況</div>", unsafe_allow_html=True)
        st.markdown("<p style='color:#475569; font-size:0.95rem;'>過去の入退室記録をもとに、どの曜日のどの時間帯が混みやすいかを可視化しています。色が濃いほど利用者が多い時間帯です。</p>", unsafe_allow_html=True)
        
        if not df_ana.empty:
            time_bins = ["15:00", "15:30", "16:00", "16:30", "17:00", "17:30", "18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30"]
            weekdays = ["月", "火", "水", "木", "金", "土", "日"]
            heatmap_data = pd.DataFrame(0, index=weekdays, columns=time_bins)

            for _, row in df_ana.iterrows():
                if pd.isnull(row['日付']) or not row['入室時間'] or not row['退室時間']: continue
                try:
                    dt = pd.to_datetime(row['日付'])
                    wd = weekdays[dt.weekday()]
                    in_t = row['入室時間'][:5]
                    out_t = row['退室時間'][:5]
                    for tb in time_bins:
                        if in_t <= tb < out_t:
                            heatmap_data.loc[wd, tb] += 1
                except: continue

            max_val = heatmap_data.values.max()
            max_val = max(max_val, 1)

            html = "<div style='overflow-x: auto;'><table style='width:100%; border-collapse: collapse; margin-bottom: 20px; min-width: 800px;'>"
            html += "<tr><th style='border: 1px solid #CBD5E1; padding: 8px; background-color: #F8FAFC; color: #0A2B56; position: sticky; left: 0; z-index: 1;'>曜日</th>"
            for tb in time_bins:
                html += f"<th style='border: 1px solid #CBD5E1; padding: 8px; background-color: #F8FAFC; color: #0A2B56; font-size:0.8rem;'>{tb}</th>"
            html += "</tr>"

            for wd in weekdays:
                html += f"<tr><th style='border: 1px solid #CBD5E1; padding: 8px; background-color: #F8FAFC; color: #0A2B56; position: sticky; left: 0; z-index: 1;'>{wd}</th>"
                for tb in time_bins:
                    val = heatmap_data.loc[wd, tb]
                    ratio = val / max_val if max_val > 0 else 0
                    bg_color = f"rgba(0, 91, 171, {ratio * 0.8})" if val > 0 else "transparent"
                    font_color = "white" if ratio > 0.5 else "#1E293B"
                    html += f"<td style='border: 1px solid #CBD5E1; padding: 8px; text-align: center; font-weight: bold; background-color: {bg_color}; color: {font_color};'>{val}</td>"
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

                    this_month = pd.Timestamp(jst_now.date()).replace(day=1)
                    sm_df = student_df[student_df['日付'] >= this_month]
                    total_h = sm_df['利用時間（時間）'].sum()

                    st.markdown(f"""
                    <div style='background: linear-gradient(135deg, #0A2B56 0%, #005BAB 100%); padding: 20px; border-radius: 12px; color: white; margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0, 91, 171, 0.3);'>
                        <h4 style='margin:0; font-size: 1.1rem; font-weight: normal;'>{selected_name} さんの今月の学習時間</h4>
                        <div style='font-size: 2.8rem; font-weight: 900; margin-top: 5px;'>{total_h:.2f} <span style='font-size: 1.2rem; font-weight: bold;'>時間</span></div>
                    </div>
                    """, unsafe_allow_html=True)

                    st.markdown("##### 📈 日別の学習推移（今月）")
                    if not sm_df.empty:
                        daily_sum = sm_df.groupby('日付')['利用時間（時間）'].sum().reset_index()
                        daily_sum['日付ラベル'] = daily_sum['日付'].dt.strftime('%m/%d')
                        chart_data = daily_sum.set_index('日付ラベル')['利用時間（時間）']
                        st.bar_chart(chart_data)
                    else:
                        st.info("今月の記録はまだありません。")

                    st.markdown("##### 📝 直近の記録一覧")
                    display_history = student_df.sort_values('日付', ascending=False).head(10)
                    display_history['日付'] = display_history['日付'].dt.strftime('%Y/%m/%d')
                    st.dataframe(display_history[['日付', '入室時間', '退室時間', '利用時間（時間）']], use_container_width=True, hide_index=True)
            else:
                st.info("検索できる生徒データがありません。")
        else:
            st.info("集計するデータがありません。")

elif menu == "⚙️ 管理":
    def get_time_index(t_str, default_idx=0):
        for i, opt in enumerate(TIME_OPTIONS):
            if opt.startswith(str(t_str)): return i
        return default_idx
        
    st.markdown("<div class='main-title'>ADMIN PANEL</div>", unsafe_allow_html=True)
    st.markdown("#### ✏️ 直近の記録の変更・削除")
    
    df_manage = load_data()
    if not df_manage.empty:
        options = [("-1", "-- 編集・削除する記録を選択してください --")]
        for i in reversed(df_manage.index[-30:]):
            row = df_manage.loc[i]
            d_str = row['日付'].strftime('%m/%d') if pd.notnull(row['日付']) else "不明"
            options.append((str(i), f"{d_str} | {row['名前']} ({row['入室時間']} - {row['退室時間']})"))
        
        selected_mng = st.selectbox("対象記録", options, format_func=lambda x: x[1], label_visibility="collapsed")
        
        if selected_mng[0] != "-1":
            target_idx = int(selected_mng[0])
            target_row = df_manage.loc[target_idx]
            
            st.markdown("<div style='margin-top: 20px; padding: 20px; border-radius: 12px; background-color: #FFFFFF; border: 1px solid #CBD5E1;'>", unsafe_allow_html=True)
            st.markdown("##### 📝 記録の編集", unsafe_allow_html=True)
            
            default_date = target_row['日付'].date() if pd.notnull(target_row['日付']) else jst_now.date()
            edit_date = st.date_input("利用日", default_date)
            
            col_n, col_g = st.columns(2)
            with col_n: edit_name = st.text_input("氏名", value=str(target_row['名前']))
            with col_g:
                current_grade = str(target_row['学年'])
                g_index = GRADES.index(current_grade) if current_grade in GRADES else 0
                edit_grade = st.selectbox("学年", GRADES, index=g_index)
                
            col_in, col_out = st.columns(2)
            in_idx = get_time_index(target_row['入室時間'], 0)
            out_idx = get_time_index(target_row['退室時間'], 0)
            
            with col_in: edit_in = st.selectbox("入室時間", TIME_OPTIONS, index=in_idx)
            with col_out: edit_out = st.selectbox("退室時間", TIME_OPTIONS, index=out_idx)
            
            st.markdown("<br>", unsafe_allow_html=True)
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("🔄 この内容で上書き保存", use_container_width=True, type="primary"):
                    t_start_str = edit_in[:5]
                    t_end_str = edit_out[:5]
                    t_start = parse_final_time(t_start_str)
                    t_end = parse_final_time(t_end_str)
                    edit_name_clean = edit_name.replace(" ", "").replace("　", "")
                    
                    if edit_name_clean and t_start and t_end:
                        start_dt = datetime.combine(edit_date, t_start)
                        end_dt = datetime.combine(edit_date, t_end)
                        if end_dt <= start_dt: st.error("⚠️ 退室時刻は入室時刻より後の時間を選択してください")
                        else:
                            duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
                            df_manage.at[target_idx, '日付'] = pd.to_datetime(edit_date)
                            df_manage.at[target_idx, '名前'] = edit_name_clean
                            df_manage.at[target_idx, '学年'] = edit_grade
                            df_manage.at[target_idx, '入室時間'] = t_start_str
                            df_manage.at[target_idx, '退室時間'] = t_end_str
                            df_manage.at[target_idx, '利用時間（時間）'] = duration
                            save_to_gs(df_manage)
                            st.success("✅ 記録を更新しました。")
                            st.cache_data.clear()
                            st.rerun()
                    else: st.error("入力内容に誤りがあります。")
            with col_btn2:
                if st.button("🚨 この記録を完全に削除", use_container_width=True):
                    df_manage = df_manage.drop(target_idx).reset_index(drop=True)
                    save_to_gs(df_manage)
                    st.success("🗑️ 削除しました。")
                    st.cache_data.clear()
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
    else: st.info("変更・削除できるデータがありません。")

st.markdown("<div style='text-align: center; font-size: 0.75rem; color: #94A3B8; margin-top: 60px;'>Tokyo Kobetsu Shido Gakuin<br>Batch Entry System v11.0</div>", unsafe_allow_html=True)
