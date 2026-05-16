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

if 'edit_item_idx' not in st.session_state: st.session_state['edit_item_idx'] = None

# --- FORMULAIRE ---
def show_saisie_form(idx_e=None):
    global df
    edit_r = df.loc[idx_e] if idx_e is not None else None
    st.subheader("🖊️ Saisie" if idx_e is None else "✏️ Modification")
    with st.form(f"form_{idx_e if idx_e else 'new'}"):
        c1, c2 = st.columns(2)
        with c1:
            l_gt = sorted(list(set([str(x) for x in df['gros_titre'] if x])))
            idx_gt = l_gt.index(edit_r['gros_titre'])+1 if (edit_r is not None and edit_r['gros_titre'] in l_gt) else 0
            f_gt = st.selectbox("Dossier", [""] + l_gt, index=idx_gt)
            f_gt_n = st.text_input("OU Nouveau Dossier")
            l_t = sorted(list(set([str(x) for x in df['titre'] if x])))
            idx_t = l_t.index(edit_r['titre'])+1 if (edit_r is not None and edit_r['titre'] in l_t) else 0
            f_t = st.selectbox("Titre", [""] + l_t, index=idx_t)
            f_t_n = st.text_input("OU Nouveau Titre")
            f_gtype = st.radio("Type calendrier :", ["Événement (Heure)", "Tâche (Journée)"], index=0 if (edit_r is None or edit_r['google_type'] != "Tâche (Journée)") else 1)
        with c2:
            f_c = st.text_area("Contenu", value=edit_r['contenu'] if edit_r is not None else "")
            f_d = st.date_input("Date", value=edit_r['dt_obj'].date() if (edit_r is not None and not pd.isna(edit_r['dt_obj'])) else None)
            f_h = st.time_input("Heure", value=edit_r['dt_obj'].time() if (edit_r is not None and not pd.isna(edit_r['dt_obj'])) else time(8,0))
            f_img = st.file_uploader("Photo")

        if st.form_submit_button("💾 ENREGISTRER"):
            f_gt_f, f_t_f = (f_gt_n if f_gt_n else f_gt), (f_t_n if f_t_n else f_t)
            date_s = datetime.combine(f_d, f_h).strftime('%Y-%m-%d %H:%M:%S') if f_d else ""
            b64 = str(edit_r['image_b64']) if (edit_r is not None) else ""
            if f_img:
                img = Image.open(f_img)
                if img.mode in ("RGBA", "P"): img = img.convert("RGB")
                img.thumbnail((400, 400))
                buf = io.BytesIO(); img.save(buf, format="JPEG", quality=70)
                b64 = base64.b64encode(buf.getvalue()).decode()
            
            temp_r = {'titre': f_t_f, 'gros_titre': f_gt_f, 'contenu': f_c, 'echeance': date_s, 
                      'type': "Task" if f_d else "Note", 'cal_event_id': edit_r['cal_event_id'] if edit_r is not None else "", 'google_type': f_gtype}
            new_cal = upsert_calendar_event(temp_r)

            if idx_e is not None:
                df.at[idx_e, 'gros_titre'], df.at[idx_e, 'titre'], df.at[idx_e, 'contenu'] = f_gt_f, f_t_f, f_c
                df.at[idx_e, 'echeance'], df.at[idx_e, 'type'], df.at[idx_e, 'image_b64'] = date_s, ("Task" if f_d else "Note"), b64
                df.at[idx_e, 'cal_event_id'], df.at[idx_e, 'google_type'] = new_cal, f_gtype
            else:
                nid = int(pd.to_numeric(df['id'], errors='coerce').max() + 1) if not df.empty else 1
                new_row = {"id": str(nid), "gros_titre": f_gt_f, "titre": f_t_f, "contenu": f_c, "echeance": date_s, 
                           "type": ("Task" if f_d else "Note"), "status": "En cours", "image_b64": b64, "cal_event_id": new_cal, "google_type": f_gtype}
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            save_data(df); st.session_state['edit_item_idx'] = None; st.rerun()

# --- COMPOSANT CARTE ---
def item_card(idx, row, is_overdue=False, key_suffix=""):
    color = "#FF4B4B" if is_overdue else "#31333F"
    with st.container(border=True):
        if is_overdue: st.markdown("🚨 **PIMPON ! RETARD** 🚨", unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns([0.1, 0.5, 0.3, 0.1])
        with c1:
            if row['status'] != 'Terminé':
                if st.checkbox("Fait", key=f"c_{idx}_{key_suffix}", label_visibility="collapsed"):
                    delete_calendar_event(row['cal_event_id'])
                    df.at[idx, 'status'], df.at[idx, 'date_archive'] = 'Terminé', datetime.now().strftime('%Y-%m-%d')
                    save_data(df); st.rerun()
            else:
                if st.button("🔄", key=f"r_{idx}_{key_suffix}"):
                    new_cal = upsert_calendar_event(row.to_dict())
                    df.at[idx, 'status'], df.at[idx, 'date_archive'], df.at[idx, 'cal_event_id'] = 'En cours', "", new_cal
                    save_data(df); st.rerun()
        with c2:
            st.markdown(f"<span style='color:{color}; font-weight:bold;'>{row['gros_titre']} > {row['titre']}</span>", unsafe_allow_html=True)
            st.write(row['contenu'])
            # --- FIX IMAGE ULTRA-SÉCURISÉ ---
            img_raw = row.get('image_b64', "")
            if isinstance(img_raw, str) and len(img_raw) > 50:
                try: st.image(base64.b64decode(img_raw), width=250)
                except: pass
        with c3:
            if row['type'] == 'Task' and not pd.isna(row['dt_obj']):
                st.markdown(f"<span style='color:{color}'>📅 {row['dt_obj'].strftime('%d/%m/%Y %H:%M')}</span>", unsafe_allow_html=True)
            else: st.caption("📝 Note")
        with c4:
            if st.button("✏️", key=f"ed_{idx}_{key_suffix}"):
                st.session_state['edit_item_idx'] = idx; st.rerun()

# --- AFFICHAGE ---
if st.session_state['edit_item_idx'] is not None:
    show_saisie_form(st.session_state['edit_item_idx'])
    if st.button("❌ Annuler"): st.session_state['edit_item_idx'] = None; st.rerun()
    st.divider()

tabs = st.tabs(["☀️ Jour", "📅 Semaine", "📊 Mois", "📂 Thèmes", "📝 Notes", "🗄️ Archive", "🖊️ Saisie"])
active = df[df['status'] == 'En cours'].copy()
if not active.empty: active = active.sort_values('dt_obj', ascending=True)

with tabs[0]:
    ov = active[(active['type'] == 'Task') & (active['dt_obj'] < now_ts)]
    for idx, r in ov.iterrows(): item_card(idx, r, is_overdue=True, key_suffix="ov")
    tod = active[(active['type'] == 'Task') & (active['dt_obj'].dt.date == now_ts.date()) & (active['dt_obj'] >= now_ts)]
    for idx, r in tod.iterrows(): item_card(idx, r, key_suffix="tod")

with tabs[1]:
    wk = active[(active['dt_obj'].dt.date > now_ts.date()) & (active['dt_obj'].dt.date <= now_ts.date() + timedelta(days=7))]
    for idx, r in wk.iterrows(): item_card(idx, r, key_suffix="wk")

with tabs[2]:
    mo = active[(active['dt_obj'].dt.date > now_ts.date() + timedelta(days=7)) & (active['dt_obj'].dt.date <= now_ts.date() + timedelta(days=30))]
    for idx, r in mo.iterrows(): item_card(idx, r, key_suffix="mo")

with tabs[3]:
    for gt in sorted(active['gros_titre'].unique()):
        with st.expander(f"📁 {gt}"):
            sub = active[active['gros_titre'] == gt].sort_values('dt_obj', ascending=True)
            for idx, r in sub.iterrows(): item_card(idx, r, key_suffix="th")

with tabs[4]:
    for idx, r in active[active['type'] == 'Note'].iterrows(): item_card(idx, r, key_suffix="nt")

with tabs[5]:
    arc = df[df['status'] == 'Terminé'].copy()
    for idx, r in arc.sort_values('id', ascending=False).iterrows(): item_card(idx, r, key_suffix="arc")

with tabs[6]:
    if st.session_state['edit_item_idx'] is None: show_saisie_form()

with st.sidebar:
    if st.button("🔔 Test Notif"): send_notif("Test", "Signal Pimpon !")
    if st.button("🚪 Déconnexion"): del st.session_state["password_correct"]; st.rerun()
