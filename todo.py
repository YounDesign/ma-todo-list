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
            
            # Normalisation du statut (pour éviter que les tâches soient invisibles)
            if 'status' not in df.columns: df['status'] = 'En cours'
            df['status'] = df['status'].fillna('En cours').astype(str)
            
            # Conversion des dates en format interne Pandas (Timestamp)
            df['dt_obj'] = pd.to_datetime(df['echeance'], errors='coerce')
            
            if 'date_archive' not in df.columns: df['date_archive'] = ""
            df['date_archive_dt'] = pd.to_datetime(df['date_archive'], errors='coerce')
            
        except Exception as e:
            st.error(f"Erreur chargement : {e}")
            df = pd.DataFrame(columns=["id", "gros_titre", "titre", "contenu", "echeance", "type", "status", "date_archive"])
        return df

    def save_data(df_to_save):
        # On nettoie les colonnes de calcul avant l'envoi vers Google Sheets
        cols_to_drop = ['dt_obj', 'date_archive_dt']
        final_df = df_to_save.drop(columns=[c for c in cols_to_drop if c in df_to_save.columns])
        conn.update(data=final_df)
        st.cache_data.clear()

    def cleanup_old_archives(df):
        # Correction du BUG de comparaison (On utilise pd.Timestamp)
        limit_date = pd.Timestamp(datetime.now().date() - timedelta(days=30))
        
        # On garde ce qui n'est pas terminé OU ce qui a été archivé il y a moins de 30 jours
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
                else: st.write("📁")
            with col2:
                st.markdown(f"**{row['gros_titre']}** > {row['titre']}")
                st.write(row['contenu'])
            with col3:
                if row['type'] == 'Task' and not pd.isna(row['dt_obj']):
                    st.markdown(f"<span style='color:{color}'>📅 {row['dt_obj'].strftime('%d/%m/%Y %H:%M')}</span>", unsafe_allow_html=True)
                    if is_overdue and row['status'] != 'Terminé':
                        new_d = st.date_input("Reporter :", value=datetime.now().date(), key=f"res_{idx}_{key_suffix}")
                        if st.button("OK", key=f"btn_res_{idx}_{key_suffix}"):
                            df.at[idx, 'echeance'] = datetime.combine(new_d, time(8, 0)).strftime('%Y-%m-%d %H:%M:%S')
                            save_data(df)
                            st.rerun()
            with col4:
                if st.button("✏️", key=f"ed_{idx}_{key_suffix}"):
                    st.session_state['edit_item_idx'] = idx
                    st.rerun()

    # --- ONGLETS ---
    tabs = st.tabs(["☀️ Journée", "📅 Semaine", "📂 Thématique", "📝 Notes", "🖊️ Saisie", "🗄️ Archive"])
    
    # Filtrage strict mais robuste
    active = df[df['status'].str.contains('En cours', case=False, na=True)]
    archives = df[df['status'].str.contains('Terminé', case=False, na=False)]

    with tabs[0]: # JOURNÉE
        st.subheader("Planning du jour")
        # Retards : Date passée ET pas terminé
        overdue = active[(active['type'] == 'Task') & (active['dt_obj'] < now)]
        if not overdue.empty:
            st.error("🚨 Retards")
            for idx, r in overdue.iterrows(): item_card(idx, r, is_overdue=True, key_suffix="ov")
        
        # Aujourd'hui
        due_today = active[(active['type'] == 'Task') & (active['dt_obj'].dt.date == now.date()) & (active['dt_obj'] >= now)]
        if not due_today.empty:
            st.subheader("📅 Aujourd'hui")
            for idx, r in due_today.iterrows(): item_card(idx, r, key_suffix="tod")
        
        if overdue.empty and due_today.empty: st.info("Rien d'urgent pour aujourd'hui.")

    with tabs[2]: # THÉMATIQUE
        if not active.empty:
            for gt in sorted(active['gros_titre'].unique()):
                with st.expander(f"📁 {gt}"):
                    for idx, r in active[active['gros_titre'] == gt].iterrows(): item_card(idx, r, key_suffix="th")

    with tabs[5]: # ARCHIVE
        st.header("Archives (30 jours)")
        if not archives.empty:
            for idx, r in archives.sort_values('date_archive', ascending=False).iterrows():
                item_card(idx, r, key_suffix="arc")

    with tabs[4]: # SAISIE
        idx_e = st.session_state['edit_item_idx']
        edit_r = df.loc[idx_e] if idx_e is not None else None
        
        with st.form("form_v11", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                l_gt = sorted(df['gros_titre'].unique().tolist()) if not df.empty else []
                f_gt = st.selectbox("Dossier existant", [""] + l_gt, index=l_gt.index(edit_r['gros_titre'])+1 if edit_r and edit_r['gros_titre'] in l_gt else 0)
                f_gt_n = st.text_input("OU Nouveau Dossier")
                
                l_t = sorted(df['titre'].unique().tolist()) if not df.empty else []
                f_t = st.selectbox("Titre existant", [""] + l_t, index=l_t.index(edit_r['titre'])+1 if edit_r and edit_r['titre'] in l_t else 0)
                f_t_n = st.text_input("OU Nouveau Titre")
            with c2:
                f_c = st.text_area("Contenu", value=edit_r['contenu'] if edit_r is not None else "")
                f_d = st.date_input("Date", value=edit_r['dt_obj'].date() if edit_r is not None and not pd.isna(edit_r['dt_obj']) else None)
                f_h = st.time_input("Heure", value=edit_r['dt_obj'].time() if edit_r is not None and not pd.isna(edit_r['dt_obj']) else time(8,0))
            
            if st.form_submit_button("💾 Enregistrer"):
                final_gt = f_gt_n if f_gt_n else f_gt
                final_t = f_t_n if f_t_n else f_t
                date_s = datetime.combine(f_d, f_h).strftime('%Y-%m-%d %H:%M:%S') if f_d else ""
                
                if idx_e is not None:
                    df.at[idx_e, 'gros_titre'], df.at[idx_e, 'titre'] = final_gt, final_t
                    df.at[idx_e, 'contenu'], df.at[idx_e, 'echeance'] = f_c, date_s
                    df.at[idx_e, 'type'] = "Task" if f_d else "Note"
                else:
                    new_id = int(df['id'].max()) + 1 if not df.empty else 1
                    new_r = {"id": new_id, "gros_titre": final_gt, "titre": final_t, "contenu": f_c, "echeance": date_s, "type": "Task" if f_d else "Note", "status": "En cours", "date_archive": ""}
                    df = pd.concat([df, pd.DataFrame([new_r])], ignore_index=True)
                
                save_data(df)
                st.session_state['edit_item_idx'] = None
                st.rerun()
