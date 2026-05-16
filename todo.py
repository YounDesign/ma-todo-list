import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta, time
import requests
import base64
import io
from PIL import Image
from googleapiclient.discovery import build
from google.oauth2 import service_account

# --- CONFIGURATION (Secrets) ---
NTFY_TOPIC = st.secrets.get("ntfy_topic", "youndesign_pkm_secret")
CALENDAR_ID = st.secrets.get("calendar_id", "")

# --- FONCTIONS GOOGLE CALENDAR ---
def get_calendar_service():
    creds_info = st.secrets["connections"]["gsheets"]
    creds = service_account.Credentials.from_service_account_info(creds_info)
    scoped_creds = creds.with_scopes(['https://www.googleapis.com/auth/calendar'])
    return build('calendar', 'v3', credentials=scoped_creds)

def sync_calendar_to_app(df):
    """SENS : AGENDA -> APP. Récupère les modifs faites sur le téléphone."""
    if not CALENDAR_ID: return df
    try:
        service = get_calendar_service()
        # On regarde 7 jours en arrière et 30 jours en avant
        time_min = (datetime.utcnow() - timedelta(days=7)).isoformat() + 'Z'
        events_result = service.events().list(calendarId=CALENDAR_ID, timeMin=time_min,
                                              singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        
        changed = False
        for event in events:
            cal_id = event['id']
            summary = event.get('summary', 'Sans titre')
            desc = event.get('description', '')
            start = event['start'].get('dateTime', event['start'].get('date'))
            # Formatage de la date Google vers notre format Sheet
            new_date_str = pd.to_datetime(start).strftime('%Y-%m-%d %H:%M:%S')

            # Cas 1 : L'événement existe déjà dans notre liste
            if cal_id in df['cal_event_id'].values:
                idx = df[df['cal_event_id'] == cal_id].index[0]
                # On met à jour si la date ou le titre a changé sur le tel
                if df.at[idx, 'echeance'] != new_date_str or df.at[idx, 'titre'] != summary:
                    df.at[idx, 'titre'] = summary
                    df.at[idx, 'echeance'] = new_date_str
                    df.at[idx, 'contenu'] = desc if desc else df.at[idx, 'contenu']
                    changed = True
            # Cas 2 : Nouvel événement créé directement sur Google Calendar
            else:
                numeric_ids = pd.to_numeric(df['id'], errors='coerce').dropna()
                new_id = int(numeric_ids.max() + 1) if not numeric_ids.empty else 1
                new_row = {
                    "id": new_id, "gros_titre": "📥 Agenda", "titre": summary, 
                    "contenu": desc, "echeance": new_date_str, "type": "Task", 
                    "status": "En cours", "date_archive": "", "image_b64": "", 
                    "notif_sent": "", "cal_event_id": cal_id
                }
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                changed = True
        
        if changed:
            save_data(df)
            st.toast("🔄 Synchronisé avec Google Calendar")
        return df
    except: return df

def upsert_calendar_event(row_data):
    """SENS : APP -> AGENDA. Crée ou modifie l'événement sur Google."""
    if not row_data['echeance'] or row_data['type'] != "Task" or not CALENDAR_ID: return ""
    try:
        service = get_calendar_service()
        start_dt = pd.to_datetime(row_data['echeance'])
        event_body = {
            'summary': row_data['titre'],
            'location': row_data['gros_titre'],
            'description': row_data['contenu'],
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Europe/Paris'},
            'end': {'dateTime': (start_dt + timedelta(minutes=30)).isoformat(), 'timeZone': 'Europe/Paris'},
        }
        if row_data.get('cal_event_id') and row_data['cal_event_id'] != "":
            event = service.events().update(calendarId=CALENDAR_ID, eventId=row_data['cal_event_id'], body=event_body).execute()
        else:
            event = service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
        return event.get('id')
    except: return ""

# --- (Le reste des fonctions load_data, save_data, send_notif est identique) ---
# --- CONNEXION ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df = conn.read(ttl=0)
        df = df.dropna(subset=['gros_titre', 'titre'], how='all')
        cols = ['id', 'status', 'date_archive', 'image_b64', 'notif_sent', 'gros_titre', 'titre', 'echeance', 'contenu', 'type', 'cal_event_id']
        for col in cols:
            if col not in df.columns: df[col] = ""
            df[col] = df[col].astype(str).replace('nan', '')
        df['dt_obj'] = pd.to_datetime(df['echeance'], errors='coerce')
        return df
    except: return pd.DataFrame(columns=['id','status','date_archive','image_b64','notif_sent','gros_titre','titre','echeance','contenu','type','cal_event_id'])

# --- MOTEUR ET SÉCURITÉ ---
df = load_data()
df = sync_calendar_to_app(df) # <-- SYNCHRO AU DÉMARRAGE

# ... (Vérification mot de passe et interface) ...

# --- DANS TON BOUTON ENREGISTRER (Onglet Saisie) ---
if st.form_submit_button("💾 ENREGISTRER TOUT"):
    # (Logique de préparation des titres, dates et images...)
    
    # Appel App -> Agenda
    temp_row = {'titre': final_t, 'gros_titre': final_gt, 'contenu': f_c, 'echeance': date_s, 'type': "Task", 'cal_event_id': edit_r['cal_event_id'] if edit_r is not None else ""}
    new_cal_id = upsert_calendar_event(temp_row)
    
    # (Enregistrement dans le DataFrame et save_data(df))
    # ...
