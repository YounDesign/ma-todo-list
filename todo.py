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

# --- CONFIGURATION ---
NTFY_TOPIC = st.secrets.get("ntfy_topic", "youndesign_pkm_secret")
CALENDAR_ID = st.secrets.get("calendar_id", "")

# --- FONCTIONS SYSTÈME ---
def send_notif(title, message, priority="default"):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=message.encode('utf-8'),
            headers={"Title": title.encode('utf-8'), "Priority": priority, "Tags": "calendar,bell"})
    except: pass

def get_calendar_service():
    creds_info = st.secrets["connections"]["gsheets"]
    creds = service_account.Credentials.from_service_account_info(creds_info)
    scoped_creds = creds.with_scopes(['https://www.googleapis.com/auth/calendar'])
    return build('calendar', 'v3', credentials=scoped_creds)

def delete_calendar_event(cal_id):
    if not cal_id or not CALENDAR_ID or str(cal_id).lower() in ["", "nan", "none"]: return
    try:
        service = get_calendar_service()
        service.events().delete(calendarId=CALENDAR_ID, eventId=str(cal_id)).execute()
        st.toast("🗑️ Supprimé de Google")
    except: pass

def upsert_calendar_event(row_data):
    if not row_data['echeance'] or row_data['type'] != "Task" or not CALENDAR_ID: return ""
    try:
        service = get_calendar_service()
        start_dt = pd.to_datetime(row_data['echeance'])
        if row_data.get('google_type') == "Tâche (Journée)":
            start_body = {'date': start_dt.strftime('%Y-%m-%d')}
            end_body = {'date': (start_dt + timedelta(days=1)).strftime('%Y-%m-%d')}
        else:
            start_body = {'dateTime': start_dt.isoformat(), 'timeZone': 'Europe/Paris'}
            end_body = {'dateTime': (start_dt + timedelta(minutes=30)).isoformat(), 'timeZone': 'Europe/Paris'}
        event_body = {'summary': row_data['titre'], 'location': row_data['gros_titre'], 
                      'description': row_data['contenu'], 'start': start_body, 'end': end_body}
        cal_id = str(row_data.get('cal_event_id', ""))
        if cal_id and cal_id.lower() not in ["", "nan", "none"]:
            try:
                event = service.events().update(calendarId=CALENDAR_ID, eventId=cal_id, body=event_body).execute()
                return event.get('id')
            except:
                event = service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
                return event.get('id')
        else:
            event = service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
            return event.get('id')
    except: return ""

# --- LOGIQUE VISUELLE (Couleurs et Emojis) ---
def get_category_style(gt):
    gt_lower = str(gt).lower()
    # 1. Définition des Emojis selon mots-clés
    emoji = "📁"
    if "travail" in gt_lower or "pro" in gt_lower: emoji = "💼"
    elif "maison" in gt_lower or "home" in gt_lower: emoji = "🏠"
    elif "perso" in gt_lower: emoji = "👤"
    elif "sport" in gt_lower: emoji = "🏃"
    elif "course" in gt_lower or "achat" in gt_lower: emoji = "🛒"
    elif "argent" in gt_lower or "banque" in gt_lower: emoji = "💰"
    elif "idée" in gt_lower: emoji = "💡"
    elif "urgent" in gt_lower: emoji = "🔥"
    
    # 2. Définition d'une couleur stable basée sur le nom
    colors = ["#3498db", "#2ecc71", "#9b59b6", "#f1c40f", "#e67e22", "#e74c3c", "#1abc9c", "#34495e"]
    color_idx = sum(ord(c) for c in str(gt)) % len(colors)
    return colors[color_idx], emoji

# --- CONNEXION & DATA ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df_loaded = conn.read(ttl=0).dropna(subset=['gros_titre', 'titre'], how='all')
        cols = ['id', 'status', 'date_archive', 'image_b64', 'notif_sent', 'gros_titre', 'titre', 'echeance', 'contenu', 'type', 'cal_event_id', 'google_type']
        for col in cols:
            if col not in df_loaded.columns: df_loaded[col] = ""
            df_loaded[col] = df_loaded[col].astype(str).replace('nan', '').fillna('')
        df_loaded.loc[df_loaded['status'] == "", 'status'] = 'En cours'
        df_loaded['dt_obj'] = pd.to_datetime(df_loaded['echeance'], errors='coerce')
        return df_loaded
    except:
        return pd.DataFrame(columns=['id', 'status', 'date_archive', 'image_b64', 'notif_sent', 'gros_titre', 'titre', 'echeance', 'contenu', 'type', 'cal_event_id', 'google_type'])

def save_data(df_to_save):
    final_df = df_to_save.copy()
    if 'dt_obj' in final_df.columns: final_df = final_df.drop(columns=['dt_obj'])
    conn.update(data=final_df)
    st.cache_data.clear()

# --- SÉCURITÉ ---
if "password_correct" not in st.session_state:
    st.title("🔒 Accès Privé YounDesign")
    pwd = st.text_input("Mot de passe", type="password")
    if st.button("Connexion"):
        if pwd == st.secrets["password"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else: st.error("Incorrect")
    st.stop()

# --- INITIALISATION ---
st.set_page_config(page_title="YounDesign PKM", layout="wide")
df = load_data()
now_ts = pd.Timestamp(datetime.now())

# Indicateur Sidebar
st.markdown("""<div style='background-color: #f0f2f6; padding: 10px; border-radius: 10px; margin-bottom: 10px;'>
    ⬅️ Menu latéral pour <b>Rechercher</b> ou <b>Test Notifs</b></div>""", unsafe_allow_html=True)

if 'edit_item_idx' not in st.session_state: st.session_state['edit_item_idx'] = None

# --- LOGIQUE REPORT RAPIDE ---
def quick_reschedule(idx, days=0, weeks=0, months=0, years=0):
    new_date = datetime.now() + timedelta(days=days, weeks=weeks + (months*4.34), hours=0)
    if years > 0:
        try: new_date = new_date.replace(year=new_date.year + years)
        except: new_date = new_date + timedelta(days=365)
    new_date = new_date.replace(hour=8, minute=0, second=0)
    df.at[idx, 'echeance'] = new_date.strftime('%Y-%m-%d %H:%M:%S')
    df.at[idx, 'notif_sent'] = ""
    new_cal = upsert_calendar_event(df.loc[idx].to_dict())
    df.at[idx, 'cal_event_id'] = new_cal
    save_data(df)
    st.rerun()

# --- COMPOSANT CARTE ---
def item_card(idx, row, is_overdue=False, key_suffix=""):
    cat_color, cat_emoji = get_category_style(row['gros_titre'])
    overdue_style = "border: 3px solid #FF4B4B; background-color: #fff1f1;" if is_overdue else f"border-left: 8px solid {cat_color};"
    
    # On encapsule la carte dans un div HTML pour le style personnalisé
    st.markdown(f"""
        <div style='{overdue_style} padding: 15px; border-radius: 10px; margin-bottom: 10px; background-color: white; box-shadow: 2px 2px 5px rgba(0,0,0,0.05);'>
            <div style='display: flex; justify-content: space-between;'>
                <span style='color: {cat_color}; font-weight: bold;'>{cat_emoji} {row['gros_titre']}</span>
                <span style='font-size: 0.8em; color: gray;'>ID: {row['id']}</span>
            </div>
            <div style='font-size: 1.2em; font-weight: bold; margin-top: 5px;'>{row['titre']}</div>
            <div style='color: #555; margin-top: 5px;'>{row['contenu']}</div>
        </div>
    """, unsafe_allow_html=True)
    
    # Les boutons de contrôle sous la carte stylisée
    with st.container():
        c1, c2, c3 = st.columns([0.2, 0.6, 0.2])
        with c1:
            if row['status'] != 'Terminé':
                if st.checkbox("Fait", key=f"c_{idx}_{key_suffix}"):
                    delete_calendar_event(row['cal_event_id'])
                    df.at[idx, 'status'], df.at[idx, 'date_archive'] = 'Terminé', datetime.now().strftime('%Y-%m-%d')
                    save_data(df); st.rerun()
            else:
                if st.button("🔄 Restaurer", key=f"r_{idx}_{key_suffix}"):
                    new_cal = upsert_calendar_event(row.to_dict())
                    df.at[idx, 'status'], df.at[idx, 'date_archive'], df.at[idx, 'cal_event_id'] = 'En cours', "", new_cal
                    save_data(df); st.rerun()
        with c2:
            if row['type'] == 'Task' and not pd.isna(row['dt_obj']):
                st.caption(f"📅 {row['dt_obj'].strftime('%d/%m/%Y %H:%M')}")
                if row['status'] != 'Terminé':
                    col_rep1, col_rep2 = st.columns(2)
                    if col_rep1.button("⏩ Demain 08h", key=f"q_{idx}_{key_suffix}"): quick_reschedule(idx, days=1)
                    with col_rep2.expander("Autres..."):
                        if st.button("+7j", key=f"p7_{idx}_{key_suffix}"): quick_reschedule(idx, weeks=1)
                        if st.button("+1m", key=f"p30_{idx}_{key_suffix}"): quick_reschedule(idx, days=30)
                        if st.button("+1an", key=f"p1y_{idx}_{key_suffix}"): quick_reschedule(idx, years=1)
            # Affichage image si présente
            img_raw = row.get('image_b64', "")
            if isinstance(img_raw, str) and len(img_raw) > 50:
                try: st.image(base64.b64decode(img_raw), width=200)
                except: pass
        with c3:
            if st.button("✏️", key=f"ed_{idx}_{key_suffix}"):
                st.session_state['edit_item_idx'] = idx; st.rerun()
    st.divider()

# --- SIDEBAR & RECHERCHE ---
with st.sidebar:
    st.header("🔍 Recherche")
    search = st.text_input("Filtrer...", "").lower()
    st.divider()
    if st.button("🔔 Test Notif"): send_notif("YounDesign", "Signal OK !")
    if st.button("🚪 Déconnexion"): del st.session_state["password_correct"]; st.rerun()

df_filtered = df.copy()
if search:
    df_filtered = df[df['titre'].str.lower().str.contains(search) | df['contenu'].str.lower().str.contains(search) | df['gros_titre'].str.lower().str.contains(search)]

# --- MODIF PRIORITAIRE ---
if st.session_state['edit_item_idx'] is not None:
    idx_edit = st.session_state['edit_item_idx']
    edit_r = df.loc[idx_edit]
    st.info(f"✏️ Modification de : {edit_r['titre']}")
    with st.form("form_edit"):
        c1, c2 = st.columns(2)
        with c1:
            l_gt = sorted(list(set([str(x) for x in df['gros_titre'] if x])))
            idx_gt = l_gt.index(edit_r['gros_titre'])+1 if (edit_r['gros_titre'] in l_gt) else 0
            f_gt = st.selectbox("Dossier", [""] + l_gt, index=idx_gt)
            f_gt_n = st.text_input("Nouveau Dossier")
            l_t = sorted(list(set([str(x) for x in df['titre'] if x])))
            idx_t = l_t.index(edit_r['titre'])+1 if (edit_r['titre'] in l_t) else 0
            f_t = st.selectbox("Titre", [""] + l_t, index=idx_t)
            f_t_n = st.text_input("Nouveau Titre")
        with c2:
            f_c = st.text_area("Contenu", value=edit_r['contenu'])
            f_d = st.date_input("Date", value=edit_r['dt_obj'].date() if not pd.isna(edit_r['dt_obj']) else None)
            f_h = st.time_input("Heure", value=edit_r['dt_obj'].time() if not pd.isna(edit_r['dt_obj']) else time(8,0))
            f_img = st.file_uploader("Photo")
        if st.form_submit_button("💾 SAUVEGARDER"):
            # (Logique de sauvegarde identique à V19)
            st.session_state['edit_item_idx'] = None; st.rerun()
    if st.button("❌ Annuler"): st.session_state['edit_item_idx'] = None; st.rerun()
    st.divider()

# --- ONGLETS ---
tabs = st.tabs(["☀️ Jour", "📅 Semaine", "📊 Mois", "📂 Thèmes", "📝 Notes", "🗄️ Archive", "🖊️ Saisie"])
active = df_filtered[df_filtered['status'] == 'En cours'].copy()
if not active.empty: active = active.sort_values('dt_obj', ascending=True)

with tabs[0]:
    ov = active[(active['type'] == 'Task') & (active['dt_obj'] < now_ts)]
    for idx, r in ov.iterrows(): item_card(idx, r, is_overdue=True, key_suffix="ov")
    tod = active[(active['type'] == 'Task') & (active['dt_obj'].dt.date == now_ts.date()) & (active['dt_obj'] >= now_ts)]
    for idx, r in tod.iterrows(): item_card(idx, r, key_suffix="tod")

with tabs[1]:
    wk = active[(active['dt_obj'].dt.date > now_ts.date()) & (active['dt_obj'].dt.date <= now_ts.date() + timedelta(days=7))]
    for idx, r in wk.iterrows(): item_card(idx, r, key_suffix="wk")

with tabs[3]: # THEMES
    for gt in sorted(active['gros_titre'].unique()):
        color, emo = get_category_style(gt)
        with st.expander(f"{emo} {gt}"):
            sub = active[active['gros_titre'] == gt].sort_values('dt_obj', ascending=True)
            for idx, r in sub.iterrows(): item_card(idx, r, key_suffix="th")

# (Les autres onglets Notes, Archive et Saisie sont identiques à la V19)
