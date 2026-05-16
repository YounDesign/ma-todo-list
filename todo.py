import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta, time
import requests

# --- CONFIGURATION SÉCURITÉ & NOTIFS ---
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
            else:
                st.error("Mot de passe incorrect")
        return False
    return True

# --- SI CONNECTÉ ---
if check_password():
    conn = st.connection("gsheets", type=GSheetsConnection)

    def load_data():
        try:
            df = conn.read(ttl=0)
            df = df.dropna(subset=['gros_titre', 'titre'], how='all')
            # On convertit le texte "YYYY-MM-DD HH:MM:SS" en objet datetime
            df['dt_obj'] = pd.to_datetime(df['echeance'], errors='coerce')
        except:
            df = pd.DataFrame(columns=["id", "gros_titre", "titre", "contenu", "echeance", "type", "status"])
        return df

    def save_data(df_to_save):
        if 'dt_obj' in df_to_save.columns:
            df_to_save = df_to_save.drop(columns=['dt_obj'])
        conn.update(data=df_to_save)
        st.cache_data.clear()

    # --- INTERFACE ---
    st.set_page_config(page_title="YounDesign PKM", layout="wide")
    
    if 'edit_item_idx' not in st.session_state: st.session_state['edit_item_idx'] = None
    
    df = load_data()
    now = datetime.now()

    def item_card(idx, row, is_overdue=False, key_suffix=""):
        color = "#FF4B4B" if is_overdue else "#31333F"
        with st.container(border=True):
            col1, col2, col3, col4 = st.columns([0.1, 0.5, 0.3, 0.1])
            with col1:
                if st.checkbox("Fait", key=f"chk_{idx}_{key_suffix}", label_visibility="collapsed"):
                    df.at[idx, 'status'] = 'Terminé'
                    save_data(df)
                    st.rerun()
            with col2:
                st.markdown(f"**{row['gros_titre']}** > {row['titre']}")
                st.write(row['contenu'])
            with col3:
                if row['type'] == 'Task' and not pd.isna(row['dt_obj']):
                    # Affichage FR : 26/03/2026 08:00
                    display_dt = row['dt_obj'].strftime('%d/%m/%Y %H:%M')
                    st.markdown(f"<span style='color:{color}'>🔔 {display_dt}</span>", unsafe_allow_html=True)
                    if is_overdue:
                        new_d = st.date_input("Reporter au :", value=now.date(), key=f"resched_d_{idx}")
                        new_t = st.time_input("Heure :", value=time(8, 0), key=f"resched_t_{idx}")
                        if st.button("Valider report", key=f"btn_res_{idx}"):
                            combined = datetime.combine(new_d, new_t)
                            df.at[idx, 'echeance'] = combined.strftime('%Y-%m-%d %H:%M:%S')
                            save_data(df)
                            st.rerun()
                else: st.caption("📝 Note")
            with col4:
                if st.button("✏️", key=f"ed_{idx}"):
                    st.session_state['edit_item_idx'] = idx
                    st.rerun()

    # --- ONGLETS ---
    tabs = st.tabs(["☀️ Journée", "📅 Semaine", "📂 Thématique", "📝 Notes", "🖊️ Saisie"])
    
    # Filtrage des tâches en cours
    tasks_active = df[df['status'] == 'En cours'] if not df.empty else pd.DataFrame()

    with tabs[0]: # JOURNÉE
        if not tasks_active.empty:
            # Retards (date et heure passées)
            overdue = tasks_active[(tasks_active['type'] == 'Task') & (tasks_active['dt_obj'] < now)]
            if not overdue.empty:
                st.subheader("⚠️ Retards")
                for idx, r in overdue.iterrows(): item_card(idx, r, is_overdue=True, key_suffix="over")
            
            # Aujourd'hui (jusqu'à minuit)
            today_end = datetime.combine(now.date(), time(23, 59, 59))
            due_today = tasks_active[(tasks_active['type'] == 'Task') & (tasks_active['dt_obj'] >= now) & (tasks_active['dt_obj'] <= today_end)]
            st.subheader("📅 Aujourd'hui")
            for idx, r in due_today.iterrows(): item_card(idx, r, key_suffix="today")
        else: st.info("Rien pour le moment.")

    with tabs[4]: # SAISIE
        idx = st.session_state['edit_item_idx']
        edit_row = df.loc[idx] if idx is not None else None
        
        st.header("🖊️ Saisie")
        with st.form("form_v9", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            with col_a:
                l_gt = sorted(df['gros_titre'].unique().tolist()) if not df.empty else []
                f_gt = st.selectbox("Gros Titre", [""] + l_gt, index=l_gt.index(edit_row['gros_titre'])+1 if edit_row and edit_row['gros_titre'] in l_gt else 0)
                f_gt_n = st.text_input("OU Nouveau")
                
                l_t = sorted(df['titre'].unique().tolist()) if not df.empty else []
                f_t = st.selectbox("Titre", [""] + l_t, index=l_t.index(edit_row['titre'])+1 if edit_row and edit_row['titre'] in l_t else 0)
            
            with col_b:
                f_c = st.text_area("Contenu", value=edit_row['contenu'] if edit_row is not None else "")
                
                # DATE + HEURE (8h00 par défaut)
                d_val = edit_row['dt_obj'].date() if edit_row is not None and not pd.isna(edit_row['dt_obj']) else None
                t_val = edit_row['dt_obj'].time() if edit_row is not None and not pd.isna(edit_row['dt_obj']) else time(8, 0)
                
                f_date = st.date_input("Date échéance", value=d_val)
                f_time = st.time_input("Heure précise", value=t_val) # Par défaut 08:00
            
            if st.form_submit_button("💾 Enregistrer"):
                final_gt = f_gt_n if f_gt_n else f_gt
                final_dt = datetime.combine(f_date, f_time) if f_date else None
                
                if idx is not None:
                    df.at[idx, 'gros_titre'] = final_gt
                    df.at[idx, 'contenu'] = f_c
                    df.at[idx, 'echeance'] = final_dt.strftime('%Y-%m-%d %H:%M:%S') if final_dt else ""
                    df.at[idx, 'type'] = "Task" if f_date else "Note"
                else:
                    new_row = {
                        "id": len(df)+1, "gros_titre": final_gt, "titre": f_t,
                        "contenu": f_c, "echeance": final_dt.strftime('%Y-%m-%d %H:%M:%S') if final_dt else "",
                        "type": "Task" if f_date else "Note", "status": "En cours"
                    }
                    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                
                save_data(df)
                st.session_state['edit_item_idx'] = None
                st.success("Tâche enregistrée à 8h00 !")
                st.rerun()
