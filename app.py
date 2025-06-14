import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PIL import Image
import google.generativeai as genai
from anthropic import Anthropic
import io
import zipfile

# --- UI-Einstellungen ---
st.set_page_config(layout="centered")
st.title("🦊 Koifox-Bot")
st.markdown("""
    *This application uses Google's Gemini for OCR and Anthropic's Claude for answering advanced accounting questions.*  
    *Made with coffee, deep minimal and tiny gummy bears*  
""")

# --- Google Drive-Verbindung (silent) ---
drive_service = None
if "gdrive_creds" in st.secrets:
    try:
        creds = service_account.Credentials.from_service_account_info(
            st.secrets["gdrive_creds"]
        )
        drive_service = build("drive", "v3", credentials=creds)
        
        # Automatische Ordner- und Dateisuche
        try:
            folder = drive_service.files().list(
                q="name='IRW_Bot_Gehirn' and mimeType='application/vnd.google-apps.folder'",
                pageSize=1,
                fields="files(id)"
            ).execute().get('files', [{}])[0]
            
            if folder.get('id'):
                zip_file = drive_service.files().list(
                    q=f"'{folder['id']}' in parents and mimeType='application/zip'",
                    pageSize=1,
                    fields="files(id)"
                ).execute().get('files', [{}])[0]
                
                if zip_file.get('id'):
                    st.session_state.drive_file_id = zip_file['id']
        except Exception:
            pass  # Silent fail

    except Exception:
        pass  # Silent fail

# --- Silent Wissen laden ---
if drive_service and hasattr(st.session_state, 'drive_file_id'):
    try:
        downloaded = drive_service.files().get_media(fileId=st.session_state.drive_file_id).execute()
        with zipfile.ZipFile(io.BytesIO(downloaded)) as zip_ref:
            drive_knowledge = "\n\n".join([
                f.read().decode("utf-8", errors="ignore")
                for file in zip_ref.namelist()
                if file.endswith((".txt", ".pdf"))
            ])
        st.session_state.drive_knowledge = drive_knowledge
    except Exception:
        st.session_state.drive_knowledge = ""

# --- Bild-Upload ---
uploaded_file = st.file_uploader(
    "**Choose an exam paper image...**\n\nDrag and drop file here\nLimit 200MB per file - PNG, JPG, JPEG, WEBP, BMP",
    type=["png", "jpg", "jpeg", "webp", "bmp"]
)

if uploaded_file:
    # --- OCR mit Gemini ---
    try:
        genai.configure(api_key=st.secrets["gemini_key"])
        model = genai.GenerativeModel("gemini-pro-vision")
        image = Image.open(uploaded_file)
        
        with st.spinner("Analysiere Dokument..."):
            try:
                response = model.generate_content(["Extrahier den Text aus diesem Bild.", image])
                extracted_text = response.text
                
                # --- Antwort mit Claude ---
                if extracted_text and hasattr(st.session_state, 'drive_knowledge'):
                    client = Anthropic(api_key=st.secrets["claude_key"])
                    response = client.messages.create(
                        model="claude-3-opus-20240229",
                        max_tokens=4000,
                        messages=[{
                            "role": "user",
                            "content": f"""
                            Accounting-Frage:\n\n{extracted_text}\n\n
                            Hintergrundwissen:\n\n{st.session_state.drive_knowledge}
                            """
                        }]
                    )
                    st.markdown("### Antwort:")
                    st.markdown(response.content[0].text)
                    
            except Exception as e:
                st.error("Analyse fehlgeschlagen. Bitte versuchen Sie es mit einem anderen Bild.")
                
    except Exception as e:
        st.error("Initialisierung fehlgeschlagen. Bitte kontaktieren Sie den Support.")
