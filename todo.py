import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import os
import requests

# --- CONFIGURATION ---
DB_NAME = "database_v6.db"
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
    c.execute('CREATE TABLE IF NOT EXISTS logs_notif (date_envoi TEXT, type_notif TEXT)')
    conn.commit()
    conn.close()

# --- NOTIFICATIONS ---
def send_notif(title, message, priority="default"):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=message.encode('utf-8'),
            headers={"Title": title.encode('utf-8'), "Priority": priority, "Tags": "calendar,rocket"})
        return True
    except:
        return False

# --- LOGIQUE DATA ---
def get_all_items():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM items WHERE status = 'En cours'", conn)
    conn.close()
    if not df.empty:
        # On convertit le texte de la base en objet Date Python
        df['echeance_dt'] = pd.to_datetime(df['echeance'], errors='coerce').dt.date
    return df

def save_item(id, gt, t, c, d, img_path, origin, status):
    conn = sqlite3.connect(DB_NAME)
    item_type = "Task" if d else "Note"
    # TRÈS IMPORTANT : On force la date en texte (YYYY-MM-DD) pour SQLite
    date_str = str(d) if d else None
    
    if id is None:
        conn.execute("""INSERT INTO items (gros_titre, titre, contenu, echeance, type, image_path, onglet_origine, status) 
                        VALUES (?,?,?,?,?,?,?,?)""", (gt, t, c, date_str, item_type, img_path, origin, status))
    else:
        conn.execute("""UPDATE items SET gros_titre=?, titre=?, contenu=?, echeance=?, type=?, image_path=?, onglet_origine=?, status=? 
                        WHERE id=?""", (gt, t, c, date_str, item_type, img_path, origin, status, id))
    conn.commit()
    conn.close()

def item_card(row, key):
    with st.container(border=True):
        col1, col2, col3, col4 = st.columns([0.1, 0.6, 0.2, 0.1])
        with col1:
            if st.checkbox("Done", key=f"chk_{row['id']}_{key}", label_visibility="collapsed"):
                conn = sqlite3.connect(DB_NAME)
                conn.execute("UPDATE items SET status = 'Terminé' WHERE id = ?", (row['id'],))
                conn.commit()
                st.rerun()
        with col2:
            st.markdown(f"**{row['gros_titre']}** > {row['titre']}")
            st.write(row['contenu'])
            if row['image_path'] and os.path.exists(row['image_path']):
                st.image(row['image_path'], width=150)
        with col3:
            if row['type'] == 'Task':
                dt = pd.to_datetime(row['echeance']).strftime('%d/%m/%Y')
                st.caption(f"📅 {dt}")
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

# --- STRUCTURE EN ONGLETS DEMANDÉE ---
t_day, t_week, t_month, t_theme, t_notif, t_param, t_saisie = st.tabs([
    "☀️ Journée", "📅 Semaine", "📊 Mois", "📂 Thématique", "🔔 Notifications", "⚙️ Paramètres", "🖊️ Saisie"
])

# 1. JOURNÉE
with t_day:
    st.header("Urgences du jour")
    if not df_all.empty:
        day_tasks = df_all[(df_all['type'] == 'Task') & (df_all['echeance_dt'] <= today)]
        for _, r in day_tasks.iterrows(): item_card(r, "day")
    else: st.info("Rien pour aujourd'hui.")

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

# 4. THÉMATIQUE (Regroupe par Gros Titre)
with t_theme:
    st.header("Classement par dossiers")
    if not df_all.empty:
        for gt in sorted(df_all['gros_titre'].unique()):
            with st.expander(f"📁 {gt}"):
                sub = df_all[df_all['gros_titre'] == gt]
                for _, r in sub.iterrows(): item_card(r, "theme")

# 5. NOTIFICATIONS
with t_notif:
    st.header("Gestion des alertes")
    st.write(f"Canal ntfy actuel : `{NTFY_TOPIC}`")
    if st.button("🚀 Tester la notification immédiate"):
        success = send_notif("Test YounDesign", "La notification fonctionne parfaitement !")
        if success: st.success("Notification envoyée sur ton tel !")
        else: st.error("Erreur d'envoi.")

# 6. PARAMÈTRES
with t_param:
    st.header("Configuration")
    if st.button("🗑️ Réinitialiser la base de données"):
        if os.path.exists(DB_NAME):
            os.remove(DB_NAME)
            st.rerun()

# 7. SAISIE (Modifiée pour corriger le bug de visibilité)
with t_saisie:
    edit_data = st.session_state['edit_item']
    st.header("🖊️ Ajouter / Modifier")
    
    with st.form("form_saisie", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            l_gt = sorted(df_all['gros_titre'].unique().tolist()) if not df_all.empty else []
            f_gt = st.selectbox("Catégorie", [""] + l_gt, index=l_gt.index(edit_data['gros_titre'])+1 if edit_data and edit_data['gros_titre'] in l_gt else 0)
            f_gt_n = st.text_input("OU Nouveau Gros Titre")
            
            l_t = sorted(df_all['titre'].unique().tolist()) if not df_all.empty else []
            f_t = st.selectbox("Titre", [""] + l_t, index=l_t.index(edit_data['titre'])+1 if edit_data and edit_data['titre'] in l_t else 0)
            f_t_n = st.text_input("OU Nouveau Titre")
            
        with c2:
            f_c = st.text_area("Description", value=edit_data['contenu'] if edit_data else "")
            f_d = st.date_input("Date échéance", value=pd.to_datetime(edit_data['echeance']).date() if edit_data and edit_data['echeance'] else None)
            f_img = st.file_uploader("Image")

        if st.form_submit_button("💾 Enregistrer dans la base"):
            final_gt = f_gt_n if f_gt_n else f_gt
            final_t = f_t_n if f_t_n else f_t
            img_path = edit_data['image_path'] if edit_data else None
            
            if f_img:
                img_path = os.path.join(IMG_FOLDER, f_img.name)
                with open(img_path, "wb") as f: f.write(f_img.getbuffer())
            
            save_item(edit_data['id'] if edit_data else None, final_gt, final_t, f_c, f_d, img_path, "App", "En cours")
            st.session_state['edit_item'] = None
            st.success("Tâche enregistrée ! Va dans l'onglet Journée ou Thématique pour la voir.")
            st.rerun()
