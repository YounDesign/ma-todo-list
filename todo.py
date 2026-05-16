import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta
import requests

# --- CONFIGURATION NOTIFICATIONS ---
NTFY_TOPIC = "youndesign_todolist_123" # Ton canal ntfy

def send_notif(title, message, priority="default"):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=message.encode('utf-8'),
            headers={"Title": title.encode('utf-8'), "Priority": priority})
    except: pass

# --- CONNEXION GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    # On lit la feuille. Si elle est vide, on crée la structure
    try:
        df = conn.read(ttl=0)
        # Nettoyage des lignes vides
        df = df.dropna(subset=['gros_titre', 'titre'], how='all')
    except:
        df = pd.DataFrame(columns=["id", "gros_titre", "titre", "contenu", "echeance", "type", "status"])
    
    # Conversion forcée de la colonne échéance en date
    if not df.empty:
        df['echeance_dt'] = pd.to_datetime(df['echeance'], errors='coerce').dt.date
    return df

def save_data(df_to_save):
    # On retire la colonne temporaire de calcul avant de sauvegarder
    if 'echeance_dt' in df_to_save.columns:
        df_to_save = df_to_save.drop(columns=['echeance_dt'])
    conn.update(data=df_to_save)
    st.cache_data.clear()

# --- INTERFACE ---
st.set_page_config(page_title="YounDesign Cloud", layout="wide")

if 'edit_item_idx' not in st.session_state: st.session_state['edit_item_idx'] = None

df = load_data()
today = datetime.now().date()

# --- COMPOSANT CARTE ---
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
            st.markdown(f"**{row['gros_titre']}** > {row['titre']}", unsafe_allow_html=True)
            st.write(row['contenu'])
        with col3:
            if row['type'] == 'Task':
                st.markdown(f"<span style='color:{color}'>📅 {row['echeance']}</span>", unsafe_allow_html=True)
                if is_overdue:
                    new_d = st.date_input("Reporter au :", value=today, key=f"resched_{idx}_{key_suffix}")
                    if st.button("Valider report", key=f"btn_res_{idx}_{key_suffix}"):
                        df.at[idx, 'echeance'] = str(new_d)
                        save_data(df)
                        send_notif("Report effectué", f"Tâche '{row['titre']}' reportée au {new_d}")
                        st.rerun()
            else: st.caption("📝 Note")
        with col4:
            if st.button("✏️", key=f"ed_{idx}_{key_suffix}"):
                st.session_state['edit_item_idx'] = idx
                st.rerun()

# --- ONGLETS ---
t_day, t_week, t_month, t_theme, t_saisie = st.tabs(["☀️ Journée", "📅 Semaine", "📊 Mois", "📂 Thématique", "🖊️ Saisie"])

# 1. JOURNÉE (Retards + Aujourd'hui)
with t_day:
    if not df.empty:
        tasks = df[df['status'] == 'En cours']
        # Retards
        overdue = tasks[(tasks['type'] == 'Task') & (tasks['echeance_dt'] < today)]
        if not overdue.empty:
            st.subheader("⚠️ Retards")
            for idx, r in overdue.iterrows(): item_card(idx, r, is_overdue=True, key_suffix="j_ret")
        # Aujourd'hui
        due_today = tasks[(tasks['type'] == 'Task') & (tasks['echeance_dt'] == today)]
        st.subheader("📅 Aujourd'hui")
        for idx, r in due_today.iterrows(): item_card(idx, r, key_suffix="j_tod")
    else: st.info("Aucune donnée.")

# 4. THÉMATIQUE
with t_theme:
    if not df.empty:
        tasks = df[df['status'] == 'En cours']
        for gt in sorted(tasks['gros_titre'].unique()):
            with st.expander(f"📁 {gt}"):
                sub = tasks[tasks['gros_titre'] == gt]
                for idx, r in sub.iterrows(): item_card(idx, r, key_suffix="th")

# 5. SAISIE / MODIFICATION
with t_saisie:
    idx = st.session_state['edit_item_idx']
    edit_row = df.loc[idx] if idx is not None else None
    
    st.header("🖊️ " + ("Modification" if idx is not None else "Nouvelle Saisie"))
    with st.form("form_cloud", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            # Propositions automatiques
            l_gt = sorted(df['gros_titre'].unique().tolist()) if not df.empty else []
            f_gt = st.selectbox("Gros Titre", [""] + l_gt, index=l_gt.index(edit_row['gros_titre'])+1 if edit_row and edit_row['gros_titre'] in l_gt else 0)
            f_gt_n = st.text_input("OU Nouveau")
            
            l_t = sorted(df['titre'].unique().tolist()) if not df.empty else []
            f_t = st.selectbox("Titre", [""] + l_t, index=l_t.index(edit_row['titre'])+1 if edit_row and edit_row['titre'] in l_t else 0)
            f_t_n = st.text_input("OU Nouveau Titre")
            
        with c2:
            f_c = st.text_area("Contenu", value=edit_row['contenu'] if edit_row is not None else "")
            f_d = st.date_input("Échéance (Optionnelle)", value=edit_row['echeance_dt'] if edit_row is not None and edit_row['echeance_dt'] else None)
        
        if st.form_submit_button("💾 Sauvegarder sur Google Sheets"):
            final_gt = f_gt_n if f_gt_n else f_gt
            final_t = f_t_n if f_t_n else f_t
            
            if idx is not None: # Update
                df.at[idx, 'gros_titre'] = final_gt
                df.at[idx, 'titre'] = final_t
                df.at[idx, 'contenu'] = f_c
                df.at[idx, 'echeance'] = str(f_d) if f_d else ""
                df.at[idx, 'type'] = "Task" if f_d else "Note"
            else: # New
                new_data = {
                    "id": len(df)+1, "gros_titre": final_gt, "titre": final_t, 
                    "contenu": f_c, "echeance": str(f_d) if f_d else "", 
                    "type": "Task" if f_d else "Note", "status": "En cours"
                }
                df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
            
            save_data(df)
            st.session_state['edit_item_idx'] = None
            st.success("Synchronisé avec Google Sheets !")
            st.rerun()

    if idx is not None:
        if st.button("❌ Annuler la modification"):
            st.session_state['edit_item_idx'] = None
            st.rerun()
