import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from anthropic import Anthropic
from PIL import Image
import google.generativeai as genai
import io
import zipfile
import logging
import datetime

# --- Erweitertes Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Session State Init ---
if 'last_upload' not in st.session_state:
    st.session_state.last_upload = None
if 'api_calls' not in st.session_state:
    st.session_state.api_calls = 0
if 'last_solve_time' not in st.session_state:
    st.session_state.last_solve_time = None

# --- API Key Validation ---
def validate_keys():
    required_keys = {
        'gemini_key': ('AIza', "Gemini"),
        'claude_key': ('sk-ant', "Claude")
    }
    missing = []
    invalid = []
    
    for key, (prefix, name) in required_keys.items():
        if key not in st.secrets:
            missing.append(name)
        elif not st.secrets[key].startswith(prefix):
            invalid.append(name)
    
    if missing or invalid:
        st.error(f"API Key Problem: Missing {', '.join(missing)} | Invalid {', '.join(invalid)}")
        st.stop()

validate_keys()

# --- UI-Einstellungen ---
st.set_page_config(layout="centered", page_title="Koifox-Bot", page_icon="🦊")
st.title("🦊 Koifox-Bot")
st.markdown("*Using Gemini for OCR + Claude 4 Opus for solutions*")

# API Call Counter anzeigen
st.sidebar.metric("API Calls diese Session", st.session_state.api_calls)

# --- Google Drive-Verbindung ---
@st.cache_resource
def load_knowledge_from_drive():
    logger.info("Loading knowledge base from Drive...")
    knowledge_base = ""
    if "gdrive_creds" not in st.secrets:
        logger.warning("No Google Drive credentials found")
        return knowledge_base
        
    try:
        creds = service_account.Credentials.from_service_account_info(st.secrets["gdrive_creds"])
        drive_service = build("drive", "v3", credentials=creds)
        
        folder_response = drive_service.files().list(
            q="name='IRW_Bot_Gehirn' and mimeType='application/vnd.google-apps.folder'",
            pageSize=1,
            fields="files(id)"
        ).execute()
        
        folder = folder_response.get('files', [{}])[0]
        if not folder.get('id'):
            logger.warning("Knowledge folder not found")
            return knowledge_base
            
        zip_response = drive_service.files().list(
            q=f"'{folder['id']}' in parents and mimeType='application/zip'",
            pageSize=1,
            fields="files(id)"
        ).execute()
        
        zip_file = zip_response.get('files', [{}])[0]
        if not zip_file.get('id'):
            logger.warning("Knowledge ZIP not found")
            return knowledge_base
            
        downloaded = drive_service.files().get_media(fileId=zip_file['id']).execute()
        with zipfile.ZipFile(io.BytesIO(downloaded)) as zip_ref:
            for file_name in zip_ref.namelist():
                if file_name.endswith(('.txt', '.md')):
                    try:
                        content = zip_ref.read(file_name).decode('utf-8', errors='ignore')
                        knowledge_base += f"\n\n--- {file_name} ---\n{content}"
                    except Exception as e:
                        logger.warning(f"Could not read {file_name}: {e}")
                        
        logger.info(f"Knowledge Base loaded: {len(knowledge_base)} characters")
        return knowledge_base
        
    except Exception as e:
        logger.error(f"Drive error: {str(e)}")
        return knowledge_base

# --- Gemini Flash Konfiguration ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")

# --- OCR mit Gemini ---
def extract_text_with_gemini(image):
    """Extrahiert Text aus Bild mit Gemini Flash"""
    try:
        logger.info("Starting Gemini OCR...")
        response = vision_model.generate_content(
            [
                "Extract ALL text from this exam image EXACTLY as written. Include all question numbers, text, and answer options (A, B, C, D, E). Do NOT interpret or solve.",
                image
            ],
            generation_config={
                "temperature": 0,
                "max_output_tokens": 4000
            }
        )
        logger.info("Gemini OCR completed successfully")
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini OCR Error: {str(e)}")
        raise e

# --- UI Optionen ---
col1, col2, col3 = st.columns([1, 1, 1])
with col1:
    use_knowledge = st.checkbox("📚 Kursmaterial", value=False)
with col2:
    debug_mode = st.checkbox("🔍 Debug", value=True)
with col3:
    prevent_rerun = st.checkbox("🔒 Rerun-Schutz", value=True, help="Verhindert mehrfache API-Calls")

# --- Datei-Upload ---
uploaded_file = st.file_uploader(
    "**Klausuraufgabe hochladen...**",
    type=["png", "jpg", "jpeg"],
    key="file_uploader"
)

if uploaded_file is not None:
    # Eindeutige File ID
    file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    
    # Reset bei neuer Datei
    if st.session_state.last_upload != file_id:
        logger.info(f"New file uploaded: {file_id}")
        st.session_state.last_upload = file_id
        if 'ocr_result' in st.session_state:
            del st.session_state.ocr_result
        if 'last_result' in st.session_state:
            del st.session_state.last_result
    
    try:
        # Bild laden und anzeigen
        image = Image.open(uploaded_file)
        st.image(image, caption="Hochgeladene Klausuraufgabe", use_container_width=True)
        
        # OCR nur wenn noch nicht gemacht
        if 'ocr_result' not in st.session_state:
            with st.spinner("📖 Lese Text mit Gemini Flash..."):
                st.session_state.ocr_result = extract_text_with_gemini(image)
                logger.info("OCR result cached in session state")
        
        ocr_text = st.session_state.ocr_result
        
        # Debug: OCR-Ergebnis anzeigen
        if debug_mode:
            with st.expander("🔍 OCR-Ergebnis", expanded=False):
                st.code(ocr_text)
        
        # Button zum Lösen mit Rerun-Schutz
        current_time = datetime.datetime.now()
        can_solve = True
        
        if prevent_rerun and st.session_state.last_solve_time:
            time_diff = (current_time - st.session_state.last_solve_time).total_seconds()
            if time_diff < 2:  # 2 Sekunden Cooldown
                can_solve = False
                st.warning("⏳ Bitte warten Sie kurz...")
        
        if st.button("🧮 Aufgaben lösen", type="primary", disabled=not can_solve):
            st.session_state.last_solve_time = current_time
            
            # Verhindere mehrfache Ausführung
            if 'last_result' in st.session_state and prevent_rerun:
                st.markdown("---")
                st.markdown("### 📊 Lösungen (aus Cache):")
                st.markdown(st.session_state.last_result)
            else:
                # Knowledge Base laden wenn gewünscht
                knowledge_section = ""
                if use_knowledge:
                    with st.spinner("📚 Lade Kursmaterial..."):
                        knowledge_base = load_knowledge_from_drive()
                        if knowledge_base:
                            knowledge_section = f"\n\nKURSMATERIAL:\n{knowledge_base[:10000]}"
                
                # Prompt
                prompt = f"""You are an expert in "Internes Rechnungswesen (31031)" at Fernuniversität Hagen.

FACHGEBIET: Gesamtes internes Rechnungswesen (Kostenrechnung, Controlling, etc.)

ANALYSIERE diesen OCR-Text:
{ocr_text}
{knowledge_section}

ANWEISUNGEN:
- Bei Multiple Choice "(x aus 5)": Prüfe JEDE Option, mehrere können richtig sein
- Bei Rechenaufgaben: Zeige Rechenweg und Endergebnis
- Immer: Präzise Fachterminologie der Fernuni Hagen

FORMAT:
Aufgabe [Nr]: [Lösung]
Begründung: [Kurze fachliche Erklärung auf Deutsch]"""

                if debug_mode:
                    with st.expander("🔍 Claude Prompt", expanded=False):
                        st.code(prompt)
                        st.info(f"Prompt-Länge: {len(prompt)} Zeichen")
                
                # Claude API-Aufruf
                with st.spinner("🧮 Löse Aufgaben mit Claude 4 Opus..."):
                    try:
                        logger.info("Calling Claude API...")
                        client = Anthropic(api_key=st.secrets["claude_key"])
                        response = client.messages.create(
                            model="claude-4-opus-20250514",
                            max_tokens=2000,
                            temperature=0,
                            messages=[{
                                "role": "user",
                                "content": prompt
                            }]
                        )
                        
                        st.session_state.api_calls += 1
                        result = response.content[0].text
                        st.session_state.last_result = result
                        logger.info("Claude API call successful")
                        
                    except Exception as e:
                        logger.error(f"Claude API Error: {str(e)}")
                        st.error(f"API Fehler: {str(e)}")
                        raise e
                
                # Ergebnisse anzeigen
                st.markdown("---")
                st.markdown("### 📊 Lösungen:")
                
                # Formatierte Ausgabe
                lines = result.split('\n')
                for line in lines:
                    if line.strip():
                        if line.startswith('Aufgabe'):
                            parts = line.split(':', 1)
                            if len(parts) == 2:
                                st.markdown(f"### {parts[0]}: **{parts[1].strip()}**")
                            else:
                                st.markdown(f"### {line}")
                        elif line.startswith('Begründung:'):
                            st.markdown(f"*{line}*")
                        else:
                            st.markdown(line)
                    
    except Exception as e:
        logger.error(f"General error: {str(e)}")
        st.error(f"❌ Fehler: {str(e)}")

# --- Footer ---
st.markdown("---")
st.caption(f"Koifox-Bot | Session API Calls: {st.session_state.api_calls}")
