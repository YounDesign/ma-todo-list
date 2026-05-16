import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import os
from PIL import Image
import requests

# --- CONFIGURATION ---
DB_NAME = "database_v2.db"
IMG_FOLDER = "task_images"
if not os.path.exists(IMG_FOLDER):
    os.makedirs(IMG_FOLDER)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS items
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  gros_titre TEXT,
                  titre TEXT,
                  contenu TEXT,
                  echeance DATE,
                  type TEXT, -- 'Note' ou 'Task'
                  image_path TEXT,
                  onglet_origine TEXT,
                  status TEXT)''')
    conn.commit()
    conn.close()

# --- NOTIFICATIONS (via ntfy.sh) ---
def send_notification(message):
    # Remplace 'mon_canal_secret_123' par un nom unique à toi
    topic = "youndesign_todolist_reminders" 
    requests.post(f"https://ntfy.sh/{topic}", 
                  data=message.encode('utf-8'),
                  headers={"Title": "Rappel To-Do List"})

# --- INTERFACE ---
st.set_page_config(page_title="YounDesign PKM", layout="wide")
init_db()

# Barre latérale : Galerie d'images
with st.sidebar:
    st.title("🖼️ Galerie Médias")
    conn = sqlite3.connect(DB_NAME)
    # On récupère les tâches qui ont une image
    df_imgs = pd.read_sql_query("SELECT id, contenu, image_path FROM items WHERE image_path IS NOT NULL", conn)
    conn.close()

    if not df_imgs.empty:
        for _, row in df_imgs.iterrows():
            st.image(row['image_path'], caption=row['contenu'][:20] + "...")
            if st.button(f"Voir la tâche", key=f"img_{row['id']}"):
                st.session_state['search_id'] = row['id']
    else:
        st.info("Aucune image disponible")

# Onglets principaux
tab_tasks, tab_notes, tab_add, tab_admin = st.tabs(["✅ Tâches", "📝 Notes", "➕ Ajouter", "⚙️ Admin"])

# --- ONGLET TÂCHES ---
with tab_tasks:
    st.header("Mes Échéances")
    conn = sqlite3.connect(DB_NAME)
    query = "SELECT * FROM items WHERE type = 'Task' AND status = 'En cours' ORDER BY echeance ASC"
    df = pd.read_sql_query(query, conn)
    conn.close()

    if 'search_id' in st.session_state:
        df = df[df['id'] == st.session_state['search_id']]
        if st.button("❌ Effacer le filtre image"):
            del st.session_state['search_id']
            st.rerun()

    # Affichage par "Gros Titre"
    for gt in df['gros_titre'].unique():
        with st.expander(f"📁 {gt}", expanded=True):
            sub_df = df[df['gros_titre'] == gt]
            for _, row in sub_df.iterrows():
                c1, c2, c3 = st.columns([0.1, 0.7, 0.2])
                with c1:
                    if st.checkbox("", key=f"check_{row['id']}"):
                        # Archivage
                        c = sqlite3.connect(DB_NAME)
                        c.execute("UPDATE items SET status = 'Terminé' WHERE id = ?", (row['id'],))
                        c.commit()
                        st.rerun()
                with c2:
                    st.markdown(f"**{row['titre']}** : {row['contenu']}")
                    st.caption(f"Source: {row['onglet_origine']}")
                with c3:
                    st.error(row['echeance']) if str(row['echeance']) <= str(datetime.now().date()) else st.warning(row['echeance'])

# --- ONGLET NOTES ---
with tab_notes:
    st.header("Mes Notes (Sans date)")
    conn = sqlite3.connect(DB_NAME)
    df_notes = pd.read_sql_query("SELECT * FROM items WHERE type = 'Note'", conn)
    conn.close()
    
    for gt in df_notes['gros_titre'].unique():
        st.subheader(gt)
        notes_sub = df_notes[df_notes['gros_titre'] == gt]
        for _, row in notes_sub.iterrows():
            st.info(f"**{row['titre']}** : {row['contenu']}  \n*Origine: {row['onglet_origine']}*")

# --- FORMULAIRE D'AJOUT ---
with tab_add:
    st.header("Nouvel élément")
    with st.form("add_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            # Récupération des catégories existantes pour auto-complétion
            conn = sqlite3.connect(DB_NAME)
            existing_gt = [r[0] for r in conn.execute("SELECT DISTINCT gros_titre FROM items").fetchall()]
            conn.close()
            
            new_gt = st.selectbox("Gros Titre (Existant)", [""] + existing_gt)
            custom_gt = st.text_input("OU Nouveau Gros Titre")
            
            new_t = st.text_input("Titre (Sous-catégorie)")
            new_c = st.text_area("Contenu / Note")
        
        with col2:
            new_date = st.date_input("Échéance (Laisser vide pour une Note)", value=None)
            new_img = st.file_uploader("Image / Photo", type=['png', 'jpg', 'jpeg'])
            new_origin = st.text_input("Onglet Excel de destination", value="App Mobile")
        
        if st.form_submit_button("Enregistrer"):
            final_gt = custom_gt if custom_gt else new_gt
            final_type = "Task" if new_date else "Note"
            img_path = None
            
            if new_img:
                img_path = os.path.join(IMG_FOLDER, new_img.name)
                with open(img_path, "wb") as f:
                    f.write(new_img.getbuffer())
            
            conn = sqlite3.connect(DB_NAME)
            conn.execute("""INSERT INTO items (gros_titre, titre, contenu, echeance, type, image_path, onglet_origine, status) 
                            VALUES (?,?,?,?,?,?,?,?)""",
                         (final_gt, new_t, new_c, new_date, final_type, img_path, new_origin, "En cours"))
            conn.commit()
            conn.close()
            st.success("Enregistré !")
            st.rerun()

# --- NOTIFICATIONS & ADMIN ---
with tab_admin:
    if st.button("🔔 Tester Rappel demain sur Mobile"):
        tomorrow = (datetime.now() + timedelta(days=1)).date()
        conn = sqlite3.connect(DB_NAME)
        tasks_tmw = conn.execute("SELECT contenu FROM items WHERE echeance = ?", (tomorrow,)).fetchall()
        conn.close()
        if tasks_tmw:
            msg = f"Demain tu as {len(tasks_tmw)} tâches : " + ", ".join([t[0] for t in tasks_tmw])
            send_notification(msg)
            st.success("Notification envoyée !")
        else:
            st.info("Rien de prévu pour demain.")
