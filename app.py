import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PIL import Image
import google.generativeai as genai
from anthropic import Anthropic
import io
import zipfile
import os

# --- UI-Einstellungen ---
st.title("🦊 Koifox-Bot")
st.markdown("""
    *This application uses Google's Gemini for OCR and Anthropic's Claude for answering advanced accounting questions.*  
    *Made with coffee, deep minimal and tiny gummy bears*  
""")

# --- Google Drive-Verbindung ---
drive_service = None
if "gdrive_creds" in st.secrets:
    try:
        creds = service_account.Credentials.from_service_account_info(
            st.secrets["gdrive_creds"]
        )
        drive_service = build("drive", "v3", credentials=creds)
        st.success("📌 Mit Google Drive verbunden!")
        
       # Silent Mode - Keine UI-Ausgaben außer bei Fehlern
        results = drive_service.files().list(
            q="name='IRW_Bot_Gehirn' and mimeType='application/vnd.google-apps.folder'",
            pageSize=1,
            fields="files(id, name, mimeType)"
        ).execute()
        files = results.get('files', [])
        
        if files:
            folder = files[0]
            st.session_state.drive_folder = folder
                
                # Automatische ZIP-Suche ohne UI-Feedback
            zip_files = drive_service.files().list(
                q=f"'{folder['id']}' in parents and mimeType='application/zip'",
                pageSize=1,
                fields="files(id, name, mimeType)"
            ).execute().get('files', [])
            
            if zip_files:
                st.session_state.drive_file = zip_files[0]
            
    except Exception as e:
        st.error(f"🔴 Verbindungsfehler: {str(e)}", icon="❌")

# --- Funktion zum Laden von Wissen aus Drive ---
def load_knowledge_from_drive(drive_service):
    try:
        if "drive_file" not in st.session_state:
            st.error("🔴 Keine ZIP-Datei ausgewählt", icon="⚠️")
            return ""
            
        file_id = st.session_state.drive_file["id"]
        file_meta = drive_service.files().get(
            fileId=file_id,
            fields="name,mimeType"
        ).execute()

        if file_meta["mimeType"] != "application/zip":
            st.error("🔴 Bitte eine ZIP-Datei auswählen", icon="📁")
            return ""

        downloaded = drive_service.files().get_media(fileId=file_id).execute()
        with zipfile.ZipFile(io.BytesIO(downloaded)) as zip_ref:
            knowledge = ""
            for file in zip_ref.namelist():
                if file.endswith((".txt", ".pdf")):
                    with zip_ref.open(file) as f:
                        knowledge += f.read().decode("utf-8", errors="ignore") + "\n\n"
            return knowledge

    except Exception as e:
        st.error(f"🔴 Fehler beim Laden: {str(e)}", icon="❌")
        return ""

# --- Wissen laden ---
drive_knowledge = ""
if drive_service and "drive_file" in st.session_state:
    drive_knowledge = load_knowledge_from_drive(drive_service)
    if drive_knowledge:
        st.success("📌 Wissen erfolgreich geladen!")
    else:
        st.warning("ℹ️ Kein Wissen aus Drive geladen")

# --- Bild-Upload und Verarbeitung ---
uploaded_file = st.file_uploader(
    "**Choose an exam paper image...**\n\nDrag and drop file here\nLimit 200MB per file - PNG, JPG, JPEG, WEBP, BMP",
    type=["png", "jpg", "jpeg", "webp", "bmp"]
)

if uploaded_file:
    # --- OCR mit Gemini ---
    genai.configure(api_key=st.secrets["gemini_key"])
    model = genai.GenerativeModel("gemini-pro-vision")
    image = Image.open(uploaded_file)
    st.image(image, caption="Hochgeladenes Bild", use_column_width=True)
    
    with st.spinner("Extrahiere Text mit Gemini..."):
        try:
            response = model.generate_content(["Extrahier den Text aus diesem Bild.", image])
            extracted_text = response.text
            st.subheader("Extrahierter Text")
            with st.container(border=True):
                st.markdown(f"""
                <div style='
                    max-height: 300px;
                    overflow-y: auto;
                    padding: 10px;
                    background: #f8f9fa;
                    border-radius: 5px;
                '>
                {extracted_text}
                </div>
                """, unsafe_allow_html=True)
                
            # Optional: Raw Text in Expander
            with st.expander("🛠️ Rohdaten anzeigen", expanded=False):
                st.code(extracted_text)
         
        except Exception as e:
            st.error(f"🔴 OCR-Fehler: {str(e)}", icon="❌")
            extracted_text = ""

    # --- Antwort mit Claude ---
    if extracted_text:
        client = Anthropic(api_key=st.secrets["claude_key"])
        with st.spinner("Claude denkt nach..."):
            try:
                response = client.messages.create(
                    model="claude-3-opus-20240229",
                    max_tokens=4000,
                    messages=[
                        {
                            "role": "user",
                            "content": f"""
                            Hier ist eine Accounting-Frage (extrahiert aus einem Bild):\n\n{extracted_text}\n\n
                            Beantworte die Frage präzise auf Deutsch. Nutze dafür dieses Hintergrundwissen:\n\n{drive_knowledge}
                            """
                        }
                    ]
                )
                st.write("**Antwort von Claude:**")
                st.markdown(response.content[0].text)
            except Exception as e:
                st.error(f"🔴 Claude-Fehler: {str(e)}", icon="❌")

# Debug-Option
with st.expander("🔍 System-Status"):
    if "drive_folder" in st.session_state:
        st.write("Drive-Ordner:", st.session_state.drive_folder)
    if "drive_file" in st.session_state:
        st.write("Drive-Datei:", st.session_state.drive_file)
    st.write("Wissens-Länge:", len(drive_knowledge))
