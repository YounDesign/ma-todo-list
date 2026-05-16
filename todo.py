import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta, time
import requests
import base64
import io
from PIL import Image

# --- CONFIGURATION ---
NTFY_TOPIC = "youndesign_pkm_secret" # <--- METS TON NOM UNIQUE ICI

def send_notif(title, message, priority="default"):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=message.encode('utf-8'),
            headers={"Title": title.encode('utf-8'), "Priority": priority, "Tags": "calendar,bell"})
    except: pass

# --- CONNEXION & CHARGEMENT (Avant le mot de passe pour le Cron-job) ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df = conn.read(ttl=0)
        for col in ['status', 'date_archive', 'image_b64', 'notif_sent', 'gros_titre', 'titre', 'echeance']:
            if col not in df.columns: df[col] = ""
            df[col] = df[col].astype(str).replace('nan', '')
        df['dt_obj'] = pd.to_datetime(df['echeance'], errors='coerce')
        return df
    except:
        return pd.DataFrame(columns=["id", "gros_titre", "titre", "contenu", "echeance", "type", "status", "date_archive", "image_b64", "notif_sent"])

def save_data(df_to_save):
    if 'dt_obj' in df_to_save.columns: df_to_save = df_to_save.drop(columns=['dt_obj'])
    conn.update(data=df_to_save)
    st.cache_data.clear()

# --- MOTEUR DE NOTIFICATIONS (S'exécute même sans mot de passe) ---
df = load_data()
now = datetime.now()

# 1. Notif à l'heure pile (Real-time)
mask_now = (df['status'] == 'En cours') & (df['dt_obj'] <= now) & (df['notif_sent'] != 'OUI')
for idx, row in df[mask_now].iterrows():
    send_notif(f"⏰ MAINTENANT : {row['titre']}", row['contenu'], priority="high")
    df.at[idx, 'notif_sent'] = 'OUI'
    save_data(df)

# 2. Notif Veille & Hebdo (Une fois par jour max)
# (Optionnel : On pourrait ajouter une table log_notif pour éviter les doublons ici)

# --- VÉRIFICATION DU MOT DE PASSE (Pour l'interface seulement) ---
def check_password():
    if "password_correct" not in st.session_state:
        st.title("🔒 Accès Privé YounDesign")
        pwd = st.text_input("Code d'accès", type="password")
        if st.button("Entrer"):
            if pwd == st.secrets["password"]:
                st.session_state["password_correct"] = True
                st.rerun()
            else: st.error("Code erroné")
        return False
    return True

if check_password():
    st.set_page_config(page_title="YounDesign PKM", layout="wide")
    
    # --- INTERFACE DES ONGLETS ---
    tabs = st.tabs(["☀️ Jour", "📅 Semaine", "📊 Mois", "📂 Thèmes", "🗄️ Archive", "🖊️ Saisie"])

    # (Ici tu remets toute la logique d'affichage des cartes et formulaires des versions précédentes)
    # ...

    with st.sidebar:
        st.header("⚙️ Paramètres")
        if st.button("🔔 TEST : Notif Immédiate"):
            send_notif("Test YounDesign", "Le signal arrive bien sur ton téléphone !", priority="high")
            st.success("Signal envoyé !")
        
        if st.button("🚪 Déconnexion"):
            del st.session_state["password_correct"]
            st.rerun()
