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

def upsert_calendar_event(row_data):
    if not row_data['echeance'] or row_data['type'] != "Task" or not CALENDAR_ID:
        return row_data.get('cal_event_id', "")
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
        cal_id = str(row_data.get('cal_event_id', ""))
        if cal_id and cal_id not in ["", "nan", "None"]:
            try:
                event = service.events().update(calendarId=CALENDAR_ID, eventId=cal_id, body=event_body).execute()
                return event.get('id')
            except:
                event = service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
                return event.get('id')
        else:
            event = service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
            return event.get('id')
    except: return row_data.get('cal_event_id', "")

# --- CONNEXION & DATA ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df = conn.read(ttl=0).dropna(subset=['gros_titre', 'titre'], how='all')
        cols = ['id', 'status', 'date_archive', 'image_b64', 'notif_sent', 'gros_titre', 'titre', 'echeance', 'contenu', 'type', 'cal_event_id']
        for col in cols:
            if col not in df.columns: df[col] = ""
            df[col] = df[col].astype(str).replace('nan', '')
        df.loc[df['status'] == "", 'status'] = 'En cours'
        df['dt_obj'] = pd.to_datetime(df['echeance'], errors='coerce')
        df['date_archive_dt'] = pd.to_datetime(df['date_archive'], errors='coerce')
        return df
    except:
        return pd.DataFrame(columns=['id', 'status', 'date_archive', 'image_b64', 'notif_sent', 'gros_titre', 'titre', 'echeance', 'contenu', 'type', 'cal_event_id'])

def save_data(df_to_save):
    final_df = df_to_save.drop(columns=['dt_obj', 'date_archive_dt'], errors='ignore')
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

# --- INITIALISATION INTERFACE ---
st.set_page_config(page_title="YounDesign PKM", layout="wide")
df = load_data()
now_ts = pd.Timestamp(datetime.now())
today = now_ts.date()

if 'edit_item_idx' not in st.session_state: 
    st.session_state['edit_item_idx'] = None

# --- COMPOSANT FORMULAIRE (Unique pour Ajout et Modif) ---
def show_saisie_form(idx_e=None):
    edit_r = df.loc[idx_e] if idx_e is not None else None
    st.subheader("🖊️ Saisie rapide" if idx_e is None else "✏️ Modification en cours")
    
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
        with c2:
            f_c = st.text_area("Contenu", value=edit_r['contenu'] if edit_r is not None else "")
            f_d = st.date_input("Date", value=edit_r['dt_obj'].date() if (edit_r is not None and not pd.isna(edit_r['dt_obj'])) else None)
            f_h = st.time_input("Heure", value=edit_r['dt_obj'].time() if (edit_r is not None and not pd.isna(edit_r['dt_obj'])) else time(8,0))
            f_img = st.file_uploader("Photo", type=['jpg', 'png', 'jpeg'])

        if st.form_submit_button("💾 ENREGISTRER TOUT"):
            final_gt, final_t = (f_gt_n if f_gt_n else f_gt), (f_t_n if f_t_n else f_t)
            date_s = datetime.combine(f_d, f_h).strftime('%Y-%m-%d %H:%M:%S') if f_d else ""
            
            # FIX IMAGE JPEG CRASH
            b64 = edit_r['image_b64'] if (edit_r is not None) else ""
            if f_img:
                img = Image.open(f_img)
                if img.mode in ("RGBA", "P"): # Convertir si transparence (PNG)
                    img = img.convert("RGB")
                img.thumbnail((400, 400))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70) # Maintenant garanti RGB
                b64 = base64.b64encode(buf.getvalue()).decode()
            
            temp_r = {'titre': final_t, 'gros_titre': final_gt, 'contenu': f_c, 'echeance': date_s, 'type': "Task" if f_d else "Note", 'cal_event_id': edit_r['cal_event_id'] if edit_r is not None else ""}
            new_cal_id = upsert_calendar_event(temp_r)

            if idx_e is not None:
                df.at[idx_e, 'gros_titre'], df.at[idx_e, 'titre'], df.at[idx_e, 'contenu'] = final_gt, final_t, f_c
                df.at[idx_e, 'echeance'], df.at[idx_e, 'type'], df.at[idx_e, 'image_b64'] = date_s, ("Task" if f_d else "Note"), b64
                df.at[idx_e, 'cal_event_id'] = new_cal_id
                df.at[idx_e, 'notif_sent'] = ""
            else:
                ids = pd.to_numeric(df['id'], errors='coerce').dropna()
                nid = int(ids.max() + 1) if not ids.empty else 1
                new_row = {"id": str(nid), "gros_titre": final_gt, "titre": final_t, "contenu": f_c, "echeance": date_s, "type": ("Task" if f_d else "Note"), "status": "En cours", "date_archive": "", "image_b64": b64, "notif_sent": "", "cal_event_id": new_cal_id}
                global df
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            
            save_data(df)
            st.session_state['edit_item_idx'] = None
            st.success("Synchronisé !")
            st.rerun()
    
    if idx_e is not None:
        if st.button("❌ Annuler la modification"):
            st.session_state['edit_item_idx'] = None
            st.rerun()

# --- COMPOSANT CARTE ---
def item_card(idx, row, is_overdue=False, key_suffix=""):
    color = "#FF4B4B" if is_overdue else "#31333F"
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([0.1, 0.5, 0.3, 0.1])
        with c1:
            if row['status'] != 'Terminé':
                if st.checkbox("Fait", key=f"c_{idx}_{key_suffix}", label_visibility="collapsed"):
                    df.at[idx, 'status'], df.at[idx, 'date_archive'] = 'Terminé', datetime.now().strftime('%Y-%m-%d')
                    save_data(df); st.rerun()
            else:
                if st.button("🔄", key=f"r_{idx}_{key_suffix}"):
                    df.at[idx, 'status'], df.at[idx, 'date_archive'], df.at[idx, 'notif_sent'] = 'En cours', "", ""
                    save_data(df); st.rerun()
        with c2:
            st.markdown(f"**{row['gros_titre']}** > {row['titre']}")
            st.write(row['contenu'])
            img_data = row.get('image_b64', "")
            if isinstance(img_data, str) and len(img_data) > 50:
                try: st.image(base64.b64decode(img_data), width=250)
                except: pass
        with c3:
            if row['type'] == 'Task' and not pd.isna(row['dt_obj']):
                st.markdown(f"<span style='color:{color}'>📅 {row['dt_obj'].strftime('%d/%m/%Y %H:%M')}</span>", unsafe_allow_html=True)
            else: st.caption("📝 Note")
        with c4:
            if st.button("✏️", key=f"ed_{idx}_{key_suffix}"):
                st.session_state['edit_item_idx'] = idx
                st.rerun()

# --- LOGIQUE D'AFFICHAGE ---
# Si on est en train de modifier, on affiche le formulaire DIRECTEMENT en haut
if st.session_state['edit_item_idx'] is not None:
    show_saisie_form(st.session_state['edit_item_idx'])
    st.divider()

# Ensuite on affiche les onglets normaux
tabs = st.tabs(["☀️ Jour", "📅 Semaine", "📊 Mois", "📂 Thèmes", "📝 Notes", "🗄️ Archive", "🖊️ Saisie"])
active = df[df['status'] == 'En cours']

with tabs[0]:
    ov = active[(active['type'] == 'Task') & (active['dt_obj'] < now_ts)]
    for idx, r in ov.iterrows(): item_card(idx, r, is_overdue=True, key_suffix="ov")
    tod = active[(active['type'] == 'Task') & (active['dt_obj'].dt.date == today) & (active['dt_obj'] >= now_ts)]
    for idx, r in tod.iterrows(): item_card(idx, r, key_suffix="tod")

with tabs[1]:
    wk = active[(active['dt_obj'].dt.date > today) & (active['dt_obj'].dt.date <= today + timedelta(days=7))]
    for idx, r in wk.iterrows(): item_card(idx, r, key_suffix="wk")

with tabs[2]:
    mo = active[(active['dt_obj'].dt.date > today + timedelta(days=7)) & (active['dt_obj'].dt.date <= today + timedelta(days=30))]
    for idx, r in mo.iterrows(): item_card(idx, r, key_suffix="mo")

with tabs[3]:
    for gt in sorted(active['gros_titre'].unique()):
        with st.expander(f"📁 {gt}"):
            for idx, r in active[active['gros_titre'] == gt].iterrows(): item_card(idx, r, key_suffix="th")

with tabs[4]:
    for idx, r in active[active['type'] == 'Note'].iterrows(): item_card(idx, r, key_suffix="nt")

with tabs[5]:
    arc = df[df['status'] == 'Terminé']
    for idx, r in arc.sort_values('date_archive', ascending=False).iterrows(): item_card(idx, r, key_suffix="arc")

with tabs[6]:
    if st.session_state['edit_item_idx'] is None:
        show_saisie_form()
    else:
        st.info("Formulaire de modification affiché en haut de page.")

with st.sidebar:
    if st.button("🔔 Test Notif"): send_notif("Test", "Liaison OK !")
    if st.button("🚪 Déconnexion"): 
        del st.session_state["password_correct"]
        st.rerun()
