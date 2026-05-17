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
NTFY_TOPIC = st.secrets.get("ntfy_topic", "youndesign_pkm_789")
CALENDAR_ID = st.secrets.get("calendar_id", "")

# --- FUSEAU HORAIRE FRANCE ---
def get_now_fr():
    return datetime.utcnow() + timedelta(hours=2)

# --- FONCTIONS SYSTÈME ---
def send_notif(title, message, priority="default"):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=message.encode('utf-8'),
            headers={"Title": title.encode('utf-8'), "Priority": priority})
    except: pass

def get_calendar_service():
    creds_info = st.secrets["connections"]["gsheets"]
    creds = service_account.Credentials.from_service_account_info(creds_info)
    scoped_creds = creds.with_scopes(['https://www.googleapis.com/auth/calendar'])
    return build('calendar', 'v3', credentials=scoped_creds)

def delete_calendar_event(cal_id):
    if not cal_id or not CALENDAR_ID or str(cal_id).lower() in ["", "nan"]: return
    try:
        service = get_calendar_service()
        service.events().delete(calendarId=CALENDAR_ID, eventId=str(cal_id)).execute()
    except: pass

def upsert_calendar_event(row_data):
    if not row_data.get('echeance') or row_data.get('type') != "Task" or not CALENDAR_ID: return ""
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

def get_category_style(gt):
    gt_lower = str(gt).lower()
    emoji = "📁"
    if "travail" in gt_lower: emoji = "💼"
    elif "maison" in gt_lower: emoji = "🏠"
    elif "idée" in gt_lower: emoji = "💡"
    colors = ["#3498db", "#2ecc71", "#9b59b6", "#f1c40f", "#e67e22", "#e74c3c", "#1abc9c", "#34495e"]
    color_idx = sum(ord(c) for c in str(gt)) % len(colors)
    return colors[color_idx], emoji

# --- CONNEXION ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df_loaded = conn.read(ttl=0).dropna(subset=['gros_titre', 'titre'], how='all')
        cols = ['id', 'status', 'date_archive', 'image_b64', 'notif_sent', 'gros_titre', 'titre', 'echeance', 'contenu', 'type', 'cal_event_id', 'google_type', 'compteur_relance']
        for col in cols:
            if col not in df_loaded.columns: df_loaded[col] = ""
            df_loaded[col] = df_loaded[col].astype(str).replace('nan', '').fillna('')
        df_loaded['status'] = df_loaded['status'].str.strip()
        df_loaded.loc[df_loaded['status'] == "", 'status'] = 'En cours'
        df_loaded['dt_obj'] = pd.to_datetime(df_loaded['echeance'], errors='coerce')
        return df_loaded
    except:
        return pd.DataFrame(columns=['id', 'status', 'date_archive', 'image_b64', 'notif_sent', 'gros_titre', 'titre', 'echeance', 'contenu', 'type', 'cal_event_id', 'google_type', 'compteur_relance'])

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
now_fr = get_now_fr()
today_date = now_fr.date()

if 'edit_item_idx' not in st.session_state: st.session_state['edit_item_idx'] = None

# --- LOGIQUE REPORT RAPIDE ---
def quick_reschedule(idx, days=0, weeks=0):
    try: current_count = int(float(df.at[idx, 'compteur_relance'] or 0))
    except: current_count = 0
    df.at[idx, 'compteur_relance'] = str(current_count + 1)
    new_d = (get_now_fr() + timedelta(days=days, weeks=weeks)).replace(hour=8, minute=0, second=0)
    df.at[idx, 'echeance'] = new_d.strftime('%Y-%m-%d %H:%M:%S')
    df.at[idx, 'notif_sent'] = ""
    df.at[idx, 'cal_event_id'] = upsert_calendar_event(df.loc[idx].to_dict())
    save_data(df); st.rerun()

# --- COMPOSANT CARTE ---
def item_card(idx, row, is_overdue=False, key_suffix=""):
    cat_color, cat_emoji = get_category_style(row['gros_titre'])
    relances = 0
    try: relances = int(float(row['compteur_relance'] or 0))
    except: pass
    
    procrastination_alert = relances >= 5
    card_bg = "#fff1f1" if is_overdue else "white"
    border_style = f"border-left: 10px solid {cat_color};"
    if is_overdue: border_style = "border: 4px solid #FF4B4B;"
    if procrastination_alert: border_style = "border: 5px solid #FF8C00;"; card_bg = "#FFF5E6"

    # HTML propre et fermé
    card_html = f"""
    <div style='{border_style} padding:15px; border-radius:10px; margin-bottom:10px; background-color:{card_bg}; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);'>
        <div style='display:flex; justify-content:space-between;'><span style='color:{cat_color}; font-weight:bold;'>{cat_emoji} {row['gros_titre']}</span>
        {"<span style='color:#FF8C00; font-weight:bold;'>⚠️ " + str(relances) + " REPORTS</span>" if relances > 0 else ""}</div>
        <div style='font-size:1.2em; font-weight:bold; margin-top:5px;'>{'📌' if row['google_type'] == 'Tâche (Journée)' else '⏰'} {row['titre']}</div>
        <div style='color:#333; margin-top:5px; white-space: pre-wrap;'>{row['contenu']}</div>
        {"<div style='color:#FF8C00; font-weight:bold; margin-top:10px;'>🚨 STOP PROCRASTINATION ! 🚨</div>" if procrastination_alert else ""}
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns([0.2, 0.6, 0.2])
    with c1:
        if row['status'] == 'En cours':
            if st.checkbox("Fait", key=f"c_{idx}_{key_suffix}", label_visibility="collapsed"):
                delete_calendar_event(row['cal_event_id'])
                df.at[idx, 'status'], df.at[idx, 'date_archive'] = 'Terminé', today_date.strftime('%Y-%m-%d')
                save_data(df); st.rerun()
        else:
            if st.button("🔄 Restaurer", key=f"r_{idx}_{key_suffix}"):
                df.at[idx, 'status'], df.at[idx, 'date_archive'] = 'En cours', ""
                df.at[idx, 'cal_event_id'] = upsert_calendar_event(df.loc[idx].to_dict())
                save_data(df); st.rerun()
    with c2:
        if not pd.isna(row['dt_obj']):
            st.caption(f"📅 {row['dt_obj'].strftime('%d/%m/%Y %H:%M')}")
            if row['status'] == 'En cours':
                cr1, cr2 = st.columns(2)
                if cr1.button("⏩ Demain 08h", key=f"q_{idx}_{key_suffix}"): quick_reschedule(idx, days=1)
                with cr2.expander("Autres..."):
                    if st.button("+7j", key=f"p7_{idx}_{key_suffix}"): quick_reschedule(idx, weeks=1)
                    if st.button("+30j", key=f"p30_{idx}_{key_suffix}"): quick_reschedule(idx, days=30)
        img_raw = str(row.get('image_b64', ""))
        if len(img_raw) > 100:
            try: st.image(base64.b64decode(img_raw), width=250)
            except: pass
    with c3:
        if st.button("✏️", key=f"ed_{idx}_{key_suffix}"):
            st.session_state['edit_item_idx'] = idx; st.rerun()
    st.divider()

# --- SIDEBAR & RECHERCHE (Fix SessionState) ---
with st.sidebar:
    st.markdown("### 🔍 Recherche")
    # Pour vider le champ, on utilise une astuce de clé dynamique
    if "search_reset" not in st.session_state: st.session_state.search_reset = 0
    
    search_query = st.text_input("Filtrer...", key=f"s_{st.session_state.search_reset}")
    if st.button("❌ Effacer la recherche"):
        st.session_state.search_reset += 1
        st.rerun()
    
    st.divider()
    if st.button("🚪 Déconnexion"): del st.session_state["password_correct"]; st.rerun()

# --- FILTRAGE ---
df_f = df.copy()
search = search_query.lower()
if search:
    df_f = df[df['titre'].str.lower().str.contains(search) | df['contenu'].str.lower().str.contains(search) | df['gros_titre'].str.lower().str.contains(search)]

# --- FORMULAIRE ---
def show_form(idx_e=None):
    global df
    edit_r = df.loc[idx_e] if idx_e is not None else None
    st.subheader("🖊️ Saisie" if idx_e is None else "✏️ Modification")
    with st.form(f"form_{idx_e if idx_e is not None else 'new'}"):
        c1, c2 = st.columns(2)
        with c1:
            l_gt = sorted(list(set([str(x) for x in df['gros_titre'] if x])))
            idx_gt = l_gt.index(edit_r['gros_titre'])+1 if (edit_r is not None and edit_r['gros_titre'] in l_gt) else 0
            f_gt = st.selectbox("Dossier existant", [""] + l_gt, index=idx_gt)
            f_gt_n = st.text_input("OU Nouveau Dossier")
            l_t = sorted(list(set([str(x) for x in df['titre'] if x])))
            idx_t = l_t.index(edit_r['titre'])+1 if (edit_r is not None and edit_r['titre'] in l_t) else 0
            f_t = st.selectbox("Titre existant", [""] + l_t, index=idx_t)
            f_t_n = st.text_input("OU Nouveau Titre")
            f_gtype = st.radio("Type :", ["Événement (Heure)", "Tâche (Journée)"], index=0 if (edit_r is None or edit_r['google_type'] != "Tâche (Journée)") else 1)
        with c2:
            f_c = st.text_area("Contenu", value=edit_r['contenu'] if edit_r is not None else "")
            f_d = st.date_input("Date", value=edit_r['dt_obj'].date() if (edit_r is not None and not pd.isna(edit_r['dt_obj'])) else None)
            f_h = st.time_input("Heure", value=edit_r['dt_obj'].time() if (edit_r is not None and not pd.isna(edit_r['dt_obj'])) else time(8,0))
            f_img = st.file_uploader("Photo")
        
        if st.form_submit_button("💾 ENREGISTRER"):
            # Validation Stricte
            if (f_gt != "" and f_gt_n != "") or (f_t != "" and f_t_n != ""):
                st.error("⚠️ Erreur : Ne remplissez pas 'Existant' ET 'Nouveau' en même temps.")
            elif (f_gt == "" and f_gt_n == "") or (f_t == "" and f_t_n == ""):
                st.error("⚠️ Erreur : Dossier et Titre obligatoires.")
            else:
                f_gt_f, f_t_f = (f_gt_n if f_gt_n else f_gt), (f_t_n if f_t_n else f_t)
                date_s = datetime.combine(f_d, f_h).strftime('%Y-%m-%d %H:%M:%S') if f_d else ""
                b64 = str(edit_r['image_b64']) if (edit_r is not None) else ""
                if f_img:
                    img = Image.open(f_img)
                    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
                    img.thumbnail((400, 400)); buf = io.BytesIO(); img.save(buf, format="JPEG", quality=70); b64 = base64.b64encode(buf.getvalue()).decode()
                
                if idx_e is not None:
                    df.at[idx_e, 'gros_titre'], df.at[idx_e, 'titre'], df.at[idx_e, 'contenu'] = f_gt_f, f_t_f, f_c
                    df.at[idx_e, 'echeance'], df.at[idx_e, 'type'], df.at[idx_e, 'image_b64'] = date_s, ("Task" if f_d else "Note"), b64
                    df.at[idx_e, 'google_type'] = f_gtype
                    df.at[idx_e, 'cal_event_id'] = upsert_calendar_event(df.loc[idx_e].to_dict())
                else:
                    nid = int(pd.to_numeric(df['id'], errors='coerce').max() + 1) if not df.empty else 1
                    nr = {"id": str(nid), "gros_titre": f_gt_f, "titre": f_t_f, "contenu": f_c, "echeance": date_s, "type": ("Task" if f_d else "Note"), "status": "En cours", "image_b64": b64, "google_type": f_gtype, "compteur_relance": "0"}
                    nr['cal_event_id'] = upsert_calendar_event(nr)
                    df = pd.concat([df, pd.DataFrame([nr])], ignore_index=True)
                save_data(df); st.session_state['edit_item_idx'] = None; st.rerun()

# --- AFFICHAGE ---
if st.session_state['edit_item_idx'] is not None:
    show_form(st.session_state['edit_item_idx'])
    if st.button("❌ Annuler"): st.session_state['edit_item_idx'] = None; st.rerun()
    st.divider()

tabs = st.tabs(["☀️ Jour", "📅 Semaine", "📊 Mois", "📂 Thèmes", "📝 Notes", "🗄️ Archive", "🖊️ Saisie"])
active = df_f[df_f['status'] == 'En cours'].copy()
if not active.empty: active = active.sort_values('dt_obj', ascending=True)

with tabs[0]: # JOUR
    ov = active[(active['type'] == 'Task') & (active['dt_obj'].dt.date < today_date)]
    for idx, r in ov.iterrows(): item_card(idx, r, is_overdue=True, key_suffix="ov")
    tod = active[(active['type'] == 'Task') & (active['dt_obj'].dt.date == today_date)]
    for idx, r in tod.iterrows(): item_card(idx, r, key_suffix="tod")
    if ov.empty and tod.empty: st.info("Rien aujourd'hui.")

with tabs[1]: # SEMAINE
    wk = active[(active['type'] == 'Task') & (active['dt_obj'].dt.date > today_date) & (active['dt_obj'].dt.date <= today_date + timedelta(days=7))]
    for idx, r in wk.iterrows(): item_card(idx, r, key_suffix="wk")

with tabs[2]: # MOIS
    mo = active[(active['type'] == 'Task') & (active['dt_obj'].dt.date > today_date) & (active['dt_obj'].dt.date <= today_date + timedelta(days=31))]
    for idx, r in mo.iterrows(): item_card(idx, r, key_suffix="mo")

with tabs[3]: # THEMES
    for gt in sorted(active['gros_titre'].unique()):
        col, emo = get_category_style(gt)
        with st.expander(f"{emo} {gt}"):
            sub = active[active['gros_titre'] == gt]
            for idx, r in sub.iterrows(): item_card(idx, r, key_suffix="th")

with tabs[4]: # NOTES
    nt = active[active['type'] == 'Note']
    for idx, r in nt.iterrows(): item_card(idx, r, key_suffix="nt")

with tabs[5]: # ARCHIVE
    arc = df_f[df_f['status'] == 'Terminé']
    for idx, r in arc.sort_values('date_archive', ascending=False).iterrows(): item_card(idx, r, key_suffix="arc")

with tabs[6]: # SAISIE
    if st.session_state['edit_item_idx'] is None: show_form()
