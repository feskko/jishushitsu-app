# ... existing code ...
        st.dataframe(section_df[['順位', '名前', '学年', '利用時間（時間）']], use_container_width=True, hide_index=True, column_config={
            "順位": st.column_config.NumberColumn("順位"), "名前": st.column_config.TextColumn("氏名"), "学年": st.column_config.TextColumn("学年"),
            "利用時間（時間）": st.column_config.ProgressColumn("累計学習時間", format="%.1f h", min_value=0, max_value=float(section_df['利用時間（時間）'].max() if section_df['利用時間（時間）'].max() > 0 else 1))
        })

    if not df.empty:
        jst_today = pd.Timestamp(jst_now.date())
        first_day_of_this_month = jst_today.replace(day=1)
        last_day_of_last_month = first_day_of_this_month - pd.Timedelta(days=1)
        last_month_num = last_day_of_last_month.month

        tab1, tab2, tab3, tab4 = st.tabs(["今月の集計", f"{last_month_num}月の集計", "直近3ヶ月", "累計"])
        def get_agg(target_df):
            if target_df.empty: return pd.DataFrame()
            return target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index().sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)

        df_vp = df[df['日付'] <= jst_today]
        
        # 今月のデータ
        df_this_month = df_vp[(df_vp['日付'].dt.year == jst_today.year) & (df_vp['日付'].dt.month == jst_today.month)]
        
        # 前月のデータ
        first_day_of_last_month = last_day_of_last_month.replace(day=1)
        df_last_month = df_vp[(df_vp['日付'] >= first_day_of_last_month) & (df_vp['日付'] <= last_day_of_last_month)]
        
        # 直近3ヶ月のデータ
        df_3months = df_vp[df_vp['日付'] >= (jst_today - pd.DateOffset(months=3))]
        
        for tab, agg_data in zip([tab1, tab2, tab3, tab4], [get_agg(df_this_month), get_agg(df_last_month), get_agg(df_3months), get_agg(df_vp)]):
            with tab:
# ... existing code ...
