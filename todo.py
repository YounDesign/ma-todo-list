import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import os

# --- CONFIGURATION ---
DB_NAME = "database_v3.db"
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
                  type TEXT, 
                  image_path TEXT,
                  onglet_origine TEXT,
                  status TEXT)''')
    conn.commit()
    conn.close()

# --- FONCTIONS DE BASE DE DONNÉES ---
def get_all_items():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM items WHERE status = 'En cours'", conn)
    conn.close()
    return df

def save_item(id, gt, t, c, d, img_path, origin, status):
    conn = sqlite3.connect(DB_NAME)
    item_type = "Task" if d else "Note"
    if id is None: # Nouvel ajout
        conn.execute("""INSERT INTO items (gros_titre, titre, contenu, echeance, type, image_path, onglet_origine, status) 
                        VALUES (?,?,?,?,?,?,?,?)""", (gt, t, c, d, item_type, img_path, origin, status))
    else: # Modification
        conn.execute("""UPDATE items SET gros_titre=?, titre=?, contenu=?, echeance=?, type=?, image_path=?, onglet_origine=?, status=? 
                        WHERE id=?""", (gt, t, c, d, item_type, img_path, origin, status, id))
    conn.commit()
    conn.close()

# --- INTERFACE ---
st.set_page_config(page_title="YounDesign PKM", layout="wide")
init_db()

# Initialisation du mode édition dans la session
if 'edit_item' not in st.session_state:
    st.session_state['edit_item'] = None

# Barre latérale : Galerie d'images
with st.sidebar:
    st.title("🖼️ Galerie Médias")
    df_all = get_all_items()
    df_imgs = df_all[df_all['image_path'].notna()]
    for _, row in df_imgs.iterrows():
        st.image(row['image_path'], caption=row['contenu'][:20])
        if st.button(f"Éditer l'élément {row['id']}", key=f"img_btn_{row['id']}"):
            st.session_state['edit_item'] = row.to_dict()

# Onglets
tab_tasks, tab_notes, tab_form = st.tabs(["✅ Tâches", "📝 Notes", "📝 Ajouter / Modifier"])

# --- ONGLET FORMULAIRE (AJOUT & MODIFICATION) ---
with tab_form:
    edit_data = st.session_state['edit_item']
    title_form = "Modifier l'élément" if edit_data else "Ajouter un nouvel élément"
    st.header(title_form)
    
    with st.form("main_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            # Gestion des catégories
            all_gt = df_all['gros_titre'].unique().tolist() if not df_all.empty else []
            default_gt = edit_data['gros_titre'] if edit_data else ""
            
            f_gt = st.selectbox("Gros Titre", options=[""] + all_gt, index=all_gt.index(default_gt)+1 if default_gt in all_gt else 0)
            f_custom_gt = st.text_input("OU Nouveau Gros Titre (si vide, utilise celui du dessus)")
            f_t = st.text_input("Titre (Sous-catégorie)", value=edit_data['titre'] if edit_data else "")
            f_c = st.text_area("Contenu / Note", value=edit_data['contenu'] if edit_data else "")
        
        with col2:
            # Gestion de la date (conversion string vers objet date si modification)
            default_date = None
            if edit_data and edit_data['echeance']:
                try:
                    default_date = datetime.strptime(str(edit_data['echeance']), '%Y-%m-%d').date()
                except:
                    default_date = None
            
            f_d = st.date_input("Échéance (Vider pour Note)", value=default_date)
            f_img = st.file_uploader("Changer l'image", type=['png', 'jpg', 'jpeg'])
            f_origin = st.text_input("Onglet Source", value=edit_data['onglet_origine'] if edit_data else "Mobile")

        submit_label = "Mettre à jour" if edit_data else "Enregistrer"
        if st.form_submit_button(submit_label):
            final_gt = f_custom_gt if f_custom_gt else f_gt
            img_path = edit_data['image_path'] if edit_data else None
            
            if f_img:
                img_path = os.path.join(IMG_FOLDER, f_img.name)
                with open(img_path, "wb") as f:
                    f.write(f_img.getbuffer())
            
            save_item(edit_data['id'] if edit_data else None, final_gt, f_t, f_c, f_d, img_path, f_origin, "En cours")
            st.session_state['edit_item'] = None # Reset le mode édition
            st.success("Opération réussie !")
            st.rerun()
            
    if edit_data:
        if st.button("❌ Annuler la modification"):
            st.session_state['edit_item'] = None
            st.rerun()

# --- AFFICHAGE DES TÂCHES ---
with tab_tasks:
    df_t = df_all[df_all['type'] == 'Task'].sort_values('echeance')
    for gt in df_t['gros_titre'].unique():
        with st.expander(f"📁 {gt}", expanded=True):
            sub = df_t[df_t['gros_titre'] == gt]
            for _, row in sub.iterrows():
                c1, c2, c3, c4 = st.columns([0.1, 0.6, 0.2, 0.1])
                c1.checkbox("", key=f"tk_{row['id']}") # À connecter à une fonction archive
                c2.markdown(f"**{row['titre']}** : {row['contenu']}")
                c3.warning(row['echeance'])
                if c4.button("✏️", key=f"ed_tk_{row['id']}"):
                    st.session_state['edit_item'] = row.to_dict()
                    st.rerun()

# --- AFFICHAGE DES NOTES ---
with tab_notes:
    df_n = df_all[df_all['type'] == 'Note']
    for gt in df_n['gros_titre'].unique():
        st.subheader(gt)
        sub = df_n[df_n['gros_titre'] == gt]
        for _, row in sub.iterrows():
            with st.container():
                col_n1, col_n2 = st.columns([0.9, 0.1])
                col_n1.info(f"**{row['titre']}** : {row['contenu']}")
                if col_n2.button("✏️", key=f"ed_nt_{row['id']}"):
                    st.session_state['edit_item'] = row.to_dict()
                    st.rerun()
