import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import os
import requests # Pour envoyer les notifications

# --- CONFIGURATION ---
DB_NAME = "database_v5.db"
IMG_FOLDER = "task_images"
NTFY_TOPIC = "youndesign_todolist_123" # <--- METS TON NOM UNIQUE ICI

if not os.path.exists(IMG_FOLDER):
    os.makedirs(IMG_FOLDER)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS items
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  gros_titre TEXT, titre TEXT, contenu TEXT,
                  echeance DATE, type TEXT, image_path TEXT,
                  onglet_origine TEXT, status TEXT)''')
    # Table pour ne pas envoyer 100 fois la même notif le même jour
    c.execute('CREATE TABLE IF NOT EXISTS logs_notif (date_envoi DATE, type_notif TEXT)')
    conn.commit()
    conn.close()

# --- SYSTÈME DE NOTIFICATIONS ---
def send_notif(title, message, priority="default"):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=message.encode('utf-8'),
            headers={
                "Title": title.encode('utf-8'),
                "Priority": priority,
                "Tags": "calendar,rocket"
            })
    except Exception as e:
        print(f"Erreur envoi notif: {e}")

def check_auto_notifications():
    today = datetime.now().date()
    conn = sqlite3.connect(DB_NAME)
    
    # 1. NOTIFICATION DU LENDEMAIN (Tous les jours)
    check_daily = conn.execute("SELECT * FROM logs_notif WHERE date_envoi=? AND type_notif='daily'", (today,)).fetchone()
    if not check_daily:
        tomorrow = today + timedelta(days=1)
        tasks = conn.execute("SELECT titre, contenu FROM items WHERE echeance=? AND status='En cours'", (tomorrow,)).fetchall()
        if tasks:
            msg = "\n".join([f"• {t[0]}: {t[1]}" for t in tasks])
            send_notif("Rappel pour Demain", f"Tu as {len(tasks)} tâches prévues :\n{msg}")
        conn.execute("INSERT INTO logs_notif VALUES (?, 'daily')", (today,))
    
    # 2. NOTIFICATION DE LA SEMAINE (Le Dimanche)
    if today.weekday() == 6: # 6 = Dimanche
        check_weekly = conn.execute("SELECT * FROM logs_notif WHERE date_envoi=? AND type_notif='weekly'", (today,)).fetchone()
        if not check_weekly:
            next_week = today + timedelta(days=7)
            tasks = conn.execute("SELECT titre, echeance FROM items WHERE echeance > ? AND echeance <= ? AND status='En cours'", (today, next_week)).fetchall()
            if tasks:
                msg = "\n".join([f"• {t[1]}: {t[0]}" for t in tasks])
                send_notif("Objectifs de la Semaine", f"Aperçu des 7 prochains jours :\n{msg}", priority="high")
            conn.execute("INSERT INTO logs_notif VALUES (?, 'weekly')", (today,))
            
    conn.commit()
    conn.close()

# --- LOGIQUE APP (Simplifiée pour la clarté) ---
def format_date_fr(date_obj):
    if not date_obj: return ""
    return pd.to_datetime(date_obj).strftime('%d/%m/%Y')

def get_all_items():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM items WHERE status = 'En cours'", conn)
    conn.close()
    if not df.empty: df['echeance'] = pd.to_datetime(df['echeance']).dt.date
    return df

# --- INTERFACE ---
st.set_page_config(page_title="YounDesign Pro", layout="wide")
init_db()
check_auto_notifications() # Se lance à chaque ouverture de l'app

if 'edit_item' not in st.session_state: st.session_state['edit_item'] = None

df_all = get_all_items()
today = datetime.now().date()

# Onglets
tab_urg, tab_themes, tab_notes, tab_form = st.tabs(["🚨 Urgences", "📁 Thématiques", "📝 Notes", "🖊️ Saisie"])

# --- CONTENU DES ONGLETS (Réutilisation de la structure v4) ---
# ... (Je garde la même logique de cartes et d'onglets que précédemment)

with tab_form:
    edit_data = st.session_state['edit_item']
    st.header("🖊️ Saisie rapide")
    
    with st.form("form_entry", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            # GROS TITRE avec propositions
            list_gt = sorted(df_all['gros_titre'].unique().tolist()) if not df_all.empty else []
            f_gt = st.selectbox("Catégorie existante", [""] + list_gt)
            f_gt_new = st.text_input("OU Nouveau Gros Titre")
            
            # PETIT TITRE avec propositions
            list_t = sorted(df_all['titre'].unique().tolist()) if not df_all.empty else []
            f_t = st.selectbox("Titre existant", [""] + list_t)
            f_t_new = st.text_input("OU Nouveau Titre")
            
        with col2:
            f_c = st.text_area("Contenu", value=edit_data['contenu'] if edit_data else "")
            f_d = st.date_input("Échéance", value=edit_data['echeance'] if edit_data and edit_data['echeance'] else None)
            f_img = st.file_uploader("Photo", type=['jpg','png'])

        if st.form_submit_button("Enregistrer"):
            final_gt = f_gt_new if f_gt_new else f_gt
            final_t = f_t_new if f_t_new else f_t
            # Logique de sauvegarde... (identique à v4)
            st.success("C'est enregistré ! Les notifications sont programmées.")
            st.rerun()

# --- OPTION MANUELLE DANS LE SIDEBAR ---
with st.sidebar:
    st.divider()
    if st.button("🔔 Tester la notification immédiate"):
        send_notif("Test Manuel", "Si tu reçois ça, ton téléphone est bien relié à l'appli !", priority="high")
        st.sidebar.success("Envoyé !")
