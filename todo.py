import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta, time
import requests

# --- CONFIGURATION ---
NTFY_TOPIC = "youndesign_todolist_123"

def send_notif(title, message, priority="default"):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=message.encode('utf-8'),
            headers={"Title": title.encode('utf-8'), "Priority": priority})
    except: pass

def check_password():
    if "password_correct" not in st.session_state:
        st.title("🔒 Accès Privé")
        pwd = st.text_input("Mot de passe", type="password")
        if st.button("Connexion"):
            if pwd == st.secrets["password"]:
                st.session_state["password_correct"] = True
                st.rerun()
            else: st.error("Incorrect")
        return False
    return True

if check_password():
    conn = st.connection("gsheets", type=GSheetsConnection)

    def load_data():
        try:
            df = conn.read(ttl=0)
            df = df.dropna(subset=['gros_titre', 'titre'], how='all')
            
            # Normalisation des types pour éviter les crashs
            for col in ['status', 'date_archive', 'gros_titre', 'titre', 'contenu', 'echeance', 'type']:
                if col not in df.columns: df[col] = ""
                df[col] = df[col].astype(str).replace('nan', '')
            
            df.loc[df['status'] == '', 'status'] = 'En cours'
            df['dt_obj'] = pd.to_datetime(df['echeance'], errors='coerce')
            df['date_archive_dt'] = pd.to_datetime(df['date_archive'], errors='coerce')
        except Exception as e:
            st.error(f"Erreur chargement : {e}")
            df = pd.DataFrame(columns=["id", "gros_titre", "titre", "contenu", "echeance", "type", "status", "date_archive"])
        return df

    def save_data(df_to_save):
        cols_to_drop = ['dt_obj', 'date_archive_dt']
        final_df = df_to_save.drop(columns=[c for c in cols_to_drop if c in df_to_save.columns])
        conn.update(data=final_df)
        st.cache_data.clear()

    def cleanup_old_archives(df):
        limit_date = pd.Timestamp(datetime.now().date() - timedelta(days=30))
        initial_len = len(df)
        mask = (df['status'] != 'Terminé') | (df['date_archive_dt'] >= limit_date) | (df['date_archive_dt'].isna())
        df = df[mask]
        if len(df) < initial_len:
            save_data(df)
        return df

    # --- INTERFACE ---
    st.set_page_config(page_title="YounDesign PKM", layout="wide")
    if 'edit_item_idx' not in st.session_state: st.session_state['edit_item_idx'] = None
    
    df = load_data()
    df = cleanup_old_archives(df)
    now = pd.Timestamp(datetime.now())
    today = now.date()

    def item_card(idx, row, is_overdue=False, key_suffix=""):
        color = "#FF4B4B" if is_overdue else "#31333F"
        with st.container(border=True):
            col1, col2, col3, col4 = st.columns([0.1, 0.5, 0.3, 0.1])
            with col1:
                if row['status'] != 'Terminé':
                    if st.checkbox("Fait", key=f"chk_{idx}_{key_suffix}", label_visibility="collapsed"):
                        df.at[idx, 'status'] = 'Terminé'
                        df.at[idx, 'date_archive'] = datetime.now().strftime('%Y-%m-%d')
                        save_data(df)
                        st.rerun()
                else:
                    # BOUTON RESTAURER (Ressortir de l'archive)
                    if st.button("🔄", key=f"res_{idx}_{key_suffix}", help="Restaurer la tâche"):
                        df.at[idx, 'status'] = 'En cours'
                        df.at[idx, 'date_archive'] = ""
                        save_data(df)
                        st.rerun()
            with col2:
                st.markdown(f"**{row['gros_titre']}** > {row['titre']}")
                st.write(row['contenu'])
            with col3:
                if row['type'] == 'Task' and not pd.isna(row['dt_obj']):
                    st.markdown(f"<span style='color:{color}'>📅 {row['dt_obj'].strftime('%d/%m/%Y %H:%M')}</span>", unsafe_allow_html=True)
                    if is_overdue and row['status'] != 'Terminé':
                        new_d = st.date_input("Reporter :", value=datetime.now().date(), key=f"re_d_{idx}_{key_suffix}")
                        if st.button("OK", key=f"re_b_{idx}_{key_suffix}"):
                            df.at[idx, 'echeance'] = datetime.combine(new_d, time(8, 0)).strftime('%Y-%m-%d %H:%M:%S')
                            save_data(df)
                            st.rerun()
                else: st.caption("📝 Note")
            with col4:
                if st.button("✏️", key=f"ed_{idx}_{key_suffix}"):
                    st.session_state['edit_item_idx'] = idx
                    st.rerun()

    # --- FILTRAGE ---
    active_tasks = df[df['status'] == 'En cours']
    
    # --- ONGLETS ---
    t_day, t_week, t_month, t_theme, t_notes, t_archive, t_saisie = st.tabs([
        "☀️ Jour", "📅 Semaine", "📊 Mois", "📂 Thèmes", "📝 Notes", "🗄️ Archive", "🖊️ Saisie"
    ])

    with t_day:
        overdue = active_tasks[(active_tasks['type'] == 'Task') & (active_tasks['dt_obj'] < now)]
        if not overdue.empty:
            st.error("🚨 Retards")
            for idx, r in overdue.iterrows(): item_card(idx, r, is_overdue=True, key_suffix="ov")
        due_today = active_tasks[(active_tasks['type'] == 'Task') & (active_tasks['dt_obj'].dt.date == today) & (active_tasks['dt_obj'] >= now)]
        if not due_today.empty:
            st.subheader("📅 Aujourd'hui")
            for idx, r in due_today.iterrows(): item_card(idx, r, key_suffix="tod")
        if overdue.empty and due_today.empty: st.info("Rien d'urgent aujourd'hui.")

    with t_week:
        week_limit = today + timedelta(days=7)
        due_week = active_tasks[(active_tasks['type'] == 'Task') & (active_tasks['dt_obj'].dt.date > today) & (active_tasks['dt_obj'].dt.date <= week_limit)]
        for idx, r in due_week.iterrows(): item_card(idx, r, key_suffix="wk")

    with t_month:
        month_limit = today + timedelta(days=30)
        due_month = active_tasks[(active_tasks['type'] == 'Task') & (active_tasks['dt_obj'].dt.date > today) & (active_tasks['dt_obj'].dt.date <= month_limit)]
        for idx, r in due_month.iterrows(): item_card(idx, r, key_suffix="mo")

    with t_theme:
        if not active_tasks.empty:
            for gt in sorted(active_tasks['gros_titre'].unique()):
                with st.expander(f"📁 {gt}"):
                    for idx, r in active_tasks[active_tasks['gros_titre'] == gt].iterrows(): item_card(idx, r, key_suffix="th")

    with t_notes:
        for idx, r in active_tasks[active_tasks['type'] == 'Note'].iterrows(): item_card(idx, r, key_suffix="nt")

    with t_archive:
        st.header("Archives (Restaurables via 🔄)")
        archives = df[df['status'] == 'Terminé']
        if not archives.empty:
            for idx, r in archives.sort_values('date_archive', ascending=False).iterrows(): item_card(idx, r, key_suffix="arc")

    with t_saisie:
        idx_e = st.session_state['edit_item_idx']
        # FIX : Utilisation d'une condition robuste pour éviter le ValueError
        edit_r = df.loc[idx_e] if idx_e is not None else None
        
        with st.form("form_v12", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                l_gt = sorted(df['gros_titre'].unique().tolist()) if not df.empty else []
                # FIX : Condition sécurisée pour index
                idx_gt = l_gt.index(edit_r['gros_titre'])+1 if (edit_r is not None and edit_r['gros_titre'] in l_gt) else 0
                f_gt = st.selectbox("Dossier", [""] + l_gt, index=idx_gt)
                f_gt_n = st.text_input("OU Nouveau")
                
                l_t = sorted(df['titre'].unique().tolist()) if not df.empty else []
                idx_t = l_t.index(edit_r['titre'])+1 if (edit_r is not None and edit_r['titre'] in l_t) else 0
                f_t = st.selectbox("Titre", [""] + l_t, index=idx_t)
                f_t_n = st.text_input("OU Nouveau Titre")
            with c2:
                f_c = st.text_area("Contenu", value=edit_r['contenu'] if edit_r is not None else "")
                f_d = st.date_input("Date", value=edit_r['dt_obj'].date() if (edit_r is not None and not pd.isna(edit_r['dt_obj'])) else None)
                f_h = st.time_input("Heure", value=edit_r['dt_obj'].time() if (edit_r is not None and not pd.isna(edit_r['dt_obj'])) else time(8,0))
            
            if st.form_submit_button("💾 Enregistrer"):
                final_gt = f_gt_n if f_gt_n else f_gt
                final_t = f_t_n if f_t_n else f_t
                date_s = datetime.combine(f_d, f_h).strftime('%Y-%m-%d %H:%M:%S') if f_date else ""
                if idx_e is not None:
                    df.at[idx_e, 'gros_titre'], df.at[idx_e, 'titre'], df.at[idx_e, 'contenu'] = final_gt, final_t, f_c
                    df.at[idx_e, 'echeance'], df.at[idx_e, 'type'] = date_s, ("Task" if f_d else "Note")
                else:
                    new_id = int(df['id'].max()) + 1 if not df.empty else 1
                    new_r = {"id": new_id, "gros_titre": final_gt, "titre": final_t, "contenu": f_c, "echeance": date_s, "type": ("Task" if f_d else "Note"), "status": "En cours", "date_archive": ""}
                    df = pd.concat([df, pd.DataFrame([new_r])], ignore_index=True)
                save_data(df)
                st.session_state['edit_item_idx'] = None
                st.rerun()
