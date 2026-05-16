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
            # On lit tout, sans cache pour voir les modifs immédiates
            df = conn.read(ttl=0)
            # Nettoyage : on enlève les lignes totalement vides
            df = df.dropna(how='all')
            # Conversion des dates
            df['dt_obj'] = pd.to_datetime(df['echeance'], errors='coerce')
            # Conversion date archivage
            if 'date_archive' in df.columns:
                df['date_archive_dt'] = pd.to_datetime(df['date_archive'], errors='coerce').dt.date
            else:
                df['date_archive'] = ""
                df['date_archive_dt'] = None
        except:
            df = pd.DataFrame(columns=["id", "gros_titre", "titre", "contenu", "echeance", "type", "status", "date_archive"])
        return df

    def save_data(df_to_save):
        # On nettoie les colonnes techniques avant l'envoi
        cols_to_drop = ['dt_obj', 'date_archive_dt']
        final_df = df_to_save.drop(columns=[c for c in cols_to_drop if c in df_to_save.columns])
        conn.update(data=final_df)
        st.cache_data.clear()

    # --- NETTOYAGE ARCHIVES (> 30 jours) ---
    def cleanup_old_archives(df):
        limit_date = datetime.now().date() - timedelta(days=30)
        # On garde les lignes qui ne sont pas des archives OU dont la date d'archive est récente
        initial_count = len(df)
        df = df[ (df['status'] != 'Terminé') | (df['date_archive_dt'] >= limit_date) | (df['date_archive_dt'].isna()) ]
        if len(df) < initial_count:
            save_data(df)
        return df

    st.set_page_config(page_title="YounDesign PKM", layout="wide")
    if 'edit_item_idx' not in st.session_state: st.session_state['edit_item_idx'] = None
    
    df = load_data()
    df = cleanup_old_archives(df)
    now = datetime.now()

    def item_card(idx, row, is_overdue=False, key_suffix=""):
        color = "#FF4B4B" if is_overdue else "#31333F"
        with st.container(border=True):
            col1, col2, col3, col4 = st.columns([0.1, 0.5, 0.3, 0.1])
            with col1:
                # Si c'est déjà archivé, on ne montre pas la checkbox
                if row['status'] != 'Terminé':
                    if st.checkbox("Fait", key=f"chk_{idx}_{key_suffix}", label_visibility="collapsed"):
                        df.at[idx, 'status'] = 'Terminé'
                        df.at[idx, 'date_archive'] = str(datetime.now().date())
                        save_data(df)
                        st.rerun()
                else: st.write("📁")
            with col2:
                st.markdown(f"**{row['gros_titre']}** > {row['titre']}")
                st.write(row['contenu'])
            with col3:
                if row['type'] == 'Task' and not pd.isna(row['dt_obj']):
                    st.markdown(f"<span style='color:{color}'>📅 {row['dt_obj'].strftime('%d/%m/%Y %H:%M')}</span>", unsafe_allow_html=True)
                    if is_overdue and row['status'] != 'Terminé':
                        new_d = st.date_input("Reporter :", value=now.date(), key=f"res_{idx}")
                        if st.button("OK", key=f"bres_{idx}"):
                            df.at[idx, 'echeance'] = datetime.combine(new_d, time(8, 0)).strftime('%Y-%m-%d %H:%M:%S')
                            save_data(df)
                            st.rerun()
            with col4:
                if st.button("✏️", key=f"ed_{idx}_{key_suffix}"):
                    st.session_state['edit_item_idx'] = idx
                    st.rerun()

    # --- ONGLETS ---
    tabs = st.tabs(["☀️ Journée", "📅 Semaine", "📂 Thématique", "📝 Notes", "🖊️ Saisie", "🗄️ Archive"])
    
    # Filtrage
    active = df[df['status'] != 'Terminé'] if not df.empty else pd.DataFrame()
    archives = df[df['status'] == 'Terminé'] if not df.empty else pd.DataFrame()

    with tabs[0]: # JOURNÉE
        if not active.empty:
            overdue = active[(active['type'] == 'Task') & (active['dt_obj'] < now)]
            if not overdue.empty:
                st.subheader("🚨 Retards")
                for idx, r in overdue.iterrows(): item_card(idx, r, is_overdue=True, key_suffix="ov")
            
            due_today = active[(active['type'] == 'Task') & (active['dt_obj'].dt.date == now.date()) & (active['dt_obj'] >= now)]
            st.subheader("📅 Aujourd'hui")
            for idx, r in due_today.iterrows(): item_card(idx, r, key_suffix="tod")
        else: st.info("Aucune tâche active.")

    with tabs[2]: # THÉMATIQUE
        if not active.empty:
            for gt in sorted(active['gros_titre'].unique()):
                with st.expander(f"📁 {gt}"):
                    for idx, r in active[active['gros_titre'] == gt].iterrows(): item_card(idx, r, key_suffix="th")

    with tabs[5]: # ARCHIVE
        st.header("Archives (30 derniers jours)")
        if not archives.empty:
            for idx, r in archives.sort_values('date_archive', ascending=False).iterrows():
                item_card(idx, r, key_suffix="arc")
        else: st.info("L'archive est vide.")

    with tabs[4]: # SAISIE
        idx_edit = st.session_state['edit_item_idx']
        edit_row = df.loc[idx_edit] if idx_edit is not None else None
        st.header("🖊️ Saisie")
        with st.form("form_v10", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                # GROS TITRE
                l_gt = sorted(df['gros_titre'].unique().tolist()) if not df.empty else []
                f_gt = st.selectbox("Dossier", [""] + l_gt, index=l_gt.index(edit_row['gros_titre'])+1 if edit_row and edit_row['gros_titre'] in l_gt else 0)
                f_gt_n = st.text_input("Nouveau Dossier")
                # TITRE
                l_t = sorted(df['titre'].unique().tolist()) if not df.empty else []
                f_t = st.selectbox("Titre", [""] + l_t, index=l_t.index(edit_row['titre'])+1 if edit_row and edit_row['titre'] in l_t else 0)
                f_t_n = st.text_input("Nouveau Titre")
            with c2:
                f_c = st.text_area("Contenu", value=edit_row['contenu'] if edit_row is not None else "")
                f_d = st.date_input("Date", value=edit_row['dt_obj'].date() if edit_row is not None and not pd.isna(edit_row['dt_obj']) else None)
                f_time = st.time_input("Heure", value=edit_row['dt_obj'].time() if edit_row is not None and not pd.isna(edit_row['dt_obj']) else time(8,0))
            
            if st.form_submit_button("💾 Enregistrer"):
                final_gt = f_gt_n if f_gt_n else f_gt
                final_t = f_t_n if f_t_n else f_t
                date_str = datetime.combine(f_d, f_time).strftime('%Y-%m-%d %H:%M:%S') if f_d else ""
                
                if idx_edit is not None:
                    df.at[idx_edit, 'gros_titre'] = final_gt
                    df.at[idx_edit, 'titre'] = final_t
                    df.at[idx_edit, 'contenu'] = f_c
                    df.at[idx_edit, 'echeance'] = date_str
                    df.at[idx_edit, 'type'] = "Task" if f_d else "Note"
                else:
                    new_id = int(df['id'].max()) + 1 if not df.empty else 1
                    new_r = {"id": new_id, "gros_titre": final_gt, "titre": final_t, "contenu": f_c, "echeance": date_str, "type": "Task" if f_d else "Note", "status": "En cours", "date_archive": ""}
                    df = pd.concat([df, pd.DataFrame([new_r])], ignore_index=True)
                
                save_data(df)
                st.session_state['edit_item_idx'] = None
                st.rerun()
