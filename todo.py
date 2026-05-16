import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta, time
import requests
import base64
from PIL import Image
import io

# --- CONFIGURATION ---
NTFY_TOPIC = "youndesign_todolist_123"

def send_notif(title, message, priority="default"):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=message.encode('utf-8'),
            headers={"Title": title.encode('utf-8'), "Priority": priority})
    except: pass

# --- SÉCURITÉ ---
def check_password():
    if "password_correct" not in st.session_state:
        st.title("🔒 Accès Privé")
        pwd = st.text_input("Mot de passe", type="password")
        if st.button("Connexion"):
            if pwd == st.secrets["password"]:
                st.session_state["password_correct"] = True
                st.rerun()
            else: st.error("Incorrect")
        return False
    return True

if check_password():
    conn = st.connection("gsheets", type=GSheetsConnection)

    def load_data():
        try:
            df = conn.read(ttl=0)
            df = df.dropna(subset=['gros_titre', 'titre'], how='all')
            for col in ['status', 'date_archive', 'image_b64', 'notif_sent']:
                if col not in df.columns: df[col] = ""
                df[col] = df[col].astype(str).replace('nan', '')
            df['dt_obj'] = pd.to_datetime(df['echeance'], errors='coerce')
            df['date_archive_dt'] = pd.to_datetime(df['date_archive'], errors='coerce')
        except:
            df = pd.DataFrame(columns=["id", "gros_titre", "titre", "contenu", "echeance", "type", "status", "date_archive", "image_b64", "notif_sent"])
        return df

    def save_data(df_to_save):
        cols_to_drop = ['dt_obj', 'date_archive_dt']
        final_df = df_to_save.drop(columns=[c for c in cols_to_drop if c in df_to_save.columns])
        conn.update(data=final_df)
        st.cache_data.clear()

    # --- LOGIQUE NOTIFICATIONS TEMPS RÉEL ---
    def process_realtime_notifications(df):
        now = datetime.now()
        updated = False
        # On cherche les tâches dont l'heure est passée et non notifiées
        mask = (df['status'] == 'En cours') & (df['type'] == 'Task') & \
               (df['dt_obj'] <= now) & (df['notif_sent'] != 'OUI')
        
        for idx, row in df[mask].iterrows():
            send_notif(f"⏰ MAINTENANT : {row['titre']}", f"{row['gros_titre']}\n{row['contenu']}", priority="high")
            df.at[idx, 'notif_sent'] = 'OUI'
            updated = True
        
        if updated:
            save_data(df)

    # --- INTERFACE ---
    st.set_page_config(page_title="YounDesign PKM", layout="wide")
    df = load_data()
    process_realtime_notifications(df) # Vérifie les notifs à chaque rafraîchissement
    
    now_ts = pd.Timestamp(datetime.now())
    today = now_ts.date()

    def item_card(idx, row, is_overdue=False, key_suffix=""):
        with st.container(border=True):
            col1, col2, col3, col4 = st.columns([0.1, 0.5, 0.3, 0.1])
            with col1:
                if row['status'] != 'Terminé':
                    if st.checkbox("Fait", key=f"chk_{idx}_{key_suffix}", label_visibility="collapsed"):
                        df.at[idx, 'status'] = 'Terminé'
                        df.at[idx, 'date_archive'] = datetime.now().strftime('%Y-%m-%d')
                        save_data(df)
                        st.rerun()
                else:
                    if st.button("🔄", key=f"res_{idx}_{key_suffix}"):
                        df.at[idx, 'status'] = 'En cours'
                        df.at[idx, 'notif_sent'] = ''
                        save_data(df)
                        st.rerun()
            with col2:
                st.markdown(f"**{row['gros_titre']}** > {row['titre']}")
                st.write(row['contenu'])
                # AFFICHAGE DE L'IMAGE SI EXISTE
                if row['image_b64'] != "":
                    try:
                        st.image(base64.b64decode(row['image_b64']), width=250)
                    except: st.caption("Erreur affichage image")
            with col3:
                if row['type'] == 'Task' and not pd.isna(row['dt_obj']):
                    color = "red" if is_overdue else "green"
                    st.markdown(f"<span style='color:{color}'>📅 {row['dt_obj'].strftime('%d/%m/%Y %H:%M')}</span>", unsafe_allow_html=True)

    # ... (Garder les onglets Jour, Semaine, Mois, Thème, Archive) ...
    # Code identique pour les onglets que la V11

    with st.tabs(["☀️ Jour", "📅 Semaine", "📂 Thèmes", "📝 Notes", "🗄️ Archive", "🖊️ Saisie"])[5]:
        idx_e = st.session_state.get('edit_item_idx')
        edit_r = df.loc[idx_e] if idx_e is not None else None
        
        with st.form("form_v12"):
            c1, c2 = st.columns(2)
            with c1:
                f_gt = st.text_input("Dossier", value=edit_r['gros_titre'] if edit_r is not None else "")
                f_t = st.text_input("Titre", value=edit_r['titre'] if edit_r is not None else "")
                f_c = st.text_area("Description", value=edit_r['contenu'] if edit_r is not None else "")
            with c2:
                f_d = st.date_input("Date", value=edit_r['dt_obj'].date() if edit_r is not None and not pd.isna(edit_r['dt_obj']) else None)
                f_h = st.time_input("Heure", value=edit_r['dt_obj'].time() if edit_r is not None and not pd.isna(edit_r['dt_obj']) else time(8,0))
                f_img = st.file_uploader("Ajouter une photo", type=['jpg', 'jpeg', 'png'])

            if st.form_submit_button("Enregistrer"):
                b64_str = edit_r['image_b64'] if edit_r is not None else ""
                if f_img:
                    # Compression de l'image pour Google Sheets
                    img = Image.open(f_img)
                    img.thumbnail((400, 400)) # Taille max
                    buffered = io.BytesIO()
                    img.save(buffered, format="JPEG", quality=70)
                    b64_str = base64.b64encode(buffered.getvalue()).decode()

                date_s = datetime.combine(f_d, f_h).strftime('%Y-%m-%d %H:%M:%S') if f_d else ""
                
                if idx_e is not None:
                    df.at[idx_e, 'gros_titre'], df.at[idx_e, 'titre'], df.at[idx_e, 'contenu'] = f_gt, f_t, f_c
                    df.at[idx_e, 'echeance'], df.at[idx_e, 'image_b64'] = date_s, b64_str
                else:
                    new_r = {"id": len(df)+1, "gros_titre": f_gt, "titre": f_t, "contenu": f_c, "echeance": date_s, 
                             "type": ("Task" if f_d else "Note"), "status": "En cours", "image_b64": b64_str, "notif_sent": ""}
                    df = pd.concat([df, pd.DataFrame([new_r])], ignore_index=True)
                
                save_data(df)
                st.rerun()
