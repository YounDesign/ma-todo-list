import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import os
import requests

# --- CONFIGURATION ---
DB_NAME = "database_v7.db"
IMG_FOLDER = "task_images"
NTFY_TOPIC = "youndesign_todolist_123" 

if not os.path.exists(IMG_FOLDER):
    os.makedirs(IMG_FOLDER)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS items
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  gros_titre TEXT, titre TEXT, contenu TEXT,
                  echeance TEXT, type TEXT, image_path TEXT,
                  onglet_origine TEXT, status TEXT)''')
    conn.commit()
    conn.close()

def send_notif(title, message, priority="default"):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=message.encode('utf-8'),
            headers={"Title": title.encode('utf-8'), "Priority": priority})
        return True
    except: return False

def get_all_items():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM items WHERE status = 'En cours'", conn)
    conn.close()
    if not df.empty:
        df['echeance_dt'] = pd.to_datetime(df['echeance'], errors='coerce').dt.date
    return df

def update_task_date(item_id, new_date):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("UPDATE items SET echeance = ? WHERE id = ?", (str(new_date), item_id))
    conn.commit()
    conn.close()

def item_card(row, key, is_overdue=False):
    # Gestion de la couleur si en retard
    border_color = "#FF4B4B" if is_overdue else "#31333F"
    
    with st.container(border=True):
        if is_overdue:
            st.markdown("🚨 **EN RETARD**", unsafe_allow_html=True)
            
        col1, col2, col3, col4 = st.columns([0.1, 0.5, 0.3, 0.1])
        
        with col1:
            if st.checkbox("Fait", key=f"chk_{row['id']}_{key}", label_visibility="collapsed"):
                conn = sqlite3.connect(DB_NAME)
                conn.execute("UPDATE items SET status = 'Terminé' WHERE id = ?", (row['id'],))
                conn.commit()
                st.rerun()
        
        with col2:
            title_style = "color: red;" if is_overdue else ""
            st.markdown(f"<span style='{title_style}'>**{row['gros_titre']}** > {row['titre']}</span>", unsafe_allow_html=True)
            st.write(row['contenu'])
            
            # Correction du BUG IMAGE : On vérifie que c'est bien une chaîne de caractères
            img_p = row['image_path']
            if isinstance(img_p, str) and img_p and os.path.exists(img_p):
                st.image(img_p, width=150)
        
        with col3:
            if row['type'] == 'Task':
                dt_display = pd.to_datetime(row['echeance']).strftime('%d/%m/%Y')
                st.caption(f"📅 {dt_display}")
                # Option de report si en retard
                if is_overdue:
                    new_d = st.date_input("Reporter au :", value=datetime.now().date(), key=f"resched_{row['id']}_{key}")
                    if st.button("Valider report", key=f"btn_resched_{row['id']}_{key}"):
                        update_task_date(row['id'], new_d)
                        st.success("Date mise à jour")
                        st.rerun()
            else:
                st.caption("📝 Note")
        
        with col4:
            if st.button("✏️", key=f"ed_{row['id']}_{key}"):
                st.session_state['edit_item'] = row.to_dict()
                st.rerun()

# --- INTERFACE ---
st.set_page_config(page_title="YounDesign PKM", layout="wide")
init_db()

if 'edit_item' not in st.session_state: st.session_state['edit_item'] = None

df_all = get_all_items()
today = datetime.now().date()

t_day, t_week, t_month, t_theme, t_notif, t_param, t_saisie = st.tabs([
    "☀️ Journée", "📅 Semaine", "📊 Mois", "📂 Thématique", "🔔 Notifications", "⚙️ Paramètres", "🖊️ Saisie"
])

# 1. JOURNÉE (Inclut les retards)
with t_day:
    st.header("Planning du jour")
    if not df_all.empty:
        # Tâches en retard
        overdue = df_all[(df_all['type'] == 'Task') & (df_all['echeance_dt'] < today)]
        if not overdue.empty:
            st.subheader("⚠️ Tâches en retard")
            for _, r in overdue.iterrows(): item_card(r, "over", is_overdue=True)
            st.divider()
            
        # Tâches d'aujourd'hui
        due_today = df_all[(df_all['type'] == 'Task') & (df_all['echeance_dt'] == today)]
        st.subheader("📅 Aujourd'hui")
        if not due_today.empty:
            for _, r in due_today.iterrows(): item_card(r, "today")
        else: st.info("Aucune tâche pour aujourd'hui.")
    else: st.info("Aucune tâche en cours.")

# 2. SEMAINE
with t_week:
    st.header("7 prochains jours")
    if not df_all.empty:
        week_tasks = df_all[(df_all['echeance_dt'] > today) & (df_all['echeance_dt'] <= today + timedelta(days=7))]
        for _, r in week_tasks.iterrows(): item_card(r, "week")

# 3. MOIS
with t_month:
    st.header("Horizon 30 jours")
    if not df_all.empty:
        month_tasks = df_all[(df_all['echeance_dt'] > today + timedelta(days=7)) & (df_all['echeance_dt'] <= today + timedelta(days=30))]
        for _, r in month_tasks.iterrows(): item_card(r, "month")

# 4. THÉMATIQUE
with t_theme:
    st.header("Par dossiers")
    if not df_all.empty:
        for gt in sorted(df_all['gros_titre'].unique()):
            with st.expander(f"📁 {gt}"):
                sub = df_all[df_all['gros_titre'] == gt]
                for _, r in sub.iterrows(): item_card(r, "theme")

# 5. NOTIFICATIONS
with t_notif:
    st.header("Alertes")
    if st.button("🚀 Test de notification"):
        send_notif("YounDesign", "Test de notification réussi !")
        st.success("Envoyé !")

# 6. PARAMÈTRES
with t_param:
    st.header("Maintenance")
    if st.button("🗑️ Réinitialiser la base"):
        if os.path.exists(DB_NAME):
            os.remove(DB_NAME)
            st.rerun()

# 7. SAISIE
with t_saisie:
    edit_data = st.session_state['edit_item']
    st.header("🖊️ Saisie" if not edit_data else "✏️ Modification")
    with st.form("form_v7"):
        c1, c2 = st.columns(2)
        with c1:
            l_gt = sorted(df_all['gros_titre'].unique().tolist()) if not df_all.empty else []
            f_gt = st.selectbox("Catégorie", [""] + l_gt, index=l_gt.index(edit_data['gros_titre'])+1 if edit_data and edit_data['gros_titre'] in l_gt else 0)
            f_gt_n = st.text_input("Nouvelle catégorie")
            l_t = sorted(df_all['titre'].unique().tolist()) if not df_all.empty else []
            f_t = st.selectbox("Titre", [""] + l_t, index=l_t.index(edit_data['titre'])+1 if edit_data and edit_data['titre'] in l_t else 0)
            f_t_n = st.text_input("Nouveau titre")
        with c2:
            f_c = st.text_area("Détails", value=edit_data['contenu'] if edit_data else "")
            f_d = st.date_input("Date", value=pd.to_datetime(edit_data['echeance']).date() if edit_data and edit_data['echeance'] else None)
            f_img = st.file_uploader("Image")
        
        if st.form_submit_button("Enregistrer"):
            # Logique d'enregistrement similaire aux versions précédentes...
            conn = sqlite3.connect(DB_NAME)
            final_gt = f_gt_n if f_gt_n else f_gt
            final_t = f_t_n if f_t_n else f_t
            d_str = str(f_d) if f_d else None
            # (Gestion image simplifiée pour l'exemple)
            img_path = edit_data['image_path'] if edit_data else None
            if f_img:
                img_path = os.path.join(IMG_FOLDER, f_img.name)
                with open(img_path, "wb") as f: f.write(f_img.getbuffer())
            
            if edit_data:
                conn.execute("UPDATE items SET gros_titre=?, titre=?, contenu=?, echeance=?, image_path=? WHERE id=?", 
                             (final_gt, final_t, f_c, d_str, img_path, edit_data['id']))
            else:
                conn.execute("INSERT INTO items (gros_titre, titre, contenu, echeance, type, image_path, status) VALUES (?,?,?,?,?,?,?)", 
                             (final_gt, final_t, f_c, d_str, "Task" if f_d else "Note", img_path, "En cours"))
            conn.commit()
            conn.close()
            st.session_state['edit_item'] = None
            st.rerun()
