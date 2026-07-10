# ... existing code ...
elif menu == "分析":
    st.markdown("<div class='main-title'>ANALYTICS DASHBOARD</div>", unsafe_allow_html=True)
    df_ana = load_data()
    jst_today = pd.Timestamp(jst_now.date())

    if not df_ana.empty:
        this_month_start = jst_today.replace(day=1)
        last_month_end = this_month_start - pd.Timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        prev_month_end = last_month_start - pd.Timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)

        # 1. 先月の確定実績 (前々月との比較)
        st.markdown(f"<div class='section-title'>🏆 {last_month_start.month}月の確定実績（{prev_month_start.month}月との比較）</div>", unsafe_allow_html=True)
        
        df_last_full = df_ana[(df_ana['日付'] >= last_month_start) & (df_ana['日付'] <= last_month_end)]
        df_prev_full = df_ana[(df_ana['日付'] >= prev_month_start) & (df_ana['日付'] <= prev_month_end)]
        
        h_lf = df_last_full['利用時間（時間）'].sum()
        h_pf = df_prev_full['利用時間（時間）'].sum()
        d_h_f = h_lf - h_pf
        p_h_f = (d_h_f / h_pf * 100) if h_pf > 0 else (100 if h_lf > 0 else 0)
        
        u_lf = df_last_full['名前'].nunique()
        u_pf = df_prev_full['名前'].nunique()
        d_u_f = u_lf - u_pf
        p_u_f = (d_u_f / u_pf * 100) if u_pf > 0 else (100 if u_lf > 0 else 0)
        
        c1, c2, c3 = st.columns(3)
        c1.metric(f"{last_month_start.month}月の総学習時間", f"{h_lf:.1f} 時間", f"{p_h_f:+.1f}% ({d_h_f:+.1f} 時間)")
        c2.metric(f"{last_month_start.month}月の利用者数", f"{u_lf} 名", f"{p_u_f:+.1f}% ({d_u_f:+d} 名)")
        if u_lf > 0:
            a_lf = h_lf / u_lf
            a_pf = h_pf / u_pf if u_pf > 0 else 0
            d_a_f = a_lf - a_pf
            p_a_f = (d_a_f / a_pf * 100) if a_pf > 0 else (100 if a_lf > 0 else 0)
            c3.metric("1人あたり平均学習時間", f"{a_lf:.1f} 時間", f"{p_a_f:+.1f}% ({d_a_f:+.1f} 時間)")
            
        # 2. 今月の進捗 (前月同日時点との比較)
        last_month_today = jst_today - pd.DateOffset(months=1)
        st.markdown(f"<div class='section-title'>📈 {this_month_start.month}月の進捗速報（前月同日時点との比較）</div>", unsafe_allow_html=True)
        
        df_this = df_ana[(df_ana['日付'] >= this_month_start) & (df_ana['日付'] <= jst_today)]
        df_last_prog = df_ana[(df_ana['日付'] >= last_month_start) & (df_ana['日付'] <= last_month_today)]
        
        hours_this = df_this['利用時間（時間）'].sum()
        hours_last = df_last_prog['利用時間（時間）'].sum()
        diff_hours = hours_this - hours_last
        pct_hours = (diff_hours / hours_last * 100) if hours_last > 0 else (100 if hours_this > 0 else 0)
        
        users_this = df_this['名前'].nunique()
        users_last = df_last_prog['名前'].nunique()
        diff_users = users_this - users_last
        pct_users = (diff_users / users_last * 100) if users_last > 0 else (100 if users_this > 0 else 0)
        
        col_met1, col_met2, col_met3 = st.columns(3)
        col_met1.metric(f"今月({this_month_start.month}月)の総学習時間", f"{hours_this:.1f} 時間", f"{pct_hours:+.1f}% ({diff_hours:+.1f} 時間)")
        col_met2.metric(f"今月({this_month_start.month}月)の利用者数", f"{users_this} 名", f"{pct_users:+.1f}% ({diff_users:+d} 名)")
        if users_this > 0:
            avg_this = hours_this / users_this
            avg_last = hours_last / users_last if users_last > 0 else 0
            diff_avg = avg_this - avg_last
            pct_avg = (diff_avg / avg_last * 100) if avg_last > 0 else (100 if avg_this > 0 else 0)
            col_met3.metric("1人あたり平均学習時間", f"{avg_this:.1f} 時間", f"{pct_avg:+.1f}% ({diff_avg:+.1f} 時間)")
            
        # --- 翌月の利用予測 ---
        today_d = jst_today.day
        next_month_first = (this_month_start + pd.DateOffset(months=1))
        days_in_month = (next_month_first - pd.Timedelta(days=1)).day
        
        proj_hours_this_month = hours_this / today_d * days_in_month if today_d > 0 else 0
        
        growth_rate_h = pct_hours / 100.0 if pct_hours != 100 else 0
        next_month_h = proj_hours_this_month * (1 + max(min(growth_rate_h, 0.15), -0.15))
        next_month_u = users_this * (1 + max(min((pct_users / 100.0), 0.1), -0.1))
        
        st.markdown(f"""
        <div style='background-color: #FFFFFF; border-left: 6px solid #F59E0B; padding: 20px; border-radius: 12px; margin-top: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);'>
            <div style='font-weight: 900; color: #0F172A; margin-bottom: 8px; font-size: 1.2rem;'>着地予測</div>
            <div style='color: #475569; font-size: 1.05rem;'>
                現在のペースを考慮すると、今月末には <b style='color: #B45309; font-size: 1.3rem;'>約 {proj_hours_this_month:.0f} 時間</b> の利用に到達する見込みです。<br>来月は <b style='color: #B45309; font-size: 1.3rem;'>約 {next_month_h:.0f} 時間</b> の利用と、<b style='color: #B45309; font-size: 1.3rem;'>約 {int(next_month_u)} 名</b> の生徒の来室が見込まれます。
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("データが蓄積されると前月比の利用率が表示されます。")
        
    st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["混雑状況", "生徒個別", "来週の予測"])
